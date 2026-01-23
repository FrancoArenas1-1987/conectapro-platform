from __future__ import annotations

from typing import Optional

import httpx

from services.common.logging_config import setup_logging
from ..settings import settings
from .catalog import IntentDef
from .types import NLUResult, NLUEntities

logger = setup_logging("nlu")


def _json_schema(allowed_intent_ids: list[str]) -> dict:
    return {
        "name": "conectapro_nlu",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "intent_id": {"type": ["string", "null"], "enum": allowed_intent_ids + [None]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "entities": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "comuna": {"type": ["string", "null"]},
                        "device": {"type": ["string", "null"]},
                        "urgency": {"type": ["string", "null"]},
                        "symptoms": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["comuna", "device", "urgency", "symptoms"],
                },
                "need_clarification": {"type": "boolean"},
                "clarifying_question": {"type": ["string", "null"]},
                "clarifying_options": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "intent_id",
                "confidence",
                "entities",
                "need_clarification",
                "clarifying_question",
                "clarifying_options",
            ],
        },
        "strict": True,
    }


async def try_llm_parse(text: str, intents: list[IntentDef]) -> Optional[NLUResult]:
    if not settings.openai_enabled:
        return None
    if not settings.openai_api_key:
        logger.warning("openai_enabled=1 pero openai_api_key vacío; se omite LLM.")
        return None

    allowed = [i.id for i in intents if i.id]
    schema = _json_schema(allowed)

    instructions = (
        "Eres un clasificador de intención para ConectaPro.\n"
        "Debes elegir intent_id SOLO desde la lista permitida.\n"
        "Si el texto no es claro o hay 2 opciones probables, marca need_clarification=true.\n"
        "NO inventes comunas; si no está explícita, deja comuna=null.\n"
        "Puedes normalizar abreviaciones explícitas (ej: 'conce' -> 'Concepción', 'thno' -> 'Talcahuano').\n"
        "Responde estrictamente según el JSON schema."
    )

    payload = {
        "model": settings.openai_model,
        "input": [
            {"role": "system", "content": instructions},
            {"role": "user", "content": text},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "strict": True,
                "schema": schema["schema"],
                "name": schema["name"],
            }
        },
        "store": False,
    }

    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=settings.openai_timeout_seconds) as client:
            r = await client.post("https://api.openai.com/v1/responses", json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        logger.warning("LLM parse falló: %s", e)
        return NLUResult(intent_id=None, confidence=0.0, method="llm", debug={"error": str(e)})

    # Respuestas API: buscamos el “output_text” (fallback) o estructura parseada simple
    # (Esto lo dejamos robusto: si cambia la forma exacta, igual no rompe: cae a rules)
    raw_text = ""
    try:
        out = data.get("output", [])
        for item in out:
            if item.get("type") == "message":
                content = item.get("content", [])
                for c in content:
                    if c.get("type") in ("output_text", "text"):
                        raw_text += c.get("text", "")
    except Exception:
        raw_text = ""

    if not raw_text:
        # no pudimos extraer; no rompemos
        return NLUResult(intent_id=None, confidence=0.0, method="llm", debug={"raw": data})

    try:
        obj = httpx.Response(200, text=raw_text).json()
    except Exception:
        return NLUResult(intent_id=None, confidence=0.0, method="llm", debug={"raw_text": raw_text})

    try:
        entities = NLUEntities(**obj.get("entities", {}))
        res = NLUResult(
            intent_id=obj.get("intent_id"),
            confidence=float(obj.get("confidence", 0.0)),
            entities=entities,
            need_clarification=bool(obj.get("need_clarification", False)),
            clarifying_question=obj.get("clarifying_question"),
            clarifying_options=list(obj.get("clarifying_options", [])),
            method="llm",
            debug={"llm": True},
        )
        return res
    except Exception as e:
        return NLUResult(intent_id=None, confidence=0.0, method="llm", debug={"parse_error": str(e), "obj": obj})
