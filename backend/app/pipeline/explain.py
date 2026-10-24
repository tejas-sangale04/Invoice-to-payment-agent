"""Explaining a decision (Setup guide, Section 7, step 7).

Code gathers the facts, the Explanation Agent writes them up, and code checks the text: it must
mention the key amounts and no amount that isn't in the facts. A failed check is sent back
once; if the second answer fails too, or the agent is off or errors, a template is used.
"""

import logging
import re
from dataclasses import dataclass
from decimal import Decimal

from app.agents import explanation
from app.models.invoice import AiUsage, Decision, Extracted, MatchIssueKind, MatchResult
from app.pipeline.decide import Outcome
from app.pipeline.money import rupees

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2

NEXT_STEP = {
    Decision.manager_approval: "A manager needs to approve or reject it before it is paid.",
    Decision.hold: "It is on hold and won't be paid until it is corrected, or the missing goods "
    "arrive, and it is reprocessed.",
    Decision.block: "It won't be paid.",
    Decision.needs_review: "A person needs to check it before anything is paid.",
}

# Rs 4,050.00 / Rs. 4050 / ₹4,050.00 / INR 4,050
_AMOUNT = re.compile(r"(?:Rs\.?|₹|INR)\s?(\d[\d,]*(?:\.\d{1,2})?)", re.IGNORECASE)


def amounts_in(text: str) -> set[int]:
    """Every rupee amount written in `text`, in paise."""
    return {int(Decimal(m.replace(",", "")) * 100) for m in _AMOUNT.findall(text)}


@dataclass
class Explanation:
    explanation: str
    supplier_email: str | None
    source: str  # "agent" or "template"

    def updates(self) -> dict:
        return {
            "explanation": self.explanation,
            "supplier_email_draft": self.supplier_email,
            "explanation_source": self.source,
        }


def facts(
    extracted: Extracted, result: MatchResult, outcome: Outcome, rejected: bool = False
) -> dict:
    """`rejected`: a manager is rejecting the invoice and wants an email to the supplier, even
    when the checks alone wouldn't have asked the supplier to do anything."""
    total = extracted.total_paise
    overcharged = result.matched_po is not None and result.difference_paise > 0
    required = [p for p in (total,) if p is not None]
    if overcharged:
        required += [result.correct_amount_paise, result.difference_paise]

    kinds = {i.kind for i in result.issues}
    if outcome.decision == Decision.block:
        action = "Please don't send this invoice again; we already have it."
    elif overcharged:
        action = (
            f"Please send a credit note or a revised invoice for "
            f"{rupees(result.correct_amount_paise)}."
        )
    elif MatchIssueKind.gst_rate in kinds:
        action = "Please send a revised invoice with the GST rate on the purchase order."
    elif MatchIssueKind.no_po in kinds:
        action = "Please tell us the purchase order number for this invoice."
    elif rejected:
        action = "Please check the invoice and send a corrected one, or contact us if it is right."
    else:
        action = None
    # What the supplier is told: no internal ids, checks or agent details.
    for_supplier = [
        "The invoice doesn't show our purchase order number"
        if i.kind == MatchIssueKind.no_po
        else i.message
        for i in result.issues
        if i.kind != MatchIssueKind.possible_duplicate
    ]
    return {
        "supplier": extracted.supplier_name,
        "invoice_no": extracted.invoice_no,
        "invoice_date": extracted.invoice_date.isoformat() if extracted.invoice_date else None,
        "purchase_order": result.matched_po,
        "decision": outcome.decision.value.replace("_", " "),
        "reason": outcome.reason,
        "problems": [i.message for i in result.issues],
        "problems_for_supplier": list(dict.fromkeys(for_supplier)),
        "invoice_total": rupees(total) if total is not None else None,
        "correct_amount": rupees(result.correct_amount_paise) if result.matched_po else None,
        "difference": rupees(result.difference_paise) if overcharged else None,
        "amounts_to_mention": [rupees(p) for p in required],
        "rejected": rejected,
        "next_step": "The invoice has been rejected and won't be paid."
        if rejected
        else NEXT_STEP[outcome.decision],
        "write_supplier_email": action is not None,
        "supplier_action": action,
    }


def check(answer: explanation.LlmExplanation, f: dict) -> list[str]:
    issues = []
    allowed = amounts_in(str(f))
    texts = {"explanation": answer.explanation}
    if f["write_supplier_email"]:
        if not answer.supplier_email:
            issues.append("supplier_email is missing")
        else:
            texts["supplier_email"] = answer.supplier_email
    for field, text in texts.items():
        if not text.strip():
            issues.append(f"{field} is empty")
            continue
        missing = [a for a in f["amounts_to_mention"] if a not in text]
        if missing:
            issues.append(f"{field} doesn't mention {', '.join(missing)}")
        made_up = amounts_in(text) - allowed
        if made_up:
            shown = ", ".join(rupees(p) for p in sorted(made_up))
            issues.append(f"{field} mentions {shown}, which is not in the facts")
    return issues


def template(f: dict) -> Explanation:
    text = f["reason"]
    if f["difference"]:
        text += (
            f" The invoice is for {f['invoice_total']}, but the correct amount is "
            f"{f['correct_amount']}, a difference of {f['difference']}."
        )
    elif f["invoice_total"]:
        text += f" The invoice total is {f['invoice_total']}."
    text += " " + f["next_step"]

    email = None
    if f["write_supplier_email"]:
        po = f" against {f['purchase_order']}" if f["purchase_order"] else ""
        lines = [
            f"Subject: Invoice {f['invoice_no']}",
            "",
            f"Dear {f['supplier']},",
            "",
            f"We received your invoice {f['invoice_no']} for {f['invoice_total']}{po}.",
        ]
        if f["rejected"]:
            lines += ["", "We have rejected this invoice and it will not be paid as it stands."]
        if f["problems_for_supplier"]:
            lines += ["", "We found the following:"]
            lines += [f"- {p}" for p in f["problems_for_supplier"]]
        if f["difference"]:
            lines += [
                "",
                f"The correct amount is {f['correct_amount']}, {f['difference']} less than "
                "invoiced.",
            ]
        lines += ["", f["supplier_action"], "", "Thank you,", "Accounts Payable"]
        email = "\n".join(lines)
    return Explanation(text, email, "template")


def explain(
    extracted: Extracted,
    result: MatchResult,
    outcome: Outcome,
    usage: AiUsage,
    rejected: bool = False,
) -> Explanation:
    """Write the explanation and supplier email for a decision. Model calls are added to
    `usage`. Never raises because of the model: the template is the fallback."""
    f = facts(extracted, result, outcome, rejected)
    explainer = explanation.get_explainer()
    if explainer is None:
        return template(f)
    feedback = None
    try:
        for _ in range(MAX_ATTEMPTS):
            call = explainer.explain(f, feedback)
            usage.calls += 1
            usage.input_tokens += call.input_tokens
            usage.output_tokens += call.output_tokens
            usage.latency_ms += call.latency_ms
            issues = [call.error] if call.parsed is None else check(call.parsed, f)
            if not issues:
                email = call.parsed.supplier_email if f["write_supplier_email"] else None
                return Explanation(call.parsed.explanation.strip(), email, "agent")
            feedback = "\n".join(f"- {i}" for i in issues)
        logger.warning("Explanation failed its checks; using the template: %s", feedback)
    except Exception:
        logger.exception("Explanation Agent failed; using the template")
    return template(f)
