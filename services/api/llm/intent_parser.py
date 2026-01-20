from __future__ import annotations

import json

from services.common.logging_config import setup_logging
from services.api.settings import settings
from .llm_client import chat_json, LLMError
from .prompt_templates import intent_system_prompt

logger = setup_logging("api")


def _validate(payload: dict, allow_services: list[str], allow_urgency: list[str]) -> dict:
    # Defaults seguros
    out = {
        "intent": "unknown",
        "service": None,
        "comuna": None,
        "problem_type": None,
        "urgency": None,
        "address": None,
        "consent": None,
        "confidence": 0.0,
    }

    if not isinstance(payload, dict):
        return out

    out["intent"] = payload.get("intent") if payload.get("intent") in {
        "create_lead", "update_lead", "ask_status", "cancel", "smalltalk", "unknown"
    } else "unknown"

    svc = payload.get("service")
    if svc in allow_services:
        out["service"] = svc

    urg = payload.get("urgency")
    if urg in allow_urgency:
        out["urgency"] = urg

    for k in ("comuna", "problem_type", "address"):
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()

    consent = payload.get("consent")
    if consent in ("yes", "no"):
        out["consent"] = consent

    conf = payload.get("confidence")
    try:
        conf = float(conf)
    except Exception:
        conf = 0.0
    out["confidence"] = max(0.0, min(1.0, conf))
    return out


async def parse_intent_safe(text: str, allow_services: list[str], allow_urgency: list[str], min_confidence: float) -> dict | None:
    """
    Devuelve dict validado o None si falla / confidence baja.
    """
    if settings.openai_enabled != 1:
        return None

    system = intent_system_prompt(allow_services, allow_urgency)

    try:
        raw = await chat_json(system=system, user=text)
        payload = json.loads(raw)
        out = _validate(payload, allow_services, allow_urgency)

        if out["confidence"] < min_confidence:
            logger.info("LLM confidence baja (%.2f), se ignora", out["confidence"])
            return None

        return out

    except (LLMError, json.JSONDecodeError) as e:
        logger.warning("LLM parse falló (fallback determinístico): %s", e)
        return None
    except Exception as e:
        logger.exception("LLM error inesperado (fallback determinístico): %s", e)
        return None
