"""Approval, separation of duties and posting to the ledger, on the emulator. Uses the PO-1
setup from pipeline_env.py: the factory invoice SD-1042 bills Rs 4,050.00 against PO-1."""

import os
import threading

import pytest
from fastapi.testclient import TestClient

from app.api import invoices as invoices_api
from app.models.invoice import InvoiceStatus as S
from app.pipeline import lookup, runner
from app.pipeline.post import post_invoice
from app.services.firestore import get_db
from tests.factories import invoice_json
from tests.pipeline_env import (
    ADMIN,
    MANAGER,
    STAFF,
    actions,
    deliver,
    overpriced_milk,
    post,
    supplier,
    upload,
    use,
)

pytestmark = [
    pytest.mark.emulator,
    pytest.mark.skipif(
        not os.environ.get("FIRESTORE_EMULATOR_HOST"), reason="emulator not running"
    ),
]

KEY = "SUP-1_SD1042"  # supplier + normalised invoice number


def ledger(api: TestClient) -> list[dict]:
    res = api.get("/ledger", headers=MANAGER)
    assert res.status_code == 200, res.text
    return res.json()["items"]


def po(api: TestClient, po_number="PO-1") -> dict:
    return api.get(f"/purchase-orders/{po_number}", headers=STAFF).json()


def upload_as(api: TestClient, headers: dict) -> dict:
    data = f"%PDF-1.7\n%{id(headers)}{len(ledger(api))}\n%%EOF\n".encode()
    res = api.post("/invoices", files={"file": ("inv.pdf", data, "application/pdf")},
                   headers=headers)  # fmt: skip
    assert res.status_code == 201, res.text
    return api.get(f"/invoices/{res.json()['invoice_id']}", headers=STAFF).json()


# ------------------------------------------------------------------ posting


def test_auto_approved_invoice_is_posted_once_and_bills_the_po(api, monkeypatch, po1) -> None:
    deliver(api, po1)
    use(monkeypatch, invoice_json())
    inv = upload(api)
    assert (inv["status"], inv["ledger_key"], inv["posted_by"]) == ("posted", KEY, "agent")
    assert inv["status_reason"] == "Posted Rs 4,050.00 to the ledger against PO-1"

    [entry] = ledger(api)
    assert entry["idempotency_key"] == KEY
    assert (entry["invoice_id"], entry["invoice_no"]) == (inv["invoice_id"], "SD-1042")
    assert (entry["supplier_id"], entry["supplier_name"]) == ("SUP-1", "Sharma Dairy Pvt Ltd")
    assert (entry["amount_paise"], entry["po_number"], entry["posted_by"]) == (
        405000,
        "PO-1",
        "agent",
    )

    order = po(api)
    assert order["status"] == "fully_billed"
    assert [line["qty_billed"] for line in order["items"]] == ["50", "2.5"]


def test_billing_part_of_a_po_leaves_it_partially_billed(api, monkeypatch) -> None:
    items = [
        {"name": "Full cream milk", "qty": "100", "unit": "L", "unit_price_paise": 6000},
        {"name": "Paneer", "qty": "2.5", "unit": "kg", "unit_price_paise": 40000, "tax_rate": "5"},
    ]
    po_number = post(api, "/purchase-orders", {"supplier_id": supplier(api), "items": items})[
        "po_number"
    ]
    deliver(api, po_number)
    use(monkeypatch, invoice_json())
    assert upload(api)["status"] == "posted"
    assert po(api, po_number)["status"] == "partially_billed"


def test_posting_again_changes_nothing(api, monkeypatch, po1) -> None:
    deliver(api, po1)
    use(monkeypatch, invoice_json())
    inv = upload(api)
    assert post_invoice(get_db(), inv["invoice_id"], "agent") == S.posted
    assert len(ledger(api)) == 1
    assert [line["qty_billed"] for line in po(api)["items"]] == ["50", "2.5"]
    assert actions(api, inv["invoice_id"]).count("posted") == 1


def _two_auto_approved_copies(api, monkeypatch, po1) -> tuple[str, str]:
    """Two uploads of SD-1042 that both got past the duplicate check at the same moment."""
    deliver(api, po1)
    monkeypatch.delitem(runner.STEPS, S.auto_approved)  # stop before posting
    monkeypatch.setattr(lookup, "duplicate_number", lambda *a: None)
    monkeypatch.setattr(lookup, "committed_quantities", lambda *a: {})
    monkeypatch.setattr(lookup, "possible_duplicate", lambda *a: None)
    use(monkeypatch, invoice_json(), invoice_json())
    first, second = upload(api), upload(api)
    assert first["status"] == second["status"] == "auto_approved"
    return first["invoice_id"], second["invoice_id"]


