import httpx
from services.common.logging_config import setup_logging
from .settings import settings

logger = setup_logging("api")


def _is_configured() -> bool:
    return bool(settings.whatsapp_phone_number_id and settings.whatsapp_access_token)


async def send_text(to_wa_id: str, text: str) -> dict:
    if not _is_configured():
        logger.warning("[MOCK SEND] WHATSAPP no configurado. to=%s text=%s", to_wa_id, text)
        return {"mock": True, "to": to_wa_id, "text": text}

    url = f"https://graph.facebook.com/{settings.whatsapp_graph_version}/{settings.whatsapp_phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_access_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_wa_id,
        "type": "text",
        "text": {"body": text},
    }

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(url, headers=headers, json=payload)

        # Log útil SIEMPRE (para debug)
        logger.info("WA SEND status=%s to=%s", r.status_code, to_wa_id)

        # Si falla, loguea el cuerpo (Meta siempre explica el motivo)
        if r.status_code >= 400:
            logger.error("WA SEND ERROR status=%s body=%s", r.status_code, r.text)

        r.raise_for_status()
        return r.json()

    except Exception:
        logger.exception("WA SEND EXCEPTION to=%s", to_wa_id)
        raise
