"""The evaluation test set: 60 cases, each a small world (suppliers, POs, deliveries), the
invoices uploaded into it and what the system should do with them.

Expected outcomes are written down per case type from the business rules (PROJECT_CONTEXT.md,
Section 8), and the expected amounts are computed here with plain arithmetic, independently of
the backend's matching code.
"""

import random
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from catalog import STRANGER, SUPPLIERS, Product, Supplier

# ------------------------------------------------------------------------------ the model


@dataclass(frozen=True)
class Line:
    product: Product
    qty: str
    price_paise: int  # agreed (PO) or billed (invoice), before tax
    tax_rate: str
    po_line: int  # 1-based PO line it is, or bills

    @property
    def billed_name(self) -> str:
        return self.product.billed_as or self.product.name


@dataclass(frozen=True)
class PO:
    supplier: Supplier
    lines: tuple[Line, ...]


@dataclass(frozen=True)
class Doc:
    """An invoice as the supplier printed it."""

    supplier: Supplier
    invoice_no: str
    invoice_date: date
    po_number: str | None  # as printed, None when not on the invoice
    lines: tuple[Line, ...]
    layout: int  # 1-4, see layouts.py
    messy: str | None = None  # a scan-like variant, see layouts.MESSY
    hidden: tuple[str, ...] = ()  # fields left off the invoice: invoice_no, invoice_date
    smudged: tuple[str, ...] = ()  # printed but unreadable: total
    po_ref: int | None = None  # 1-based PO it really is for (None: none of ours)


@dataclass
class Case:
    id: str
    kind: str
    description: str
    suppliers: list[Supplier]  # in our supplier list
    pos: list[PO]  # created in order: PO-1, PO-2, ...
    receipts: list[tuple[int, list[str | None]]]  # (PO, qty received per line; None = none)
    invoice: Doc
    decision: str
    rule: str | None
    prior: list[Doc] = field(default_factory=list)  # uploaded first; each is posted
    same_file: bool = False  # the invoice is byte-for-byte the first prior invoice
    approve: bool = False  # a manager approves it if it waits for approval
    split: str = "dev"


KINDS = {
    "perfect_match": "Perfect match",
    "price_within_tolerance": "Small price difference (within tolerance)",
    "price_overcharge": "Large price overcharge",
    "short_delivery": "Short delivery",
    "duplicate": "Duplicate (exact and near-duplicate)",
    "missing_po_one_match": "Missing PO number, one clear match",
    "no_matching_po": "No matching PO",
    "blurry_or_missing_field": "Blurry or missing field",
    "gst_layouts": "Varied layouts with GST",
}

# ------------------------------------------------------------------------------ arithmetic


