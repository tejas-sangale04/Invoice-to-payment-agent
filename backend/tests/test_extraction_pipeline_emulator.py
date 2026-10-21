"""Extraction and validation steps in the pipeline, with a scripted extractor, on the emulator."""

import os

import pytest
from fastapi.testclient import TestClient

from app.agents import extraction
from app.agents.extraction import ExtractionTimeout
from app.main import create_app
from app.models.invoice import InvoiceStatus as S
from app.pipeline import runner
from app.services import firebase
from app.services import storage as storage_svc
from app.services.firestore import get_db
from app.services.storage import LocalStorage, get_storage
from tests.conftest import _fake_verify, bearer
from tests.emulator_utils import clear_firestore
from tests.factories import CONFIDENT, FakeExtractor, invoice_json

pytestmark = [
    pytest.mark.emulator,
    pytest.mark.skipif(
        not os.environ.get("FIRESTORE_EMULATOR_HOST"), reason="emulator not running"
    ),
]

STAFF = bearer("staff-token")
PDF = b"%PDF-1.7\n%%EOF\n"


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, tmp_path) -> TestClient:
    clear_firestore()
    monkeypatch.setattr(firebase, "verify_id_token", _fake_verify)
    store = LocalStorage(str(tmp_path), "http://testserver", "secret", ttl=60)
    monkeypatch.setattr(storage_svc, "get_storage", lambda: store)
    app = create_app()
    app.dependency_overrides[get_storage] = lambda: store
    return TestClient(app)


def use(monkeypatch: pytest.MonkeyPatch, fake: FakeExtractor) -> FakeExtractor:
    monkeypatch.setattr(extraction, "get_extractor", lambda: fake)
    return fake


def run(api: TestClient) -> dict:
    res = api.post("/invoices", files={"file": ("inv.pdf", PDF, "application/pdf")}, headers=STAFF)
    assert res.status_code == 201, res.text
    return api.get(f"/invoices/{res.json()['invoice_id']}", headers=STAFF).json()


def actions(api: TestClient, invoice_id: str) -> list[str]:
    items = api.get(f"/audit-log?invoice_id={invoice_id}", headers=STAFF).json()["items"]
    return [a["action"] for a in items]


def test_valid_reading_is_saved_in_paise_and_validated(api, monkeypatch) -> None:
    fake = use(monkeypatch, FakeExtractor(invoice_json()))
    inv = run(api)

    assert fake.feedback == [None]  # one call, no retry needed
    assert actions(api, inv["invoice_id"]) == [
        "uploaded",
        "processing_started",
        "extracted",
        "validated",
        "matched",
        "decided_needs_review",
    ]
    e = inv["extracted"]
    assert (e["supplier_name"], e["invoice_no"], e["po_number"]) == (
        "Sharma Dairy Pvt Ltd",
        "SD-1042",
        "PO-1",
    )
    assert (e["subtotal_paise"], e["cgst_paise"], e["sgst_paise"], e["total_paise"]) == (
        400000,
        2500,
        2500,
        405000,
    )
    assert e["items"][1] == {
        "name": "Paneer",
        "qty": "2.5",
        "unit": "kg",
        "unit_price_paise": 40000,
        "tax_rate": "5",
        "amount_paise": 100000,
    }
    assert inv["validation_issues"] == []
    assert inv["ai_usage"] == {
        "calls": 1,
        "input_tokens": 1000,
        "output_tokens": 200,
        "latency_ms": 1500,
    }
    # No supplier or PO exists in this test, so a person takes over; never auto-approved.
    assert inv["status"] == "needs_review"
    assert inv["decision_rule"] == "no_matching_po"


def test_failed_checks_are_fed_back_once_and_the_retry_can_fix_them(api, monkeypatch) -> None:
    fake = use(monkeypatch, FakeExtractor(invoice_json(total="5,050.00"), invoice_json()))
    inv = run(api)
    assert fake.feedback[0] is None
    assert "but the total reads Rs 5,050.00" in fake.feedback[1]
    assert inv["extracted"]["total_paise"] == 405000
    assert inv["ai_usage"]["calls"] == 2
    assert "validated" in actions(api, inv["invoice_id"])


def test_still_wrong_after_retry_goes_to_review_with_the_reasons(api, monkeypatch) -> None:
    low = {**CONFIDENT, "totals": 0.4}
    use(
        monkeypatch,
        FakeExtractor(invoice_json(field_confidence=low), invoice_json(field_confidence=low)),
    )
    inv = run(api)
    assert inv["status"] == "needs_review"
    assert inv["decision"] == "needs_review"
    assert inv["validation_issues"] == ["Not confident enough reading: totals"]
    assert "didn't check out: Not confident enough reading: totals" in inv["status_reason"]
    assert inv["extracted"]["total_paise"] == 405000  # the reading is kept for the reviewer
    assert actions(api, inv["invoice_id"])[-2:] == ["extracted", "validation_failed"]


def test_unreadable_output_twice_goes_to_review_with_nothing_used(api, monkeypatch) -> None:
    use(monkeypatch, FakeExtractor("not json", '{"invoice_no": "x"}'))
    inv = run(api)
    assert inv["status"] == "needs_review"
    assert inv["extracted"] is None
    assert inv["validation_issues"][0].startswith("The response did not match the schema")
    assert actions(api, inv["invoice_id"])[-1] == "extraction_failed"


def test_gemini_timeouts_retry_then_fail_safe(api, monkeypatch) -> None:
    fake = use(monkeypatch, FakeExtractor(*[ExtractionTimeout("slow")] * 5))
    inv = run(api)
    assert len(fake.feedback) == 5  # one per task attempt
    assert inv["status"] == "failed"
    assert inv["decision"] == "needs_review"
    assert "ExtractionTimeout" in inv["status_reason"]


def test_timeout_then_success_on_task_retry(api, monkeypatch) -> None:
    use(monkeypatch, FakeExtractor(ExtractionTimeout("slow"), invoice_json()))
    inv = run(api)
    assert "validated" in actions(api, inv["invoice_id"])
    assert inv["processing_attempts"] == 2


def test_resuming_at_extracted_does_not_call_the_model_again(api, monkeypatch) -> None:
    fake = use(monkeypatch, FakeExtractor(invoice_json()))
    inv = run(api)
    db = get_db()
    # Simulate a crash right after the reading was saved: put it back to `extracted`.
    db.collection("invoices").document(inv["invoice_id"]).update({"status": "extracted"})
    assert runner.run_steps(db, inv["invoice_id"]) == S.needs_review
    assert fake.feedback == [None]  # still only the original call
    assert actions(api, inv["invoice_id"]).count("validated") == 2


def test_stricter_rules_apply_on_revalidation(api, monkeypatch) -> None:
    use(monkeypatch, FakeExtractor(invoice_json()))
    inv = run(api)
    db = get_db()
    db.collection("business_rules").document("default").set({"min_field_confidence": "0.99"})
    db.collection("invoices").document(inv["invoice_id"]).update({"status": "extracted"})
    runner.run_steps(db, inv["invoice_id"])
    doc = db.collection("invoices").document(inv["invoice_id"]).get().to_dict()
    assert doc["status"] == "needs_review"
    assert doc["validation_issues"][0].startswith("Not confident enough reading:")
