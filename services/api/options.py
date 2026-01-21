from __future__ import annotations

from sqlalchemy.orm import Session

from services.common.logging_config import setup_logging
from services.api.matching import find_top_providers
from services.api.models import Lead, LeadOffer, Provider
from services.api.settings import settings
from services.api.whatsapp_cloud import send_text

logger = setup_logging("options")


def _options_limit() -> int:
    limit = settings.top_providers_limit
    if isinstance(limit, int) and limit > 0:
        return limit
    return 0


async def _send_options(db: Session, wa_id: str, lead: Lead) -> None:
    if not lead.service or not lead.comuna:
        await send_text(
            wa_id,
            "Necesito el servicio y la comuna para buscar profesionales. ¿Me repites tu necesidad?",
        )
        return

    limit = _options_limit()
    providers = find_top_providers(
        db=db,
        service=lead.service,
        comuna=lead.comuna,
        limit=limit,
    )

    if not providers:
        lead.status = "WAIT_SERVICE"
        db.commit()
        await send_text(
            wa_id,
            "No encontré profesionales disponibles para esa necesidad en tu comuna.\n"
            "Describe el problema con más detalle o prueba otra comuna.",
        )
        return

    if limit > 0:
        providers = providers[:limit]

    db.query(LeadOffer).filter(LeadOffer.lead_id == lead.id).delete()
    db.commit()

    for idx, p in enumerate(providers, start=1):
        offer = LeadOffer(lead_id=lead.id, provider_id=p.id, rank=idx)
        db.add(offer)
    db.commit()

    lines = [f"Tengo {len(providers)} profesionales que pueden ayudarte en {lead.comuna}:"]
    for idx, p in enumerate(providers, start=1):
        rating = f"{p.rating_avg:.1f}" if p.rating_count > 0 else "sin evaluaciones"
        rating_meta = (
            f"⭐ {rating} ({p.rating_count} evals)" if p.rating_count > 0 else "⭐ sin evaluaciones"
        )
        lines.append(f"{idx}) {p.name} — {rating_meta}")

    lines.append("Responde con el número del profesional que prefieras.")
    await send_text(wa_id, "\n".join(lines))
    logger.info("Options sent | lead_id=%s | count=%s", lead.id, len(providers))
