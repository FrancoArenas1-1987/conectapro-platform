from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from openai import OpenAI
from sqlalchemy.orm import Session

from services.common.logging_config import setup_logging
from .models import Provider, ProviderCoverage
from .nlu.engine import _norm

logger = setup_logging("llm_orchestrator")


class LLMOrchestrator:
    """
    Orquestador basado en OpenAI (ChatGPT) para manejar conversaciones,
    inferencias, consultas a DB y generación de respuestas.
    """

    def __init__(self, api_key: str, model: str = "gpt-3.5-turbo"):
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
                messages=[{"role": "system", "content": prompt}],
                tools=tools,
                tool_choice="auto"
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
IMPORTANTE: Siempre debes usar las tools para cualquier consulta a la base de datos. Nunca respondas con información directa de la DB. Usa tools obligatoriamente.
- Si el usuario pide un servicio (ej: "busco kinesiólogo"), usa get_available_comunas para listar comunas disponibles.
- No uses get_available_comunas si ya hay un servicio seleccionado en el contexto.
- Si el usuario menciona una comuna específica (ej: "concepcion", "conce") y hay un servicio seleccionado en el contexto, OBLIGATORIAMENTE usa query_providers para buscar proveedores en esa comuna.
- Si el usuario menciona una comuna sin servicio seleccionado, pide que especifique el servicio.
- Maneja abreviaturas comunes (ej: "conce" = "Concepción").
- Ejemplos:
  - Mensaje: "busco kine" → Usa get_available_comunas con service="kinesiologo"
  - Mensaje: "concepcion" (con service="kinesiologo") → Usa query_providers con service="kinesiologo", comuna="concepcion"
  - Mensaje: "busco kine en concepcion" → Usa query_providers con service="kinesiologo", comuna="concepcion"
- Responde de manera amigable y humana solo después de usar tools.
- Avanza el proceso: después de listar comunas, espera selección de comuna; después de comuna, envía opciones.

Responde como orquestador: decide qué hacer y usa tools si es necesario.
"""

    def _define_tools(self) -> List[Dict]:
        return [
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
                    "name": "get_available_comunas",
                    "description": "Obtiene las comunas disponibles para un servicio específico.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "service": {
                                "type": "string",
                                "description": "El nombre del servicio"
                            }
                        },
                        "required": ["service"]
                    }
                }
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

        elif name == "get_available_comunas":
            service = args.get("service")
            comunas = self._get_comunas(db, service)
            # Update lead
            if lead:
                lead.service = service
                db.commit()
            return {"type": "get_available_comunas", "result": comunas}

        elif name == "send_options":
            lead_id = args.get("lead_id")
            # Lógica para enviar opciones
            return {"type": "send_options", "lead_id": lead_id}

        return {}

    def _query_providers(self, db: Session, service: str, comuna_norm: str) -> List[Dict]:
        # Similar a pick_best_service_for_intent
        rows = (
            db.query(Provider.id, Provider.service, Provider.rating_avg, ProviderCoverage.comuna)
            .join(ProviderCoverage, ProviderCoverage.provider_id == Provider.id)
            .filter(Provider.active == True)
            .filter(Provider.service == service)
            .all()
        )
        providers = []
        for row in rows:
            cov_comuna = row[3]
            if _norm(cov_comuna) == comuna_norm:
                providers.append({
                    "id": row[0],
                    "service": row[1],
                    "rating": row[2]
                })
        return providers

    def _get_comunas(self, db: Session, service: str) -> List[str]:
        rows = (
            db.query(ProviderCoverage.comuna)
            .join(Provider, Provider.id == ProviderCoverage.provider_id)
            .filter(Provider.active == True)
            .filter(Provider.service == service)
            .distinct()
            .all()
        )
        return [row[0] for row in rows]

    def _generate_final_response(self, actions: List[Dict], context: Dict) -> str:
        # Basado en acciones, generar respuesta
        has_send_options = any(a["type"] == "send_options" for a in actions)
        if has_send_options:
            return ""  # No enviar mensaje adicional si ya se envían opciones
        
        for action in actions:
            if action["type"] == "query_providers" and action["result"]:
                providers = action["result"]
                if providers:
                    # Enviar opciones automáticamente
                    return f"Encontré {len(providers)} proveedores. Enviando opciones..."
                else:
                    return "No encontré proveedores en esa comuna."
            elif action["type"] == "get_available_comunas":
                comunas = action["result"]
                return f"Disponible en: {', '.join(comunas[:5])}"
            elif action["type"] == "send_options":
                return "Opciones enviadas."
        return "Procesé tu solicitud."


# Instancia global (configurar con API key)
orchestrator = None

def get_orchestrator() -> LLMOrchestrator:
    global orchestrator
    if orchestrator is None:
        import os
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set")
        orchestrator = LLMOrchestrator(api_key)
    return orchestrator