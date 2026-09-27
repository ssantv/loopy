"""Configuración de la aplicación vía variables de entorno (pydantic-settings)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Loopy"
    env: str = "development"
    debug: bool = True

    # URL asíncrona: sqlite+aiosqlite:///... · postgresql+asyncpg://user:pass@host:5432/db
    database_url: str = "sqlite+aiosqlite:///./loopy_dev.db"

    # Sesiones con token opaco almacenado en BD
    session_token_bytes: int = 32
    session_ttl_days: int = 30

    # Rate limit del login (intentos fallidos por email+IP dentro de la ventana)
    login_max_attempts: int = 5
    login_window_seconds: int = 300

    cors_origins: list[str] = ["http://localhost:5173"]

    # Web Push (VAPID)
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:admin@example.com"

    # Scheduler de notificaciones
    push_poll_seconds: int = 15
    push_backoff: list[int] = [30, 60, 300, 1800, 21600]  # segundos entre reintentos
    push_max_attempts: int = 6


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()