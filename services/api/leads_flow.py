from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from services.common.logging_config import setup_logging
from datetime import datetime
import unicodedata

from services.api.matching import list_available_services
from services.api.models import (
    ConversationState,
    Customer,
    Lead,
    LeadOffer,
    Provider,
    ProviderCoverage,
    ProviderState,
    Review,
)
import difflib
import re

from services.api.whatsapp_cloud import send_list, send_text

from services.api.nlu.engine import NLUEngine, build_service_intent_index, pick_best_service_for_intent, get_available_comunas_for_intent

logger = setup_logging("leads_flow")

NLU = NLUEngine()

def _normalize_text(text: str) -> str:
    """Normaliza texto: lowercase, quita tildes y espacios extra."""
    t = (text or "").strip().lower()
    t = unicodedata.normalize('NFD', t).encode('ascii', 'ignore').decode('ascii')
    return t

# Comuna aliases for common abbreviations
COMUNA_ALIASES = {
    "conce": "concepcion",
    "cpt": "concepcion",
    "san pedro": "san pedro de la paz",
    "spdp": "san pedro de la paz",
    "los angeles": "los angeles",
    "la": "los angeles",
    "thno": "talcahuano",
    "talc": "talcahuano",
    "talcahuano": "talcahuano",
    # Add more as needed
}

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


def _parse_yes_no(text: str):
    t = (text or "").strip().lower()
    if t in {"1", "si", "sí", "s"}:
        return True
    if t in {"2", "no", "n"}:
        return False
    return None


def _parse_rating(text: str) -> int | None:
    t = (text or "").strip().lower()
    if not t:
        return None
    first = t.split()[0]
    try:
        val = int(first)
    except ValueError:
        return None
    if 0 <= val <= 5:
        return val
    return None


def _match_service_from_text(text: str, services: list[str]) -> str | None:
    t = _normalize_text(text)
    if not t:
        return None
    tokens = [tok for tok in re.split(r"\s+", t) if len(tok) >= 3]
    for svc in services:
        svc_norm = _normalize_text(svc)
        if not svc_norm:
            continue
        if svc_norm in t or t in svc_norm:
            return svc
        for tok in tokens:
            if len(tok) >= 4 and (svc_norm.startswith(tok) or tok in svc_norm):
                return svc
            if len(tok) >= 4:
                ratio = difflib.SequenceMatcher(None, tok, svc_norm).ratio()
                if ratio >= 0.84:
                    return svc
    return None


def _normalize_comuna_key(text: str) -> str:
    text_norm = _normalize_text(text)
    for prefix in ("en la ", "en el ", "en "):
        if text_norm.startswith(prefix):
            text_norm = text_norm[len(prefix):].strip()
            break
    if text_norm == "conce":
        text_norm = "concepcion"
    return COMUNA_ALIASES.get(text_norm, text_norm)


def _resolve_comuna(text: str, comunas_map: dict[str, str]) -> tuple[str, str]:
    key = _normalize_comuna_key(text)
    canonical = comunas_map.get(key, text.strip())
    return key, canonical


async def _send_comuna_picker(
    wa_id: str,
    message: str,
    comunas: list[str],
) -> None:
    if not comunas:
        await send_text(wa_id, message)
        return
    rows = []
    for comuna in comunas[:10]:
        key = _normalize_comuna_key(comuna)
        rows.append(
            {
                "id": f"comuna:{key}",
                "title": comuna,
            }
        )
    if not rows:
        await send_text(wa_id, message)
        return
    await send_list(
        wa_id,
        body_text=message,
        button_text="Elegir comuna",
        rows=rows,
        section_title="Comunas disponibles",
    )


def _sync_state_after_options(state: ConversationState, lead: Lead) -> None:
    if lead.status == "WAIT_SERVICE":
        state.step = "WAIT_SERVICE"
    elif lead.status == "WAIT_CHOICE":
        state.step = "WAIT_CHOICE"


def _ensure_customer(db: Session, wa_id: str) -> Customer:
    cust = db.query(Customer).filter(Customer.wa_id == wa_id).first()
    if not cust:
        cust = Customer(wa_id=wa_id)
        db.add(cust)
        db.commit()
    return cust


