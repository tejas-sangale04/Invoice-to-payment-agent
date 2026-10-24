"""Scores one run of a case against its ground truth."""

from decimal import Decimal

from app.pipeline.explain import amounts_in
from app.pipeline.lookup import normalize_invoice_no
from app.pipeline.match import normalize_po_number
from app.pipeline.money import rupees
from app.services.master_data import normalize_name

FIELDS = [
    "supplier_name",
    "supplier_gstin",
    "invoice_no",
    "invoice_date",
    "po_number",
    "line_items",
    "subtotal",
    "gst",
    "total",
]
PAYABLE = {"auto_approve", "manager_approval"}
STOPPED = {"hold", "block", "needs_review", "failed"}


def decision_of(invoice: dict) -> str:
    """The decision as one label; a pipeline that gave up counts as 'failed'."""
    if invoice["status"] == "failed":
        return "failed"
    return invoice.get("decision") or "none"


def _same_lines(truth: list[dict], read: list[dict]) -> bool:
    if len(truth) != len(read):
        return False
    return all(
        Decimal(t["qty"]) == Decimal(str(r["qty"]))
        and t["unit_price_paise"] == r["unit_price_paise"]
        and Decimal(t["tax_rate"]) == Decimal(str(r["tax_rate"]))
        and t["amount_paise"] == r.get("amount_paise")
        for t, r in zip(truth, read, strict=True)
    )


def compare_fields(truth: dict, extracted: dict | None) -> dict[str, bool]:
    """Field by field: did the saved reading get it right? Text is compared the way the app
    compares it (case, punctuation and 'Pvt Ltd' don't matter); amounts to the paisa."""
    if extracted is None:
        return dict.fromkeys(FIELDS, False)
    e = extracted

    def norm(f, a, b) -> bool:
        return (f(a) if a else None) == (f(b) if b else None)

    gst = truth["gst_paise"]
    return {
        "supplier_name": norm(normalize_name, truth["supplier_name"], e.get("supplier_name")),
        "supplier_gstin": norm(str.upper, truth["supplier_gstin"], e.get("supplier_gstin")),
        "invoice_no": norm(normalize_invoice_no, truth["invoice_no"], e.get("invoice_no")),
        "invoice_date": truth["invoice_date"] == e.get("invoice_date"),
        "po_number": norm(normalize_po_number, truth["po_number"], e.get("po_number")),
        "line_items": _same_lines(truth["items"], e.get("items") or []),
        "subtotal": truth["subtotal_paise"] == e.get("subtotal_paise"),
        "gst": (gst["cgst"], gst["sgst"], gst["igst"])
        == (e.get("cgst_paise"), e.get("sgst_paise"), e.get("igst_paise")),
        "total": truth["total_paise"] == e.get("total_paise"),
    }


def required_amounts(expect: dict) -> list[int]:
    """Amounts an explanation must mention: the invoice total, and for a wrong amount also
    the correct amount and the difference."""
    total = expect["invoice_total_paise"]
    if total is None:
        return []
    correct = expect["correct_amount_paise"]
    if correct is None or correct == total:
        return [total]
    return [total, correct, abs(total - correct)]


def explanation_expected(truth: dict) -> bool:
    """The Explanation Agent runs at the decision step for anything not auto-approved. Exact
    re-uploads and unreadable invoices stop before that step."""
    expect = truth["expect"]
    return (
        expect["decision"] != "auto_approve"
        and expect["rule"] is not None
        and not truth["invoice"]["same_file_as_prior"]
    )


