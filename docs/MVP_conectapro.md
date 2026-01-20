PROMPT MAESTRO — PROYECTO CONECTAPRO (v2 · ORIENTADO A PRODUCCIÓN)
1. Contexto general

Estás trabajando sobre el proyecto ConectaPro, una plataforma productiva, multi-servicio y multi-proveedor, cuyo objetivo es conectar clientes reales con técnicos reales, a través de WhatsApp, con foco en:

operación confiable

trazabilidad completa

control de calidad

escalabilidad comercial

ConectaPro NO es un chatbot.
Es un orquestador de servicios transaccional, con reglas claras y comportamiento predecible.

El objetivo final es salir al mercado con un producto funcional, no solo validar tecnología.

2. Fuente de verdad y control de cambios (NO romper)

El repositorio se entrega siempre como un ZIP

Ese ZIP es la fuente de verdad absoluta del código

No se inventan archivos que no existan

No se cambian estructuras sin justificación técnica fuerte

Los cambios deben ser:

mínimos

coherentes

compatibles hacia atrás

auditables

👉 La estabilidad es prioritaria sobre la velocidad.

3. Principio rector del sistema (CRÍTICO)

El sistema es determinístico y auditable.

Existe explícitamente:

ConversationState

Lead.status

reglas de transición claras

El LLM:

❌ NO decide flujos

❌ NO asigna proveedores

❌ NO cambia estados

❌ NO escribe en la base de datos

❌ NO “interpreta” reglas de negocio

El backend:

✅ decide

✅ valida

✅ persiste

✅ controla errores

✅ garantiza consistencia

4. Uso de OpenAI (con guardrails estrictos)

OpenAI se usa solo como capa auxiliar, nunca como fuente de verdad.

OpenAI se utiliza exclusivamente para:

Comprender lenguaje natural libre

Extraer intención y campos estructurados

Reformular respuestas para tono humano

Manejar desvíos conversacionales (“me salí del flujo”)

Reglas duras:

Si OpenAI falla → fallback inmediato al flujo determinístico

El MVP nunca puede caerse por depender del LLM

El LLM debe operar bajo feature flag

El sistema debe poder operar sin OpenAI habilitado

5. Objetivo actual del desarrollo (FOCO PRODUCTIVO)

El objetivo actual es evolucionar el MVP hacia producto productivo, manteniendo:

Webhook WhatsApp existente

leads_flow.py como cerebro central

DB y modelos actuales

Matching determinístico

Worker de cierre automático

La integración con OpenAI debe:

mejorar UX conversacional

permitir texto libre

no comprometer control ni trazabilidad

no introducir estados implícitos

6. Arquitectura obligatoria para OpenAI

OpenAI NO se mezcla con lógica de negocio.

Debe existir una capa aislada y versionable:

services/api/llm/
 ├── llm_client.py        # cliente OpenAI
 ├── intent_parser.py    # extracción estructurada
 ├── prompt_templates.py # prompts versionados


👉 Esta capa NO importa modelos ni DB.

7. Flujo obligatorio del mensaje
Mensaje usuario
   ↓
OpenAI → JSON estructurado (intent, campos, confidence)
   ↓
Validación backend (allowlists, confidence, estado)
   ↓
State Machine (decisión determinística)
   ↓
Respuesta:
   - determinística
   - opcionalmente reescrita por LLM

8. Esquema estándar de intención (INQUEBRANTABLE)

El LLM debe devolver EXCLUSIVAMENTE JSON, sin texto adicional:

{
  "intent": "create_lead | update_lead | ask_status | cancel | smalltalk | unknown",
  "service": "Electricidad | Gasfiteria | Cerrajeria | null",
  "comuna": "string | null",
  "problem_type": "string | null",
  "urgency": "hoy | 1_2_dias | semana | null",
  "address": "string | null",
  "consent": "yes | no | null",
  "confidence": 0.0
}

Reglas estrictas:

confidence < 0.85 → NO asumir

Campos ambiguos → null

Nunca inventar servicios, comunas o urgencias fuera de allowlist

Nunca “completar” datos por intuición

9. Principios productivos (NUEVO · CRÍTICO)

A partir de ahora, toda decisión debe considerar:

Estabilidad operacional

El sistema debe resistir:

mensajes duplicados

latencia

reintentos de webhook

fallos parciales

Observabilidad

Todo paso relevante debe quedar logueado

Logs deben permitir:

reconstruir una conversación

auditar decisiones

detectar cuellos de botella

Seguridad

Tokens protegidos

Inputs validados

Nada crítico controlado por prompt

Costos

Uso de OpenAI optimizado

No usar LLM donde una regla basta

10. Forma de trabajo esperada del asistente

Cuando se entregue un ZIP, el asistente debe:

Analizar el ZIP completo

Detectar errores, riesgos y deudas técnicas

Proponer solo cambios necesarios

Entregar scripts completos (copy/paste)

Indicar con precisión:

archivo

cambio

motivo

Entregar pasos claros para implementar

Nunca asumir contexto fuera del ZIP + este PROMPT.

11. Prioridades técnicas (ordenadas)

Estabilidad del sistema

Flujo END-TO-END funcional

Observabilidad

Preparación para producción

Escalabilidad futura

Optimización fina

12. Criterio de calidad esperado

Las soluciones deben ser:

Profesionales

Auditables

Determinísticas

Reproducibles

Seguras ante fallos

Aptas para producción real

No se aceptan:

hacks rápidos

lógica implícita en prompts

decisiones “porque sí”

dependencias frágiles

13. Resultado esperado de cada iteración

Cada iteración debe dejar el proyecto:

compilando

levantando en Docker

con flujo completo funcional

sin romper nada previo

un paso más cerca de producción

Fin del PROMPT MAESTRO v2 – CONECTAPRO