from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from services.common.logging_config import setup_logging
from services.api.llm_orchestrator import get_orchestrator
from services.api.matching import list_available_services
from services.api.models import Lead, Provider, ProviderCoverage
from services.api.settings import settings
from services.api.whatsapp_cloud import send_text

logger = setup_logging("llm_router")


def _list_available_comunas(db: Session) -> list[str]:
    rows_cov = (
        db.query(func.distinct(ProviderCoverage.comuna))
        .join(Provider, Provider.id == ProviderCoverage.provider_id)
        .filter(Provider.active == True)
        .all()
    )
    rows_direct = (
        db.query(func.distinct(Provider.comuna))
        .filter(Provider.active == True)
        .all()
    )
    comunas = {row[0] for row in rows_cov if row[0]}
    comunas |= {row[0] for row in rows_direct if row[0]}
    return sorted(comunas)


async def try_handle_llm(
    *,
    db: Session,
    wa_id: str,
    text: str,
    state: Any,
    lead: Lead,
) -> bool:
    if not settings.openai_enabled or not settings.llm_orchestrator_enabled:
        return False

    if state.step in {"WAIT_CHOICE", "WAIT_CONSENT", "CONNECTED"}:
        return False

    try:
        orchestrator = get_orchestrator()
    except Exception as exc:
        logger.warning("LLM orchestrator unavailable: %s", exc)
        return False

    services = list_available_services(db)
    comunas = _list_available_comunas(db)
    context = {
        "step": state.step,
        "current_service": lead.service,
        "current_comuna": lead.comuna,
        "lead_id": lead.id,
    }

    result = orchestrator.orchestrate_response(text, context, db, services, comunas)
    actions = result.get("actions", [])
    response_text = result.get("response") or ""

    for action in actions:
        if action.get("type") == "send_options":
            from services.api.options import _send_options

            lead.status = "WAIT_CHOICE"
            state.step = "WAIT_CHOICE"
            db.commit()
            await _send_options(db, wa_id, lead)
            if lead.status == "WAIT_SERVICE":
                state.step = "WAIT_SERVICE"
            elif lead.status == "WAIT_CHOICE":
                state.step = "WAIT_CHOICE"
            db.commit()

    if response_text:
        await send_text(wa_id, response_text)
        return True

    if actions:
        return True

    return False
