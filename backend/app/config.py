"""
config.py — Configuración centralizada de la aplicación

Usamos pydantic-settings para leer y validar las variables de entorno.
Ventaja: si falta una variable obligatoria, la app falla al arrancar
con un mensaje claro en lugar de fallar silenciosamente en producción.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    # ---- LLM ----
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_fine_tuned_model: str = ""   # se completa en FASE 4
    llm_temperature: float = 0.3        # 0 = determinístico, 1 = creativo
    llm_max_tokens: int = 500

    # ---- WhatsApp / Twilio ----
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = "whatsapp:+14155238886"  # número sandbox Twilio

    # ---- Base de datos relacional ----
    database_url: str = "postgresql://asistente:asistente123@db:5432/asistente_db"

    # ---- Redis (caché de sesiones) ----
    redis_url: str = "redis://redis:6379"

    # ---- BD Vectorial (FASE 1+) ----
    chroma_persist_path: str = "./chroma_db"
    pinecone_api_key: str = ""
    pinecone_index_name: str = "academic-notes"

    # ---- Google APIs (FASE 3+) ----
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"

    # ---- App general ----
    secret_key: str = "dev-secret-key-change-in-production"
    debug: bool = True
    log_level: str = "INFO"

    # Pydantic v2: lee desde archivo .env automáticamente
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


# lru_cache garantiza que Settings() se instancia una sola vez
# (patrón Singleton): no se re-lee el .env en cada request.
@lru_cache
def get_settings() -> Settings:
    return Settings()
