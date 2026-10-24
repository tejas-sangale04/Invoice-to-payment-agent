"""Emailing the supplier: on rejection, and about a held invoice. The mail server is faked;
everything else is real, on the emulator. The supplier in pipeline_env is ap@example.in."""

import os

import pytest

from app.services import mailer
from app.services.mailer import MailerError
from tests.factories import invoice_json
from tests.pipeline_env import ADMIN, MANAGER, STAFF, actions, deliver, overpriced_milk, upload, use

pytestmark = [
    pytest.mark.emulator,
    pytest.mark.skipif(
        not os.environ.get("FIRESTORE_EMULATOR_HOST"), reason="emulator not running"
    ),
]

EMAIL = {
    "subject": "Invoice SD-1042: please send a credit note",
    "body": "Dear Sharma Dairy,\n\nInvoice SD-1042 bills Rs 61 a litre; the PO price is Rs 60.\n",
}


class FakeMailer:
    sender = "Brew & Bake Accounts <accounts@example.in>"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self.error: str | None = None

    def send(self, to: str, subject: str, body: str) -> None:
        if self.error:
            raise MailerError(self.error)
        self.sent.append((to, subject, body))


@pytest.fixture
def smtp(monkeypatch: pytest.MonkeyPatch) -> FakeMailer:
    fake = FakeMailer()
    monkeypatch.setattr(mailer, "get_mailer", lambda: fake)
    return fake


def waiting(api, monkeypatch) -> str:
    """Milk billed Rs 61 against Rs 60: within tolerance, so it waits for a manager."""
    deliver(api, "PO-1")
    use(monkeypatch, overpriced_milk())
    inv = upload(api)
    assert inv["status"] == "pending_approval"
    return inv["invoice_id"]


def held(api, monkeypatch) -> str:
    deliver(api, "PO-1", milk="40")
    use(monkeypatch, invoice_json())
    inv = upload(api)
    assert inv["status"] == "on_hold"
    return inv["invoice_id"]


def test_rejecting_can_email_the_supplier_on_file(api, monkeypatch, po1, smtp) -> None:
    invoice_id = waiting(api, monkeypatch)
    body = {"reason": "Overbilled", "email": EMAIL}
    res = api.post(f"/invoices/{invoice_id}/reject", json=body, headers=MANAGER)
    assert res.status_code == 200, res.text
    inv = res.json()
    assert inv["status"] == "rejected"
    assert smtp.sent == [("ap@example.in", EMAIL["subject"], EMAIL["body"].strip())]
    sent = inv["supplier_email"]
    assert (sent["status"], sent["to"], sent["error"]) == ("sent", "ap@example.in", None)
    assert (sent["by_email"], sent["subject"]) == ("manager@example.com", EMAIL["subject"])
    assert actions(api, invoice_id)[-2:] == ["rejected", "supplier_emailed"]


def test_rejecting_without_an_email_sends_nothing(api, monkeypatch, po1, smtp) -> None:
    invoice_id = waiting(api, monkeypatch)
    res = api.post(f"/invoices/{invoice_id}/reject", json={"reason": "No"}, headers=MANAGER)
    assert res.json()["status"] == "rejected" and res.json()["supplier_email"] is None
    assert smtp.sent == []


def test_email_that_cant_go_out_stops_the_rejection(api, monkeypatch, po1) -> None:
    # No mail settings: refuse before rejecting, so the manager can fix it or untick the box.
    monkeypatch.setattr(mailer, "get_mailer", lambda: None)
    invoice_id = waiting(api, monkeypatch)
    body = {"reason": "Overbilled", "email": EMAIL}
    res = api.post(f"/invoices/{invoice_id}/reject", json=body, headers=MANAGER)
    assert res.status_code == 503
    assert "Email isn't set up" in res.json()["error"]["message"]
    assert api.get(f"/invoices/{invoice_id}", headers=STAFF).json()["status"] == "pending_approval"


def test_a_failed_send_is_recorded_and_the_rejection_stands(api, monkeypatch, po1, smtp) -> None:
    invoice_id = waiting(api, monkeypatch)
    smtp.error = "The mail server refused the login."
    body = {"reason": "Overbilled", "email": EMAIL}
    res = api.post(f"/invoices/{invoice_id}/reject", json=body, headers=MANAGER)
    assert res.status_code == 200
    inv = res.json()
    assert inv["status"] == "rejected"
    assert (inv["supplier_email"]["status"], inv["supplier_email"]["error"]) == (
        "failed",
        "The mail server refused the login.",
    )
    assert actions(api, invoice_id)[-1] == "supplier_email_failed"

    # Try again once the mail settings are fixed.
    smtp.error = None
    res = api.post(f"/invoices/{invoice_id}/email-supplier", json=EMAIL, headers=MANAGER)
    assert res.json()["supplier_email"]["status"] == "sent"
    assert len(smtp.sent) == 1


