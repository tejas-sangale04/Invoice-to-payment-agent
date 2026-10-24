"""Failure injection: each test breaks one thing and checks the pipeline still ends safely.

Gemini's replies are scripted here (the failures are the point, not the reading), so these
results are the same in both agent modes. The world is PO-1 from Sharma Dairy: 50 L milk at
Rs 60 and 2.5 kg paneer at Rs 400 + 5% GST, all delivered; the invoice is SD-1042 for
Rs 4,050.00.
"""

import functools
import threading

import pytest

from app.agents import explanation, extraction, resolution
from app.agents.extraction import ExtractionTimeout
from app.models.invoice import InvoiceStatus as S
from app.pipeline import post, runner
from app.services import tasks
from harness import MANAGER, STAFF, build_world, call, clear_firestore, upload
from tests.factories import FakeExtractor, invoice_json

WORLD = {
    "suppliers": [
        {"key": "sharma", "name": "Sharma Dairy Pvt Ltd", "email": "ap@example.in", "gstin": None}
    ],
    "purchase_orders": [
        {
            "po_number": "PO-1",
            "supplier": "sharma",
            "items": [
                {"name": "Full cream milk", "qty": "50", "unit": "L", "unit_price_paise": 6000},
                {
                    "name": "Paneer",
                    "qty": "2.5",
                    "unit": "kg",
                    "unit_price_paise": 40000,
                    "tax_rate": "5",
                },  # fmt: skip
            ],
        }
    ],
    "receipts": [
        {
            "po_number": "PO-1",
            "items": [
                {"line_id": "1", "qty_received": "50"},
                {"line_id": "2", "qty_received": "2.5"},
            ],
        }
    ],
}


def pdf(tag: str) -> bytes:
    return f"%PDF-1.7\n% failure injection: {tag}\n%%EOF\n".encode()


@pytest.fixture
def world(evaluation, monkeypatch: pytest.MonkeyPatch):
    """A fresh world with PO-1, and a scripted Extraction Agent; the other agents are off."""
    clear_firestore()
    build_world(evaluation.api, WORLD)
    monkeypatch.setattr(explanation, "get_explainer", lambda: None)
    monkeypatch.setattr(resolution, "get_resolver", lambda: None)

    def script(*responses) -> FakeExtractor:
        fake = FakeExtractor(*responses)
        monkeypatch.setattr(extraction, "get_extractor", lambda: fake)
        return fake

    return script


def state(api) -> dict:
    po = call(api, "GET", "/purchase-orders/PO-1", STAFF)
    return {
        "ledger": call(api, "GET", "/ledger", MANAGER)["items"],
        "billed": [line["qty_billed"] for line in po["items"]],
        "po_status": po["status"],
    }


def record(evaluation, name: str, expected: str, actual: str, passed: bool) -> None:
    evaluation.results["failures"].append(
        {"name": name, "expected": expected, "actual": actual, "passed": passed}
    )
    assert passed, f"{name}: expected {expected}; got {actual}"


def test_gemini_timeout(evaluation, world) -> None:
    fake = world(*[ExtractionTimeout("Gemini did not answer within 60s")] * 10)
    inv, _ = upload(evaluation.api, pdf("timeout"), "timeout.pdf")
    st = state(evaluation.api)
    record(
        evaluation,
        "Gemini timeout (every attempt)",
        "retried, then failed for a person to check; nothing posted",
        f"{inv['status']} after {inv['processing_attempts']} attempts ({len(fake.feedback)} "
        f"calls), {len(st['ledger'])} ledger entries",
        inv["status"] == "failed" and inv["processing_attempts"] > 1 and not st["ledger"],
    )


def test_gemini_invalid_json(evaluation, world) -> None:
    fake = world("Sure! Here is the invoice: {supplier: Sharma", '{"invoice_no": 12}')
    inv, _ = upload(evaluation.api, pdf("bad json"), "bad-json.pdf")
    st = state(evaluation.api)
    record(
        evaluation,
        "Gemini returns invalid JSON (twice)",
        "one corrective retry, then needs review; nothing posted",
        f"{inv['status']} after {len(fake.feedback)} calls, {len(st['ledger'])} ledger entries",
        inv["status"] == "needs_review" and len(fake.feedback) == 2 and not st["ledger"],
    )


def _failing_once(fn, failures: list[int]):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if failures[0] > 0:
            failures[0] -= 1
            raise RuntimeError("Firestore write failed (injected)")
        return fn(*args, **kwargs)

    return wrapper


def test_firestore_write_error_while_posting(evaluation, world, monkeypatch) -> None:
    # The write fails inside the posting transaction, after the ledger entry and the PO update
    # were staged, on every attempt.
    monkeypatch.setattr(post, "apply_transition", _failing_once(post.apply_transition, [99]))
    world(invoice_json())
    inv, _ = upload(evaluation.api, pdf("write error"), "write-error.pdf")
    st = state(evaluation.api)
    record(
        evaluation,
        "Firestore write error during posting (every attempt)",
        "nothing half-saved: no ledger entry, PO billing unchanged, invoice left for a person",
        f"{inv['status']}, {len(st['ledger'])} ledger entries, PO billed {st['billed']} "
        f"({st['po_status']})",
        inv["status"] == "failed" and not st["ledger"] and st["billed"] == ["0", "0"],
    )


