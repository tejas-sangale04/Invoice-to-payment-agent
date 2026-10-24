"""Dashboard metrics from invoices that went through the real pipeline, on the emulator."""

import os

import pytest

from tests.factories import invoice_json
from tests.pipeline_env import MANAGER, STAFF, deliver, overpriced_milk, upload, use

pytestmark = [
    pytest.mark.emulator,
    pytest.mark.skipif(
        not os.environ.get("FIRESTORE_EMULATOR_HOST"), reason="emulator not running"
    ),
]


def metrics(api) -> dict:
    res = api.get("/dashboard/metrics", headers=MANAGER)
    assert res.status_code == 200, res.text
    return res.json()


def test_empty_dashboard(api) -> None:
    m = metrics(api)
    assert (m["invoices_uploaded"], m["invoices_processed"], m["posted_paise"]) == (0, 0, 0)
    assert m["avg_processing_seconds"] is None and m["avg_ai_cost_paise"] is None
    assert len(m["daily"]) == 14


def test_staff_cannot_see_the_dashboard(api) -> None:
    assert api.get("/dashboard/metrics", headers=STAFF).status_code == 403


def test_metrics_after_a_mix_of_invoices(api, monkeypatch, po1) -> None:
    deliver(api, po1, milk="40")
    use(
        monkeypatch,
        invoice_json(),  # held: Rs 600.00 too high
        overpriced_milk() | {"invoice_no": "SD-2001"},  # held too (40 L received)
        invoice_json(po_number=None, invoice_no="SD-2002"),  # needs review
    )
    first = b"%PDF-1.7\nfirst\n%%EOF\n"
    held, held2, review = upload(api, first), upload(api), upload(api)
    duplicate = upload(api, first)  # the same file again
    assert [i["status"] for i in (held, held2, review, duplicate)] == [
        "on_hold", "on_hold", "needs_review", "blocked_duplicate",
    ]  # fmt: skip

    m = metrics(api)
    assert (m["invoices_uploaded"], m["invoices_processed"]) == (4, 4)
    assert m["decision_counts"] == {"hold": 2, "needs_review": 1, "block": 1}
    assert m["status_counts"]["on_hold"] == 2
    # Held overcharges: 600.00 on the first, 600.00 + 50.00 on the second.
    assert m["money_saved_paise"] == 60000 + 65000
    assert (m["duplicates_blocked"], m["duplicates_blocked_paise"]) == (1, 405000)
    assert m["avg_processing_seconds"] >= 0
    assert set(m["avg_step_seconds"]) >= {"start", "extract", "validate", "match", "decide"}
    # Three invoices called the (fake) model once each with 1,000 + 200 tokens; the duplicate
    # was caught before any model call.
    assert (m["avg_ai_calls"], m["avg_tokens"]) == (1, 1200)
    # (1,000 x $0.30 + 200 x $2.50) per million tokens x Rs 88 = Rs 0.0704
    assert m["avg_ai_cost_paise"] == pytest.approx(7.04)
    assert "gemini-2.5-flash at $0.3 input and $2.5 output" in m["ai_price_note"]
    assert m["daily"][-1]["uploaded"] == 4 and m["daily"][-1]["decided"] == 4
    assert m["retried_invoices"] == 0


def test_posted_invoices_count_in_the_ledger_totals(api, monkeypatch, po1) -> None:
    deliver(api, po1)
    use(monkeypatch, invoice_json())
    assert upload(api)["status"] == "posted"
    m = metrics(api)
    assert (m["posted_count"], m["posted_paise"], m["money_saved_paise"]) == (1, 405000, 0)
    assert m["decision_counts"] == {"auto_approve": 1}
    assert "post" in m["avg_step_seconds"]