def _round(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def line_value(line: Line) -> Decimal:
    return Decimal(line.qty) * line.price_paise


def totals(doc: Doc) -> dict[str, int]:
    """What the supplier prints: line amounts, subtotal, GST and total, in paise."""
    amounts = [_round(line_value(i)) for i in doc.lines]
    tax = _round(sum(line_value(i) * Decimal(i.tax_rate) / 100 for i in doc.lines))
    if doc.supplier.inter_state:
        cgst = sgst = 0
        igst = tax
    else:
        cgst = _round(Decimal(tax) / 2)
        sgst, igst = tax - cgst, 0
    subtotal = sum(amounts)
    return {
        "amounts": amounts,
        "subtotal": subtotal,
        "cgst": cgst,
        "sgst": sgst,
        "igst": igst,
        "total": subtotal + cgst + sgst + igst,
    }


def correct_amount(doc: Doc, po: PO, received: list[Decimal], billed: list[Decimal]) -> int:
    """What we should pay (Setup guide, Section 5): per line, no more than was received and not
    yet billed, at no more than the PO price, with GST at the PO rate."""
    total = 0
    for line in doc.lines:
        agreed = po.lines[line.po_line - 1]
        n = line.po_line - 1
        qty = min(Decimal(line.qty), max(received[n] - billed[n], Decimal(0)))
        value = qty * min(line.price_paise, agreed.price_paise)
        total += _round(value) + _round(value * Decimal(agreed.tax_rate) / 100)
    return total


def po_status(po: PO, billed: list[Decimal]) -> str:
    if all(b >= Decimal(i.qty) for b, i in zip(billed, po.lines, strict=True)):
        return "fully_billed"
    return "partially_billed" if any(b > 0 for b in billed) else "open"


# ------------------------------------------------------------------------------ printing

LAYOUT_DATES = {1: "%d/%m/%Y", 2: "%d %b %Y", 3: "%d-%m-%Y", 4: "%d.%m.%Y"}


def _indian(n: int) -> str:
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return ",".join([head, *groups, tail]) if head else ",".join([*groups, tail])


def money(paise: int, layout: int) -> str:
    rupees, p = divmod(paise, 100)
    if layout == 3:
        return f"{rupees}.{p:02d}"
    if layout == 4:
        return f"{_indian(rupees)}.{p:02d}"
    return f"{rupees:,}.{p:02d}"


def qty_text(qty: str) -> str:
    return f"{Decimal(qty).normalize():f}"


def printed(doc: Doc) -> dict:
    """Every value as it appears on the page. The layouts draw these strings, and the oracle
    reader returns them, so the page and the ground truth can't disagree."""
    t = totals(doc)
    s = doc.supplier
    tax_text = (lambda r: f"{qty_text(r)}%") if doc.layout == 1 else qty_text
    return {
        "supplier_name": s.printed_name or s.name,
        "supplier_gstin": s.gstin,
        "address": list(s.address),
        "email": s.email,
        "invoice_no": None if "invoice_no" in doc.hidden else doc.invoice_no,
        "invoice_date": None
        if "invoice_date" in doc.hidden
        else doc.invoice_date.strftime(LAYOUT_DATES[doc.layout]),
        "po_number": doc.po_number,
        "items": [
            {
                "name": line.billed_name,
                "qty": qty_text(line.qty),
                "unit": line.product.unit,
                "unit_price": money(line.price_paise, doc.layout),
                "tax_rate": tax_text(line.tax_rate),
                "amount": money(amount, doc.layout),
            }
            for line, amount in zip(doc.lines, t["amounts"], strict=True)
        ],
        "subtotal": money(t["subtotal"], doc.layout),
        "cgst": money(t["cgst"], doc.layout) if not s.inter_state else None,
        "sgst": money(t["sgst"], doc.layout) if not s.inter_state else None,
        "igst": money(t["igst"], doc.layout) if s.inter_state else None,
        "total": money(t["total"], doc.layout),
        "total_paise": t["total"],
        "inter_state": s.inter_state,
    }


def reading(doc: Doc) -> dict:
    """The correct reading of the invoice, in the Extraction Agent's JSON shape: values as
    printed, null where a field is missing or can't be read, with honest confidence."""
    p = printed(doc)
    total = None if "total" in doc.smudged else p["total"]
    return {
        "supplier_name": p["supplier_name"],
        "supplier_gstin": p["supplier_gstin"],
        "invoice_no": p["invoice_no"],
        "invoice_date": None if "invoice_date" in doc.hidden else doc.invoice_date.isoformat(),
        "po_number": p["po_number"],
        "items": p["items"],
        "subtotal": p["subtotal"],
        "cgst": p["cgst"],
        "sgst": p["sgst"],
        "igst": p["igst"],
        "total": total,
        "field_confidence": {
            "supplier_name": 1.0,
            "invoice_no": 1.0,
            "invoice_date": 1.0,
            "po_number": 1.0,
            "line_items": 1.0,
            "totals": 0.2 if total is None else 1.0,
        },
    }


def fields(doc: Doc) -> dict:
    """Ground truth for field-level extraction accuracy, normalised (paise, ISO dates)."""
    t = totals(doc)
    return {
        "supplier_name": doc.supplier.printed_name or doc.supplier.name,
        "supplier_gstin": doc.supplier.gstin,
        "invoice_no": None if "invoice_no" in doc.hidden else doc.invoice_no,
        "invoice_date": None if "invoice_date" in doc.hidden else doc.invoice_date.isoformat(),
        "po_number": doc.po_number,
        "items": [
            {
                "qty": qty_text(i.qty),
                "unit_price_paise": i.price_paise,
                "tax_rate": qty_text(i.tax_rate),
                "amount_paise": a,
            }
            for i, a in zip(doc.lines, t["amounts"], strict=True)
        ],
        "subtotal_paise": t["subtotal"],
        "gst_paise": {"cgst": t["cgst"], "sgst": t["sgst"], "igst": t["igst"]},
        "total_paise": None if "total" in doc.smudged else t["total"],
    }


# ------------------------------------------------------------------------------ expectations

STATUS_FOR = {
    "auto_approve": "posted",
    "manager_approval": "pending_approval",
    "hold": "on_hold",
    "block": "blocked_duplicate",
    "needs_review": "needs_review",
}


def expectations(case: Case) -> dict:
    """The end state after the case runs: final status, the correct amount, the ledger and
    each PO's billing status."""
    received = [[Decimal(0)] * len(po.lines) for po in case.pos]
    for po_n, qtys in case.receipts:
        for n, qty in enumerate(qtys):
            if qty is not None:
                received[po_n - 1][n] += Decimal(qty)
    billed = [[Decimal(0)] * len(po.lines) for po in case.pos]
    ledger = []

    def post(doc: Doc, amount: int) -> None:
        ledger.append({"invoice_no": doc.invoice_no, "amount_paise": amount})
        for line in doc.lines:
            billed[doc.po_ref - 1][line.po_line - 1] += Decimal(line.qty)

    for doc in case.prior:
        po = case.pos[doc.po_ref - 1]
        post(doc, correct_amount(doc, po, received[doc.po_ref - 1], billed[doc.po_ref - 1]))

    inv = case.invoice
    amount = None
    if inv.po_ref and case.decision not in ("block", "needs_review"):
        n = inv.po_ref - 1
        amount = correct_amount(inv, case.pos[n], received[n], billed[n])
    status = STATUS_FOR[case.decision]
    if case.decision == "auto_approve" or (case.decision == "manager_approval" and case.approve):
        status = "posted"
        post(inv, amount)
    return {
        "decision": case.decision,
        "rule": case.rule,
        "status": status,
        "po_number": f"PO-{inv.po_ref}" if inv.po_ref else None,
        "correct_amount_paise": amount,
        "invoice_total_paise": None if "total" in inv.smudged else totals(inv)["total"],
        "approve": case.approve,
        "ledger": ledger,
        "po_status": {f"PO-{n}": po_status(po, billed[n - 1]) for n, po in enumerate(case.pos, 1)},
    }


# ------------------------------------------------------------------------------ building cases


class Builder:
    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)

    def products(self, s: Supplier, k: int) -> list[Product]:
        chosen = self.rng.sample(range(len(s.products)), min(k, len(s.products)))
        return [s.products[i] for i in sorted(chosen)]

    def po(self, s: Supplier, products: list[Product], qtys: list[str] | None = None) -> PO:
        qtys = qtys or [self.rng.choice(p.qty_options) for p in products]
        return PO(
            s,
            tuple(
                Line(p, q, p.price_paise, p.tax_rate, n)
                for n, (p, q) in enumerate(zip(products, qtys, strict=True), 1)
            ),
        )

    def invoice_no(self, s: Supplier) -> str:
        return s.invoice_no.format(n=self.rng.randint(100, 9999))

    def day(self) -> date:
        return date(2026, 10, self.rng.randint(1, 22))

    def bill(self, po: PO, po_n: int, layout: int, printed_po: str | None = "", **kw) -> Doc:
        """An invoice for everything on the PO, at the PO's prices."""
        po_number = f"PO-{po_n}" if printed_po == "" else printed_po
        return Doc(
            po.supplier,
            self.invoice_no(po.supplier),
            self.day(),
            po_number,
            po.lines,
            layout,
            po_ref=po_n,
            **kw,
        )


