from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class IntentDef:
    id: str
    label: str
    aliases: List[str]
    keywords: List[str]


def load_intents(catalog_path: Optional[str] = None) -> List[IntentDef]:
    if not catalog_path:
        here = os.path.dirname(__file__)
        catalog_path = os.path.join(here, "..", "catalog", "intents_es.json")
        catalog_path = os.path.abspath(catalog_path)

    with open(catalog_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    intents: List[IntentDef] = []
    for it in data.get("intents", []):
        intents.append(
            IntentDef(
                id=str(it.get("id")),
                label=str(it.get("label")),
                aliases=[str(x) for x in it.get("aliases", []) if x],
                keywords=[str(x) for x in it.get("keywords", []) if x],
            )
        )
    return intents


def intents_by_id(intents: List[IntentDef]) -> Dict[str, IntentDef]:
    return {i.id: i for i in intents if i.id}
