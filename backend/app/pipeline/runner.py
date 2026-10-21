"""Runs an invoice through the agent pipeline (Setup guide, Section 7).

The pipeline is resumable: each step is chosen from the invoice's saved status, so a restarted
job carries on from where the last one stopped instead of starting over. Each step moves the
invoice on through `transition`, which is idempotent, so running a step twice is harmless.
"""

import logging
from collections.abc import Callable

from google.cloud import firestore

from app.agents import extraction
from app.models.invoice import AiUsage, Decision, Extracted, MatchIssue, MatchResult
from app.models.invoice import InvoiceStatus as S
from app.models.invoice import MatchIssueKind as K
from app.pipeline import lookup
from app.pipeline.decide import decide
from app.pipeline.match import match_invoice, normalize_po_number
from app.pipeline.status import InvalidTransition, transition
from app.pipeline.validate import check, to_extracted
from app.services import rules as rules_svc
from app.services import storage as storage_svc

logger = logging.getLogger(__name__)

AGENT = "agent"
Step = Callable[[firestore.Client, str], None]


def _invoice(db: firestore.Client, invoice_id: str) -> dict:
    return db.collection("invoices").document(invoice_id).get().to_dict()


def _start(db: firestore.Client, invoice_id: str) -> None:
    # Duplicate check, part 1: the exact same file was uploaded before. Caught before any
    # model call, so a re-upload costs nothing.
    me = _invoice(db, invoice_id)
    original = lookup.duplicate_file(db, me)
    if original:
        reason = f"This is the same file as {original['invoice_id']}, uploaded earlier."
        transition(
            db,
            invoice_id,
            S.blocked_duplicate,
            actor=AGENT,
            action="duplicate_blocked",
            details=reason,
            expected_from=S.received,
            updates={
                "decision": Decision.block.value,
                "decision_rule": "duplicate",
                "decision_reason": reason,
                "duplicate_of": original["invoice_id"],
            },
        )
        return
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


def _match(db: firestore.Client, invoice_id: str) -> None:
    """Duplicate check (part 2), supplier and PO lookup, and the 3-way match. Records what it
    found as match_result; the decide step turns that into a decision."""
    me = _invoice(db, invoice_id)
    e = Extracted(**me["extracted"])
    rules = rules_svc.get_rules(db)
    supplier = lookup.resolve_supplier(db, e)
    supplier_key = lookup.supplier_key(supplier, e)
    invoice_no_key = lookup.normalize_invoice_no(e.invoice_no)
    duplicate_key = f"{supplier_key}|{invoice_no_key}"
    issues: list[MatchIssue] = []
    result = MatchResult(supplier_id=supplier.key)

    original = lookup.duplicate_number(db, me, duplicate_key)
    if original:
        issues.append(
            MatchIssue(
                kind=K.duplicate,
                message=f"Invoice {e.invoice_no} from {e.supplier_name} was already uploaded "
                f"as {original['invoice_id']}",
            )
        )
    else:
        po_number = normalize_po_number(e.po_number)
        po = lookup.get_po(db, po_number) if po_number else None
        if supplier.problem:
            issues.append(MatchIssue(kind=K.supplier, message=supplier.problem))
        if not e.po_number:
            # Phase 7 adds the Resolution Agent, which searches open POs for these.
            issues.append(MatchIssue(kind=K.no_po, message="The invoice has no PO number"))
        elif po is None:
            issues.append(
                MatchIssue(kind=K.no_po, message=f"PO number '{e.po_number}' was not found")
            )
        elif po["status"] == "closed":
            issues.append(MatchIssue(kind=K.no_po, message=f"{po_number} is closed"))
        elif supplier.supplier and po["supplier_id"] != supplier.key:
            issues.append(
                MatchIssue(
                    kind=K.supplier,
                    message=f"{po_number} is for {po['supplier_name']}, but this invoice is "
                    f"from {supplier.supplier['name']}",
                )
            )
        if po is not None and not issues:
            committed = lookup.committed_quantities(db, me, po["po_number"])
            result = match_invoice(e, po, rules.price_tolerance_percent, committed)
            if e.total_paise is not None and e.invoice_date is not None:
                other = lookup.possible_duplicate(
                    db, me, supplier_key, e.total_paise, e.invoice_date
                )
                if other:
                    result.issues.append(
                        MatchIssue(
                            kind=K.possible_duplicate,
                            message=f"{other['invoice_id']} is from the same supplier for the "
                            "same total within a week, under a different invoice number",
                        )
                    )
    result.issues = issues + result.issues

    transition(
        db,
        invoice_id,
        S.matched,
        actor=AGENT,
        action="matched",
        details=f"Matched against {result.matched_po}"
        if result.matched_po
        else "Could not be matched to a purchase order",
        expected_from=S.validated,
        updates={
            "match_result": result.model_dump(mode="json"),
            "supplier_key": supplier_key,
            "invoice_no_key": invoice_no_key,
            "duplicate_key": duplicate_key,
        },
    )


def _decide(db: firestore.Client, invoice_id: str) -> None:
    """Apply the business rules to the saved match result (no model call)."""
    me = _invoice(db, invoice_id)
    result = MatchResult(**me["match_result"])
    total = me["extracted"].get("total_paise") or 0
    outcome = decide(result, total, rules_svc.get_rules(db))
    transition(
        db,
        invoice_id,
        outcome.status,
        actor=AGENT,
        action=f"decided_{outcome.decision.value}",
        details=outcome.reason,
        expected_from=S.matched,
        updates={
            "decision": outcome.decision.value,
            "decision_rule": outcome.rule,
            "decision_reason": outcome.reason,
        },
    )


# Status the invoice is in -> the step that moves it on. Statuses not listed are resting
# states (waiting for a person, or finished), where the pipeline stops.
STEPS: dict[S, Step] = {
    S.received: _start,
    S.extracting: _extract,
    S.extracted: _validate,
    S.validated: _match,
    S.matched: _decide,
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