def test_firestore_write_error_then_retry(evaluation, world, monkeypatch) -> None:
    monkeypatch.setattr(post, "apply_transition", _failing_once(post.apply_transition, [1]))
    world(invoice_json())
    inv, _ = upload(evaluation.api, pdf("write error once"), "write-error-once.pdf")
    st = state(evaluation.api)
    amounts = [e["amount_paise"] for e in st["ledger"]]
    record(
        evaluation,
        "Firestore write error during posting, then the retry",
        "posted exactly once: one Rs 4,050.00 entry, PO billed once",
        f"{inv['status']}, ledger {amounts}, PO billed {st['billed']} ({st['po_status']})",
        inv["status"] == "posted" and amounts == [405000] and st["billed"] == ["50", "2.5"],
    )


@pytest.mark.parametrize("same_file", [True, False], ids=["same-file", "rescanned-copy"])
def test_same_invoice_uploaded_twice_at_once(evaluation, world, monkeypatch, same_file) -> None:
    # Both uploads are saved first, then processed at the same moment on two workers.
    from app.api import invoices as invoices_api

    monkeypatch.setattr(invoices_api, "enqueue_processing", lambda *a: None)
    outcomes = []
    for attempt in range(5):
        clear_firestore()
        build_world(evaluation.api, WORLD)
        world(*[invoice_json()] * 4)
        files = [pdf(f"twice {attempt}")] * 2 if same_file else [pdf("a"), pdf("b")]
        ids = [upload(evaluation.api, f, "twice.pdf")[0]["invoice_id"] for f in files]
        start = threading.Barrier(2)

        def work(invoice_id: str, start: threading.Barrier = start) -> None:
            start.wait()
            tasks._run_inline(invoice_id)

        threads = [threading.Thread(target=work, args=(i,)) for i in ids]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        notes = []
        for i in ids:
            inv = call(evaluation.api, "GET", f"/invoices/{i}", STAFF)
            if inv["status"] == "pending_approval":
                # Both copies were matched at the same moment, so the second was only flagged
                # as a possible duplicate. A manager who approves it anyway must not pay twice.
                call(evaluation.api, "POST", f"/invoices/{i}/approve", MANAGER, json={})
                notes.append(f"one held for a manager ({inv['decision_rule']}), then approved")
        statuses = sorted(
            call(evaluation.api, "GET", f"/invoices/{i}", STAFF)["status"] for i in ids
        )
        outcomes.append((statuses, len(state(evaluation.api)["ledger"]), notes))
    kind = "same file" if same_file else "two scans of one invoice"
    record(
        evaluation,
        f"Same invoice uploaded twice concurrently ({kind}, 5 tries)",
        "one ledger entry; the other copy blocked as a duplicate, at the latest when posting",
        "; ".join(
            f"{'/'.join(s)}, {n} entry" + (f" ({', '.join(notes)})" if notes else "")
            for s, n, notes in outcomes
        ),
        all(s == ["blocked_duplicate", "posted"] and n == 1 for s, n, _ in outcomes),
    )


def test_corrupted_or_empty_pdf(evaluation, world) -> None:
    fake = world("", "")
    empty = evaluation.api.post("/invoices", files={"file": ("e.pdf", b"")}, headers=STAFF)
    invoices = call(evaluation.api, "GET", "/invoices", STAFF)["items"]
    broken = b"%PDF-1.7\n\x00\x9c\xff garbage, no objects, no xref"
    inv, _ = upload(evaluation.api, broken, "broken.pdf")
    st = state(evaluation.api)
    record(
        evaluation,
        "Corrupted or empty PDF",
        "empty file refused at upload; unreadable PDF sent to review; nothing posted",
        f"empty: HTTP {empty.status_code}, {len(invoices)} invoices saved; corrupted: "
        f"{inv['status']} after {len(fake.feedback)} calls; {len(st['ledger'])} ledger entries",
        empty.status_code == 422
        and not invoices
        and inv["status"] == "needs_review"
        and not st["ledger"],
    )


def test_job_restarted_mid_pipeline(evaluation, world, monkeypatch) -> None:
    # The worker dies after matching, before the decision; Cloud Tasks runs the job again.
    decide = runner.STEPS[S.matched]
    monkeypatch.setitem(runner.STEPS, S.matched, _failing_once(decide, [1]))
    fake = world(invoice_json())  # a second reading would find no scripted reply and fail
    inv, _ = upload(evaluation.api, pdf("restart"), "restart.pdf")
    st = state(evaluation.api)
    audit = call(evaluation.api, "GET", f"/audit-log?invoice_id={inv['invoice_id']}", STAFF)
    actions = [a["action"] for a in audit["items"]]
    record(
        evaluation,
        "Cloud Tasks job restarted mid-pipeline",
        "resumes from the saved step: one Gemini call, posted once",
        f"{inv['status']} after {inv['processing_attempts']} attempts, {len(fake.feedback)} "
        f"Gemini call(s), 'extracted' logged {actions.count('extracted')}x, "
        f"{len(st['ledger'])} ledger entries",
        inv["status"] == "posted"
        and inv["processing_attempts"] == 2
        and len(fake.feedback) == 1
        and actions.count("extracted") == 1
        and len(st["ledger"]) == 1,
    )
