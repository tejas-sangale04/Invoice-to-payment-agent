from decimal import Decimal

from app.pipeline.money import line_amounts, to_paise


def test_example_from_spec() -> None:
    # 50 L milk at Rs 60 = Rs 3,000; 40 L = Rs 2,400.
    assert line_amounts(Decimal("50"), 6000, Decimal("0")) == (300000, 0)
    assert line_amounts(Decimal("40"), 6000, Decimal("0")) == (240000, 0)


def test_gst_is_rounded_half_up_to_the_paisa() -> None:
    # 1.5 x Rs 0.33 = 49.5 paise -> 50; 18% of 49.5 = 8.91 -> 9
    assert line_amounts(Decimal("1.5"), 33, Decimal("18")) == (50, 9)


def test_fractional_quantities_avoid_float_error() -> None:
    # 0.1 + 0.2 style issues: 2.675 kg at Rs 100 = Rs 267.50 exactly.
    assert line_amounts(Decimal("2.675"), 10000, Decimal("5")) == (26750, 1338)


def test_to_paise_rounds_halves_away_from_zero() -> None:
    assert to_paise(Decimal("0.5")) == 1
    assert to_paise(Decimal("2.4999")) == 2
