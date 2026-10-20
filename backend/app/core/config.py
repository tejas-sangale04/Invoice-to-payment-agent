from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables (and backend/.env locally)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "InvoiceFlow API"
    google_cloud_project: str = "demo-invoiceflow"
    firestore_database: str = "(default)"
    cors_origins: list[str] = ["http://localhost:5173"]
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
