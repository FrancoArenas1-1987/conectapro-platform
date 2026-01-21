from __future__ import annotations

from typing import List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from services.common.logging_config import setup_logging
from ..models import Provider
from .catalog import IntentDef, load_intents, intents_by_id
from .llm_parser import try_llm_parse
from .rules import top_intents
from .types import NLUResult

logger = setup_logging("nlu")


class NLUEngine:
    """
    Motor híbrido: reglas + (opcional) LLM enjaulado.

    - El LLM solo produce intent_id + entidades + pregunta.
    - El ranking final siempre lo hace DB (providers activos + comuna + rating).
    """

    def __init__(self, intents: Optional[List[IntentDef]] = None):
        self.intents: List[IntentDef] = intents or load_intents()
        self.by_id = intents_by_id(self.intents)

    def allowlist(self) -> set[str]:
        return set(self.by_id.keys())

    def parse(self, text: str) -> NLUResult:
        top = top_intents(text, self.intents, k=3)
        if not top:
            return NLUResult(intent_id=None, confidence=0.0, method="rules", debug={"top": []})

        best_id, best_score, _ = top[0]
        second = top[1] if len(top) > 1 else None

        res = NLUResult(intent_id=best_id, confidence=float(best_score), method="rules")
        res.debug = {"top": [{"id": i, "score": float(s), "dbg": dbg} for i, s, dbg in top]}

        # ambigüedad => pregunta
        if second and (best_score < 0.55 or (best_score - second[1]) < 0.08):
            a = self.by_id.get(best_id)
            b = self.by_id.get(second[0])
            if a and b:
                res.need_clarification = True
                res.clarifying_options = [a.label, b.label]
                res.clarifying_question = (
                    "Para ayudarte mejor, ¿cuál de estas opciones se parece más a lo que necesitas?\n"
                    f"1) {a.label}\n"
                    f"2) {b.label}\n"
                    "Responde 1 o 2."
                )
        return res

    async def parse_hybrid(self, text: str) -> NLUResult:
        llm = await try_llm_parse(text, self.intents)
        top = top_intents(text, self.intents, k=3)
        rules_scores = {intent_id: score for intent_id, score, _ in top}

        llm_intent = None
        llm_score = 0.0
        if llm and llm.intent_id in self.allowlist():
            llm_intent = llm.intent_id
            llm_score = float(llm.confidence or 0.0)

        combined: dict[str, float] = {}
        for intent_id, score, _ in top:
            combined[intent_id] = score

        if llm_intent:
            rule_score = rules_scores.get(llm_intent, 0.0)
            combined[llm_intent] = (0.6 * llm_score) + (0.4 * rule_score)

        if not combined:
            r = NLUResult(intent_id=None, confidence=0.0, method="rules", debug={"top": []})
            r.method = "hybrid" if llm is not None else "rules"
            return r

        ranked = sorted(combined.items(), key=lambda x: x[1], reverse=True)
        best_id, best_score = ranked[0]
        second = ranked[1] if len(ranked) > 1 else None

        res = NLUResult(intent_id=best_id, confidence=float(best_score), method="hybrid")
        res.debug = {
            "rules_top": [{"id": i, "score": float(s)} for i, s, _ in top],
            "llm_intent": llm_intent,
            "llm_confidence": llm_score,
        }

        if second and (best_score < 0.55 or (best_score - second[1]) < 0.08):
            a = self.by_id.get(best_id)
            b = self.by_id.get(second[0])
            if a and b:
                res.need_clarification = True
                res.clarifying_options = [a.label, b.label]
                res.clarifying_question = (
                    "Para ayudarte mejor, ¿cuál de estas opciones se parece más a lo que necesitas?\n"
                    f"1) {a.label}\n"
                    f"2) {b.label}\n"
                    "Responde 1 o 2."
                )
        return res


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def build_service_intent_index(
    services: List[str], intents: List[IntentDef]
) -> Tuple[dict[str, str], dict[str, List[str]]]:
    """
    Asocia los nombres de Provider.service (strings) a intent_id del catálogo
    usando aliases/keywords (para mantener compatibilidad sin migrar DB).
    """
    service_to_intent: dict[str, str] = {}
    intent_to_services: dict[str, List[str]] = {}

    for svc in services:
        s = _norm(svc)
        if not s:
            continue

        best_id = None
        best = 0.0
        for it in intents:
            hit = 0.0
            for al in it.aliases:
                a = _norm(al)
                if a and (a in s or s in a):
                    hit = max(hit, 1.0)
            if hit < 1.0:
                for kw in it.keywords:
                    k = _norm(kw)
                    if k and k in s:
                        hit = max(hit, 0.7)
            if hit > best:
                best = hit
                best_id = it.id

        if best_id and best >= 0.7:
            service_to_intent[svc] = best_id
            intent_to_services.setdefault(best_id, []).append(svc)

    for k in list(intent_to_services.keys()):
        intent_to_services[k] = sorted(intent_to_services[k], key=lambda x: _norm(x))
    return service_to_intent, intent_to_services


def pick_best_service_for_intent(db: Session, intent_id: str, comuna: str, intent_to_services: dict[str, List[str]]) -> Optional[str]:
    candidates = intent_to_services.get(intent_id) or []
    if not candidates:
        return None

    normalized_comuna = _norm(comuna)
    if not normalized_comuna:
        return None

    rows = (
        db.query(Provider.service, Provider.rating_avg)
        .filter(Provider.active == True)
        .filter(func.lower(Provider.comuna) == normalized_comuna)
        .filter(Provider.service.in_(candidates))
        .all()
    )
    if not rows:
        return None

    agg: dict[str, dict[str, float]] = {}
    for svc, rat in rows:
        a = agg.setdefault(svc, {"n": 0.0, "sum": 0.0})
        a["n"] += 1.0
        a["sum"] += float(rat or 0.0)

    best_svc = None
    best_key = None
    for svc, a in agg.items():
        n = a["n"]
        avg = (a["sum"] / n) if n else 0.0
        key = (n, avg)
        if best_key is None or key > best_key:
            best_key = key
            best_svc = svc
    return best_svc