def _clear_customer_pending(db: Session, wa_id: str, lead_id: int):
    cust = db.query(Customer).filter(Customer.wa_id == wa_id).first()
    if cust and cust.pending_lead_id == lead_id:
        cust.pending_lead_id = None
        cust.blocked_until = None
        db.commit()


async def _handle_provider_followup(db: Session, provider: Provider, text: str) -> bool:
    st = db.query(ProviderState).filter(ProviderState.provider_id == provider.id).first()
    if not st or not st.pending_lead_id or not st.pending_question:
        return False

    lead = db.query(Lead).filter(Lead.id == st.pending_lead_id).first()
    if not lead:
        return False

    ans = _parse_yes_no(text)
    if ans is None:
        await send_text(provider.whatsapp_e164, "Responde 1=SI o 2=NO para continuar.")
        return True

    if st.pending_question == "CONTACT":
        lead.provider_contact_confirmed = ans
    elif st.pending_question == "SERVICE":
        lead.provider_service_confirmed = ans

    db.commit()
    await send_text(provider.whatsapp_e164, "Gracias, respuesta registrada.")
    return True


async def handle_user_incoming(db: Session, wa_id: str, text: str, raw_message=None):
    logger.info("➡️ Enter | wa_id=%s | text=%s", wa_id, text)

    provider = db.query(Provider).filter(Provider.whatsapp_e164 == wa_id).first()
    if provider:
        handled = await _handle_provider_followup(db, provider, text)
        if handled:
            return
        await send_text(provider.whatsapp_e164, "No tengo seguimientos pendientes para ti.")
        return

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
    if not state.lead_id:
        state.lead_id = lead.id
        db.commit()

    logger.info(
        "🧠 State snapshot | wa_id=%s | step=%s | lead_id=%s | status=%s | service=%s | comuna=%s",
        wa_id, state.step, lead.id, lead.status, lead.service, lead.comuna
    )

    if _is_greeting(text) and state.step != "START":
        state.step = "START"
        lead.status = "OPEN"
        db.commit()
        await send_text(wa_id, INTRO)
        return

    # Service universe from DB (Provider.service values)
    services = list_available_services(db)
    logger.info("📚 Services loaded | count=%s", len(services) if services else 0)

    _service_to_intent, intent_to_services = build_service_intent_index(services, NLU.intents)
    known_comunas_rows = db.query(func.distinct(Provider.comuna)).filter(Provider.comuna.isnot(None)).all()
    known_comunas_rows.extend(db.query(func.distinct(ProviderCoverage.comuna)).filter(ProviderCoverage.comuna.isnot(None)).all())
    comunas_map: dict[str, str] = {}
    for row in known_comunas_rows:
        raw = row[0]
        if not raw:
            continue
        key = _normalize_text(raw)
        comunas_map.setdefault(key, raw)

    # Handle greeting in START
    if _is_greeting(text) and state.step == "START":
        await send_text(wa_id, INTRO)
        return
    if state.step == "START":
        if _is_greeting(text):
            logger.info("👋 Greeting detected -> sending INTRO")
            await send_text(wa_id, INTRO)
            return

        lead.problem_type = (text or "").strip()[:160]

        nlu = await NLU.parse_hybrid(text)
        logger.info(
            "🧩 NLU result | intent_id=%s | need_clarification=%s",
            getattr(nlu, "intent_id", None), getattr(nlu, "need_clarification", None)
        )

        if nlu.need_clarification and nlu.clarifying_question:
            logger.info("❓ Need clarification -> WAIT_INTENT_CLARIFICATION")
            state.step = "WAIT_INTENT_CLARIFICATION"
            state.temp_data = {"intent_options": nlu.clarifying_options}
            lead.status = "WAIT_SERVICE"
            db.commit()
            await send_text(wa_id, nlu.clarifying_question)
            return

        if nlu.intent_id:
            comuna_entity = (nlu.entities.comuna if nlu.entities else None) if hasattr(nlu, "entities") else None
            if comuna_entity:

                comuna_key, comuna_canonical = _resolve_comuna(comuna_entity, comunas_map)
                logger.info(
                    "✅ Intent+comuna detected -> resolve service | intent_id=%s | comuna=%s",
                    nlu.intent_id,
                    comuna_canonical,
                )
                best_service = pick_best_service_for_intent(db, nlu.intent_id, comuna_key, intent_to_services)
                if best_service:
                    lead.service = best_service
                    lead.comuna = comuna_canonical

                    lead.status = "WAIT_CHOICE"
                    state.step = "WAIT_CHOICE"
                    db.commit()
                    from services.api.options import _send_options
                    await _send_options(db, wa_id, lead)
                    _sync_state_after_options(state, lead)
                    db.commit()
                    return

                available_comunas = get_available_comunas_for_intent(db, nlu.intent_id, intent_to_services, comuna_canonical)
                if available_comunas:
                    comunas_str = ", ".join(available_comunas[:5])
                    message = (
                        f"No encontré profesionales disponibles para esa necesidad en {comuna_canonical}.\n"

                        f"Tenemos disponibles en: {comunas_str}.\n"
                        "Prueba una de estas comunas o describe tu necesidad de otra forma."
                    )
                else:
                    message = (
                        "No encontré profesionales disponibles para esa necesidad en tu comuna.\n"
                        "Describe el problema con más detalle o prueba otra comuna."
                    )

                state.temp_data = state.temp_data or {}
                state.temp_data["previous_intent"] = nlu.intent_id
                lead.service = None
                lead.comuna = None

                lead.status = "WAIT_SERVICE"
                state.step = "WAIT_SERVICE"
                db.commit()
                await _send_comuna_picker(wa_id, message, available_comunas)
                return

            logger.info("✅ Intent detected -> WAIT_COMUNA | intent_id=%s", nlu.intent_id)
            lead.service = f"INTENT:{nlu.intent_id}"
            lead.status = "WAIT_COMUNA"
            state.step = "WAIT_COMUNA"
            db.commit()
            available_comunas = get_available_comunas_for_intent(
                db,
                nlu.intent_id,
                intent_to_services,
            )
            await _send_comuna_picker(
                wa_id,
                "Perfecto. ¿En qué comuna necesitas al profesional?",
                available_comunas,
            )
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
        # Check if text is a known comuna and we have previous intent
        comunas_set = set(comunas_map.keys())
        logger.info("📋 WAIT_SERVICE | text=%s | comunas_set=%s", text, comunas_set)

        text_norm, comuna_canonical = _resolve_comuna(text, comunas_map)
        logger.info("📝 Normalized comuna | original=%s | normalized=%s", text, text_norm)

        prev_intent = (state.temp_data or {}).get("previous_intent")
        logger.info("🎯 Prev intent | %s", prev_intent)
        
        if text_norm in comunas_set and prev_intent:
            logger.info("🔄 Detected comuna with previous intent | comuna=%s | intent=%s", text_norm, prev_intent)
            best_service = pick_best_service_for_intent(db, prev_intent, text_norm, intent_to_services)
            logger.info("🎯 pick_best_service_for_intent result | best_service=%s", best_service)
            if best_service:
                logger.info("✅ Found service for comuna | best_service=%s", best_service)
                lead.service = best_service
                lead.comuna = comuna_canonical
                lead.status = "WAIT_CHOICE"
                state.step = "WAIT_CHOICE"
                state.temp_data = {}  # Clear
                db.commit()
                from services.api.options import _send_options
                await _send_options(db, wa_id, lead)
                _sync_state_after_options(state, lead)
                db.commit()
                return
            else:
                # No service in this comuna either
                available_comunas = get_available_comunas_for_intent(db, prev_intent, intent_to_services, comuna_canonical)
                if available_comunas:
                    comunas_str = ", ".join(available_comunas[:5])
                    message = (
                        f"No encontré profesionales para esa necesidad en {comuna_canonical} tampoco.\n"
                        f"Tenemos disponibles en: {comunas_str}.\n"
                        "Prueba una de estas comunas o describe tu necesidad de otra forma."
                    )
                else:
                    message = (
                        f"No encontré profesionales para esa necesidad en {comuna_canonical} tampoco.\n"
                        "Prueba otra comuna o describe tu necesidad de otra forma."
                    )
                lead.service = None
                lead.comuna = None
                lead.status = "WAIT_SERVICE"
                state.step = "WAIT_SERVICE"
                state.temp_data = {}
                db.commit()
                await _send_comuna_picker(wa_id, message, available_comunas)
                return
        
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
            available_comunas = get_available_comunas_for_intent(
                db,
                nlu2.intent_id,
                intent_to_services,
            )
            await _send_comuna_picker(
                wa_id,
                "Perfecto. ¿En qué comuna necesitas al profesional?",
                available_comunas,
            )
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
        comuna_key, comuna_canonical = _resolve_comuna(comuna, comunas_map)
        logger.info("📍 Comuna received | comuna=%s | canonical=%s", comuna, comuna_canonical)

        if len(comuna) < 3:
            await send_text(wa_id, "Dime tu comuna (ej: Talcahuano, Concepción, San Pedro).")
            return

        lead.comuna = comuna_canonical

        if _is_intent_marker(lead.service):
            intent_id = _get_intent_id(lead.service)
            logger.info("🔁 Resolving intent -> service | intent_id=%s | comuna=%s", intent_id, comuna)

            if intent_id:
                best_service = pick_best_service_for_intent(db, intent_id, comuna_key, intent_to_services)
                logger.info("🎯 pick_best_service_for_intent result | best_service=%s", best_service)

                if not best_service:
                    # Save previous intent for context
                    state.temp_data = state.temp_data or {}
                    state.temp_data["previous_intent"] = intent_id
                    
                    # Get available comunas for this service
                    available_comunas = get_available_comunas_for_intent(db, intent_id, intent_to_services, comuna_canonical)
                    if available_comunas:
                        comunas_str = ", ".join(available_comunas[:5])  # Limit to 5
                        message = (
                            f"No encontré profesionales disponibles para esa necesidad en {comuna_canonical}.\n"
                            f"Tenemos disponibles en: {comunas_str}.\n"
                            "Prueba una de estas comunas o describe tu necesidad de otra forma."
                        )
                    else:
                        message = (
                            "No encontré profesionales disponibles para esa necesidad en tu comuna.\n"
                            "Describe el problema con más detalle o prueba otra comuna."
                        )
                    
                    lead.service = None
                    lead.comuna = None
                    lead.status = "WAIT_SERVICE"
                    state.step = "WAIT_SERVICE"
                    db.commit()
                    await _send_comuna_picker(wa_id, message, available_comunas)
                    return

                lead.service = best_service

        # Continue to options step (existing options sender)
        lead.status = "WAIT_CHOICE"
        state.step = "WAIT_CHOICE"
        db.commit()

        logger.info("📤 Sending options | lead_id=%s | service=%s | comuna=%s", lead.id, lead.service, lead.comuna)
        from services.api.options import _send_options
        await _send_options(db, wa_id, lead)
        _sync_state_after_options(state, lead)
        db.commit()
        return

    # STEP: WAIT_CHOICE
    if state.step == "WAIT_CHOICE":
        offers = (
            db.query(LeadOffer)
            .filter(LeadOffer.lead_id == lead.id)
            .order_by(LeadOffer.rank.asc())
            .all()
        )
        if not offers:
            await send_text(wa_id, "No tengo opciones disponibles. Describe nuevamente tu necesidad.")
            state.step = "WAIT_SERVICE"
            lead.status = "WAIT_SERVICE"
            db.commit()
            return

        choice_raw = (text or "").strip()
        if not choice_raw.isdigit():
            await send_text(wa_id, "Responde con el número del profesional que prefieres.")
            return

        choice = int(choice_raw)
        if choice < 1 or choice > len(offers):
            await send_text(wa_id, "Opción inválida. Responde con el número indicado.")
            return

        chosen = offers[choice - 1]
        lead.provider_id = chosen.provider_id
        lead.status = "WAIT_CONSENT"
        state.step = "WAIT_CONSENT"
        db.commit()
        await send_text(
            wa_id,
            "¿Autorizas que compartamos tu número con este profesional para que te contacte?\n"
            "Responde:\n1) SI\n2) NO",
        )
        return

    # STEP: WAIT_CONSENT
    if state.step == "WAIT_CONSENT":
        consent = _parse_yes_no(text)
        if consent is None:
            await send_text(wa_id, "Responde 1=SI o 2=NO para continuar.")
            return

        if not consent:
            lead.status = "WAIT_CHOICE"
            state.step = "WAIT_CHOICE"
            db.commit()
            from services.api.options import _send_options
            await _send_options(db, wa_id, lead)
            return

        provider = db.query(Provider).filter(Provider.id == lead.provider_id).first()
        if not provider:
            await send_text(wa_id, "No pude encontrar al profesional seleccionado. Elige otra opción.")
            lead.status = "WAIT_CHOICE"
            state.step = "WAIT_CHOICE"
            db.commit()
            from services.api.options import _send_options
            await _send_options(db, wa_id, lead)
            return

        _ensure_customer(db, wa_id)

        lead.status = "CONNECTED"
        lead.connected_at = datetime.utcnow()
        state.step = "CONNECTED"
        db.commit()

        await send_text(
            wa_id,
            "¡Listo! Compartimos tu contacto con el profesional.\n"
            f"{provider.name or 'Profesional'}\n"
            "En breve el profesional te contactará.",
        )
        if provider.whatsapp_e164:
            await send_text(
                provider.whatsapp_e164,
                "Nuevo cliente ConectaPro 👋\n"
                f"Nombre: {lead.customer_name or 'Cliente'}\n"
                f"Problema: {lead.problem_type or 'No especificado'}\n"
                f"Comuna: {lead.comuna or '-'}\n"
                f"Contacto: {lead.customer_wa_id}",
            )
        return

    # FOLLOWUP: CONTACT_CONFIRM_PENDING
    if lead.status == "CONTACT_CONFIRM_PENDING":
        ans = _parse_yes_no(text)
        if ans is None:
            await send_text(wa_id, "Responde 1=SI o 2=NO para continuar.")
            return
        lead.user_contact_confirmed = ans
        db.commit()
        await send_text(wa_id, "Gracias, respuesta registrada.")
        return

    # FOLLOWUP: SERVICE_CONFIRM_PENDING
    if lead.status == "SERVICE_CONFIRM_PENDING":
        ans = _parse_yes_no(text)
        if ans is None:
            await send_text(wa_id, "Responde 1=SI o 2=NO para continuar.")
            return
        lead.user_service_confirmed = ans
        db.commit()
        await send_text(wa_id, "Gracias, respuesta registrada.")
        return

    # FOLLOWUP: RATING_PENDING
    if lead.status == "RATING_PENDING":
        rating = _parse_rating(text)
        if rating is None:
            await send_text(wa_id, "Responde con un número 0 a 5 (ej: 5 excelente).")
            return
        if rating == 0:
            lead.status = "CLOSED"
            db.commit()
            _clear_customer_pending(db, wa_id, lead.id)
            await send_text(wa_id, "Gracias, tu caso fue cerrado.")
            return

        provider = db.query(Provider).filter(Provider.id == lead.provider_id).first()
        if provider:
            provider.rating_avg = (
                (provider.rating_avg * provider.rating_count + rating) / (provider.rating_count + 1)
            )
            provider.rating_count += 1
            db.commit()

        lead.rating_stars = rating
        lead.status = "CLOSED"
        db.commit()

        if provider:
            review = Review(
                lead_id=lead.id,
                provider_id=provider.id,
                customer_wa_id=lead.customer_wa_id,
                stars=rating,
                comment=(text or "").strip(),
            )
            db.add(review)
            db.commit()

        _clear_customer_pending(db, wa_id, lead.id)
        await send_text(wa_id, "¡Gracias por tu evaluación! Caso cerrado.")
        return

    # Unknown step safety
    logger.warning("⚠️ Unknown step -> resetting to START | step=%s", state.step)
    state.step = "START"
    db.commit()
    await send_text(wa_id, INTRO)
