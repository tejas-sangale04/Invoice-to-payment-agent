"""Editing a PO and deleting an unposted invoice, on the emulator."""

import os

import pytest

from tests.factories import invoice_json
from tests.pipeline_env import ADMIN, MANAGER, STAFF, actions, deliver, upload, use

pytestmark = [
    pytest.mark.emulator,
    pytest.mark.skipif(
        not os.environ.get("FIRESTORE_EMULATOR_HOST"), reason="emulator not running"
    ),
]

ITEMS = [
    {"name": "Full cream milk", "qty": "50", "unit": "L", "unit_price_paise": 6000},
    {"name": "Paneer", "qty": "2.5", "unit": "kg", "unit_price_paise": 40000, "tax_rate": "5"},
]


def test_a_manager_can_edit_a_po_nothing_is_billed_against(api, po1) -> None:
    items = [{**ITEMS[0], "unit_price_paise": 6100}, ITEMS[1]]
    res = api.put("/purchase-orders/PO-1", json={"items": items}, headers=MANAGER)
    assert res.status_code == 200, res.text
    assert res.json()["items"][0]["unit_price_paise"] == 6100
    assert api.get("/purchase-orders/PO-1", headers=STAFF).json()["supplier_id"] == "SUP-1"


def test_staff_cannot_edit_a_po(api, po1) -> None:
    res = api.put("/purchase-orders/PO-1", json={"items": ITEMS}, headers=STAFF)
    assert res.status_code == 403


def test_a_po_with_a_posted_invoice_is_locked(api, monkeypatch, po1) -> None:
    deliver(api, "PO-1")
    use(monkeypatch, invoice_json())
    assert upload(api)["status"] == "posted"
    res = api.put("/purchase-orders/PO-1", json={"items": ITEMS}, headers=MANAGER)
    assert res.status_code == 409


def test_received_goods_cannot_be_edited_away(api, po1) -> None:
    deliver(api, "PO-1")
    short = [{**ITEMS[0], "qty": "40"}, ITEMS[1]]
    assert (
        api.put("/purchase-orders/PO-1", json={"items": short}, headers=MANAGER).status_code == 409
    )
    assert (
        api.put("/purchase-orders/PO-1", json={"items": ITEMS[:1]}, headers=MANAGER).status_code
        == 409
    )
    more = [ITEMS[0], ITEMS[1], {**ITEMS[0], "name": "Butter"}]
    assert (
        api.put("/purchase-orders/PO-1", json={"items": more}, headers=MANAGER).status_code == 200
    )


def test_fixing_the_po_then_reprocessing_posts_the_invoice(api, monkeypatch, po1) -> None:
    use(monkeypatch, invoice_json(), invoice_json())
    deliver(api, "PO-1", milk="40")
    inv = upload(api)
    assert inv["status"] == "on_hold"
    api.put(
        "/purchase-orders/PO-1",
        json={"items": [{**ITEMS[0], "qty": "40"}, ITEMS[1]]},
        headers=MANAGER,
    )
    assert api.post(f"/invoices/{inv['invoice_id']}/reprocess", headers=MANAGER).status_code == 200


def test_deleting_an_unposted_invoice_lets_the_same_file_be_uploaded_again(
    api, monkeypatch, po1
) -> None:
    use(monkeypatch, invoice_json(supplier_name="Nobody Traders", supplier_gstin=None))
    data = b"%PDF-1.7\n%same file\n%%EOF\n"
    first = upload(api, data)
    assert first["status"] == "needs_review"
    res = api.delete(f"/invoices/{first['invoice_id']}", headers=MANAGER)
    assert res.status_code == 204
    assert api.get(f"/invoices/{first['invoice_id']}", headers=STAFF).status_code == 404
    assert actions(api, first["invoice_id"])[-1] == "deleted"
    use(monkeypatch, invoice_json())
    deliver(api, "PO-1")
    second = upload(api, data)
    assert second["status"] == "posted"


def test_a_posted_invoice_cannot_be_deleted(api, monkeypatch, po1) -> None:
    deliver(api, "PO-1")
    use(monkeypatch, invoice_json())
    inv = upload(api)
    assert inv["status"] == "posted"
    assert api.delete(f"/invoices/{inv['invoice_id']}", headers=ADMIN).status_code == 409
    assert api.get(f"/invoices/{inv['invoice_id']}", headers=STAFF).status_code == 200


def test_staff_cannot_delete_and_missing_is_404(api, po1) -> None:
    assert api.delete("/invoices/INV-1", headers=STAFF).status_code == 403
    assert api.delete("/invoices/INV-99", headers=MANAGER).status_code == 404
