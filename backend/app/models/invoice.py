from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel


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


class MatchLine(BaseModel):
    name: str
    billed_qty: Decimal
    available_qty: Decimal
    billed_unit_price_paise: int
    po_unit_price_paise: int
    issue: str | None = None


class MatchResult(BaseModel):
    """3-way match outcome (filled in from Phase 5)."""

    matched_po: str | None = None
    per_line: list[MatchLine] = []
    issues: list[str] = []
    correct_amount_paise: int = 0
    difference_paise: int = 0


class AiUsage(BaseModel):
    """Recorded per invoice for the dashboard; summed over every model call."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0


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
    explanation: str | None = None
    supplier_email_draft: str | None = None
    uploaded_by: str
    approved_by: str | None = None
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


class FileLink(BaseModel):
    url: str
    content_type: str
    expires_in_seconds: int


class ProcessInvoiceTask(BaseModel):
    invoice_id: str
