ConectaPro - Build con LOGS (Observabilidad)

Este paquete agrega logs detallados en:
- services/api/whatsapp_webhook.py  (entrada de eventos, mensajes, errores)
- services/api/leads_flow.py        (paso a paso del flujo y transiciones)
- services/common/logging_config.py (control por LOG_LEVEL)

Recomendado:
- En tu .env agrega:
  LOG_LEVEL=INFO
  (o DEBUG para aún más detalle)

Ver logs:
  docker logs -f conectapro-platform-api-1

Si no ves POST /webhooks/whatsapp al escribir en WhatsApp:
- El problema es ngrok / configuración webhook en Meta (no está llegando el evento).