def full(po: PO) -> list[str]:
    return [line.qty for line in po.lines]


def reprice(line: Line, percent: str) -> Line:
    """The line billed `percent` above its PO price (rounded down to whole paise)."""
    over = int(line.price_paise * Decimal(percent) / 100)
    return replace(line, price_paise=line.price_paise + over)


ROTATION = list(SUPPLIERS.values())
PO_STYLES = ["PO-{n}", "PO {n}", "P.O. No. {n:03d}", "PO-{n}", "PO/{n}"]


def build_cases() -> list[Case]:
    cases: list[Case] = []
    counter: dict[str, int] = {}

    def add(kind: str, description: str, **kw) -> None:
        counter[kind] = counter.get(kind, 0) + 1
        n = counter[kind]
        cases.append(Case(id=f"{kind}-{n:02d}", kind=kind, description=description, **kw))

    def seed() -> int:
        return 1000 + len(cases)

    # Perfect match (15): every layout, five of them scanned or photographed.
    messy = {2: "scan", 5: "rotate", 8: "lowres", 11: "scan", 13: "noise"}
    for i in range(15):
        b = Builder(seed())
        s = ROTATION[i % len(ROTATION)]
        po = b.po(s, b.products(s, 1 + i % 4))
        style = PO_STYLES[i % len(PO_STYLES)].format(n=1)
        add(
            "perfect_match",
            f"{s.name}: {len(po.lines)} line(s), all delivered, billed at PO prices",
            suppliers=[s],
            pos=[po],
            receipts=[(1, full(po))],
            invoice=b.bill(po, 1, 1 + i % 4, printed_po=style, messy=messy.get(i)),
            decision="auto_approve",
            rule="all_matched",
        )

    # Within tolerance (6): one line up to 2% above the PO price.
    for i, pct in enumerate(["0.5", "1", "1.5", "1.8", "2", "1.2"]):
        b = Builder(seed())
        s = ROTATION[(i * 3 + 1) % len(ROTATION)]
        po = b.po(s, b.products(s, 2))
        doc = b.bill(po, 1, 1 + (i + 1) % 4)
        target = max(range(len(po.lines)), key=lambda n: po.lines[n].price_paise)
        lines = list(doc.lines)
        lines[target] = reprice(lines[target], pct)
        add(
            "price_within_tolerance",
            f"{s.name}: {lines[target].billed_name} billed {pct}% above the PO price",
            suppliers=[s],
            pos=[po],
            receipts=[(1, full(po))],
            invoice=replace(doc, lines=tuple(lines)),
            decision="manager_approval",
            rule="price_within_tolerance",
            approve=True,
        )

    # Overcharge (6): one line well above the PO price (3% is just over the 2% limit).
    for i, pct in enumerate(["5", "8", "12", "25", "3", "50"]):
        b = Builder(seed())
        s = ROTATION[(i * 5 + 2) % len(ROTATION)]
        po = b.po(s, b.products(s, 1 + i % 3))
        doc = b.bill(po, 1, 1 + (i + 2) % 4, messy="scan" if i == 3 else None)
        n = i % len(po.lines)
        lines = list(doc.lines)
        lines[n] = reprice(lines[n], pct)
        add(
            "price_overcharge",
            f"{s.name}: {lines[n].billed_name} billed {pct}% above the PO price",
            suppliers=[s],
            pos=[po],
            receipts=[(1, full(po))],
            invoice=replace(doc, lines=tuple(lines)),
            decision="hold",
            rule="price_over_tolerance",
        )

    # Short delivery (6): billed for more than arrived.
    for i in range(6):
        b = Builder(seed())
        s = ROTATION[(i * 3 + 4) % len(ROTATION)]
        po = b.po(s, b.products(s, 2 + i % 2))
        got: list[str | None] = full(po)
        if i in (0, 3):  # one line short by a fifth
            got[0] = qty_text(str(Decimal(got[0]) * Decimal("0.8")))
        elif i == 1:  # one line never arrived
            got[-1] = None
        elif i == 2:  # two lines short
            got = [qty_text(str(Decimal(q) / 2)) for q in got]
        receipts = [(1, got)]
        if i in (4, 5):  # two deliveries that together still fall short
            half = [qty_text(str(Decimal(q) / 2)) for q in full(po)]
            receipts = [(1, half), (1, [half[0], *([None] * (len(half) - 1))])]
        add(
            "short_delivery",
            f"{s.name}: billed for the full order, part of it not delivered",
            suppliers=[s],
            pos=[po],
            receipts=receipts,
            invoice=b.bill(po, 1, 1 + (i + 3) % 4, messy="rotate" if i == 4 else None),
            decision="hold",
            rule="quantity_exceeds_received",
        )

    # Duplicates (5): three exact re-uploads, a scanned copy, and a different-format number.
    for i in range(5):
        b = Builder(seed())
        s = ROTATION[(i * 2 + 1) % len(ROTATION)]
        po = b.po(s, b.products(s, 2))
        original = b.bill(po, 1, 1 + i % 4)
        if i < 3:
            dup, how = original, "the same file uploaded again"
        elif i == 3:
            dup, how = replace(original, messy="scan"), "a scanned copy of a paid invoice"
        else:
            dup = replace(
                original,
                invoice_no=original.invoice_no.replace("-", "/"),
                layout=1 + (original.layout % 4),
            )
            how = "the same invoice re-issued in another layout, number written with '/'"
        add(
            "duplicate",
            f"{s.name}: {how}",
            suppliers=[s],
            pos=[po],
            receipts=[(1, full(po))],
            prior=[original],
            invoice=dup,
            same_file=i < 3,
            decision="block",
            rule="duplicate",
        )

    # Missing PO number, one clear match (4): the supplier has another PO that doesn't fit.
    for i in range(4):
        b = Builder(seed())
        s = [SUPPLIERS["sharma"], SUPPLIERS["konkan"], SUPPLIERS["cleanpro"], SUPPLIERS["deccan"]][
            i
        ]
        prior: list[Doc] = []
        products = b.products(s, 2)
        if i == 0:  # the other PO is for different items
            others = [p for p in s.products if p not in products][:2]
            pos, target = [b.po(s, others), b.po(s, products)], 2
            receipts = [(1, full(pos[0])), (2, full(pos[1]))]
            why = "the other open PO is for different items"
        elif i == 1:  # the other PO has the same items, but nothing has arrived on it
            pos, target = [b.po(s, products), b.po(s, products)], 1
            receipts = [(1, full(pos[0]))]
            why = "the other PO has the same items, nothing delivered yet"
        elif i == 2:  # the other PO is too small for the invoice
            big = [max(p.qty_options, key=Decimal) for p in products]
            small = [min(p.qty_options, key=Decimal) for p in products]
            pos, target = [b.po(s, products, small), b.po(s, products, big)], 2
            receipts = [(1, small), (2, big)]
            why = "the other PO is for smaller quantities"
        else:  # the other PO was already billed in full
            pos, target = [b.po(s, products), b.po(s, products)], 2
            receipts = [(1, full(pos[0])), (2, full(pos[1]))]
            prior = [b.bill(pos[0], 1, 2)]
            why = "the other PO was billed in full last week"
        invoice = b.bill(pos[target - 1], target, 1 + i % 4, printed_po=None)
        if prior and totals(prior[0])["total"] == totals(invoice)["total"]:
            invoice = replace(invoice, invoice_date=date(2026, 10, 23))
            prior = [replace(prior[0], invoice_date=date(2026, 10, 2))]
        add(
            "missing_po_one_match",
            f"{s.name}: no PO number printed; {why}",
            suppliers=[s],
            pos=pos,
            receipts=receipts,
            prior=prior,
            invoice=invoice,
            decision="manager_approval",
            rule="matched_without_po_number",
            approve=True,
        )

    # No matching PO (4).
    b = Builder(seed())
    s = SUPPLIERS["mehta"]
    po = b.po(s, b.products(s, 2))
    add(
        "no_matching_po",
        f"{s.name}: quotes PO-7, which doesn't exist",
        suppliers=[s],
        pos=[po],
        receipts=[(1, full(po))],
        invoice=replace(b.bill(po, 1, 2, printed_po="PO-7"), po_ref=None),
        decision="needs_review",
        rule="no_matching_po",
    )
    b = Builder(seed())
    s = SUPPLIERS["konkan"]
    po = b.po(s, b.products(s, 2))
    stranger_po = b.po(STRANGER, list(STRANGER.products))
    add(
        "no_matching_po",
        f"{STRANGER.name}: not in our supplier list, quotes our PO-1",
        suppliers=[s],
        pos=[po],
        receipts=[(1, full(po))],
        invoice=replace(b.bill(stranger_po, 1, 3), po_ref=None),
        decision="needs_review",
        rule="no_matching_po",
    )
    b = Builder(seed())
    a, other = SUPPLIERS["sharma"], SUPPLIERS["deccan"]
    po_a = b.po(a, b.products(a, 2))
    po_other = b.po(other, b.products(other, 2))
    add(
        "no_matching_po",
        f"{other.name}: quotes PO-1, which is Sharma Dairy's",
        suppliers=[a, other],
        pos=[po_a],
        receipts=[(1, full(po_a))],
        invoice=replace(b.bill(po_other, 1, 4), po_ref=None),
        decision="needs_review",
        rule="no_matching_po",
    )
    b = Builder(seed())
    s = SUPPLIERS["surat"]
    ordered = b.po(s, [s.products[0], s.products[1]])
    billed_for = b.po(s, [s.products[2], s.products[3]])
    add(
        "no_matching_po",
        f"{s.name}: no PO number printed, and its only open PO is for other items",
        suppliers=[s],
        pos=[ordered],
        receipts=[(1, full(ordered))],
        invoice=replace(b.bill(billed_for, 1, 1, printed_po=None), po_ref=None),
        decision="needs_review",
        rule="no_matching_po",
    )

    # Blurry or missing field (6): three can't be read in full, three are blurry but legible.
    unreadable = [
        ("invoice_no", "scan", "no invoice number printed"),
        ("invoice_date", None, "no invoice date printed"),
        ("total", "scan", "a stain covers the grand total"),
    ]
    for i, (what, mess, why) in enumerate(unreadable):
        b = Builder(seed())
        s = ROTATION[(i * 3 + 2) % len(ROTATION)]
        po = b.po(s, b.products(s, 2))
        doc = b.bill(po, 1, [1, 3, 2][i], messy=mess)
        doc = replace(doc, smudged=(what,)) if what == "total" else replace(doc, hidden=(what,))
        add(
            "blurry_or_missing_field",
            f"{s.name}: {why}",
            suppliers=[s],
            pos=[po],
            receipts=[(1, full(po))],
            invoice=doc,
            decision="needs_review",
            rule=None,
        )
    for i, mess in enumerate(["blur", "blurnoise", "rotateblur"]):
        b = Builder(seed())
        s = ROTATION[(i * 3 + 5) % len(ROTATION)]
        po = b.po(s, b.products(s, 2 + i % 2))
        add(
            "blurry_or_missing_field",
            f"{s.name}: a blurry photo, still legible ({mess})",
            suppliers=[s],
            pos=[po],
            receipts=[(1, full(po))],
            invoice=b.bill(po, 1, 2 + i, messy=mess),
            decision="auto_approve",
            rule="all_matched",
        )

    # Varied layouts with GST (8): several GST rates per invoice, CGST + SGST and IGST.
    gst = ["sharma", "surat", "bean", "deccan", "mehta", "nilgiri", "cleanpro", "sharma"]
    for i, key in enumerate(gst):
        b = Builder(seed())
        s = SUPPLIERS[key]
        po = b.po(s, list(s.products) if i == 7 else b.products(s, 3))
        add(
            "gst_layouts",
            f"{s.name}: {len(po.lines)} lines, GST "
            + ", ".join(sorted({f"{qty_text(i.tax_rate)}%" for i in po.lines}))
            + (" as IGST" if s.inter_state else " as CGST + SGST"),
            suppliers=[s],
            pos=[po],
            receipts=[(1, full(po))],
            invoice=b.bill(po, 1, 1 + i % 4, messy={3: "scan", 6: "rotate"}.get(i)),
            decision="auto_approve",
            rule="all_matched",
        )

    # About a third of each case type is held out: tune on dev, report on both.
    seen: dict[str, int] = {}
    for case in cases:
        seen[case.kind] = seen.get(case.kind, 0) + 1
        case.split = "holdout" if seen[case.kind] % 3 == 0 else "dev"
    return cases


