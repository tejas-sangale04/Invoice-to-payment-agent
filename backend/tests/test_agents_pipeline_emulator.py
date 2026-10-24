"""The Resolution and Explanation agents in the real pipeline, on the emulator, with scripted
stand-ins for Gemini. PO-1: 50 L milk at Rs 60 and 2.5 kg paneer at Rs 400 + 5% GST."""

import os

import pytest

from app.agents import explanation, resolution
from tests.factories import FakeExplainer, FakeResolver, invoice_json
from tests.pipeline_env import deliver, purchase_order, upload, use

pytestmark = [
    pytest.mark.emulator,
    pytest.mark.skipif(
        not os.environ.get("FIRESTORE_EMULATOR_HOST"), reason="emulator not running"
    ),
]

NO_PO = invoice_json(po_number=None)


@pytest.fixture
def agent(monkeypatch: pytest.MonkeyPatch):
    def use_resolver(script) -> FakeResolver:
        fake = FakeResolver(script)
        monkeypatch.setattr(resolution, "get_resolver", lambda: fake)
        return fake

    return use_resolver


def picks(po_number):
    return lambda invoice, search: {"po_number": po_number, "reasoning": f"{po_number} fits."}


# ---------------------------------------------------------------- resolution


def test_agent_finds_the_po_and_a_manager_must_approve(api, monkeypatch, po1, agent) -> None:
    deliver(api, po1)

    def script(invoice, search):
        assert invoice["supplier"] == "Sharma Dairy Pvt Ltd"
        assert [line["name"] for line in invoice["lines"]] == ["Milk", "Paneer"]
        found = search()["purchase_orders"]
        assert [p["po_number"] for p in found] == ["PO-1"]
        assert found[0]["lines"][0] == {
            "name": "Full cream milk",
            "unit": "L",
            "ordered": "50",
            "received": "50",
            "already_billed": "0",
            "can_still_bill": "50",
            "can_bill_now": "50",
            "unit_price": "Rs 60.00",
            "gst_percent": "0",
        }
        return {"po_number": "po 1", "reasoning": "PO-1 has 50 L milk and 2.5 kg paneer."}

    fake = agent(script)
    use(monkeypatch, NO_PO)
    inv = upload(api)
    assert len(fake.searches) == 1
    assert inv["status"] == "pending_approval"
    assert inv["decision_rule"] == "matched_without_po_number"
    assert inv["decision_reason"] == (
        "The invoice has no PO number; it was matched to PO-1 by the agent."
    )
    assert inv["match_result"]["matched_po"] == "PO-1"
    assert inv["match_result"]["matched_without_po_number"] is True
    r = inv["resolution"]
    assert (r["proposed_po"], r["verified"], r["fitting_pos"]) == ("PO-1", True, ["PO-1"])
    assert r["reasoning"] == "PO-1 has 50 L milk and 2.5 kg paneer."
    assert inv["ai_usage"]["calls"] == 2  # reading + resolution


def test_found_po_is_still_held_for_a_short_delivery(api, monkeypatch, po1, agent) -> None:
    deliver(api, po1, milk="40")
    agent(picks("PO-1"))
    use(monkeypatch, NO_PO)
    inv = upload(api)
    assert (inv["status"], inv["decision_rule"]) == ("on_hold", "quantity_exceeds_received")
    assert inv["match_result"]["matched_without_po_number"] is True


def test_two_pos_that_fit_go_to_a_person(api, monkeypatch, po1, agent) -> None:
    purchase_order(api, "SUP-1")  # PO-2, the same items
    agent(picks("PO-1"))
    use(monkeypatch, NO_PO)
    inv = upload(api)
    assert inv["status"] == "needs_review"
    assert inv["decision_reason"] == (
        "The invoice has no PO number. The agent suggested PO-1, but PO-2 also fit, so a "
        "person needs to choose."
    )
    assert inv["resolution"]["verified"] is False


def test_a_po_whose_deliveries_cover_the_invoice_beats_one_only_ordered(
    api, monkeypatch, po1, agent
) -> None:
    deliver(api, po1, milk="40")  # PO-1 is short of milk
    deliver(api, purchase_order(api, "SUP-1"))  # PO-2 has everything
    agent(picks("PO-2"))
    use(monkeypatch, NO_PO)
    inv = upload(api)
    assert (inv["status"], inv["match_result"]["matched_po"]) == ("pending_approval", "PO-2")
    assert inv["resolution"]["fitting_pos"] == ["PO-2"]


