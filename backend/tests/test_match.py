from decimal import Decimal

import pytest

from app.models.invoice import Extracted, ExtractedItem
from app.models.invoice import MatchIssueKind as K
from app.pipeline.match import match_invoice, normalize_po_number, normalize_unit, pair_lines

TOL = Decimal("2.0")


def po(received=None, billed=None, **overrides) -> dict:
    """PO-205 from the spec: 50 L milk at Rs 60 (no GST), 10 kg paneer at Rs 320 (5% GST)."""
    doc = {
        "po_number": "PO-205",
        "supplier_id": "SUP-1",
        "supplier_name": "Sharma Dairy Pvt Ltd",
        "status": "open",
        "items": [
            {
                "line_id": "1",
                "name": "Full cream milk",
                "qty": "50",
                "unit": "L",
                "unit_price_paise": 6000,
                "tax_rate": "0",
            },
            {
                "line_id": "2",
                "name": "Paneer",
                "qty": "10",
                "unit": "kg",
                "unit_price_paise": 32000,
                "tax_rate": "5",
            },
        ],  # fmt: skip
        "received": received if received is not None else {"1": "50", "2": "10"},
        "billed": billed or {},
    }
    return {**doc, **overrides}


def item(name="Milk", qty="50", unit="L", price=6000, rate="0") -> ExtractedItem:
    return ExtractedItem(
        name=name, qty=Decimal(qty), unit=unit, unit_price_paise=price, tax_rate=Decimal(rate)
    )


def invoice(*items: ExtractedItem, total: int | None = None) -> Extracted:
    if total is None:
        total = sum(round(i.qty * i.unit_price_paise * (1 + i.tax_rate / 100)) for i in items)
    return Extracted(supplier_name="Sharma Dairy", invoice_no="SD-1", items=list(items),
                     total_paise=total)  # fmt: skip


def kinds(result) -> list[K]:
    return [i.kind for i in result.issues]


# ------------------------------------------------------------ normalising


@pytest.mark.parametrize(
    "raw",
    ["PO-205", "po-205", "PO 205", "PO205", "P.O. No. 205", "PO#205", "PO-0205", "205", "po/205"],
)
def test_po_numbers_are_normalised(raw: str) -> None:
    assert normalize_po_number(raw) == "PO-205"


@pytest.mark.parametrize("raw", [None, "", "ORD-77", "SD/2026/0457", "PO-"])
def test_things_that_are_not_our_po_numbers(raw) -> None:
    assert normalize_po_number(raw) is None


def test_units_are_normalised() -> None:
    assert normalize_unit("Ltr") == normalize_unit("L") == normalize_unit("litres") == "l"
    assert normalize_unit("KGS") == "kg"
    assert normalize_unit("Nos.") == normalize_unit("pcs") == "pcs"
    assert normalize_unit(None) is None


def test_line_names_pair_by_words_and_each_po_line_is_used_once() -> None:
    po_names = ["Full cream milk", "Paneer", "Butter"]
    assert pair_lines(["Butter", "Milk", "Paneer"], po_names) == [2, 0, 1]
    assert pair_lines(["Cheese"], po_names) == [None]
    # Ties go to the line in the same position.
    assert pair_lines(["Paneer", "Paneer"], po_names) == [None, 1]
    assert pair_lines(["Paneers"], po_names) == [1]


# --------------------------------------------------------------- matching


def test_everything_matches() -> None:
    result = match_invoice(invoice(item(), item("Paneer", "10", "kg", 32000, "5")), po(), TOL)
    assert result.issues == []
    assert result.matched_po == "PO-205"
    assert result.correct_amount_paise == 300000 + 320000 + 16000
    assert result.difference_paise == 0
    milk = result.per_line[0]
    assert (milk.po_item_name, milk.received_qty, milk.available_qty) == (
        "Full cream milk",
        Decimal(50),
        Decimal(50),
    )


def test_spec_example_partial_delivery_is_an_overcharge_of_600() -> None:
    # 50 L ordered, only 40 L received, invoice bills 50 L (Rs 3,000).
    result = match_invoice(invoice(item()), po(received={"1": "40"}), TOL)
    assert kinds(result) == [K.quantity]
    assert "billed 50 L, but only 40 L can be billed (received 40)" in result.issues[0].message
    assert result.correct_amount_paise == 240000
    assert result.difference_paise == 60000


