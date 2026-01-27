from __future__ import annotations

import json
from typing import Any, Dict, List

from openai import OpenAI
from sqlalchemy.orm import Session

from services.common.logging_config import setup_logging
from .knowledge_base import describe_conectapro
from .matching import find_top_providers, list_available_services
from .models import Provider, ProviderCoverage
from .nlu.engine import _norm
from .settings import settings

logger = setup_logging("llm_orchestrator")


class LLMOrchestrator:
    """
    Orquestador basado en OpenAI (ChatGPT) para manejar conversaciones,
    inferencias, consultas a DB y generación de respuestas.
    """

    def __init__(self, api_key: str, model: str = "gpt-4.1-mini"):
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def orchestrate_response(
        self,
        user_message: str,
        context: Dict[str, Any],
        db: Session,
        services: List[str],
        comunas: List[str]
    ) -> Dict[str, Any]:
        """
        Orquesta la respuesta usando LLM.
        """
        logger.info("🤖 Orchestrating response for message: %s", user_message)

        # Construir prompt con contexto
        prompt = self._build_prompt(user_message, context, services, comunas)

        # Definir tools
        tools = self._define_tools()

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_message},
                ],
                tools=tools,
                tool_choice="auto",
                timeout=settings.openai_timeout_seconds,
            )

            message = response.choices[0].message
            logger.info("🤖 LLM response: %s", message.content)
            if message.tool_calls:
                logger.info("🔧 Tool calls: %s", [tc.function.name for tc in message.tool_calls])
                actions = []
                for tool_call in message.tool_calls:
                    action = self._execute_tool(tool_call, db, context)
                    actions.append(action)
                    # If query_providers found providers, add send_options
                    if action["type"] == "query_providers" and action["result"]:
                        actions.append({"type": "send_options", "lead_id": context.get("lead_id")})
                final_response = self._generate_final_response(actions, context)
                logger.info("🤖 Final response: %s", final_response)
                return {
                    "response": final_response,
                    "actions": actions,
                    "next_step": "CONTINUE"
                }
            else:
                logger.info("🤖 Direct response: %s", message.content)
                return {
                    "response": message.content,
                    "actions": [],
                    "next_step": "CONTINUE"
                }

        except Exception as e:
            logger.error("Error en LLM orchestration: %s", e)
            return {
                "response": "Lo siento, hubo un error. Intenta nuevamente.",
                "actions": [],
                "next_step": "ERROR"
            }

    def _build_prompt(self, user_message: str, context: Dict, services: List[str], comunas: List[str]) -> str:
        return f"""
Eres ConectaPro, un asistente para conectar usuarios con profesionales locales.

Contexto de la conversación:
- Estado actual: {context.get('step', 'START')}
- Servicio actual: {context.get('current_service', 'Ninguno')}
- Comuna actual: {context.get('current_comuna', 'Ninguna')}
- Historial: {context.get('history', [])}
- Servicios disponibles: {', '.join(services)}
- Comunas disponibles: {', '.join(comunas)}

Mensaje del usuario: "{user_message}"

Instrucciones:
IMPORTANTE: Siempre debes usar tools para consultar datos. Nunca respondas con información directa de la DB.
- Si el usuario pregunta "qué es ConectaPro" o pide explicación, usa describe_conectapro.
- Si el usuario pide servicios disponibles, usa list_services.
- Si el usuario pide comunas, usa list_comunas (con service si aplica).
- Si el usuario menciona una comuna específica y hay un servicio, usa query_providers.
- Si el usuario menciona comuna sin servicio, pide especificar el servicio.
- Maneja abreviaturas comunes (ej: "conce" = "Concepción").
- Ejemplos:
  - Mensaje: "busco kine" → Usa list_comunas con service="kinesiologo"
  - Mensaje: "concepcion" (con service="kinesiologo") → Usa query_providers con service="kinesiologo", comuna="concepcion"
  - Mensaje: "busco kine en concepcion" → Usa query_providers con service="kinesiologo", comuna="concepcion"
- Responde de manera clara y amigable después de usar tools.

Responde como orquestador: decide qué hacer y usa tools si es necesario.
"""

    def _define_tools(self) -> List[Dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "describe_conectapro",
                    "description": "Entrega una explicación breve y clara de ConectaPro.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "query_providers",
                    "description": "Consulta proveedores disponibles para un servicio en una comuna específica.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "service": {
                                "type": "string",
                                "description": "El nombre del servicio (ej: kinesiólogo, electricista)"
                            },
                            "comuna": {
                                "type": "string",
                                "description": "El nombre de la comuna"
                            }
                        },
                        "required": ["service", "comuna"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "list_comunas",
                    "description": "Obtiene comunas disponibles para un servicio o generales.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "service": {
                                "type": "string",
                                "description": "El nombre del servicio"
                            }
                        },
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "list_services",
                    "description": "Lista servicios disponibles en la plataforma.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "send_options",
                    "description": "Envía las opciones de proveedores al usuario.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "lead_id": {
                                "type": "integer",
                                "description": "El ID del lead"
                            }
                        },
                        "required": ["lead_id"]
                    }
                }
            }
        ]

    def _execute_tool(self, tool_call: Any, db: Session, context: Dict) -> Dict[str, Any]:
        name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)

        lead_id = context.get("lead_id")
        lead = None
        if lead_id:
            from .models import Lead
            lead = db.query(Lead).filter(Lead.id == lead_id).first()

        if name == "describe_conectapro":
            return {"type": "describe_conectapro", "result": describe_conectapro()}

        if name == "list_services":
            services = list_available_services(db)
            return {"type": "list_services", "result": services}

        if name == "query_providers":
            service = args.get("service")
            comuna = args.get("comuna")
            # Normalizar
            comuna_norm = _norm(comuna)
            # Lógica similar a pick_best_service_for_intent
            # Retornar lista de proveedores
            providers = self._query_providers(db, service, comuna_norm)
            # Update lead
            if lead:
                lead.service = service
                lead.comuna = comuna
                db.commit()
            return {"type": "query_providers", "result": providers}

        if name == "list_comunas":
            service = args.get("service")
            comunas = self._get_comunas(db, service)
            # Update lead
            if lead:
                if service:
                    lead.service = service
                db.commit()
            return {"type": "list_comunas", "result": comunas}

        if name == "send_options":
            lead_id = args.get("lead_id")
            # Lógica para enviar opciones
            return {"type": "send_options", "lead_id": lead_id}

        return {}

    def _query_providers(self, db: Session, service: str, comuna_norm: str) -> List[Dict]:
        if not service or not comuna_norm:
            return []
        providers = find_top_providers(db, service=service, comuna=comuna_norm, limit=3)
        return [
            {"id": provider.id, "service": provider.service, "rating": provider.rating_avg}
            for provider in providers
        ]

    def _get_comunas(self, db: Session, service: str) -> List[str]:
        rows_cov = (
            db.query(ProviderCoverage.comuna)
            .join(Provider, Provider.id == ProviderCoverage.provider_id)
            .filter(Provider.active == True)
        )
        rows_direct = (
            db.query(Provider.comuna)
            .filter(Provider.active == True)
        )
        if service:
            rows_cov = rows_cov.filter(Provider.service == service)
            rows_direct = rows_direct.filter(Provider.service == service)
        comunas = {row[0] for row in rows_cov.distinct().all() if row[0]}
        comunas |= {row[0] for row in rows_direct.distinct().all() if row[0]}
        return sorted(comunas)

    def _generate_final_response(self, actions: List[Dict], context: Dict) -> str:
        # Basado en acciones, generar respuesta
        has_send_options = any(a["type"] == "send_options" for a in actions)
        if has_send_options:
            return ""  # No enviar mensaje adicional si ya se envían opciones
        
        for action in actions:
            if action["type"] == "query_providers":
                providers = action.get("result") or []
                if providers:
                    return f"Encontré {len(providers)} proveedores. Enviando opciones..."
                return "No encontré proveedores en esa comuna."
            if action["type"] == "list_comunas":
                comunas = action.get("result") or []
                return f"Disponible en: {', '.join(comunas[:5])}"
            if action["type"] == "list_services":
                services = action.get("result") or []
                return f"Servicios disponibles: {', '.join(services[:8])}"
            if action["type"] == "describe_conectapro":
                return action.get("result") or "ConectaPro conecta personas con profesionales."
            if action["type"] == "send_options":
                return "Opciones enviadas."
        return "Procesé tu solicitud."


# Instancia global (configurar con API key)
orchestrator = None

def get_orchestrator() -> LLMOrchestrator:
    global orchestrator
    if orchestrator is None:
        api_key = settings.openai_api_key
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set")
        orchestrator = LLMOrchestrator(api_key, model=settings.openai_model)
    return orchestrator