def test_a_proposal_that_does_not_fit_is_refused(api, monkeypatch, po1, agent) -> None:
    agent(picks("PO-9"))
    use(monkeypatch, NO_PO)
    inv = upload(api)
    assert inv["status"] == "needs_review"
    assert (
        "The agent suggested PO-9, but its items or quantities don't fit"
        in (inv["decision_reason"])
    )


def test_a_fully_billed_po_does_not_fit(api, monkeypatch, po1, agent) -> None:
    deliver(api, po1)
    agent(picks("PO-1"))
    use(monkeypatch, invoice_json(), invoice_json(po_number=None, invoice_no="SD-1043"))
    assert upload(api)["status"] == "posted"  # SD-1042 bills all of PO-1
    second = upload(api)
    assert second["status"] == "needs_review"
    assert (
        "The agent suggested PO-1, but its items or quantities don't fit"
        in (second["decision_reason"])
    )


def test_agent_finding_nothing_goes_to_a_person(api, monkeypatch, po1, agent) -> None:
    agent(picks(None))
    use(monkeypatch, NO_PO)
    assert upload(api)["decision_reason"] == (
        "The invoice has no PO number, and no single open PO from Sharma Dairy Pvt Ltd fits it."
    )


def test_agent_error_goes_to_a_person(api, monkeypatch, po1, agent) -> None:
    agent(lambda invoice, search: TimeoutError("slow"))
    use(monkeypatch, NO_PO)
    inv = upload(api)
    assert inv["status"] == "needs_review"
    assert inv["decision_reason"] == (
        "The invoice has no PO number, and the search for its PO failed."
    )


def test_search_filters_by_item_and_date(api, monkeypatch, po1, agent) -> None:
    def script(invoice, search):
        assert search(item_name="ghee")["purchase_orders"] == []
        assert search(item_name="paneer")["purchase_orders"][0]["po_number"] == "PO-1"
        assert search(ordered_before="2000-01-01")["purchase_orders"] == []
        assert len(search(ordered_after="2000-01-01", ordered_before="not a date")[
            "purchase_orders"]) == 1  # fmt: skip
        return {"po_number": None, "reasoning": "checked"}

    fake = agent(script)
    use(monkeypatch, NO_PO)
    upload(api)
    assert len(fake.searches) == 4


# --------------------------------------------------------------- explanation


def test_held_invoice_gets_the_template_when_the_agent_is_off(api, monkeypatch, po1) -> None:
    deliver(api, po1, milk="40")
    use(monkeypatch, invoice_json())
    inv = upload(api)
    assert inv["status"] == "on_hold"
    assert inv["explanation_source"] == "template"
    assert (
        "The invoice is for Rs 4,050.00, but the correct amount is Rs 3,450.00, a "
        in (inv["explanation"])
    )
    assert (
        "Please send a credit note or a revised invoice for Rs 3,450.00."
        in (inv["supplier_email_draft"])
    )


def test_held_invoice_gets_the_agents_explanation(api, monkeypatch, po1) -> None:
    deliver(api, po1, milk="40")
    answer = {
        "explanation": "Sharma Dairy billed 50 L of milk but 40 L arrived: the invoice is "
        "Rs 4,050.00, the correct amount Rs 3,450.00, Rs 600.00 too much. It is on hold.",
        "supplier_email": "Subject: Invoice SD-1042\n\nDear Sharma Dairy,\n\nInvoice SD-1042 "
        "for Rs 4,050.00 on PO-1 bills 50 L of milk; we received 40 L. The correct amount is "
        "Rs 3,450.00, Rs 600.00 less. Please send a credit note.\n\nAccounts Payable",
    }
    fake = FakeExplainer(answer)
    monkeypatch.setattr(explanation, "get_explainer", lambda: fake)
    use(monkeypatch, invoice_json())
    inv = upload(api)
    assert inv["explanation_source"] == "agent"
    assert inv["explanation"] == answer["explanation"]
    assert inv["supplier_email_draft"] == answer["supplier_email"]
    assert fake.facts[0]["amounts_to_mention"] == ["Rs 4,050.00", "Rs 3,450.00", "Rs 600.00"]
    assert inv["ai_usage"]["calls"] == 2  # reading + explanation


def test_auto_approved_invoices_are_not_explained(api, monkeypatch, po1) -> None:
    deliver(api, po1)
    use(monkeypatch, invoice_json())
    inv = upload(api)
    assert inv["status"] == "posted"
    assert (inv["explanation"], inv["supplier_email_draft"]) == (None, None)
