import secrets
from functools import lru_cache
from typing import Literal

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

    # Public base URL of this API. Used for local file links and as the Cloud Tasks target.
    api_base_url: str = "http://localhost:8000"

    # Invoice files: "local" keeps them on disk (dev/tests); "gcs" uses Cloud Storage.
    storage_mode: Literal["local", "gcs"] = "local"
    local_storage_dir: str = ".data/uploads"
    gcs_bucket: str = ""
    # Signs short-lived local file links. A fresh random value per process is fine for dev.
    file_url_secret: str = secrets.token_urlsafe(32)
    file_url_ttl_seconds: int = 900

    # Background processing: "inline" runs the pipeline in this process after the response
    # (dev/tests); "cloud_tasks" enqueues a Cloud Tasks HTTP task with retries.
    tasks_mode: Literal["inline", "cloud_tasks"] = "inline"
    tasks_location: str = "asia-south1"
    tasks_queue: str = "invoice-processing"
    # Service account Cloud Tasks signs its OIDC token as; the task endpoint accepts only it.
    tasks_service_account: str = ""
    # Retries before an invoice is marked failed (Cloud Tasks queue max attempts must match).
    max_processing_attempts: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
