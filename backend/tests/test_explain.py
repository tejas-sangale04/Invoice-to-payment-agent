from decimal import Decimal

import pytest

from app.agents import explanation
from app.models.invoice import AiUsage, MatchIssue, MatchResult
from app.models.invoice import MatchIssueKind as K
from app.models.rules import BusinessRules
from app.pipeline.decide import decide
from app.pipeline.explain import amounts_in, check, explain, facts, template
from app.pipeline.match import match_invoice
from tests.factories import FakeExplainer
from tests.test_match import invoice, item, po

RULES = BusinessRules(
    price_tolerance_percent=Decimal("2"),
    auto_approve_max_paise=5000000,
    min_field_confidence=Decimal("0.85"),
)


def held():
    """The spec example: 50 L billed, 40 L received, so Rs 600.00 too much."""
    e = invoice(item())
    result = match_invoice(e, po(received={"1": "40"}), RULES.price_tolerance_percent)
    return e, result, decide(result, e.total_paise, RULES)


GOOD = {
    "explanation": "Sharma Dairy billed 50 L of milk but only 40 L arrived, so the invoice "
    "for Rs 3,000.00 should be Rs 2,400.00, Rs 600.00 too much. It is on hold.",
    "supplier_email": "Subject: Invoice SD-1\n\nDear Sharma Dairy,\n\nYour invoice SD-1 for "
    "Rs 3,000.00 against PO-205 bills 50 L of milk, but we received 40 L. The correct amount "
    "is Rs 2,400.00, Rs 600.00 less. Please send a credit note.\n\nAccounts Payable",
}


@pytest.fixture
def explainer(monkeypatch: pytest.MonkeyPatch):
    def use(*responses) -> FakeExplainer:
        fake = FakeExplainer(*responses)
        monkeypatch.setattr(explanation, "get_explainer", lambda: fake)
        return fake

    return use


def test_amounts_are_read_in_any_rupee_style() -> None:
    text = "Rs 4,050.00, Rs. 600 and ₹2,400.50 but not 2.5 kg or GST 5%"
    assert amounts_in(text) == {405000, 60000, 240050}


def test_facts_name_the_key_amounts_and_what_to_ask_the_supplier() -> None:
    e, result, outcome = held()
    f = facts(e, result, outcome)
    assert f["amounts_to_mention"] == ["Rs 3,000.00", "Rs 2,400.00", "Rs 600.00"]
    assert (f["decision"], f["purchase_order"]) == ("hold", "PO-205")
    assert f["write_supplier_email"] is True
    assert f["supplier_action"] == "Please send a credit note or a revised invoice for Rs 2,400.00."


def test_within_tolerance_still_asks_for_a_credit_note() -> None:
    # The ledger is posted at the PO price, so the supplier is asked to correct the invoice.
    e = invoice(item(price=6100))
    result = match_invoice(e, po(), RULES.price_tolerance_percent)
    f = facts(e, result, decide(result, e.total_paise, RULES))
    assert f["write_supplier_email"] is True
    assert f["amounts_to_mention"] == ["Rs 3,050.00", "Rs 3,000.00", "Rs 50.00"]


def above_limit():
    e = invoice(item())
    result = match_invoice(e, po(), RULES.price_tolerance_percent)
    return e, result, decide(result, e.total_paise, RULES.model_copy(
        update={"auto_approve_max_paise": 100000}))  # fmt: skip


def test_no_supplier_email_when_only_a_manager_needs_to_look() -> None:
    f = facts(*above_limit())
    assert (f["decision"], f["write_supplier_email"]) == ("manager approval", False)
    assert f["amounts_to_mention"] == ["Rs 3,000.00"]


def test_missing_po_asks_the_supplier_for_it() -> None:
    e = invoice(item())
    result = MatchResult(issues=[MatchIssue(kind=K.no_po, message="The invoice has no PO number")])
    f = facts(e, result, decide(result, e.total_paise, RULES))
    assert f["amounts_to_mention"] == ["Rs 3,000.00"]
    assert f["supplier_action"] == "Please tell us the purchase order number for this invoice."
    # The supplier isn't told about our checks or the agent.
    assert f["problems_for_supplier"] == ["The invoice doesn't show our purchase order number"]


def test_check_catches_missing_and_made_up_amounts() -> None:
    e, result, outcome = held()
    f = facts(e, result, outcome)
    assert check(explanation.LlmExplanation(**GOOD), f) == []
    bad = explanation.LlmExplanation(
        explanation="Overbilled by Rs 650.00 on Rs 3,000.00 (should be Rs 2,400.00).",
        supplier_email=None,
    )
    assert check(bad, f) == [
        "supplier_email is missing",
        "explanation doesn't mention Rs 600.00",
        "explanation mentions Rs 650.00, which is not in the facts",
    ]


def test_template_mentions_every_key_amount() -> None:
    e, result, outcome = held()
    f = facts(e, result, outcome)
    t = template(f)
    assert t.source == "template"
    assert check(explanation.LlmExplanation(explanation=t.explanation,
                                            supplier_email=t.supplier_email), f) == []  # fmt: skip
    assert t.supplier_email.startswith("Subject: Invoice SD-1\n\nDear Sharma Dairy,")
    assert "- Milk: billed 50 L, but only 40 L can be billed" in t.supplier_email
    assert t.supplier_email.endswith("Thank you,\nAccounts Payable")


def test_agent_text_is_used_when_it_passes(explainer) -> None:
    fake = explainer(GOOD)
    usage = AiUsage(calls=1, input_tokens=1000)
    result = explain(*held(), usage)
    assert (result.source, result.explanation) == ("agent", GOOD["explanation"])
    assert result.supplier_email == GOOD["supplier_email"]
    assert (usage.calls, usage.input_tokens) == (2, 1400)
    assert fake.feedback == [None]


def test_a_failed_check_is_sent_back_once(explainer) -> None:
    wrong = {**GOOD, "explanation": "The invoice is Rs 700.00 too high."}
    fake = explainer(wrong, GOOD)
    assert explain(*held(), AiUsage()).source == "agent"
    assert "explanation mentions Rs 700.00, which is not in the facts" in fake.feedback[1]


def test_template_after_two_failures(explainer) -> None:
    wrong = {**GOOD, "supplier_email": None}
    usage = AiUsage()
    fake = explainer(wrong, "not json")
    result = explain(*held(), usage)
    assert result.source == "template"
    assert usage.calls == 2
    assert len(fake.feedback) == 2


def test_template_when_the_agent_errors_or_is_off(explainer, monkeypatch) -> None:
    explainer(TimeoutError("slow"))
    assert explain(*held(), AiUsage()).source == "template"
    monkeypatch.setattr(explanation, "get_explainer", lambda: None)
    assert explain(*held(), AiUsage()).source == "template"


def test_an_unasked_for_email_is_dropped(explainer) -> None:
    text = "The invoice is for Rs 3,000.00, above the Rs 1,000.00 limit. A manager decides."
    explainer({"explanation": text, "supplier_email": "Subject: hi"})
    out = explain(*above_limit(), AiUsage())
    assert (out.source, out.explanation, out.supplier_email) == ("agent", text, None)
