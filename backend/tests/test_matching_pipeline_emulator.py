"""Duplicate check, PO lookup, 3-way match and decisions through the real pipeline, on the
emulator, with a scripted extractor. PO-1 is the factory invoice's PO: 50 L milk at Rs 60 and
2.5 kg paneer at Rs 400 + 5% GST (Rs 4,050.00 in total)."""

import copy
import itertools
import os

import pytest
from fastapi.testclient import TestClient

from app.agents import extraction
from app.main import create_app
from app.services import firebase
from app.services import storage as storage_svc
from app.services.firestore import get_db
from app.services.storage import LocalStorage, get_storage
from tests.conftest import _fake_verify, bearer
from tests.emulator_utils import clear_firestore
from tests.factories import GOOD, FakeExtractor, invoice_json

pytestmark = [
    pytest.mark.emulator,
    pytest.mark.skipif(
        not os.environ.get("FIRESTORE_EMULATOR_HOST"), reason="emulator not running"
    ),
]

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


# ------------------------------------------------------------------ outcomes


def test_fully_delivered_invoice_is_auto_approved(api, monkeypatch, po1) -> None:
    deliver(api, po1)
    use(monkeypatch, invoice_json())
    inv = upload(api)
    assert inv["status"] == "auto_approved"
    assert (inv["decision"], inv["decision_rule"]) == ("auto_approve", "all_matched")
    m = inv["match_result"]
    assert (m["matched_po"], m["supplier_id"], m["issues"]) == ("PO-1", "SUP-1", [])
    assert (m["correct_amount_paise"], m["difference_paise"]) == (405000, 0)
    assert m["per_line"][0]["po_item_name"] == "Full cream milk"
    assert actions(api, inv["invoice_id"])[-2:] == ["matched", "decided_auto_approve"]


def test_partial_delivery_is_held_with_the_overcharge(api, monkeypatch, po1) -> None:
    deliver(api, po1, milk="40")
    use(monkeypatch, invoice_json())
    inv = upload(api)
    assert inv["status"] == "on_hold"
    assert inv["decision_rule"] == "quantity_exceeds_received"
    assert inv["match_result"]["difference_paise"] == 60000
    assert "Milk: billed 50 L, but only 40 L can be billed (received 40)" in inv["status_reason"]
    assert "so the invoice is Rs 600.00 too high" in inv["decision_reason"]


def test_held_invoice_passes_once_the_rest_is_delivered_and_reprocessed(
    api, monkeypatch, po1
) -> None:
    deliver(api, po1, milk="40")
    use(monkeypatch, invoice_json(), invoice_json())
    inv = upload(api)
    assert inv["status"] == "on_hold"
    deliver(api, po1, milk="10", paneer=None)  # the rest of the milk, in a second receipt
    res = api.post(f"/invoices/{inv['invoice_id']}/reprocess", headers=MANAGER)
    assert res.status_code == 200, res.text
    again = api.get(f"/invoices/{inv['invoice_id']}", headers=STAFF).json()
    assert again["status"] == "auto_approved"


def test_price_within_tolerance_needs_a_manager(api, monkeypatch, po1) -> None:
    deliver(api, po1)
    use(monkeypatch, overpriced_milk())
    inv = upload(api)
    assert inv["status"] == "pending_approval"
    assert inv["decision_rule"] == "price_within_tolerance"
    assert "(1.67% higher, within the 2.0% limit)" in inv["decision_reason"]


def test_admin_tolerance_is_used(api, monkeypatch, po1) -> None:
    res = api.put(
        "/business-rules",
        json={"price_tolerance_percent": "1", "auto_approve_max_paise": 5000000,
              "min_field_confidence": "0.85"},
        headers=ADMIN,
    )  # fmt: skip
    assert res.status_code == 200, res.text
    deliver(api, po1)
    use(monkeypatch, overpriced_milk())
    assert upload(api)["decision_rule"] == "price_over_tolerance"


# ---------------------------------------------------------------- duplicates


def test_same_file_twice_is_blocked_before_any_model_call(api, monkeypatch, po1) -> None:
    deliver(api, po1)
    fake = use(monkeypatch, invoice_json())
    data = b"%PDF-1.7\nsame bytes\n%%EOF\n"
    first, second = upload(api, data), upload(api, data)
    assert first["status"] == "auto_approved"
    assert second["status"] == "blocked_duplicate"
    assert (second["decision"], second["decision_rule"]) == ("block", "duplicate")
    assert (
        second["status_reason"]
        == f"This is the same file as {first['invoice_id']}, uploaded earlier."
    )
    assert len(fake.feedback) == 1  # Gemini was called for the first upload only


