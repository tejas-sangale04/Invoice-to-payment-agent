"""Deterministic money arithmetic. All amounts are integer paise; intermediates use Decimal."""

from decimal import ROUND_HALF_UP, Decimal


def to_paise(amount: Decimal) -> int:
    """Round a Decimal paise amount to a whole paisa, halves away from zero."""
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def line_amounts(qty: Decimal, unit_price_paise: int, tax_rate: Decimal) -> tuple[int, int]:
    """Return (taxable line total, tax) in paise for one line. `tax_rate` is a percent, e.g. 18."""
    taxable = qty * unit_price_paise
    return to_paise(taxable), to_paise(taxable * tax_rate / 100)