# ------------------------------------------------------------------------------ truth files


def _supplier_json(s: Supplier) -> dict:
    return {"key": s.key, "name": s.name, "email": s.email, "gstin": s.gstin}


def truth(case: Case, files: dict[str, str]) -> dict:
    """The case's ground truth, as saved next to its files. `files` names each document."""
    inv = case.invoice
    return {
        "id": case.id,
        "kind": case.kind,
        "split": case.split,
        "description": case.description,
        "world": {
            "suppliers": [_supplier_json(s) for s in case.suppliers],
            "purchase_orders": [
                {
                    "po_number": f"PO-{n}",
                    "supplier": po.supplier.key,
                    "items": [
                        {
                            "name": i.product.name,
                            "qty": i.qty,
                            "unit": i.product.unit,
                            "unit_price_paise": i.price_paise,
                            "tax_rate": i.tax_rate,
                        }
                        for i in po.lines
                    ],
                }
                for n, po in enumerate(case.pos, 1)
            ],
            "receipts": [
                {
                    "po_number": f"PO-{po_n}",
                    "items": [
                        {"line_id": str(n), "qty_received": q}
                        for n, q in enumerate(qtys, 1)
                        if q is not None
                    ],
                }
                for po_n, qtys in case.receipts
            ],
        },
        "prior": [
            {
                "file": files[f"prior-{n}"],
                "invoice_no": doc.invoice_no,
                "reading": reading(doc),
                "expect_status": "posted",
            }
            for n, doc in enumerate(case.prior, 1)
        ],
        "invoice": {
            "file": files["invoice"],
            "layout": inv.layout,
            "messy": inv.messy,
            "same_file_as_prior": case.same_file,
            "reading": reading(inv),
            "fields": fields(inv),
        },
        "expect": expectations(case),
    }
