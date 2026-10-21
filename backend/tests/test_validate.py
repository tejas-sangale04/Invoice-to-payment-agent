from decimal import Decimal

import pytest

from app.pipeline.validate import check, to_extracted
from tests.factories import CONFIDENT, llm_invoice

MIN = Decimal("0.85")


def issues_for(**changes) -> list[str]:
    extracted, parse_issues = to_extracted(llm_invoice(**changes))
    return parse_issues + check(extracted, MIN)


def test_valid_invoice_converts_to_paise_and_passes() -> None:
    extracted, issues = to_extracted(llm_invoice())
    assert issues == []
    assert check(extracted, MIN) == []
    assert extracted.supplier_gstin == "27ABCDE1234F1Z5"
    assert extracted.po_number == "PO-1"
    assert [(i.qty, i.unit_price_paise, i.tax_rate, i.amount_paise) for i in extracted.items] == [
        (Decimal("50"), 6000, Decimal("0"), 300000),
        (Decimal("2.5"), 40000, Decimal("5"), 100000),
    ]
    assert (extracted.subtotal_paise, extracted.cgst_paise, extracted.sgst_paise) == (
        400000,
        2500,
        2500,
    )
    assert extracted.total_paise == 405000


def test_rounding_within_one_rupee_is_accepted() -> None:
    assert issues_for(total="4,050.99", cgst="25.40", sgst="25.40") == []


def test_line_arithmetic_mismatch() -> None:
    items = llm_invoice().model_dump()["items"]
    items[0]["amount"] = "3,600.00"
    issues = issues_for(items=items, subtotal="4,600.00", total="4,650.00")
    assert issues == [
        "Line 1 (Milk): 50 x Rs 60.00 = Rs 3,000.00, but the line amount reads Rs 3,600.00"
    ]


def test_subtotal_mismatch() -> None:
    assert issues_for(subtotal="4,500.00", total="4,550.00") == [
        "Line amounts add up to Rs 4,000.00, but the subtotal reads Rs 4,500.00"
    ]


def test_total_mismatch() -> None:
    assert issues_for(total="5,050.00") == [
        "Subtotal Rs 4,000.00 + GST Rs 50.00 = Rs 4,050.00, but the total reads Rs 5,050.00"
    ]


def test_gst_must_match_line_rates() -> None:
    assert issues_for(cgst="90.00", sgst="90.00", total="4,180.00") == [
        "GST charged is Rs 180.00, but the line rates give Rs 50.00"
    ]


def test_igst_is_valid_for_inter_state() -> None:
    assert issues_for(cgst=None, sgst=None, igst="50.00") == []


def test_igst_and_cgst_together_is_flagged() -> None:
    issues = issues_for(cgst="25.00", sgst="25.00", igst="50.00", total="4,100.00")
    assert "Both IGST and CGST/SGST are charged; an invoice should have one or the other" in issues


def test_cgst_and_sgst_must_be_equal() -> None:
    assert "CGST (Rs 40.00) and SGST (Rs 10.00) should be equal" in issues_for(
        cgst="40.00", sgst="10.00"
    )


def test_required_fields() -> None:
    issues = issues_for(supplier_name=None, invoice_no=" ", invoice_date=None, total=None)
    assert issues == [
        "Supplier name is missing",
        "Invoice number is missing",
        "Invoice date is missing",
        "Total is missing",
    ]
    assert "No line items were found" in issues_for(
        items=[], subtotal=None, cgst=None, sgst=None, total="0"
    )


def test_missing_po_number_is_allowed_here() -> None:
    # Matching without a PO number is handled later by the Resolution Agent.
    assert issues_for(po_number=None) == []


def test_low_confidence_is_flagged() -> None:
    low = {**CONFIDENT, "totals": 0.6, "invoice_no": 0.5}
    assert issues_for(field_confidence=low) == ["Not confident enough reading: invoice no, totals"]


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"total": "about 4000"}, "Total: 'about 4000' is not a number"),
        ({"invoice_date": "20/10/2026"}, "Invoice date: '20/10/2026' is not a YYYY-MM-DD date"),
        ({"subtotal": "-4000"}, "Subtotal: '-4000' is negative"),
    ],
)
def test_unparseable_values_are_reported(changes: dict, expected: str) -> None:
    assert expected in issues_for(**changes)