def test_same_supplier_and_invoice_number_is_blocked(api, monkeypatch, po1) -> None:
    deliver(api, po1)
    use(monkeypatch, invoice_json(), invoice_json(invoice_no="sd 1042"))
    first, second = upload(api), upload(api)
    assert second["status"] == "blocked_duplicate"
    assert second["decision_reason"] == (
        f"Invoice sd 1042 from Sharma Dairy Pvt Ltd was already uploaded as {first['invoice_id']}."
    )


def test_a_rejected_original_does_not_block_a_corrected_copy(api, monkeypatch, po1) -> None:
    deliver(api, po1)
    use(monkeypatch, invoice_json(), invoice_json())
    first = upload(api)
    get_db().collection("invoices").document(first["invoice_id"]).update({"status": "rejected"})
    assert upload(api)["status"] == "auto_approved"


def test_two_invoices_cannot_bill_the_same_delivery(api, monkeypatch, po1) -> None:
    deliver(api, po1)
    use(monkeypatch, invoice_json(), invoice_json(invoice_no="SD-1043", invoice_date="2026-10-24"))
    first, second = upload(api), upload(api)
    assert first["status"] == "auto_approved"
    # The first invoice isn't posted yet, but its quantities are already spoken for.
    assert second["decision_rule"] == "quantity_exceeds_received"
    assert "already billed on other invoices" in second["decision_reason"]
    kinds = [i["kind"] for i in second["match_result"]["issues"]]
    assert "possible_duplicate" in kinds  # same supplier and total within a week


def test_same_total_within_a_week_under_a_new_number_needs_a_manager(api, monkeypatch, po1) -> None:
    deliver(api, po1)
    use(monkeypatch, invoice_json(), invoice_json(invoice_no="SD-1043", invoice_date="2026-10-24"))
    first = upload(api)
    get_db().collection("invoices").document(first["invoice_id"]).update({"status": "on_hold"})
    second = upload(api)  # the held first invoice doesn't use up the delivery
    assert (second["status"], second["decision_rule"]) == ("pending_approval", "possible_duplicate")
    assert second["decision_reason"] == (
        f"{first['invoice_id']} is from the same supplier for the same total within a week, "
        "under a different invoice number."
    )


# ------------------------------------------------------------- can't match


def test_unknown_po_number_goes_to_review(api, monkeypatch, po1) -> None:
    use(monkeypatch, invoice_json(po_number="PO-99"))
    inv = upload(api)
    assert (inv["status"], inv["decision_rule"]) == ("needs_review", "no_matching_po")
    assert inv["decision_reason"] == "PO number 'PO-99' was not found."


def test_missing_po_number_goes_to_review(api, monkeypatch, po1) -> None:
    use(monkeypatch, invoice_json(po_number=None))
    assert upload(api)["decision_reason"] == "The invoice has no PO number."


def test_unknown_supplier_goes_to_review(api, monkeypatch, po1) -> None:
    use(monkeypatch, invoice_json(supplier_name="Fresh Farms Produce"))
    inv = upload(api)
    assert inv["status"] == "needs_review"
    assert "Supplier 'Fresh Farms Produce' is not in the supplier list" in inv["decision_reason"]


def test_po_of_another_supplier_goes_to_review(api, monkeypatch, po1) -> None:
    supplier(api, "Fresh Farms Produce")
    use(monkeypatch, invoice_json(supplier_name="Fresh Farms Produce"))
    inv = upload(api)
    assert inv["decision_reason"] == (
        "PO-1 is for Sharma Dairy Pvt Ltd, but this invoice is from Fresh Farms Produce."
    )


def test_supplier_found_by_gstin_even_with_another_name(api, monkeypatch) -> None:
    po = purchase_order(api, supplier(api, gstin="27ABCDE1234F1Z5"))
    deliver(api, po)
    use(monkeypatch, invoice_json(supplier_name="SDPL Dairy Division"))
    assert upload(api)["status"] == "auto_approved"


def test_gstin_of_another_supplier_goes_to_review(api, monkeypatch, po1) -> None:
    supplier(api, "Metro Packaging Co", gstin="27ABCDE1234F1Z5")  # the GSTIN on the invoice
    use(monkeypatch, invoice_json())
    inv = upload(api)
    assert inv["status"] == "needs_review"
    assert inv["decision_reason"] == (
        "The invoice is from Sharma Dairy Pvt Ltd, but its GSTIN 27ABCDE1234F1Z5 belongs to "
        "Metro Packaging Co."
    )


def test_gstin_that_differs_from_the_one_on_file_goes_to_review(api, monkeypatch) -> None:
    po = purchase_order(api, supplier(api, gstin="27AAACS1234D1Z9"))
    deliver(api, po)
    use(monkeypatch, invoice_json())
    assert (
        "doesn't match Sharma Dairy Pvt Ltd's GSTIN 27AAACS1234D1Z9"
        in (upload(api)["decision_reason"])
    )
