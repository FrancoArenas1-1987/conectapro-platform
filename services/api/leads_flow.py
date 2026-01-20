from sqlalchemy.orm import Session

from services.common.logging_config import setup_logging
from services.api.matching import list_available_services
from services.api.models import Lead, ConversationState
from services.api.whatsapp_cloud import send_text

from services.api.nlu.engine import NLUEngine, build_service_intent_index, pick_best_service_for_intent

logger = setup_logging("leads_flow")

NLU = NLUEngine()

INTRO = (
    "Hola 👋 Soy ConectaPro.\n"
    "Te ayudo a conectar con profesionales según tu necesidad y comuna.\n\n"
    "Escríbeme qué necesitas, por ejemplo:\n"
    "• Necesito un electricista\n"
    "• Busco kinesiólogo\n"
    "• Abogado por herencia"
)


def _is_greeting(text: str) -> bool:
    t = (text or "").strip().lower()
    return t in {
        "hola", "hola!", "buenas", "buenos dias", "buenos días",
        "buenas tardes", "buenas noches", "hello", "hi"
    }


def _is_intent_marker(s: str) -> bool:
    return bool(s) and s.startswith("INTENT:")


def _get_intent_id(s: str):
    if not _is_intent_marker(s):
        return None
    return s.split("INTENT:", 1)[1].strip() or None


def _pick_1_or_2(text: str):
    t = (text or "").strip()
    return t if t in ("1", "2") else None


