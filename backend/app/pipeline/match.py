"""3-way match: invoice vs purchase order vs goods received (Setup guide, Section 7, step 5).

Pure functions, no Firestore: everything is computed from the extracted invoice and the PO
document, so every rule can be unit-tested. Money stays in integer paise.
"""

import re
from decimal import Decimal

from app.models.invoice import Extracted, MatchIssue, MatchLine, MatchResult
from app.models.invoice import MatchIssueKind as K
from app.pipeline.money import line_amounts, qty_text, rupees, to_paise

_PO_NUMBER = re.compile(r"^P\.?O\.?\s*[-/#:]?\s*(?:NO\.?\s*[-/#:]?\s*)?0*(\d+)$")
_DIGITS = re.compile(r"^0*(\d+)$")

_UNITS = {
    "l": "l", "ltr": "l", "ltrs": "l", "litre": "l", "litres": "l", "liter": "l", "liters": "l",
    "ml": "ml",
    "kg": "kg", "kgs": "kg", "kilo": "kg", "kilos": "kg", "kilogram": "kg", "kilograms": "kg",
    "g": "g", "gm": "g", "gms": "g", "gram": "g", "grams": "g",
    "pc": "pcs", "pcs": "pcs", "piece": "pcs", "pieces": "pcs", "no": "pcs", "nos": "pcs",
    "unit": "pcs", "units": "pcs", "ea": "pcs", "each": "pcs",
    "dozen": "dozen", "doz": "dozen", "box": "box", "boxes": "box", "pack": "pack",
    "packs": "pack", "pkt": "pack", "pkts": "pack",
}  # fmt: skip


def normalize_po_number(raw: str | None) -> str | None:
    """'po-1', 'P.O. No. 001', 'PO 1' and '1' all become 'PO-1'. None if it doesn't look like
    one of ours."""
    if not raw:
        return None
    text = raw.strip().upper()
    found = _PO_NUMBER.match(text) or _DIGITS.match(text)
    return f"PO-{found.group(1)}" if found else None


def normalize_unit(unit: str | None) -> str | None:
    if not unit:
        return None
    key = re.sub(r"[^a-z]", "", unit.lower())
    return _UNITS.get(key, key or None)


def _tokens(name: str) -> set[str]:
    words = re.sub(r"[^a-z0-9 ]", " ", name.lower()).split()
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words}


