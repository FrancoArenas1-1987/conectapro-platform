from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from services.common.logging_config import setup_logging
from services.api.settings import settings
from services.api.models import Lead, Provider, Customer, ProviderState
from services.api.whatsapp_cloud import send_text

logger = setup_logging("worker")

engine = create_engine(settings.database_url, pool_pre_ping=True, echo=False)


def _now() -> datetime:
    return datetime.utcnow()


def _is_due(dt: datetime | None, *, hours: int) -> bool:
    if not dt:
        return False
    return dt.replace(tzinfo=None) <= (_now() - timedelta(hours=hours))


async def _send_contact_followup(db: Session, lead: Lead, provider: Provider):
    lead.status = "CONTACT_CONFIRM_PENDING"
    lead.followup_stage = "CONTACT"
    lead.followup_sent_at = _now()
    db.commit()

    # barrera práctica: quedan bloqueados hasta responder (o hasta que venza el bloqueo, si no responden)
    block_until = _now() + timedelta(days=settings.practical_block_days)

    cust = db.query(Customer).filter(Customer.wa_id == lead.customer_wa_id).first()
    if cust:
        cust.pending_lead_id = lead.id
        cust.blocked_until = block_until
        db.commit()

    provider.blocked_until = block_until
    db.commit()

    st = db.query(ProviderState).filter(ProviderState.provider_id == provider.id).first()
    if not st:
        st = ProviderState(provider_id=provider.id)
        db.add(st)
        db.commit()
        db.refresh(st)
    st.pending_lead_id = lead.id
    st.pending_question = "CONTACT"
    db.commit()

    await send_text(
        lead.customer_wa_id,
        "Seguimiento ConectaPro 👋\n"
        "¿Pudiste *contactar* al profesional?\n"
        "Responde:\n1) SI\n2) NO",
    )

    if provider.whatsapp_e164:
        await send_text(
            provider.whatsapp_e164,
            "Seguimiento ConectaPro 👋\n"
            f"LeadID: {lead.id}\n"
            "¿Pudiste *contactar* al cliente?\n"
            "Responde:\n1) SI\n2) NO",
        )


async def _send_service_followup(db: Session, lead: Lead, provider: Provider):
    lead.status = "SERVICE_CONFIRM_PENDING"
    lead.followup_stage = "SERVICE"
    lead.followup_sent_at = _now()
    db.commit()

    block_until = _now() + timedelta(days=settings.practical_block_days)
    cust = db.query(Customer).filter(Customer.wa_id == lead.customer_wa_id).first()
    if cust:
        cust.pending_lead_id = lead.id
        cust.blocked_until = block_until
        db.commit()

    provider.blocked_until = block_until
    db.commit()

    st = db.query(ProviderState).filter(ProviderState.provider_id == provider.id).first()
    if not st:
        st = ProviderState(provider_id=provider.id)
        db.add(st)
        db.commit()
        db.refresh(st)
    st.pending_lead_id = lead.id
    st.pending_question = "SERVICE"
    db.commit()

    await send_text(
        lead.customer_wa_id,
        "Seguimiento ConectaPro 👋\n"
        "¿Se *realizó* el servicio?\n"
        "Responde:\n1) SI\n2) NO",
    )

    if provider.whatsapp_e164:
        await send_text(
            provider.whatsapp_e164,
            "Seguimiento ConectaPro 👋\n"
            f"LeadID: {lead.id}\n"
            "¿Se *realizó* el servicio?\n"
            "Responde:\n1) SI\n2) NO",
        )


async def _send_rating_request(db: Session, lead: Lead):
    lead.status = "RATING_PENDING"
    lead.followup_stage = "RATING"
    lead.followup_sent_at = _now()
    db.commit()

    block_until = _now() + timedelta(days=settings.practical_block_days)
    cust = db.query(Customer).filter(Customer.wa_id == lead.customer_wa_id).first()
    if cust:
        cust.pending_lead_id = lead.id
        cust.blocked_until = block_until
        db.commit()

    await send_text(
        lead.customer_wa_id,
        "Último paso 🙌\n"
        "Evalúa al profesional (solo si el servicio se realizó):\n"
        "1-5 estrellas (ej: '5 excelente')\n"
        "0 para omitir",
    )


def _clear_provider_state(db: Session, provider_id: int):
    st = db.query(ProviderState).filter(ProviderState.provider_id == provider_id).first()
    if st:
        st.pending_lead_id = None
        st.pending_question = None
        db.commit()


