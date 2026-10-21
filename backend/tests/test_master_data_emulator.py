"""Supplier, PO, goods receipt and business-rule flows against the Firestore emulator."""

import os

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services import firebase
from tests.conftest import _fake_verify, bearer
from tests.emulator_utils import clear_firestore

pytestmark = [
    pytest.mark.emulator,
    pytest.mark.skipif(
        not os.environ.get("FIRESTORE_EMULATOR_HOST"), reason="emulator not running"
    ),
]

STAFF, ADMIN = bearer("staff-token"), bearer("admin-token")


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    clear_firestore()
    monkeypatch.setattr(firebase, "verify_id_token", _fake_verify)
    return TestClient(create_app())


def _supplier(api: TestClient, name: str = "Sharma Dairy Pvt Ltd") -> dict:
    res = api.post("/suppliers", json={"name": name, "email": "ap@sharmadairy.in"}, headers=ADMIN)
    assert res.status_code == 201, res.text
    return res.json()


def _po(api: TestClient, supplier_id: str) -> dict:
    res = api.post(
        "/purchase-orders",
        json={
            "supplier_id": supplier_id,
            "items": [
                {"name": "Milk", "qty": "50", "unit": "L", "unit_price_paise": 6000},
                {
                    "name": "Paneer",
                    "qty": "2.5",
                    "unit": "kg",
                    "unit_price_paise": 40000,
                    "tax_rate": "5",
                },
            ],
        },
        headers=STAFF,
    )
    assert res.status_code == 201, res.text
    return res.json()


def test_supplier_ids_are_sequential_and_duplicates_rejected(api: TestClient) -> None:
    assert _supplier(api)["supplier_id"] == "SUP-1"
    assert _supplier(api, "Fresh Farms")["supplier_id"] == "SUP-2"
    dup = api.post(
        "/suppliers", json={"name": "sharma dairy", "email": "x@example.com"}, headers=ADMIN
    )
    assert dup.status_code == 409
    listed = api.get("/suppliers", headers=STAFF).json()["items"]
    assert [s["name"] for s in listed] == ["Fresh Farms", "Sharma Dairy Pvt Ltd"]


def test_po_totals_are_computed_in_paise(api: TestClient) -> None:
    po = _po(api, _supplier(api)["supplier_id"])
    assert po["po_number"] == "PO-1"
    assert po["status"] == "open"
    assert po["supplier_name"] == "Sharma Dairy Pvt Ltd"
    assert [line["line_id"] for line in po["items"]] == ["1", "2"]
    # Milk 50 x 60 = 3,000.00; paneer 2.5 x 400 = 1,000.00 + 5% = 50.00
    assert (po["subtotal_paise"], po["tax_paise"], po["total_paise"]) == (400000, 5000, 405000)
    assert api.get("/purchase-orders/PO-1", headers=STAFF).json() == po


def test_po_for_unknown_supplier_is_rejected(api: TestClient) -> None:
    res = api.post(
        "/purchase-orders",
        json={
            "supplier_id": "SUP-404",
            "items": [{"name": "Milk", "qty": "1", "unit": "L", "unit_price_paise": 1}],
        },
        headers=STAFF,
    )
    assert res.status_code == 422


def test_partial_deliveries_accumulate_and_over_delivery_is_blocked(api: TestClient) -> None:
    _po(api, _supplier(api)["supplier_id"])

    def receive(qty: str, line: str = "1") -> httpx.Response:
        return api.post(
            "/goods-receipts",
            json={
                "po_number": "PO-1",
                "received_on": "2026-10-20",
                "items": [{"line_id": line, "qty_received": qty}],
            },
            headers=STAFF,
        )

    assert receive("30").json()["gr_id"] == "GR-1"
    assert receive("10").json()["gr_id"] == "GR-2"
    over = receive("10.5")
    assert over.status_code == 409
    assert "more than the 50 ordered" in over.json()["error"]["message"]
    assert receive("1", line="9").status_code == 422

    po = api.get("/purchase-orders/PO-1", headers=STAFF).json()
    assert [line["qty_received"] for line in po["items"]] == ["40", "0"]
    receipts = api.get("/goods-receipts?po_number=PO-1", headers=STAFF).json()["items"]
    assert [r["gr_id"] for r in receipts] == ["GR-2", "GR-1"]
    assert receipts[0]["received_by"] == "u-staff"


def test_receipt_for_missing_po_is_404(api: TestClient) -> None:
    res = api.post(
        "/goods-receipts",
        json={
            "po_number": "PO-9",
            "received_on": "2026-10-20",
            "items": [{"line_id": "1", "qty_received": "1"}],
        },
        headers=STAFF,
    )
    assert res.status_code == 404


def test_pagination(api: TestClient) -> None:
    for name in ["A Co", "B Co", "C Traders"]:
        _supplier(api, name)
    first = api.get("/suppliers?limit=2", headers=STAFF).json()
    assert len(first["items"]) == 2 and first["next_cursor"]
    second = api.get(f"/suppliers?limit=2&cursor={first['next_cursor']}", headers=STAFF).json()
    assert len(second["items"]) == 1 and second["next_cursor"] is None


def test_business_rules_default_and_update(api: TestClient) -> None:
    assert api.get("/business-rules", headers=ADMIN).json() == {
        "price_tolerance_percent": "2.0",
        "auto_approve_max_paise": 5000000,
        "min_field_confidence": "0.85",
    }
    new = {
        "price_tolerance_percent": "1.5",
        "auto_approve_max_paise": 100000,
        "min_field_confidence": "0.9",
    }
    assert api.put("/business-rules", json=new, headers=ADMIN).status_code == 200
    assert api.get("/business-rules", headers=ADMIN).json() == new
    bad = {**new, "min_field_confidence": "1.5"}
    assert api.put("/business-rules", json=bad, headers=ADMIN).status_code == 422
