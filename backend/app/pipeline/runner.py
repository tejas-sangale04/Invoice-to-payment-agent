"""Runs an invoice through the agent pipeline (Setup guide, Section 7).

The pipeline is resumable: each step is chosen from the invoice's saved status, so a restarted
job carries on from where the last one stopped instead of starting over. Each step moves the
invoice on through `transition`, which is idempotent, so running a step twice is harmless.
"""

import logging
from collections.abc import Callable

from google.cloud import firestore

from app.models.invoice import InvoiceStatus as S
from app.pipeline.status import InvalidTransition, transition

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


def _extract(db: firestore.Client, invoice_id: str) -> None:
    # The Extraction Agent (Gemini) arrives in Phase 4. Until then, every invoice goes to a
    # person instead of guessing - the same safe outcome as a failed extraction.
    transition(
        db,
        invoice_id,
        S.needs_review,
        actor=AGENT,
        action="extraction_unavailable",
        details="Automatic invoice reading is not switched on yet, so a person needs to "
        "check this invoice.",
        expected_from=S.extracting,
        updates={"decision": "needs_review"},
    )


# Status the invoice is in -> the step that moves it on. Statuses not listed are resting
# states (waiting for a person, or finished), where the pipeline stops.
STEPS: dict[S, Step] = {
    S.received: _start,
    S.extracting: _extract,
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