async def tick():
    with Session(engine) as db:
        # 1) Programar followup de contacto para leads CONNECTED
        leads_connected = db.query(Lead).filter(Lead.status == "CONNECTED").all()
        for lead in leads_connected:
            if lead.connected_at and _is_due(lead.connected_at, hours=settings.followup_contact_after_hours):
                if not lead.provider_id:
                    continue
                provider = db.query(Provider).filter(Provider.id == lead.provider_id).first()
                if not provider or not provider.active:
                    continue
                logger.info("Followup CONTACT | lead_id=%s", lead.id)
                await _send_contact_followup(db, lead, provider)

        # 2) Avanzar o cerrar CONTACT_CONFIRM_PENDING
        leads_contact = db.query(Lead).filter(Lead.status == "CONTACT_CONFIRM_PENDING").all()
        for lead in leads_contact:
            if not lead.provider_id:
                continue
            provider = db.query(Provider).filter(Provider.id == lead.provider_id).first()
            if not provider:
                continue

            # Si alguno dijo NO, cerramos
            if lead.user_contact_confirmed is False or lead.provider_contact_confirmed is False:
                lead.status = "CLOSED"
                db.commit()
                _clear_provider_state(db, provider.id)
                provider.blocked_until = None
                db.commit()
                cust = db.query(Customer).filter(Customer.wa_id == lead.customer_wa_id).first()
                if cust and cust.pending_lead_id == lead.id:
                    cust.pending_lead_id = None
                    cust.blocked_until = None
                    db.commit()
                continue

            # Si ambos confirmaron SI
            if lead.user_contact_confirmed is True and lead.provider_contact_confirmed is True:
                logger.info("CONTACT ok -> SERVICE | lead_id=%s", lead.id)
                await _send_service_followup(db, lead, provider)
                continue

            # Si falta respuesta, re-preguntar cada 24h (sin spamear)
            if lead.followup_sent_at and _is_due(lead.followup_sent_at, hours=24):
                lead.followup_sent_at = _now()
                db.commit()
                if lead.user_contact_confirmed is None:
                    await send_text(lead.customer_wa_id, "Recordatorio: responde 1=SI 2=NO ¿Pudiste contactar al profesional?")
                if lead.provider_contact_confirmed is None and provider.whatsapp_e164:
                    await send_text(provider.whatsapp_e164, f"Recordatorio LeadID {lead.id}: responde 1=SI 2=NO ¿Pudiste contactar al cliente?")

        # 3) Avanzar o cerrar SERVICE_CONFIRM_PENDING
        leads_service = db.query(Lead).filter(Lead.status == "SERVICE_CONFIRM_PENDING").all()
        for lead in leads_service:
            if not lead.provider_id:
                continue
            provider = db.query(Provider).filter(Provider.id == lead.provider_id).first()
            if not provider:
                continue

            if lead.user_service_confirmed is False or lead.provider_service_confirmed is False:
                lead.status = "CLOSED"
                db.commit()
                _clear_provider_state(db, provider.id)
                provider.blocked_until = None
                db.commit()
                cust = db.query(Customer).filter(Customer.wa_id == lead.customer_wa_id).first()
                if cust and cust.pending_lead_id == lead.id:
                    cust.pending_lead_id = None
                    cust.blocked_until = None
                    db.commit()
                continue

            if lead.user_service_confirmed is True and lead.provider_service_confirmed is True:
                logger.info("SERVICE ok -> RATING | lead_id=%s", lead.id)
                _clear_provider_state(db, provider.id)
                provider.blocked_until = None
                db.commit()
                await _send_rating_request(db, lead)
                continue

            if lead.followup_sent_at and _is_due(lead.followup_sent_at, hours=24):
                lead.followup_sent_at = _now()
                db.commit()
                if lead.user_service_confirmed is None:
                    await send_text(lead.customer_wa_id, "Recordatorio: responde 1=SI 2=NO ¿Se realizó el servicio?")
                if lead.provider_service_confirmed is None and provider.whatsapp_e164:
                    await send_text(provider.whatsapp_e164, f"Recordatorio LeadID {lead.id}: responde 1=SI 2=NO ¿Se realizó el servicio?")


def main():
    logger.info("Worker iniciado")
    time.sleep(3)

    while True:
        try:
            asyncio.run(tick())
        except Exception:
            logger.exception("Worker tick falló")
        time.sleep(30)


if __name__ == "__main__":
    main()
