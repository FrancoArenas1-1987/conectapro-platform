from fastapi import APIRouter, Request

from services.common.logging_config import setup_logging
from services.api.db import SessionLocal
from services.api.models import InboundMessage
from services.api.settings import settings
from services.api.leads_flow import handle_user_incoming

router = APIRouter()
logger = setup_logging("whatsapp_webhook")


def _safe_get(d, *keys, default=None):
    cur = d
    for k in keys:
        try:
            cur = cur[k]
        except Exception:
            return default
    return cur


@router.post("/webhooks/whatsapp")
async def whatsapp_webhook(request: Request):
    """Receives WhatsApp Cloud API webhooks.

    Logs:
      - event type (messages/statuses)
      - wa_id, msg_id, type, text
      - unexpected payload shapes
      - exceptions inside processing

    Returns 200 OK even on internal errors to avoid WhatsApp retry storms.
    """

    try:
        payload = await request.json()
    except Exception as e:
        logger.exception("❌ No se pudo leer JSON del webhook: %s", e)
        return {"ok": True}

    value = _safe_get(payload, "entry", 0, "changes", 0, "value", default={})
    phone_number_id = value.get("metadata", {}).get("phone_number_id")
    has_messages = "messages" in value
    has_statuses = "statuses" in value

    logger.info(
        "📩 Webhook event | phone_number_id=%s | has_messages=%s | has_statuses=%s",
        phone_number_id,
        has_messages,
        has_statuses,
    )

    # Status updates (delivered/read/etc.)
    if has_statuses and not has_messages:
        statuses = value.get("statuses", [])
        kinds = [s.get("status") for s in statuses]
        logger.info("ℹ️ Status event | kinds=%s", kinds)
        for status in statuses:
            if status.get("status") == "failed":
                logger.warning(
                    "❌ WA message failed | id=%s | recipient_id=%s | errors=%s",
                    status.get("id"),
                    status.get("recipient_id"),
                    status.get("errors"),
                )
        return {"ok": True}

    if not has_messages:
        logger.info("ℹ️ Event without messages (ignored)")
        return {"ok": True}

    # Extract first message
    message = value["messages"][0]
    wa_id = _safe_get(value, "contacts", 0, "wa_id", default=None)
    msg_id = message.get("id")
    mtype = message.get("type")

    text = None
    if mtype == "text":
        text = _safe_get(message, "text", "body", default=None)
    elif mtype == "interactive":
        list_reply = _safe_get(message, "interactive", "list_reply", default={})
        button_reply = _safe_get(message, "interactive", "button_reply", default={})
        reply_title = list_reply.get("title") or button_reply.get("title")
        reply_id = list_reply.get("id") or button_reply.get("id")
        text = reply_title or reply_id
        if reply_id and reply_id.startswith("comuna:"):
            text = reply_id.split("comuna:", 1)[1]

    logger.info(
        "💬 Incoming message | wa_id=%s | msg_id=%s | type=%s | text=%s",
        wa_id,
        msg_id,
        mtype,
        text,
    )

    if not wa_id:
        logger.warning("⚠️ Missing wa_id in payload; cannot process")
        return {"ok": True}

    if not text:
        logger.info("ℹ️ Non-text message (ignored) | type=%s", mtype)
        return {"ok": True}

    db = None
    try:
        db = SessionLocal()
        if msg_id:
            exists = (
                db.query(InboundMessage)
                .filter(InboundMessage.customer_wa_id == wa_id)
                .filter(InboundMessage.message_id == msg_id)
                .first()
            )
            if exists:
                logger.info("♻️ Duplicate message ignored | wa_id=%s | msg_id=%s", wa_id, msg_id)
                return {"ok": True}
            db.add(InboundMessage(customer_wa_id=wa_id, message_id=msg_id, text=text or ""))
            db.commit()
        await handle_user_incoming(db=db, wa_id=wa_id, text=text, raw_message=message)
        logger.info("✅ Processed message | wa_id=%s | msg_id=%s", wa_id, msg_id)
    except Exception as e:
        logger.exception(
            "❌ Error procesando mensaje | wa_id=%s | msg_id=%s | err=%s",
            wa_id,
            msg_id,
            e,
        )
        return {"ok": True}
    finally:
        try:
            if db is not None:
                db.close()
        except Exception:
            pass

    return {"ok": True}


@router.get("/webhooks/whatsapp")
async def whatsapp_verify(request: Request):
    params = dict(request.query_params)
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == settings.whatsapp_verify_token and challenge:
        return int(challenge)
    return {"ok": False}
