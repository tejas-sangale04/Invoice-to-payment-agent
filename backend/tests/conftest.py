import os
from unittest.mock import MagicMock

# Tests never call Gemini; ones that need extraction inject a fake extractor.
os.environ["EXTRACTOR"] = "disabled"

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services import firebase
from app.services.firestore import get_db

# Fake ID tokens for unit tests: token string -> decoded claims.
FAKE_TOKENS = {
    "staff-token": {"uid": "u-staff", "email": "staff@example.com", "role": "staff"},
    "manager-token": {"uid": "u-manager", "email": "manager@example.com", "role": "manager"},
    "admin-token": {"uid": "u-admin", "email": "admin@example.com", "role": "admin"},
    "norole-token": {"uid": "u-norole", "email": "new@example.com"},
    "badrole-token": {"uid": "u-bad", "email": "bad@example.com", "role": "superuser"},
}


def _fake_verify(token: str) -> dict:
    if token not in FAKE_TOKENS:
        raise ValueError("invalid token")
    return FAKE_TOKENS[token]


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(firebase, "verify_id_token", _fake_verify)
    app = create_app()
    # Unit tests never touch Firestore; anything needing a real database is an emulator test.
    app.dependency_overrides[get_db] = lambda: MagicMock()
    return TestClient(app)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
