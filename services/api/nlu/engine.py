from __future__ import annotations

from typing import List, Optional, Tuple

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from services.common.logging_config import setup_logging
from ..models import Provider, ProviderCoverage
from .catalog import IntentDef, load_intents, intents_by_id
from .llm_parser import try_llm_parse
from .rules import top_intents
from .types import NLUResult

logger = setup_logging("nlu_engine")

# Comuna aliases for common abbreviations
COMUNA_ALIASES = {
    "conce": "concepcion",
    "san pedro": "san pedro de la paz",
    "los angeles": "los angeles",  # if needed
    # Add more as needed
}

# Proximity map for comunas in Biobío region (normalized)
PROXIMITY_MAP = {
    "concepcion": ["talcahuano", "san pedro de la paz", "chiguayante", "hualpen", "coronel", "penco", "tome", "lota", "florida", "hualqui", "santa juana", "nacimento", "los angeles", "cabrero", "yumbel"],
    "talcahuano": ["concepcion", "san pedro de la paz", "hualpen", "coronel", "penco", "tome", "lota", "chiguayante", "florida", "hualqui", "santa juana", "nacimento", "los angeles", "cabrero", "yumbel"],
    "san pedro de la paz": ["concepcion", "talcahuano", "chiguayante", "hualpen", "coronel", "penco", "tome", "lota", "florida", "hualqui", "santa juana", "nacimento", "los angeles", "cabrero", "yumbel"],
    "chiguayante": ["concepcion", "san pedro de la paz", "talcahuano", "hualqui", "florida", "santa juana", "hualpen", "coronel", "penco", "tome", "lota", "nacimento", "los angeles", "cabrero", "yumbel"],
    "hualpen": ["talcahuano", "concepcion", "san pedro de la paz", "coronel", "penco", "tome", "lota", "chiguayante", "florida", "hualqui", "santa juana", "nacimento", "los angeles", "cabrero", "yumbel"],
    "coronel": ["talcahuano", "hualpen", "lota", "penco", "tome", "concepcion", "san pedro de la paz", "chiguayante", "florida", "hualqui", "santa juana", "nacimento", "los angeles", "cabrero", "yumbel"],
    "penco": ["talcahuano", "hualpen", "coronel", "tome", "lota", "concepcion", "san pedro de la paz", "chiguayante", "florida", "hualqui", "santa juana", "nacimento", "los angeles", "cabrero", "yumbel"],
    "los angeles": ["nacimento", "cabrero", "yumbel", "santa barbara", "quilaco", "negrete", "nacimiento", "concepcion", "talcahuano", "san pedro de la paz", "chiguayante", "hualpen", "coronel", "penco", "tome"],
    # Add more as needed
}


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
    if not s:
        return ""
    s = s.strip().lower().replace("_", " ").replace("-", " ")
    # Remove accents
    trans = str.maketrans('áéíóúüñ', 'aeiouun')
    s = s.translate(trans)
    return " ".join(s.split())


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
    logger.info("🔍 pick_best_service_for_intent | intent_id=%s | comuna=%s | candidates=%s", intent_id, comuna, candidates)
    if not candidates:
        logger.info("❌ No candidates for intent")
        return None

    normalized_comuna = _norm(comuna)
    logger.info("🔄 Normalized comuna | original=%s | normalized=%s", comuna, normalized_comuna)
    if not normalized_comuna:
        logger.info("❌ Normalized comuna is empty")
        return None

    # Handle abbreviations
    if normalized_comuna == "conce":
        normalized_comuna = "concepcion"
    normalized_comuna = COMUNA_ALIASES.get(normalized_comuna, normalized_comuna)
    logger.info("📝 Final normalized comuna | %s", normalized_comuna)

    rows = (
        db.query(Provider.id, Provider.service, Provider.rating_avg, ProviderCoverage.comuna)
        .join(ProviderCoverage, ProviderCoverage.provider_id == Provider.id)
        .filter(Provider.active == True)
        .filter(Provider.service.in_(candidates))
        .all()
    )
    logger.info("📊 Query results | rows_count=%s", len(rows))
    for row in rows:
        logger.info("📋 Row | id=%s | service=%s | rating=%s | cov_comuna=%s", row[0], row[1], row[2], row[3])
    
    # Filter by normalized comuna
    filtered_rows = []
    for provider_id, svc, rat, cov_comuna in rows:
        norm_cov = _norm(cov_comuna) if cov_comuna else ""
        logger.info("🔍 Checking comuna | cov_comuna=%s | norm_cov=%s | match=%s", cov_comuna, norm_cov, norm_cov == normalized_comuna)
        if cov_comuna and _norm(cov_comuna) == normalized_comuna:
            filtered_rows.append((provider_id, svc, rat))
    
    logger.info("✅ Filtered rows | count=%s", len(filtered_rows))
    rows = filtered_rows
    if not rows:
        return None

    agg: dict[str, dict[str, float]] = {}
    seen_provider_ids: set[int] = set()
    for provider_id, svc, rat in rows:
        if provider_id in seen_provider_ids:
            continue
        seen_provider_ids.add(provider_id)
        a = agg.setdefault(svc, {"n": 0.0, "sum": 0.0})
        a["n"] += 1.0
        a["sum"] += float(rat or 0.0)

    best_svc = None
    best_key = None
    for svc, a in agg.items():
        n = a["n"]
        avg = (a["sum"] / n) if n else 0.0
        key = (n, avg)
        if best_key is None:
            best_key = key
            best_svc = svc
        elif key > best_key:
            best_key = key
            best_svc = svc
def get_available_comunas_for_intent(db: Session, intent_id: str, intent_to_services: dict[str, List[str]], reference_comuna: Optional[str] = None) -> List[str]:
    candidates = intent_to_services.get(intent_id) or []
    logger.info("🌍 get_available_comunas_for_intent | intent_id=%s | candidates=%s | reference_comuna=%s", intent_id, candidates, reference_comuna)
    if not candidates:
        logger.info("❌ No candidates for comunas")
        return []

    rows_cov = (
        db.query(func.distinct(ProviderCoverage.comuna))
        .join(Provider, Provider.id == ProviderCoverage.provider_id)
        .filter(Provider.active == True)
        .filter(Provider.service.in_(candidates))
        .all()
    )
    comunas_cov = [row[0] for row in rows_cov if row[0]]
    logger.info("📍 Available comunas | %s", comunas_cov)

    all_comunas = set(comunas_cov)
    
    if reference_comuna:
        ref_norm = _norm(reference_comuna)
        # Handle abbreviations
        if ref_norm == "conce":
            ref_norm = "concepcion"
        ref_norm = COMUNA_ALIASES.get(ref_norm, ref_norm)
        proximity_list = PROXIMITY_MAP.get(ref_norm, [])
        # Sort by proximity: first those in proximity_list, then others
        sorted_comunas = []
        for prox in proximity_list:
            if prox in all_comunas:
                sorted_comunas.append(prox)
        for com in sorted(all_comunas):
            if com not in sorted_comunas:
                sorted_comunas.append(com)
        return sorted_comunas
    else:
        return sorted(list(all_comunas))
