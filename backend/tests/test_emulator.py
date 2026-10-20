"""Integration tests against the real Firebase Auth and Firestore emulators.

Run from the repo root with:
    firebase emulators:exec --only auth,firestore "cd backend && pytest -m emulator"
"""

import os
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from firebase_admin import auth

from app.main import create_app
from app.services.firebase import init_firebase, set_role_claim
from app.services.firestore import get_db

pytestmark = [
    pytest.mark.emulator,
    pytest.mark.skipif(
        not (
            os.environ.get("FIREBASE_AUTH_EMULATOR_HOST")
            and os.environ.get("FIRESTORE_EMULATOR_HOST")
        ),
        reason="Firebase emulators not running",
    ),
]


def _sign_in(email: str, password: str) -> str:
    """Get a real ID token from the Auth emulator's REST API (what the frontend SDK does)."""
    host = os.environ["FIREBASE_AUTH_EMULATOR_HOST"]
    res = httpx.post(
        f"http://{host}/identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=fake-key",
        json={"email": email, "password": password, "returnSecureToken": True},
    )
    res.raise_for_status()
    return res.json()["idToken"]


def test_real_token_with_role_claim_round_trip() -> None:
    init_firebase()
    email = f"{uuid.uuid4().hex[:8]}@invoiceflow.test"
    user = auth.create_user(email=email, password="password123")
    set_role_claim(user.uid, "manager")

    client = TestClient(create_app())
    res = client.get("/me", headers={"Authorization": f"Bearer {_sign_in(email, 'password123')}"})

    assert res.status_code == 200
    assert res.json() == {"uid": user.uid, "email": email, "role": "manager"}


def test_firestore_emulator_read_write() -> None:
    doc = get_db().collection("_smoke").document(uuid.uuid4().hex)
    doc.set({"ok": True})
    assert doc.get().to_dict() == {"ok": True}
