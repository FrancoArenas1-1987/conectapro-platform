from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Dict, List, Tuple

from .catalog import IntentDef


def _norm(text: str) -> str:
    t = (text or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    return t


def _similar(a: str, b: str) -> float:
    a = _norm(a)
    b = _norm(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def score_intent(text: str, intent: IntentDef) -> Tuple[float, Dict[str, int]]:
    """
    Score simple:
      - hits por keywords (frases y tokens)
      - hits por aliases (contención + fuzzy)
    """
    t = _norm(text)
    if not t:
        return 0.0, {"kw": 0, "alias": 0}

    kw_hits = 0
    alias_hits = 0

    for kw in intent.keywords:
        k = _norm(kw)
        if not k:
            continue
        if " " in k:
            if k in t:
                kw_hits += 2
        else:
            if re.search(rf"\b{re.escape(k)}\b", t):
                kw_hits += 1

    for al in intent.aliases:
        a = _norm(al)
        if not a:
            continue
        if a in t:
            alias_hits += 3
            continue
        if len(a) <= 30:
            sim = _similar(t, a)
            if sim >= 0.82:
                alias_hits += 2

    raw = (kw_hits * 1.0) + (alias_hits * 1.2)
    denom = max(6.0, (len(t.split()) / 6.0) + 6.0)
    score = min(1.0, raw / denom)

    return score, {"kw": kw_hits, "alias": alias_hits}


def top_intents(text: str, intents: List[IntentDef], k: int = 3) -> List[Tuple[str, float, Dict[str, int]]]:
    scored: List[Tuple[str, float, Dict[str, int]]] = []
    for it in intents:
        s, dbg = score_intent(text, it)
        if s > 0:
            scored.append((it.id, s, dbg))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:k]
