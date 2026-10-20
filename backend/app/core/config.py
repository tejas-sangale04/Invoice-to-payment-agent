from functools import lru_cache

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Put backend/.env into os.environ too: the Google SDKs read FIRESTORE_EMULATOR_HOST and
# FIREBASE_AUTH_EMULATOR_HOST from the environment, not from Settings. Real env vars win.
load_dotenv()


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables (and backend/.env locally)."""

    model_config = SettingsConfigDict(extra="ignore")

    app_name: str = "InvoiceFlow API"
    google_cloud_project: str = "demo-invoiceflow"
    firestore_database: str = "(default)"
    cors_origins: list[str] = ["http://localhost:5173"]
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
