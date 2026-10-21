"""Turns what the Extraction Agent read into paise, and checks it with code (Setup guide, Step 3).

Issues are written as plain sentences: they are shown to staff and fed back to the model on its
one corrective retry.
"""

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from app.agents.schemas import LlmInvoice
from app.models.invoice import Extracted, ExtractedItem
from app.pipeline.money import to_paise

TOLERANCE_PAISE = 100  # +/- Rs 1 for rounding on printed invoices

_CURRENCY = re.compile(r"(?i)(₹|rs\.?|inr|/-)")


def _decimal(raw: str | None, field: str, issues: list[str]) -> Decimal | None:
    if raw is None or str(raw).strip() == "":
        return None
    text = _CURRENCY.sub("", str(raw)).replace(",", "").replace("%", "").strip()
    try:
        value = Decimal(text)
    except InvalidOperation:
        issues.append(f"{field}: '{raw}' is not a number")
        return None
    if value < 0:
        issues.append(f"{field}: '{raw}' is negative")
        return None
    return value


def _paise(raw: str | None, field: str, issues: list[str]) -> int | None:
    value = _decimal(raw, field, issues)
    return None if value is None else to_paise(value * 100)


def _rupees(paise: int) -> str:
    return f"Rs {Decimal(paise) / 100:,.2f}"


def to_extracted(raw: LlmInvoice) -> tuple[Extracted, list[str]]:
    """Convert the model's strings to typed values. Returns the result and any parse issues."""
    issues: list[str] = []
    items: list[ExtractedItem] = []
    for i, line in enumerate(raw.items, start=1):
        label = f"Line {i} ({line.name})"
        qty = _decimal(line.qty, f"{label} quantity", issues)
        price = _paise(line.unit_price, f"{label} unit price", issues)
        rate = _decimal(line.tax_rate, f"{label} GST rate", issues)
        if qty is None or price is None:
            issues.append(f"{label}: quantity and unit price are required")
            continue
        items.append(
            ExtractedItem(
                name=line.name.strip(),
                qty=qty,
                unit=line.unit,
                unit_price_paise=price,
                tax_rate=rate or Decimal("0"),
                amount_paise=_paise(line.amount, f"{label} amount", issues),
            )
        )

    invoice_date = None
    if raw.invoice_date:
        try:
            invoice_date = date.fromisoformat(raw.invoice_date.strip())
        except ValueError:
            issues.append(f"Invoice date: '{raw.invoice_date}' is not a YYYY-MM-DD date")

    extracted = Extracted(
        supplier_name=(raw.supplier_name or "").strip() or None,
        supplier_gstin=(raw.supplier_gstin or "").strip().upper() or None,
        invoice_no=(raw.invoice_no or "").strip() or None,
        invoice_date=invoice_date,
        po_number=(raw.po_number or "").strip().upper() or None,
        items=items,
        subtotal_paise=_paise(raw.subtotal, "Subtotal", issues),
        cgst_paise=_paise(raw.cgst, "CGST", issues) or 0,
        sgst_paise=_paise(raw.sgst, "SGST", issues) or 0,
        igst_paise=_paise(raw.igst, "IGST", issues) or 0,
        total_paise=_paise(raw.total, "Total", issues),
        field_confidence=raw.field_confidence.model_dump(),
    )
    return extracted, issues


def check(extracted: Extracted, min_confidence: Decimal) -> list[str]:
    """All the arithmetic and completeness checks. An empty list means the invoice is valid."""
    issues: list[str] = []
    e = extracted

    for field, label in [
        ("supplier_name", "Supplier name"),
        ("invoice_no", "Invoice number"),
        ("invoice_date", "Invoice date"),
        ("total_paise", "Total"),
    ]:
        if getattr(e, field) is None:
            issues.append(f"{label} is missing")
    if not e.items:
        issues.append("No line items were found")

    # Each line: quantity x unit price = printed line amount.
    taxable_sum = 0
    expected_tax = Decimal(0)
    for i, item in enumerate(e.items, start=1):
        line_value = item.qty * item.unit_price_paise
        line_total = to_paise(line_value)
        if item.amount_paise is not None and abs(line_total - item.amount_paise) > TOLERANCE_PAISE:
            issues.append(
                f"Line {i} ({item.name}): {item.qty} x {_rupees(item.unit_price_paise)} = "
                f"{_rupees(line_total)}, but the line amount reads {_rupees(item.amount_paise)}"
            )
        taxable_sum += item.amount_paise if item.amount_paise is not None else line_total
        expected_tax += line_value * item.tax_rate / 100

    if (
        e.items
        and e.subtotal_paise is not None
        and abs(taxable_sum - e.subtotal_paise) > TOLERANCE_PAISE
    ):
        issues.append(
            f"Line amounts add up to {_rupees(taxable_sum)}, but the subtotal reads "
            f"{_rupees(e.subtotal_paise)}"
        )
    subtotal = e.subtotal_paise if e.subtotal_paise is not None else taxable_sum

    # GST: CGST + SGST (intra-state) or IGST (inter-state), never both.
    if e.igst_paise and (e.cgst_paise or e.sgst_paise):
        issues.append(
            "Both IGST and CGST/SGST are charged; an invoice should have one or the other"
        )
    if abs(e.cgst_paise - e.sgst_paise) > TOLERANCE_PAISE:
        issues.append(
            f"CGST ({_rupees(e.cgst_paise)}) and SGST ({_rupees(e.sgst_paise)}) should be equal"
        )
    tax = e.cgst_paise + e.sgst_paise + e.igst_paise
    expected = to_paise(expected_tax)
    if e.items and abs(tax - expected) > TOLERANCE_PAISE:
        issues.append(f"GST charged is {_rupees(tax)}, but the line rates give {_rupees(expected)}")

    if e.total_paise is not None and abs(subtotal + tax - e.total_paise) > TOLERANCE_PAISE:
        issues.append(
            f"Subtotal {_rupees(subtotal)} + GST {_rupees(tax)} = {_rupees(subtotal + tax)}, "
            f"but the total reads {_rupees(e.total_paise)}"
        )

    low = [k for k, v in e.field_confidence.items() if Decimal(str(v)) < min_confidence]
    if low:
        issues.append(
            "Not confident enough reading: " + ", ".join(k.replace("_", " ") for k in sorted(low))
        )
    return issues