def test_already_billed_quantity_is_not_available_again() -> None:
    result = match_invoice(
        invoice(item(qty="20")), po(received={"1": "50"}, billed={"1": "40"}), TOL
    )
    assert kinds(result) == [K.quantity]
    assert (
        "only 10 L can be billed (received 50, 40 already billed on other invoices)"
        in result.issues[0].message
    )
    assert result.per_line[0].available_qty == Decimal(10)


def test_unposted_invoices_count_as_billed() -> None:
    result = match_invoice(
        invoice(item(qty="20")),
        po(received={"1": "50"}, billed={"1": "20"}),
        TOL,
        committed={"1": Decimal(20)},
    )
    assert kinds(result) == [K.quantity]
    assert result.per_line[0].already_billed_qty == Decimal(40)


def test_multiple_deliveries_add_up() -> None:
    # The PO keeps a running received total per line across all its goods receipts.
    result = match_invoice(invoice(item(qty="45")), po(received={"1": "45"}), TOL)
    assert result.issues == []


def test_billing_part_of_a_po_is_fine() -> None:
    result = match_invoice(invoice(item(qty="20")), po(), TOL)
    assert result.issues == []


def test_price_within_tolerance() -> None:
    result = match_invoice(invoice(item(price=6100)), po(), TOL)  # 1.67% higher
    assert kinds(result) == [K.price_within_tolerance]
    assert "(1.67% higher, within the 2.0% limit)" in result.issues[0].message
    assert result.correct_amount_paise == 300000  # we pay the PO price
    assert result.difference_paise == 5000


def test_price_exactly_at_tolerance_is_within() -> None:
    result = match_invoice(invoice(item(price=6120)), po(), TOL)  # exactly 2%
    assert kinds(result) == [K.price_within_tolerance]


def test_price_over_tolerance() -> None:
    result = match_invoice(invoice(item(price=6500)), po(), TOL)
    assert kinds(result) == [K.price_over_tolerance]
    assert "Rs 65.00 per L, PO-205 price is Rs 60.00 (8.33% higher, limit 2.0%)" in (
        result.issues[0].message
    )


def test_a_lower_price_is_not_a_problem_and_we_pay_what_is_billed() -> None:
    result = match_invoice(invoice(item(price=5500)), po(), TOL)
    assert result.issues == []
    assert result.correct_amount_paise == 275000


def test_gst_rate_must_match_the_po() -> None:
    result = match_invoice(invoice(item("Paneer", "10", "kg", 32000, "12")), po(), TOL)
    assert kinds(result) == [K.gst_rate]
    assert "GST 12% on the invoice, 5% on PO-205" in result.issues[0].message
    assert result.correct_amount_paise == 320000 + 16000  # at the PO's 5%


def test_igst_invoice_matches_by_rate() -> None:
    # Inter-state: IGST 5% instead of CGST 2.5% + SGST 2.5%; the line rate is still 5.
    result = match_invoice(invoice(item("Paneer", "10", "kg", 32000, "5")), po(), TOL)
    assert result.issues == []


def test_different_unit_cannot_be_compared() -> None:
    result = match_invoice(invoice(item(unit="kg")), po(), TOL)
    assert kinds(result) == [K.unit]


def test_unit_spellings_are_the_same_unit() -> None:
    assert match_invoice(invoice(item(unit="Ltr")), po(), TOL).issues == []


def test_line_not_on_the_po() -> None:
    result = match_invoice(invoice(item(), item("Ghee", "2", "kg", 60000)), po(), TOL)
    assert kinds(result) == [K.unmatched_line]
    assert result.issues[0].message == "Ghee is not on PO-205"
    assert result.issues[0].line == 2


def test_several_problems_on_one_line_are_all_reported() -> None:
    result = match_invoice(invoice(item(price=7000)), po(received={"1": "40"}), TOL)
    assert kinds(result) == [K.quantity, K.price_over_tolerance]
    assert result.correct_amount_paise == 240000  # 40 L at the PO price
    assert ";" in result.per_line[0].issue


def test_difference_uses_the_printed_total() -> None:
    result = match_invoice(invoice(item(), total=310000), po(), TOL)
    assert result.difference_paise == 10000
