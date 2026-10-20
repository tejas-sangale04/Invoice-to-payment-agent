from types import SimpleNamespace

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from app.models.user import CurrentUser, Role
from app.services import firebase
from app.services.auth import require_role
from tests.conftest import bearer


def test_health_needs_no_auth(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "healthy"}


def test_me_without_token_is_401_with_standard_error(client: TestClient) -> None:
    res = client.get("/me")
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthenticated"


def test_me_with_invalid_token_is_401(client: TestClient) -> None:
    assert client.get("/me", headers=bearer("forged")).status_code == 401


def test_me_with_non_bearer_header_is_401(client: TestClient) -> None:
    assert client.get("/me", headers={"Authorization": "Basic abc"}).status_code == 401


@pytest.mark.parametrize(
    ("token", "role"),
    [("staff-token", "staff"), ("manager-token", "manager"), ("admin-token", "admin")],
)
def test_me_returns_role_from_token_claims(client: TestClient, token: str, role: str) -> None:
    res = client.get("/me", headers=bearer(token))
    assert res.status_code == 200
    assert res.json()["role"] == role


@pytest.mark.parametrize("token", ["norole-token", "badrole-token"])
def test_unknown_or_missing_role_is_none(client: TestClient, token: str) -> None:
    assert client.get("/me", headers=bearer(token)).json()["role"] is None


@pytest.mark.parametrize(
    ("minimum", "token", "allowed"),
    [
        (Role.staff, "staff-token", True),
        (Role.staff, "manager-token", True),
        (Role.staff, "admin-token", True),
        (Role.staff, "norole-token", False),
        (Role.manager, "staff-token", False),
        (Role.manager, "manager-token", True),
        (Role.manager, "admin-token", True),
        (Role.admin, "manager-token", False),
        (Role.admin, "admin-token", True),
    ],
)
def test_role_hierarchy(client: TestClient, minimum: Role, token: str, allowed: bool) -> None:
    @client.app.get("/_probe")
    def probe(user: CurrentUser = Depends(require_role(minimum))) -> dict[str, str]:
        return {"uid": user.uid}

    res = client.get("/_probe", headers=bearer(token))
    assert res.status_code == (200 if allowed else 403)
    if not allowed:
        assert res.json()["error"]["code"] == "forbidden"


def test_set_role_requires_admin(client: TestClient) -> None:
    res = client.put("/users/u-staff/role", json={"role": "admin"}, headers=bearer("manager-token"))
    assert res.status_code == 403


def test_admin_can_set_role(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(firebase, "get_user", lambda uid: SimpleNamespace(email="x@example.com"))
    monkeypatch.setattr(firebase, "set_role_claim", lambda uid, role: calls.append((uid, role)))

    res = client.put(
        "/users/u-norole/role", json={"role": "manager"}, headers=bearer("admin-token")
    )

    assert res.status_code == 200
    assert res.json() == {"uid": "u-norole", "email": "x@example.com", "role": "manager"}
    assert calls == [("u-norole", "manager")]


def test_set_role_rejects_unknown_role(client: TestClient) -> None:
    res = client.put("/users/u-x/role", json={"role": "owner"}, headers=bearer("admin-token"))
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "validation_error"