def _post_together(*invoice_ids: str) -> list[S]:
    results: dict[int, S] = {}
    start = threading.Barrier(len(invoice_ids))

    def go(i: int, invoice_id: str) -> None:
        start.wait()
        results[i] = post_invoice(get_db(), invoice_id, "agent")

    threads = [threading.Thread(target=go, args=p) for p in enumerate(invoice_ids)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return [results[i] for i in range(len(invoice_ids))]


def test_two_copies_posted_at_once_make_one_ledger_entry(api, monkeypatch, po1) -> None:
    first, second = _two_auto_approved_copies(api, monkeypatch, po1)
    assert sorted(_post_together(first, second)) == sorted([S.posted, S.blocked_duplicate])
    [entry] = ledger(api)
    blocked = second if entry["invoice_id"] == first else first
    inv = api.get(f"/invoices/{blocked}", headers=STAFF).json()
    assert inv["duplicate_of"] == entry["invoice_id"]
    assert inv["status_reason"] == (
        f"Invoice SD-1042 from Sharma Dairy Pvt Ltd is already in the ledger as "
        f"{entry['invoice_id']}, so it was not posted again."
    )
    assert [line["qty_billed"] for line in po(api)["items"]] == ["50", "2.5"]  # billed once


def test_the_same_invoice_posted_twice_at_once_is_posted_once(api, monkeypatch, po1) -> None:
    first, _ = _two_auto_approved_copies(api, monkeypatch, po1)
    assert _post_together(first, first, first) == [S.posted] * 3
    assert len(ledger(api)) == 1
    assert [line["qty_billed"] for line in po(api)["items"]] == ["50", "2.5"]


# ---------------------------------------------------------------- approvals


def test_manager_approval_posts_at_the_po_price(api, monkeypatch, po1) -> None:
    deliver(api, po1)
    use(monkeypatch, overpriced_milk())
    inv = upload(api)
    assert inv["status"] == "pending_approval"
    assert ledger(api) == []

    res = api.post(f"/invoices/{inv['invoice_id']}/approve", json={"comment": "OK this once"},
                   headers=MANAGER)  # fmt: skip
    assert res.status_code == 200, res.text
    done = res.json()
    assert done["status"] == "posted"
    assert (done["approved_by"], done["approved_by_email"]) == ("u-manager", "manager@example.com")
    assert done["approval_comment"] == "OK this once"
    assert actions(api, inv["invoice_id"])[-2:] == ["approved", "posted"]
    [entry] = ledger(api)
    # Billed Rs 4,100.00 at Rs 61 a litre; the PO price is Rs 60, so Rs 4,050.00 is posted.
    assert (entry["amount_paise"], entry["posted_by"]) == (405000, "u-manager")


def test_approve_without_a_comment(api, monkeypatch, po1) -> None:
    deliver(api, po1)
    use(monkeypatch, overpriced_milk())
    inv = upload(api)
    res = api.post(f"/invoices/{inv['invoice_id']}/approve", headers=MANAGER)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "posted"


def _held_short_delivery(api, monkeypatch, po1) -> str:
    deliver(api, po1, milk="40")
    use(monkeypatch, invoice_json())
    inv = upload(api)
    assert inv["status"] == "on_hold"
    return inv["invoice_id"]


def test_a_manager_can_approve_a_held_invoice_and_only_the_delivered_part_is_paid(
    api, monkeypatch, po1
) -> None:
    invoice_id = _held_short_delivery(api, monkeypatch, po1)
    res = api.post(f"/invoices/{invoice_id}/approve", json={}, headers=MANAGER)
    assert res.status_code == 422  # a hold is only overridden with a reason
    assert api.get(f"/invoices/{invoice_id}", headers=STAFF).json()["status"] == "on_hold"

    res = api.post(
        f"/invoices/{invoice_id}/approve", json={"comment": "Rest follows"}, headers=MANAGER
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "posted"
    # 40 L at Rs 60 + 2.5 kg paneer with GST: Rs 3,450.00, not the Rs 4,050.00 billed.
    [entry] = ledger(api)
    assert entry["amount_paise"] == 345000
    # Only the 40 L paid for count as billed, so the other 10 L can still be billed later.
    assert [line["qty_billed"] for line in po(api)["items"]] == ["40", "2.5"]


def test_a_held_invoice_can_be_rejected(api, monkeypatch, po1) -> None:
    invoice_id = _held_short_delivery(api, monkeypatch, po1)
    res = api.post(
        f"/invoices/{invoice_id}/reject", json={"reason": "Send a credit note"}, headers=MANAGER
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "rejected"
    assert ledger(api) == []


def test_nobody_approves_or_rejects_their_own_upload(api, monkeypatch, po1) -> None:
    deliver(api, po1)
    use(monkeypatch, overpriced_milk())
    inv = upload_as(api, MANAGER)
    assert inv["status"] == "pending_approval"
    for verb, body in (("approve", {}), ("reject", {"reason": "No"})):
        res = api.post(f"/invoices/{inv['invoice_id']}/{verb}", json=body, headers=MANAGER)
        assert res.status_code == 403
        assert res.json()["error"]["message"] == (
            f"You uploaded this invoice, so another manager has to {verb} it"
        )
    # Another manager (here an admin) can.
    res = api.post(f"/invoices/{inv['invoice_id']}/approve", json={}, headers=ADMIN)
    assert res.json()["status"] == "posted"


def test_staff_cannot_approve_reject_or_see_the_ledger(api, monkeypatch, po1) -> None:
    deliver(api, po1)
    use(monkeypatch, overpriced_milk())
    inv = upload_as(api, MANAGER)
    assert api.post(f"/invoices/{inv['invoice_id']}/approve", headers=STAFF).status_code == 403
    res = api.post(f"/invoices/{inv['invoice_id']}/reject", json={"reason": "x"}, headers=STAFF)
    assert res.status_code == 403
    assert api.get("/ledger", headers=STAFF).status_code == 403


def test_reject_needs_a_reason_and_posts_nothing(api, monkeypatch, po1) -> None:
    deliver(api, po1)
    use(monkeypatch, overpriced_milk())
    inv = upload(api)
    url = f"/invoices/{inv['invoice_id']}/reject"
    assert api.post(url, json={"reason": "   "}, headers=MANAGER).status_code == 422
    assert api.post(url, json={}, headers=MANAGER).status_code == 422

    res = api.post(url, json={"reason": "Ask for a credit note"}, headers=MANAGER)
    assert res.status_code == 200, res.text
    done = res.json()
    assert (done["status"], done["rejection_reason"]) == ("rejected", "Ask for a credit note")
    assert done["status_reason"] == "Rejected by manager@example.com: Ask for a credit note"
    assert ledger(api) == []
    assert po(api)["status"] == "open"


def test_only_invoices_waiting_for_approval_can_be_decided(api, monkeypatch, po1) -> None:
    deliver(api, po1)
    use(monkeypatch, invoice_json())
    inv = upload(api)  # auto-approved and posted
    res = api.post(f"/invoices/{inv['invoice_id']}/approve", headers=MANAGER)
    assert res.status_code == 409
    assert res.json()["error"]["message"] == (
        "Only invoices waiting for approval or on hold can be approved (this one is posted)"
    )
    res = api.post(f"/invoices/{inv['invoice_id']}/reject", json={"reason": "x"}, headers=MANAGER)
    assert res.status_code == 409
    assert api.post("/invoices/INV-99/approve", headers=MANAGER).status_code == 404


def test_if_posting_fails_after_approval_the_pipeline_posts_it(api, monkeypatch, po1) -> None:
    deliver(api, po1)
    use(monkeypatch, overpriced_milk())
    inv = upload(api)

    def broken(*args):
        raise RuntimeError("Firestore write failed")

    monkeypatch.setattr(invoices_api, "post_invoice", broken)
    res = api.post(f"/invoices/{inv['invoice_id']}/approve", headers=MANAGER)
    assert res.status_code == 200, res.text
    # The response is read before the background job runs; the job then posts it.
    assert res.json()["status"] == "approved"
    after = api.get(f"/invoices/{inv['invoice_id']}", headers=STAFF).json()
    assert (after["status"], after["posted_by"]) == ("posted", "agent")
    assert len(ledger(api)) == 1
