from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"
    base_url: str = "http://localhost"

    # WhatsApp Cloud
    whatsapp_verify_token: str = "changeme-verify-token"
    whatsapp_phone_number_id: str = ""
    whatsapp_access_token: str = ""
    whatsapp_graph_version: str = "v20.0"
    whatsapp_provider_template_name: str = ""
    whatsapp_provider_template_lang: str = "es_ES"

    # DB
    database_url: str = "postgresql+psycopg://conectapro:conectapro@db:5432/conectapro"

    # Defaults (fallback determinístico)
    default_comuna: str = "Talcahuano"
    default_servicio: str = "Electricidad"

    # Worker
    close_confirm_after_hours: int = 24
    close_confirm_urgency_hoy_hours: int = 4
    close_confirm_urgency_1_2_dias_hours: int = 24
    close_confirm_urgency_semana_hours: int = 48

    # Nuevo flujo (router + doble confirmación)
    followup_contact_after_hours: int = 24
    followup_timeout_hours: int = 48
    practical_block_days: int = 7

    # OpenAI (capa LLM aislada)
    openai_enabled: int = 0
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    openai_min_confidence: float = 0.85
    openai_timeout_seconds: int = 20
    llm_orchestrator_enabled: int = 0

    # Allowlists (mínimo viable)
    allow_services: str = "Electricidad,Gasfiteria,Cerrajeria"
    allow_urgency: str = "hoy,1_2_dias,semana"

    # Matching
    top_providers_limit: int = 3

    def allow_services_list(self) -> list[str]:
        return [x.strip() for x in self.allow_services.split(",") if x.strip()]

    def allow_urgency_list(self) -> list[str]:
        return [x.strip() for x in self.allow_urgency.split(",") if x.strip()]


settings = Settings()