def test_a_held_invoice_can_be_emailed(api, monkeypatch, po1, smtp) -> None:
    invoice_id = held(api, monkeypatch)
    res = api.post(f"/invoices/{invoice_id}/email-supplier", json=EMAIL, headers=MANAGER)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "on_hold"
    assert [m[0] for m in smtp.sent] == ["ap@example.in"]
    assert "supplier_emailed" in actions(api, invoice_id)


def test_the_recipient_cannot_be_chosen_by_the_caller(api, monkeypatch, po1, smtp) -> None:
    invoice_id = held(api, monkeypatch)
    body = {**EMAIL, "to": "someone@else.com", "cc": "x@y.com"}
    api.post(f"/invoices/{invoice_id}/email-supplier", json=body, headers=MANAGER)
    assert [m[0] for m in smtp.sent] == ["ap@example.in"]


def test_only_managers_can_email_and_a_subject_cant_inject_headers(
    api, monkeypatch, po1, smtp
) -> None:
    invoice_id = held(api, monkeypatch)
    url = f"/invoices/{invoice_id}/email-supplier"
    assert api.post(url, json=EMAIL, headers=STAFF).status_code == 403
    bad = {**EMAIL, "subject": "Hi\nBcc: someone@else.com"}
    assert api.post(url, json=bad, headers=MANAGER).status_code == 422
    assert api.post(url, json={**EMAIL, "body": " "}, headers=MANAGER).status_code == 422
    assert smtp.sent == []


def test_posted_invoices_are_not_emailed(api, monkeypatch, po1, smtp) -> None:
    deliver(api, "PO-1")
    use(monkeypatch, invoice_json())
    inv = upload(api)
    assert inv["status"] == "posted"
    res = api.post(f"/invoices/{inv['invoice_id']}/email-supplier", json=EMAIL, headers=ADMIN)
    assert res.status_code == 409
    assert smtp.sent == []


def test_no_supplier_on_file_means_no_address(api, monkeypatch, po1, smtp) -> None:
    use(monkeypatch, invoice_json(supplier_name="Nobody Traders", supplier_gstin=None))
    inv = upload(api)
    assert inv["status"] == "needs_review"
    res = api.post(f"/invoices/{inv['invoice_id']}/email-supplier", json=EMAIL, headers=MANAGER)
    assert res.status_code == 422
    assert "isn't matched to a supplier on file" in res.json()["error"]["message"]
    assert smtp.sent == []


def test_email_status_tells_the_app_whether_to_offer_sending(api, monkeypatch, smtp) -> None:
    res = api.get("/email-status", headers=MANAGER)
    assert res.json() == {"enabled": True, "sender": FakeMailer.sender}
    assert api.get("/email-status", headers=STAFF).status_code == 403
    monkeypatch.setattr(mailer, "get_mailer", lambda: None)
    assert api.get("/email-status", headers=MANAGER).json() == {"enabled": False, "sender": None}


def test_the_agent_drafts_the_email_and_nothing_is_sent(api, monkeypatch, po1, smtp) -> None:
    invoice_id = waiting(api, monkeypatch)
    url = f"/invoices/{invoice_id}/email-draft"
    plain = api.post(url, headers=MANAGER).json()["email"]
    assert plain.startswith("Subject:") and "We have rejected" not in plain
    rejected = api.post(f"{url}?rejected=true", headers=MANAGER)
    assert rejected.status_code == 200, rejected.text
    assert "We have rejected this invoice" in rejected.json()["email"]
    assert smtp.sent == []
    assert (
        api.get(f"/invoices/{invoice_id}", headers=MANAGER).json()["status"] == "pending_approval"
    )


def test_only_managers_can_ask_for_a_draft(api, monkeypatch, po1, smtp) -> None:
    invoice_id = waiting(api, monkeypatch)
    assert api.post(f"/invoices/{invoice_id}/email-draft", headers=STAFF).status_code == 403


def test_no_draft_before_the_invoice_is_read(api, monkeypatch, po1, smtp) -> None:
    use(monkeypatch, "", "")
    inv = upload(api)
    assert inv["status"] == "needs_review"
    res = api.post(f"/invoices/{inv['invoice_id']}/email-draft", headers=MANAGER)
    assert res.status_code == 409
