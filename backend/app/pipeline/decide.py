"""Decision rules (Setup guide, Section 8). Code decides; the model never does.

Rules are checked in order and the first that applies wins. Rule 2 (extraction failed or low
confidence) is applied earlier in the pipeline, which sends those invoices to review before
they reach matching.
"""

from dataclasses import dataclass

from app.models.invoice import Decision, InvoiceStatus, MatchIssueKind, MatchResult
from app.models.rules import BusinessRules
from app.pipeline.money import rupees

K = MatchIssueKind

STATUS_FOR: dict[Decision, InvoiceStatus] = {
    Decision.auto_approve: InvoiceStatus.auto_approved,
    Decision.manager_approval: InvoiceStatus.pending_approval,
    Decision.hold: InvoiceStatus.on_hold,
    Decision.block: InvoiceStatus.blocked_duplicate,
    Decision.needs_review: InvoiceStatus.needs_review,
}


@dataclass(frozen=True)
class Outcome:
    decision: Decision
    rule: str  # which rule fired, for the dashboard and tests
    reason: str  # plain sentence(s) built from match_result numbers

    @property
    def status(self) -> InvoiceStatus:
        return STATUS_FOR[self.decision]


def decide(result: MatchResult, total_paise: int, rules: BusinessRules) -> Outcome:
    def messages(*kinds: MatchIssueKind) -> list[str]:
        return [i.message for i in result.issues if i.kind in kinds]

    def outcome(decision: Decision, rule: str, reasons: list[str]) -> Outcome:
        return Outcome(decision, rule, ". ".join(r.rstrip(".") for r in reasons) + ".")

    # 1. Duplicate
    if found := messages(K.duplicate):
        return outcome(Decision.block, "duplicate", found)
    # 3. No matching PO (also: unknown supplier, lines or units we can't match with confidence)
    if found := messages(K.no_po, K.supplier, K.unmatched_line, K.unit):
        return outcome(Decision.needs_review, "no_matching_po", found)
    # 4. Billed more than was received and not yet billed
    if found := messages(K.quantity):
        return outcome(
            Decision.hold,
            "quantity_exceeds_received",
            found + messages(K.price_over_tolerance, K.gst_rate) + _difference(result),
        )
    # 5. Price above tolerance (a GST rate that differs from the PO is held the same way)
    if found := messages(K.price_over_tolerance, K.gst_rate):
        return outcome(Decision.hold, "price_over_tolerance", found + _difference(result))
    # 6. Price above the PO but within tolerance
    if found := messages(K.price_within_tolerance):
        return outcome(Decision.manager_approval, "price_within_tolerance", found)
    # 7. Above the auto-approve limit
    if total_paise > rules.auto_approve_max_paise:
        return outcome(
            Decision.manager_approval,
            "above_auto_approve_limit",
            [
                f"Total {rupees(total_paise)} is above the auto-approve limit of "
                f"{rupees(rules.auto_approve_max_paise)}"
            ],
        )
    # 8. Matched without a PO number (the Resolution Agent, Phase 7, sets this)
    if result.matched_without_po_number:
        return outcome(
            Decision.manager_approval,
            "matched_without_po_number",
            [f"The invoice has no PO number; it was matched to {result.matched_po} by the agent"],
        )
    # Possibly the same invoice sent twice under a new number: a person should look.
    if found := messages(K.possible_duplicate):
        return outcome(Decision.manager_approval, "possible_duplicate", found)
    # 9. Everything matches
    return outcome(
        Decision.auto_approve,
        "all_matched",
        [f"Quantities, prices and GST match {result.matched_po} and the goods received"],
    )


def _difference(result: MatchResult) -> list[str]:
    if result.difference_paise > 0:
        return [
            f"The correct amount is {rupees(result.correct_amount_paise)}, so the invoice is "
            f"{rupees(result.difference_paise)} too high"
        ]
    return []
