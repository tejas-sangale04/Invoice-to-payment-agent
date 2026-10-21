"""Invoice intake, status machine, audit log and background processing on the emulator."""

import os
import threading

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models.invoice import InvoiceStatus as S
from app.pipeline import runner
from app.pipeline.status import InvalidTransition, transition
from app.services import firebase
from app.services.firestore import get_db
from app.services.storage import LocalStorage, get_storage
from tests.conftest import _fake_verify, bearer
from tests.emulator_utils import clear_firestore

pytestmark = [
    pytest.mark.emulator,
    pytest.mark.skipif(
        not os.environ.get("FIRESTORE_EMULATOR_HOST"), reason="emulator not running"
    ),
]

STAFF, MANAGER = bearer("staff-token"), bearer("manager-token")
PDF = b"%PDF-1.7\n1 0 obj << >> endobj\n%%EOF\n"


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, tmp_path) -> TestClient:
    clear_firestore()
    monkeypatch.setattr(firebase, "verify_id_token", _fake_verify)
    app = create_app()
    store = LocalStorage(str(tmp_path), "http://testserver", "test-secret", ttl=60)
    app.dependency_overrides[get_storage] = lambda: store
    return TestClient(app)


def upload(api: TestClient, data: bytes = PDF, name: str = "milk.pdf") -> dict:
    res = api.post("/invoices", files={"file": (name, data, "application/pdf")}, headers=STAFF)
    assert res.status_code == 201, res.text
    return res.json()


def audit_actions(api: TestClient, invoice_id: str) -> list[tuple[str, str | None, str]]:
    items = api.get(f"/audit-log?invoice_id={invoice_id}", headers=STAFF).json()["items"]
    return [(a["action"], a["from_status"], a["to_status"]) for a in items]


def test_upload_creates_record_then_pipeline_routes_to_review(api: TestClient) -> None:
    created = upload(api)
    assert created["invoice_id"] == "INV-1"
    assert created["status"] == "received"  # the response returns before processing
    assert created["file_name"] == "milk.pdf"
    assert created["content_type"] == "application/pdf"
    assert len(created["file_hash"]) == 64

    # The background job ran after the response: no extractor yet, so a person reviews it.
    inv = api.get("/invoices/INV-1", headers=STAFF).json()
    assert inv["status"] == "needs_review"
    assert inv["decision"] == "needs_review"
    assert "switched off" in inv["status_reason"]
    assert inv["processing_attempts"] == 1
    assert set(inv["status_times"]) == {"received", "extracting", "needs_review"}
    assert audit_actions(api, "INV-1") == [
        ("uploaded", None, "received"),
        ("processing_started", "received", "extracting"),
        ("extraction_unavailable", "extracting", "needs_review"),
    ]


def test_signed_file_link_serves_the_original_bytes(api: TestClient) -> None:
    upload(api)
    link = api.get("/invoices/INV-1/file", headers=STAFF).json()
    assert link["content_type"] == "application/pdf"
    res = api.get(link["url"].removeprefix("http://testserver"))
    assert res.status_code == 200
    assert res.content == PDF
    assert res.headers["content-type"] == "application/pdf"
    tampered = link["url"].replace("INV", "x").replace("sig=", "sig=0")
    assert api.get(tampered.removeprefix("http://testserver")).status_code == 403


def test_list_filters_by_status_and_paginates(api: TestClient) -> None:
    for i in range(3):
        upload(api, PDF + str(i).encode(), f"{i}.pdf")
    page = api.get("/invoices?limit=2", headers=STAFF).json()
    assert [i["invoice_id"] for i in page["items"]] == ["INV-3", "INV-2"]
    rest = api.get(f"/invoices?limit=2&cursor={page['next_cursor']}", headers=STAFF).json()
    assert [i["invoice_id"] for i in rest["items"]] == ["INV-1"]
    assert len(api.get("/invoices?status=needs_review", headers=STAFF).json()["items"]) == 3
    assert api.get("/invoices?status=paid", headers=STAFF).json()["items"] == []
    assert api.get("/invoices/INV-9", headers=STAFF).status_code == 404


