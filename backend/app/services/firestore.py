from functools import lru_cache

from google.cloud import firestore

from app.core.config import get_settings


@lru_cache
def get_db() -> firestore.Client:
    """Firestore client. Honours FIRESTORE_EMULATOR_HOST automatically for local dev and tests."""
    settings = get_settings()
    return firestore.Client(project=settings.firebase_project, database=settings.firestore_database)