async def handle_user_incoming(db: Session, wa_id: str, text: str, raw_message=None):
    logger.info("➡️ Enter | wa_id=%s | text=%s", wa_id, text)

    # Load / create conversation state
    state = db.query(ConversationState).filter(ConversationState.customer_wa_id == wa_id).first()
    if not state:
        state = ConversationState(
            customer_wa_id=wa_id,
            step="START",
            lead_id=None
        )

        db.add(state)
        db.commit()
        logger.info("🆕 Created ConversationState | wa_id=%s | step=START", wa_id)

    # Load / create current lead
    lead = db.query(Lead).filter(Lead.customer_wa_id== wa_id).order_by(Lead.id.desc()).first()
    if not lead:
        lead = Lead(customer_wa_id=wa_id, status="OPEN")
        db.add(lead)
        db.commit()
        logger.info("🆕 Created Lead | wa_id=%s | lead_id=%s", wa_id, lead.id)

    logger.info(
        "🧠 State snapshot | wa_id=%s | step=%s | lead_id=%s | status=%s | service=%s | comuna=%s",
        wa_id, state.step, lead.id, lead.status, lead.service, lead.comuna
    )

    # Service universe from DB (Provider.service values)
    services = list_available_services(db)
    logger.info("📚 Services loaded | count=%s", len(services) if services else 0)

    # Build index between intents and existing services
    _, intent_to_services = build_service_intent_index(services, NLU.intents)

    # Hybrid parse (rules-first)
    nlu = await NLU.parse_hybrid(text)
    logger.info(
        "🧩 NLU result | intent_id=%s | confidence=%s | need_clarification=%s",
        getattr(nlu, "intent_id", None), getattr(nlu, "confidence", None), getattr(nlu, "need_clarification", None)
    )

    # STEP: START
    if state.step == "START":
        if _is_greeting(text):
            logger.info("👋 Greeting detected -> sending INTRO")
            await send_text(wa_id, INTRO)
            return

        lead.problem_type = (text or "").strip()[:160]

        if nlu.need_clarification and nlu.clarifying_question:
            logger.info("❓ Need clarification -> WAIT_INTENT_CLARIFICATION")
            state.step = "WAIT_INTENT_CLARIFICATION"
            state.temp_data = {"intent_options": nlu.clarifying_options}
            lead.status = "WAIT_SERVICE"
            db.commit()
            await send_text(wa_id, nlu.clarifying_question)
            return

        if nlu.intent_id:
            logger.info("✅ Intent detected -> WAIT_COMUNA | intent_id=%s", nlu.intent_id)
            lead.service = f"INTENT:{nlu.intent_id}"
            lead.status = "WAIT_COMUNA"
            state.step = "WAIT_COMUNA"
            db.commit()
            await send_text(wa_id, "Perfecto. ¿En qué comuna necesitas al profesional?")
            return

        service_guess = _match_service_from_text(text, services) if services else None
        if service_guess:
            logger.info("✅ Legacy service match -> WAIT_COMUNA | service=%s", service_guess)
            lead.service = service_guess
            lead.status = "WAIT_COMUNA"
            state.step = "WAIT_COMUNA"
            db.commit()
            await send_text(wa_id, "Perfecto. ¿En qué comuna necesitas al profesional?")
            return

        logger.info("🤷 No match -> WAIT_SERVICE")
        state.step = "WAIT_SERVICE"
        lead.status = "WAIT_SERVICE"
        db.commit()
        await send_text(
            wa_id,
            "No logré identificar tu necesidad 😕\n"
            "Descríbela con un poco más de detalle.\n"
            "Ejemplo: 'Mi notebook no prende' / 'Se me gotea el techo' / 'Busco abogado por herencia'."
        )
        return

    # STEP: WAIT_INTENT_CLARIFICATION
    if state.step == "WAIT_INTENT_CLARIFICATION":
        options = (state.temp_data or {}).get("intent_options", [])
        choice = _pick_1_or_2(text)
        logger.info("🧾 Clarification choice | choice=%s | options=%s", choice, options)

        if not choice:
            await send_text(wa_id, "Por favor responde 1 o 2 🙂")
            return

        idx = int(choice) - 1
        if idx >= len(options):
            await send_text(wa_id, "Opción inválida. Responde 1 o 2 🙂")
            return

        chosen_label = options[idx]
        chosen_id = None
        for it in NLU.intents:
            if it.label == chosen_label:
                chosen_id = it.id
                break

        logger.info("✅ Clarification resolved | label=%s | intent_id=%s", chosen_label, chosen_id)

        if not chosen_id:
            logger.warning("⚠️ Could not map label to intent_id -> WAIT_SERVICE")
            state.step = "WAIT_SERVICE"
            lead.status = "WAIT_SERVICE"
            db.commit()
            await send_text(wa_id, "No pude resolver tu opción. Describe tu necesidad nuevamente.")
            return

        lead.service = f"INTENT:{chosen_id}"
        lead.status = "WAIT_COMUNA"
        state.step = "WAIT_COMUNA"
        state.temp_data = {}
        db.commit()
        await send_text(wa_id, "Gracias 👍 ¿En qué comuna necesitas al profesional?")
        return

    # STEP: WAIT_SERVICE
    if state.step == "WAIT_SERVICE":
        nlu2 = await NLU.parse_hybrid(text)
        logger.info(
            "🧩 NLU2 result | intent_id=%s | need_clarification=%s",
            getattr(nlu2, "intent_id", None), getattr(nlu2, "need_clarification", None)
        )

        if nlu2.need_clarification and nlu2.clarifying_question:
            logger.info("❓ Still ambiguous -> WAIT_INTENT_CLARIFICATION")
            state.step = "WAIT_INTENT_CLARIFICATION"
            state.temp_data = {"intent_options": nlu2.clarifying_options}
            db.commit()
            await send_text(wa_id, nlu2.clarifying_question)
            return

        if nlu2.intent_id:
            logger.info("✅ Intent detected in WAIT_SERVICE -> WAIT_COMUNA | intent_id=%s", nlu2.intent_id)
            lead.service = f"INTENT:{nlu2.intent_id}"
            lead.status = "WAIT_COMUNA"
            state.step = "WAIT_COMUNA"
            db.commit()
            await send_text(wa_id, "Perfecto. ¿En qué comuna necesitas al profesional?")
            return

        service_guess = _match_service_from_text(text, services) if services else None
        if service_guess:
            logger.info("✅ Legacy service match in WAIT_SERVICE -> WAIT_COMUNA | service=%s", service_guess)
            lead.service = service_guess
            lead.status = "WAIT_COMUNA"
            state.step = "WAIT_COMUNA"
            db.commit()
            await send_text(wa_id, "Perfecto. ¿En qué comuna necesitas al profesional?")
            return

        logger.info("🤷 Still no match in WAIT_SERVICE")
        await send_text(
            wa_id,
            "Aún no logro identificar el tipo de ayuda.\n"
            "Descríbelo con más detalle (qué pasó / qué necesitas que hagan)."
        )
        return

    # STEP: WAIT_COMUNA
    if state.step == "WAIT_COMUNA":
        comuna = (text or "").strip()
        logger.info("📍 Comuna received | comuna=%s", comuna)

        if len(comuna) < 3:
            await send_text(wa_id, "Dime tu comuna (ej: Talcahuano, Concepción, San Pedro).")
            return

        lead.comuna = comuna

        if _is_intent_marker(lead.service):
            intent_id = _get_intent_id(lead.service)
            logger.info("🔁 Resolving intent -> service | intent_id=%s | comuna=%s", intent_id, comuna)

            if intent_id:
                best_service = pick_best_service_for_intent(db, intent_id, comuna, intent_to_services)
                logger.info("🎯 pick_best_service_for_intent result | best_service=%s", best_service)

                if not best_service:
                    lead.service = None
                    lead.status = "WAIT_SERVICE"
                    state.step = "WAIT_SERVICE"
                    db.commit()
                    await send_text(
                        wa_id,
                        "No encontré profesionales disponibles para esa necesidad en tu comuna.\n"
                        "Describe el problema con más detalle o prueba otra comuna."
                    )
                    return

                lead.service = best_service

        # Continue to options step (existing options sender)
        lead.status = "WAIT_CHOICE"
        state.step = "WAIT_CHOICE"
        db.commit()

        logger.info("📤 Sending options | lead_id=%s | service=%s | comuna=%s", lead.id, lead.service, lead.comuna)
        from services.api.options import _send_options
        await _send_options(db, wa_id, lead)
        return

    # Unknown step safety
    logger.warning("⚠️ Unknown step -> resetting to START | step=%s", state.step)
    state.step = "START"
    db.commit()
    await send_text(wa_id, INTRO)
