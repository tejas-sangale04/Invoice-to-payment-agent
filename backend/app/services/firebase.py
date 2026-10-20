import firebase_admin
from firebase_admin import auth

from app.core.config import get_settings


def init_firebase() -> firebase_admin.App:
    """Initialise the Admin SDK once.

    On Cloud Run this uses the service's default credentials. Locally, setting
    FIREBASE_AUTH_EMULATOR_HOST makes the SDK talk to the Auth emulator instead.
    """
    if firebase_admin._apps:
        return firebase_admin.get_app()
    return firebase_admin.initialize_app(options={"projectId": get_settings().google_cloud_project})


def verify_id_token(token: str) -> dict:
    init_firebase()
    return auth.verify_id_token(token)


def set_role_claim(uid: str, role: str) -> None:
    init_firebase()
    auth.set_custom_user_claims(uid, {"role": role})


def get_user(uid: str) -> auth.UserRecord:
    init_firebase()
    return auth.get_user(uid)
