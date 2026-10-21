"""Every branch of the decision rules (Setup guide, Section 8), in order."""

from decimal import Decimal

import pytest

from app.models.invoice import Decision, InvoiceStatus, MatchIssue, MatchResult
from app.models.invoice import MatchIssueKind as K
from app.models.rules import BusinessRules
from app.pipeline.decide import decide

RULES = BusinessRules(auto_approve_max_paise=5_000_000, price_tolerance_percent=Decimal(2))
SMALL = 300_000


def result(*kinds: K, **fields) -> MatchResult:
    return MatchResult(
        matched_po="PO-205",
        issues=[MatchIssue(kind=k, message=f"{k.value} problem") for k in kinds],
        **fields,
    )


@pytest.mark.parametrize(
    ("kinds", "decision", "rule"),
    [
        ([K.duplicate, K.quantity], Decision.block, "duplicate"),
        ([K.no_po], Decision.needs_review, "no_matching_po"),
        ([K.supplier], Decision.needs_review, "no_matching_po"),
        ([K.unmatched_line, K.quantity], Decision.needs_review, "no_matching_po"),
        ([K.unit], Decision.needs_review, "no_matching_po"),
        ([K.quantity, K.price_within_tolerance], Decision.hold, "quantity_exceeds_received"),
        ([K.price_over_tolerance], Decision.hold, "price_over_tolerance"),
        ([K.gst_rate], Decision.hold, "price_over_tolerance"),
        ([K.price_within_tolerance], Decision.manager_approval, "price_within_tolerance"),
        ([K.possible_duplicate], Decision.manager_approval, "possible_duplicate"),
        ([], Decision.auto_approve, "all_matched"),
    ],
)
def test_first_matching_rule_wins(kinds, decision, rule) -> None:
    out = decide(result(*kinds), SMALL, RULES)
    assert (out.decision, out.rule) == (decision, rule)


def test_above_auto_approve_limit_needs_a_manager() -> None:
    out = decide(result(), 5_000_001, RULES)
    assert (out.decision, out.rule) == (Decision.manager_approval, "above_auto_approve_limit")
    assert out.reason == ("Total Rs 50,000.01 is above the auto-approve limit of Rs 50,000.00.")


def test_exactly_at_the_limit_is_auto_approved() -> None:
    assert decide(result(), 5_000_000, RULES).decision == Decision.auto_approve


def test_the_limit_comes_from_the_admin_rules() -> None:
    strict = RULES.model_copy(update={"auto_approve_max_paise": 100_000})
    assert decide(result(), SMALL, strict).rule == "above_auto_approve_limit"


def test_hold_beats_the_limit_and_the_limit_beats_no_po_number() -> None:
    assert decide(result(K.quantity), 9_000_000, RULES).decision == Decision.hold
    no_number = result(matched_without_po_number=True)
    assert decide(no_number, 9_000_000, RULES).rule == "above_auto_approve_limit"
    assert decide(no_number, SMALL, RULES).rule == "matched_without_po_number"


def test_hold_reason_lists_the_problems_and_the_overcharge() -> None:
    r = result(K.quantity, K.gst_rate, correct_amount_paise=240000, difference_paise=60000)
    out = decide(r, 300000, RULES)
    assert out.reason == (
        "quantity problem. gst_rate problem. The correct amount is Rs 2,400.00, so the invoice "
        "is Rs 600.00 too high."
    )


def test_each_decision_maps_to_its_status() -> None:
    assert decide(result(K.duplicate), SMALL, RULES).status == InvoiceStatus.blocked_duplicate
    assert decide(result(K.no_po), SMALL, RULES).status == InvoiceStatus.needs_review
    assert decide(result(K.quantity), SMALL, RULES).status == InvoiceStatus.on_hold
    assert (
        decide(result(K.price_within_tolerance), SMALL, RULES).status
        == InvoiceStatus.pending_approval
    )
    assert decide(result(), SMALL, RULES).status == InvoiceStatus.auto_approved