def score(truth: dict, obs: dict, prices: dict) -> dict:
    expect = truth["expect"]
    inv = obs["invoice"]
    decision = decision_of(inv)
    status = inv["status"]
    expected_ledger = {e["invoice_no"]: e["amount_paise"] for e in expect["ledger"]}

    # Safety: what must never happen.
    wrong_approval = decision == "auto_approve" and expect["decision"] != "auto_approve"
    paid_wrongly = status == "posted" and expect["status"] != "posted"
    duplicate_paid = truth["kind"] == "duplicate" and (
        status == "posted" or len(obs["ledger"]) > len(expect["ledger"])
    )
    wrong_amounts = [
        f"{e['invoice_no']}: posted {rupees(e['amount_paise'])}, correct "
        f"{rupees(expected_ledger[e['invoice_no']])}"
        for e in obs["ledger"]
        if e["invoice_no"] in expected_ledger
        and e["amount_paise"] != expected_ledger[e["invoice_no"]]
    ]

    # End state: ledger and PO billing status.
    problems = []
    got_ledger = sorted((e["invoice_no"], e["amount_paise"]) for e in obs["ledger"])
    want_ledger = sorted((e["invoice_no"], e["amount_paise"]) for e in expect["ledger"])
    if got_ledger != want_ledger:
        problems.append(f"ledger {got_ledger}, expected {want_ledger}")
    for po, want in expect["po_status"].items():
        if obs["po_status"].get(po) != want:
            problems.append(f"{po} is {obs['po_status'].get(po)}, expected {want}")
    problems += [
        f"earlier invoice ended {p['status']}" for p in obs["prior"] if p["status"] != "posted"
    ]

    match = inv.get("match_result") or {}
    correct = expect["correct_amount_paise"]
    amount_ok = None
    if correct is not None:
        amount_ok = match.get("matched_po") == expect["po_number"] and (
            match.get("correct_amount_paise") == correct
        )

    fields = None
    if not truth["invoice"]["same_file_as_prior"]:
        fields = compare_fields(truth["invoice"]["fields"], inv.get("extracted"))

    explanation = None
    if explanation_expected(truth) or inv.get("explanation"):
        text = inv.get("explanation") or ""
        found = amounts_in(text)
        missing = [rupees(a) for a in required_amounts(expect) if a not in found]
        explanation = {
            "expected": explanation_expected(truth),
            "present": bool(text),
            "source": inv.get("explanation_source"),
            "amounts_ok": bool(text) and not missing,
            "missing_amounts": missing,
            "text": text,
            "supplier_email": inv.get("supplier_email_draft"),
        }

    usage = inv.get("ai_usage") or {}
    cost_usd = (
        usage.get("input_tokens", 0) * prices["input_usd_per_mtok"]
        + usage.get("output_tokens", 0) * prices["output_usd_per_mtok"]
    ) / 1_000_000
    return {
        "invoice_id": inv["invoice_id"],
        "decision": decision,
        "rule": inv.get("decision_rule"),
        "status": status,
        "decision_reason": inv.get("decision_reason"),
        "validation_issues": inv.get("validation_issues") or [],
        "expected_decision": expect["decision"],
        "decision_ok": decision == expect["decision"],
        "status_ok": status == expect["status"],
        "wrong_approval": wrong_approval,
        "paid_wrongly": paid_wrongly,
        "duplicate_paid": duplicate_paid,
        "wrong_amounts": wrong_amounts,
        "held_unnecessarily": expect["decision"] in PAYABLE and decision in STOPPED,
        "end_state_ok": not problems,
        "end_state_problems": problems,
        "correct_amount_ok": amount_ok,
        "correct_amount_paise": match.get("correct_amount_paise"),
        "fields": fields,
        "explanation": explanation,
        "approved_by_manager": obs["approved_by_manager"],
        "wall_ms": obs["wall_ms"],
        "ai": {
            "calls": usage.get("calls", 0),
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "latency_ms": usage.get("latency_ms", 0),
        },
        "cost_inr": cost_usd * prices["usd_to_inr"],
    }


def safety_failures(run: dict) -> list[str]:
    """What fails a case in any mode: money that should not have moved."""
    out = []
    if run["wrong_approval"]:
        out.append(f"auto-approved, but should have been '{run.get('expected_decision')}'")
    if run["paid_wrongly"]:
        out.append("posted to the ledger, but should not have been")
    if run["duplicate_paid"]:
        out.append("a duplicate was paid")
    out += [f"wrong amount posted: {w}" for w in run["wrong_amounts"]]
    return out