def _similarity(a: str, b: str) -> tuple[float, float]:
    """(containment, jaccard). 'Milk' vs 'Full cream milk' is fully contained."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0, 0.0
    shared = len(ta & tb)
    return shared / min(len(ta), len(tb)), shared / len(ta | tb)


def pair_lines(invoice_names: list[str], po_names: list[str]) -> list[int | None]:
    """For each invoice line, the index of its PO line (or None). Each PO line is used once;
    the most similar pairs are taken first, and a pair must share at least half the words of
    the shorter name."""
    candidates = []
    for i, inv_name in enumerate(invoice_names):
        for j, po_name in enumerate(po_names):
            containment, jaccard = _similarity(inv_name, po_name)
            if containment >= 0.5:
                candidates.append((-containment, -jaccard, abs(i - j), i, j))
    pairs: list[int | None] = [None] * len(invoice_names)
    used: set[int] = set()
    for *_, i, j in sorted(candidates):
        if pairs[i] is None and j not in used:
            pairs[i] = j
            used.add(j)
    return pairs


def _pct(over: int, base: int) -> Decimal:
    return (Decimal(over) * 100 / base).quantize(Decimal("0.01")) if base else Decimal(100)


def match_invoice(
    extracted: Extracted,
    po: dict,
    price_tolerance_percent: Decimal,
    committed: dict[str, Decimal] | None = None,
) -> MatchResult:
    """Compare each billed line with its PO line. `po` is the purchase_orders document:
    quantities and rates are strings, `received` and `billed` (posted to the ledger) map
    line_id -> quantity. `committed` is what other invoices that are approved or awaiting
    approval, but not yet posted, already bill per line: that can't be billed twice either."""
    po_number = po["po_number"]
    po_items: list[dict] = po["items"]
    received = {k: Decimal(v) for k, v in po.get("received", {}).items()}
    billed = {k: Decimal(v) for k, v in po.get("billed", {}).items()}
    for line_id, qty in (committed or {}).items():
        billed[line_id] = billed.get(line_id, Decimal(0)) + qty
    tolerance = Decimal(price_tolerance_percent)

    issues: list[MatchIssue] = []
    lines: list[MatchLine] = []
    correct_taxable = 0
    correct_tax = 0
    pairs = pair_lines([i.name for i in extracted.items], [p["name"] for p in po_items])

    for n, (item, j) in enumerate(zip(extracted.items, pairs, strict=True), start=1):
        billed_amount = to_paise(item.qty * item.unit_price_paise)
        line = MatchLine(
            line=n,
            name=item.name,
            unit=item.unit,
            billed_qty=item.qty,
            billed_unit_price_paise=item.unit_price_paise,
            billed_tax_rate=item.tax_rate,
            billed_amount_paise=billed_amount,
        )
        lines.append(line)

        def flag(kind: K, message: str, line: MatchLine = line, n: int = n) -> None:
            issues.append(MatchIssue(kind=kind, message=message, line=n))
            line.issue = f"{line.issue}; {message}" if line.issue else message

        if j is None:
            flag(K.unmatched_line, f"{item.name} is not on {po_number}")
            continue

        po_item = po_items[j]
        line_id = po_item["line_id"]
        po_price = po_item["unit_price_paise"]
        po_rate = Decimal(po_item["tax_rate"])
        got, already = received.get(line_id, Decimal(0)), billed.get(line_id, Decimal(0))
        available = max(got - already, Decimal(0))
        line.po_line_id = line_id
        line.po_item_name = po_item["name"]
        line.unit = po_item["unit"]
        line.received_qty = got
        line.already_billed_qty = already
        line.available_qty = available
        line.po_unit_price_paise = po_price
        line.po_tax_rate = po_rate

        unit, po_unit = normalize_unit(item.unit), normalize_unit(po_item["unit"])
        if unit and po_unit and unit != po_unit:
            flag(
                K.unit,
                f"{item.name}: billed in {item.unit}, but {po_number} is in {po_item['unit']}",
            )
            continue

        u = po_item["unit"]
        if item.qty > available:
            detail = f"received {qty_text(got)}"
            if already:
                detail += f", {qty_text(already)} already billed on other invoices"
            flag(
                K.quantity,
                f"{item.name}: billed {qty_text(item.qty)} {u}, but only {qty_text(available)} "
                f"{u} can be billed ({detail})",
            )

        if item.unit_price_paise > po_price:
            pct = _pct(item.unit_price_paise - po_price, po_price)
            price_text = (
                f"{item.name}: billed {rupees(item.unit_price_paise)} per {u}, "
                f"{po_number} price is {rupees(po_price)} ({pct}% higher"
            )
            if pct > tolerance:
                flag(K.price_over_tolerance, f"{price_text}, limit {tolerance}%)")
            else:
                flag(K.price_within_tolerance, f"{price_text}, within the {tolerance}% limit)")

        if item.tax_rate != po_rate:
            flag(
                K.gst_rate,
                f"{item.name}: GST {qty_text(item.tax_rate)}% on the invoice, "
                f"{qty_text(po_rate)}% on {po_number}",
            )

        # What we should pay for this line: no more than is available, at no more than the
        # PO price, with GST at the PO rate.
        taxable, tax = line_amounts(
            min(item.qty, available), min(item.unit_price_paise, po_price), po_rate
        )
        line.correct_amount_paise = taxable
        correct_taxable += taxable
        correct_tax += tax

    correct = correct_taxable + correct_tax
    total = extracted.total_paise
    if total is None:
        total = sum(line.billed_amount_paise for line in lines)
    return MatchResult(
        matched_po=po_number,
        supplier_id=po.get("supplier_id"),
        per_line=lines,
        issues=issues,
        correct_amount_paise=correct,
        difference_paise=total - correct,
    )
