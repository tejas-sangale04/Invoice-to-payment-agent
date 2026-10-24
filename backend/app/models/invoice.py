from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, StringConstraints, field_validator


class InvoiceStatus(StrEnum):
    received = "received"
    extracting = "extracting"
    extracted = "extracted"
    validated = "validated"
    matched = "matched"
    auto_approved = "auto_approved"
    pending_approval = "pending_approval"
    approved = "approved"
    rejected = "rejected"
    posted = "posted"
    paid = "paid"
    on_hold = "on_hold"
    blocked_duplicate = "blocked_duplicate"
    needs_review = "needs_review"
    failed = "failed"


class Decision(StrEnum):
    auto_approve = "auto_approve"
    manager_approval = "manager_approval"
    hold = "hold"
    block = "block"
    needs_review = "needs_review"


class ExtractedItem(BaseModel):
    name: str
    qty: Decimal
    unit: str | None = None
    unit_price_paise: int
    tax_rate: Decimal = Decimal("0")
    amount_paise: int | None = None  # the line amount as printed, before tax


class Extracted(BaseModel):
    """What the Extraction Agent read from the invoice, converted to paise by code."""

    supplier_name: str | None = None
    supplier_gstin: str | None = None
    invoice_no: str | None = None
    invoice_date: date | None = None
    po_number: str | None = None
    items: list[ExtractedItem] = []
    subtotal_paise: int | None = None
    cgst_paise: int = 0
    sgst_paise: int = 0
    igst_paise: int = 0
    total_paise: int | None = None
    field_confidence: dict[str, float] = {}


class MatchIssueKind(StrEnum):
    """What went wrong, from code. The decision step maps each kind to a rule (Section 8)."""

    duplicate = "duplicate"  # same file, or same supplier + invoice number
    supplier = "supplier"  # supplier not in the system, or not the PO's supplier
    no_po = "no_po"  # no PO number, unknown PO or closed PO
    unmatched_line = "unmatched_line"  # a billed line the PO doesn't have
    unit = "unit"  # billed in a different unit, so quantities can't be compared
    quantity = "quantity"  # billed more than received and not yet billed
    price_over_tolerance = "price_over_tolerance"
    price_within_tolerance = "price_within_tolerance"
    gst_rate = "gst_rate"  # line GST rate differs from the PO
    possible_duplicate = "possible_duplicate"  # same supplier and total within 7 days


class MatchIssue(BaseModel):
    kind: MatchIssueKind
    message: str
    line: int | None = None  # 1-based invoice line, when the issue is about one line


class MatchLine(BaseModel):
    """One invoice line compared with its PO line and what has been received."""

    line: int
    name: str
    po_line_id: str | None = None
    po_item_name: str | None = None
    unit: str | None = None
    billed_qty: Decimal
    received_qty: Decimal = Decimal("0")
    already_billed_qty: Decimal = Decimal("0")
    available_qty: Decimal = Decimal("0")  # received minus already billed
    billed_unit_price_paise: int
    po_unit_price_paise: int | None = None
    billed_tax_rate: Decimal = Decimal("0")
    po_tax_rate: Decimal | None = None
    billed_amount_paise: int = 0  # billed qty x billed price, before tax
    correct_amount_paise: int = 0  # payable qty x payable price, before tax
    issue: str | None = None


class MatchResult(BaseModel):
    """3-way match outcome. Everything here is computed by code, never by the model."""

    matched_po: str | None = None
    supplier_id: str | None = None
    matched_without_po_number: bool = False
    per_line: list[MatchLine] = []
    issues: list[MatchIssue] = []
    correct_amount_paise: int = 0  # what we should pay, including GST at PO rates
    difference_paise: int = 0  # invoice total minus the correct amount


class Resolution(BaseModel):
    """What the Resolution Agent proposed for an invoice without a PO number, and what code
    found when it checked."""

    proposed_po: str | None = None
    reasoning: str | None = None
    fitting_pos: list[str] = []  # open POs of the supplier that fit, by code's check
    verified: bool = False
    message: str = ""


class AiUsage(BaseModel):
    """Recorded per invoice for the dashboard; summed over every model call."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0


class SupplierEmail(BaseModel):
    """The email a manager has read and wants sent to the supplier on file."""

    subject: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8000)]

    @field_validator("subject")
    @classmethod
    def _one_line(cls, value: str) -> str:
        if "\r" in value or "\n" in value:
            raise ValueError("The subject must be one line")
        return value


class EmailDraft(BaseModel):
    """What the Explanation Agent wrote for the supplier, for a manager to read and send."""

    email: str  # "Subject: ..." on the first line, then the message
    source: str  # "agent", or "template" when the agent's text failed its checks


class SentEmail(BaseModel):
    """The last email sent (or tried) to the supplier about an invoice."""

    to: str
    subject: str
    body: str
    status: str  # "sent" or "failed"
    error: str | None = None
    by: str
    by_email: str | None = None
    at: datetime


class EmailStatus(BaseModel):
    enabled: bool
    sender: str | None = None


class Invoice(BaseModel):
    invoice_id: str
    status: InvoiceStatus
    status_reason: str | None = None
    file_name: str
    content_type: str
    file_size: int
    file_hash: str
    extracted: Extracted | None = None
    match_result: MatchResult | None = None
    validation_issues: list[str] = []
    ai_usage: AiUsage | None = None
    decision: Decision | None = None
    decision_reason: str | None = None
    decision_rule: str | None = None
    explanation: str | None = None
    explanation_source: str | None = None  # "agent", or "template" when the agent's text failed
    resolution: Resolution | None = None
    supplier_email_draft: str | None = None
    supplier_email: SentEmail | None = None
    uploaded_by: str
    approved_by: str | None = None
    approved_by_email: str | None = None
    approval_comment: str | None = None
    rejected_by: str | None = None
    rejected_by_email: str | None = None
    rejection_reason: str | None = None
    duplicate_of: str | None = None
    ledger_key: str | None = None
    posted_by: str | None = None
    processing_attempts: int = 0
    created_at: datetime
    updated_at: datetime
    status_times: dict[str, datetime] = {}


class AuditEntry(BaseModel):
    invoice_id: str
    action: str
    actor: str
    from_status: InvoiceStatus | None = None
    to_status: InvoiceStatus | None = None
    details: str | None = None
    timestamp: datetime


class ApproveRequest(BaseModel):
    comment: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=1000)] = None


class RejectRequest(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    # When set, the supplier is emailed after the rejection is saved.
    email: SupplierEmail | None = None


class LedgerEntry(BaseModel):
    idempotency_key: str
    invoice_id: str
    invoice_no: str
    supplier_id: str
    supplier_name: str
    amount_paise: int
    po_number: str
    posted_by: str
    posted_at: datetime


class FileLink(BaseModel):
    url: str
    content_type: str
    expires_in_seconds: int


class ProcessInvoiceTask(BaseModel):
    invoice_id: str