def test_manager_can_reprocess_and_it_is_audited(api: TestClient) -> None:
    upload(api)
    assert api.post("/invoices/INV-1/reprocess", headers=STAFF).status_code == 403
    res = api.post("/invoices/INV-1/reprocess", headers=MANAGER)
    assert res.status_code == 200
    assert res.json()["status"] == "received"
    # ...and the background job ran it through again.
    assert api.get("/invoices/INV-1", headers=STAFF).json()["status"] == "needs_review"
    actions = [a for a, _, _ in audit_actions(api, "INV-1")]
    assert actions[3:] == ["reprocess_requested", "processing_started", "extraction_unavailable"]


def test_reprocess_refused_for_invoices_that_are_not_stuck(api: TestClient) -> None:
    upload(api)
    db = get_db()
    db.collection("invoices").document("INV-1").update({"status": "pending_approval"})
    res = api.post("/invoices/INV-1/reprocess", headers=MANAGER)
    assert res.status_code == 409
    assert "pending approval" in res.json()["error"]["message"]


def test_transition_is_idempotent_and_guards_unsafe_moves(api: TestClient) -> None:
    upload(api)
    db = get_db()
    # needs_review -> received twice: second call is a no-op, so only one audit entry.
    transition(db, "INV-1", S.received, actor="u", action="x")
    transition(db, "INV-1", S.received, actor="u", action="x")
    assert [a for a, _, _ in audit_actions(api, "INV-1")].count("x") == 1
    with pytest.raises(InvalidTransition):
        transition(db, "INV-1", S.posted, actor="u", action="y")
    with pytest.raises(InvalidTransition):  # moved on by someone else
        transition(db, "INV-1", S.extracting, actor="u", action="y", expected_from=S.matched)


def test_concurrent_workers_produce_one_transition(api: TestClient) -> None:
    upload(api)
    db = get_db()
    transition(db, "INV-1", S.received, actor="u", action="reset")
    errors: list[Exception] = []

    def worker() -> None:
        try:
            transition(
                db, "INV-1", S.extracting, actor="agent", action="race", expected_from=S.received
            )
        except Exception as exc:  # pragma: no cover - would fail the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert [a for a, _, _ in audit_actions(api, "INV-1")].count("race") == 1


def test_pipeline_resumes_from_saved_status(api: TestClient) -> None:
    upload(api)
    db = get_db()
    calls: list[str] = []
    transition(db, "INV-1", S.received, actor="u", action="reset")
    transition(db, "INV-1", S.extracting, actor="agent", action="processing_started")

    def fake_start(db, invoice_id):  # must not run: the invoice is already past `received`
        calls.append("start")

    original = runner.STEPS[S.received]
    runner.STEPS[S.received] = fake_start
    try:
        assert runner.run_steps(db, "INV-1") == S.needs_review
    finally:
        runner.STEPS[S.received] = original
    assert calls == []


def test_errors_retry_then_fail_safe_to_a_person(api: TestClient, monkeypatch) -> None:
    def boom(db, invoice_id):
        raise TimeoutError("Gemini timed out")

    monkeypatch.setitem(runner.STEPS, S.extracting, boom)
    upload(api)  # inline mode retries max_processing_attempts times, then gives up safely
    inv = api.get("/invoices/INV-1", headers=STAFF).json()
    assert inv["status"] == "failed"
    assert inv["decision"] == "needs_review"
    assert "TimeoutError" in inv["status_reason"]
    assert inv["processing_attempts"] == 5
    assert audit_actions(api, "INV-1")[-1] == ("processing_failed", "extracting", "failed")


def test_queue_failure_marks_invoice_failed_not_lost(api: TestClient, monkeypatch) -> None:
    def broken(invoice_id, background):
        raise ConnectionError("Cloud Tasks unavailable")

    monkeypatch.setattr("app.api.invoices.enqueue_processing", broken)
    upload(api)
    inv = api.get("/invoices/INV-1", headers=STAFF).json()
    assert inv["status"] == "failed"
    assert "could not be queued" in inv["status_reason"]
