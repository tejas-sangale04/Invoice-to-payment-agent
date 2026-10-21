"""Runs an invoice through the agent pipeline (Setup guide, Section 7).

The pipeline is resumable: each step is chosen from the invoice's saved status, so a restarted
job carries on from where the last one stopped instead of starting over. Each step moves the
invoice on through `transition`, which is idempotent, so running a step twice is harmless.
"""

import logging
from collections.abc import Callable

from google.cloud import firestore

from app.agents import extraction
from app.models.invoice import AiUsage, Extracted
from app.models.invoice import InvoiceStatus as S
from app.pipeline.status import InvalidTransition, transition
from app.pipeline.validate import check, to_extracted
from app.services import rules as rules_svc
from app.services import storage as storage_svc

logger = logging.getLogger(__name__)

AGENT = "agent"
Step = Callable[[firestore.Client, str], None]


def _start(db: firestore.Client, invoice_id: str) -> None:
    transition(
        db,
        invoice_id,
        S.extracting,
        actor=AGENT,
        action="processing_started",
        expected_from=S.received,
    )


MAX_EXTRACTION_ATTEMPTS = 2  # one read plus one corrective retry (Setup guide, Step 3)


def _extract(db: firestore.Client, invoice_id: str) -> None:
    """Gemini reads the file; code checks it. On failed checks the issues go back to Gemini
    once. The last reading is saved either way; the validate step then decides."""
    extractor = extraction.get_extractor()
    if extractor is None:
        transition(
            db,
            invoice_id,
            S.needs_review,
            actor=AGENT,
            action="extraction_unavailable",
            details="Automatic invoice reading is switched off, so a person needs to check "
            "this invoice.",
            expected_from=S.extracting,
            updates={"decision": "needs_review"},
        )
        return

    doc = db.collection("invoices").document(invoice_id).get().to_dict()
    data = storage_svc.get_storage().read(doc["file_path"])
    min_confidence = rules_svc.get_rules(db).min_field_confidence
    usage = AiUsage(**(doc.get("ai_usage") or {}))

    extracted: Extracted | None = None
    issues: list[str] = []
    feedback: str | None = None
    for _ in range(MAX_EXTRACTION_ATTEMPTS):
        # Timeouts and API errors raise here, so the background task retries the step.
        call = extractor.extract(data, doc["content_type"], feedback)
        usage.calls += 1
        usage.input_tokens += call.input_tokens
        usage.output_tokens += call.output_tokens
        usage.latency_ms += call.latency_ms
        if call.parsed is None:
            issues = [call.error or "The response could not be read"]
        else:
            extracted, issues = to_extracted(call.parsed)
            issues += check(extracted, min_confidence)
        if not issues:
            break
        feedback = "\n".join(f"- {issue}" for issue in issues)

    updates = {"ai_usage": usage.model_dump(), "validation_issues": issues}
    if extracted is None:
        transition(
            db,
            invoice_id,
            S.needs_review,
            actor=AGENT,
            action="extraction_failed",
            details="The agent couldn't read this invoice in a usable form, so a person needs "
            "to check it.",
            expected_from=S.extracting,
            updates={**updates, "decision": "needs_review"},
        )
        return
    transition(
        db,
        invoice_id,
        S.extracted,
        actor=AGENT,
        action="extracted",
        details=f"Read {len(extracted.items)} line item(s) in {usage.calls} attempt(s)",
        expected_from=S.extracting,
        updates={**updates, "extracted": extracted.model_dump(mode="json")},
    )


def _validate(db: firestore.Client, invoice_id: str) -> None:
    """Deterministic checks on the saved reading (no model call, so safe to re-run)."""
    doc = db.collection("invoices").document(invoice_id).get().to_dict()
    extracted = Extracted(**doc["extracted"])
    issues = check(extracted, rules_svc.get_rules(db).min_field_confidence)
    if issues:
        transition(
            db,
            invoice_id,
            S.needs_review,
            actor=AGENT,
            action="validation_failed",
            details="Some details on this invoice didn't check out: " + "; ".join(issues),
            expected_from=S.extracted,
            updates={"validation_issues": issues, "decision": "needs_review"},
        )
        return
    transition(
        db,
        invoice_id,
        S.validated,
        actor=AGENT,
        action="validated",
        details="Totals, GST and required fields check out",
        expected_from=S.extracted,
        updates={"validation_issues": []},
    )


def _await_matching(db: firestore.Client, invoice_id: str) -> None:
    # The 3-way match arrives in Phase 5. Until then a person takes it from here.
    transition(
        db,
        invoice_id,
        S.needs_review,
        actor=AGENT,
        action="matching_unavailable",
        details="Read and checked. Matching against purchase orders and deliveries is not "
        "switched on yet, so a person needs to check this invoice.",
        expected_from=S.validated,
        updates={"decision": "needs_review"},
    )


# Status the invoice is in -> the step that moves it on. Statuses not listed are resting
# states (waiting for a person, or finished), where the pipeline stops.
STEPS: dict[S, Step] = {
    S.received: _start,
    S.extracting: _extract,
    S.extracted: _validate,
    S.validated: _await_matching,
}

_MAX_STEPS = 20  # guards against a step that fails to move the invoice on


def run_steps(db: firestore.Client, invoice_id: str) -> S:
    ref = db.collection("invoices").document(invoice_id)
    for _ in range(_MAX_STEPS):
        status = S(ref.get().get("status"))
        step = STEPS.get(status)
        if step is None:
            return status
        logger.info("Running step", extra={"invoice_id": invoice_id, "step": status.value})
        step(db, invoice_id)
    raise RuntimeError(f"Pipeline did not settle after {_MAX_STEPS} steps")


def process_invoice(db: firestore.Client, invoice_id: str, attempt: int, max_attempts: int) -> S:
    """Run the pipeline once. Raises on error so the caller (Cloud Tasks) retries, except on
    the last attempt, where the invoice is marked failed so a person picks it up."""
    db.collection("invoices").document(invoice_id).update(
        {"processing_attempts": firestore.Increment(1)}
    )
    try:
        return run_steps(db, invoice_id)
    except Exception as exc:
        logger.exception(
            "Pipeline attempt %s/%s failed", attempt, max_attempts, extra={"invoice_id": invoice_id}
        )
        if attempt < max_attempts:
            raise
        try:
            transition(
                db,
                invoice_id,
                S.failed,
                actor=AGENT,
                action="processing_failed",
                details=f"Processing failed after {attempt} attempts ({type(exc).__name__}). "
                "A person needs to check this invoice.",
                updates={"decision": "needs_review"},
            )
        except InvalidTransition:
            logger.error("Could not mark invoice failed", extra={"invoice_id": invoice_id})
        return S.failed
