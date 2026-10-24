"""Shared setup for the pipeline tests on the emulator: an API client with local file storage,
a scripted extractor, and PO-1, the factory invoice's PO: 50 L milk at Rs 60 and 2.5 kg paneer
at Rs 400 + 5% GST (Rs 4,050.00 in total). The fixtures are registered in conftest.py."""

import copy
import itertools

import pytest
from fastapi.testclient import TestClient

from app.agents import extraction
from app.main import create_app
from app.services import firebase
from app.services import storage as storage_svc
from app.services.storage import LocalStorage, get_storage
from tests.conftest import _fake_verify, bearer
from tests.emulator_utils import clear_firestore
from tests.factories import GOOD, FakeExtractor

STAFF, MANAGER, ADMIN = bearer("staff-token"), bearer("manager-token"), bearer("admin-token")
_files = itertools.count()


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, tmp_path) -> TestClient:
    clear_firestore()
    monkeypatch.setattr(firebase, "verify_id_token", _fake_verify)
    store = LocalStorage(str(tmp_path), "http://testserver", "secret", ttl=60)
    monkeypatch.setattr(storage_svc, "get_storage", lambda: store)
    app = create_app()
    app.dependency_overrides[get_storage] = lambda: store
    return TestClient(app)


def post(api: TestClient, path: str, body: dict, headers=STAFF) -> dict:
    res = api.post(path, json=body, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def supplier(api: TestClient, name="Sharma Dairy Pvt Ltd", gstin=None) -> str:
    body = {"name": name, "email": "ap@example.in", "gstin": gstin}
    return post(api, "/suppliers", body, ADMIN)["supplier_id"]


def purchase_order(api: TestClient, supplier_id: str) -> str:
    items = [
        {"name": "Full cream milk", "qty": "50", "unit": "L", "unit_price_paise": 6000},
        {"name": "Paneer", "qty": "2.5", "unit": "kg", "unit_price_paise": 40000, "tax_rate": "5"},
    ]
    return post(api, "/purchase-orders", {"supplier_id": supplier_id, "items": items})["po_number"]


def deliver(api: TestClient, po: str, milk="50", paneer: str | None = "2.5") -> None:
    items = [{"line_id": "1", "qty_received": milk}]
    if paneer:
        items.append({"line_id": "2", "qty_received": paneer})
    post(api, "/goods-receipts", {"po_number": po, "received_on": "2026-10-19", "items": items})


@pytest.fixture
def po1(api: TestClient) -> str:
    po = purchase_order(api, supplier(api))
    assert po == "PO-1"
    return po


def use(monkeypatch: pytest.MonkeyPatch, *responses) -> FakeExtractor:
    fake = FakeExtractor(*responses)
    monkeypatch.setattr(extraction, "get_extractor", lambda: fake)
    return fake


def upload(api: TestClient, data: bytes | None = None) -> dict:
    data = data or b"%PDF-1.7\n%" + str(next(_files)).encode() + b"\n%%EOF\n"
    res = api.post("/invoices", files={"file": ("inv.pdf", data, "application/pdf")}, headers=STAFF)
    assert res.status_code == 201, res.text
    return api.get(f"/invoices/{res.json()['invoice_id']}", headers=STAFF).json()


def actions(api: TestClient, invoice_id: str) -> list[str]:
    items = api.get(f"/audit-log?invoice_id={invoice_id}", headers=STAFF).json()["items"]
    return [a["action"] for a in items]


def overpriced_milk() -> dict:
    """Milk billed at Rs 61 (1.67% over the PO), with totals that still add up."""
    data = copy.deepcopy(GOOD)
    data["items"][0].update(unit_price="61.00", amount="3,050.00")
    data.update(subtotal="4,050.00", total="4,100.00")
    return data
