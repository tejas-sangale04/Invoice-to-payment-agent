"""Draws invoices as PDFs in four layouts (reportlab), and makes scan-like copies (Pillow).

Every value on the page comes from scenarios.printed(), the same strings the ground truth uses.
"""

import io
import random
import zlib
from collections.abc import Callable

import pypdfium2 as pdfium
from PIL import Image, ImageChops, ImageFilter, ImageOps
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from catalog import BUYER


class Page:
    """A reportlab canvas that remembers where named fields were drawn, so they can be
    smudged afterwards."""

    def __init__(self, size: tuple[float, float]) -> None:
        self.buf = io.BytesIO()
        self.c = Canvas(self.buf, pagesize=size, invariant=1)
        self.width, self.height = size
        self.boxes: dict[str, tuple[float, float, float, float]] = {}

    def text(
        self,
        x: float,
        y: float,
        s: str,
        font: str = "Helvetica",
        size: float = 9,
        align: str = "left",
        name: str | None = None,
        color=colors.black,
    ) -> None:
        width = stringWidth(s, font, size)
        left = {"left": x, "right": x - width, "center": x - width / 2}[align]
        self.c.setFillColor(color)
        self.c.setFont(font, size)
        self.c.drawString(left, y, s)
        if name:
            self.boxes[name] = (left, y - size * 0.25, width, size * 1.2)

    def rule(self, x1: float, y: float, x2: float, width: float = 0.6, dash=None) -> None:
        self.c.setLineWidth(width)
        self.c.setDash(*(dash or []))
        self.c.line(x1, y, x2, y)
        self.c.setDash()

    def smudge(self, name: str, seed: int) -> None:
        """A coffee stain over a field: drawn in the PDF, so the value can't be read."""
        x, y, w, h = self.boxes[name]
        rng = random.Random(seed)
        self.c.setFillColor(colors.Color(0.42, 0.27, 0.13, alpha=0.93))
        for _ in range(9):
            dx, dy = rng.uniform(-0.15, 0.85) * w, rng.uniform(-0.4, 0.6) * h
            self.c.ellipse(x + dx - 6, y + dy - 5, x + dx + w * 0.4 + 6, y + dy + h + 5, 0, 1)
        self.c.setFillColor(colors.Color(0.55, 0.38, 0.2, alpha=0.5))
        self.c.circle(x + w / 2, y + h / 2, w * 0.6, 0, 1)

    def finish(self) -> bytes:
        self.c.showPage()
        self.c.save()
        return self.buf.getvalue()


def hsn(name: str) -> str:
    return str(4000 + zlib.crc32(name.encode()) % 5000)


def words(paise: int) -> str:
    """Rupees in Indian-English words, e.g. 'Four Thousand Fifty Rupees Only'."""
    ones = (
        "Zero One Two Three Four Five Six Seven Eight Nine Ten Eleven Twelve Thirteen Fourteen "
        "Fifteen Sixteen Seventeen Eighteen Nineteen"
    ).split()
    tens = "Zero Ten Twenty Thirty Forty Fifty Sixty Seventy Eighty Ninety".split()

    def below_1000(n: int) -> list[str]:
        out = []
        if n >= 100:
            out += [ones[n // 100], "Hundred"]
            n %= 100
        if n >= 20:
            out.append(tens[n // 10])
            n %= 10
        if n:
            out.append(ones[n])
        return out

    rupees, p = divmod(paise, 100)
    parts = []
    for unit, size in (("Crore", 10**7), ("Lakh", 10**5), ("Thousand", 1000)):
        if rupees >= size:
            parts += [*below_1000(rupees // size), unit]
            rupees %= size
    parts += below_1000(rupees)
    text = " ".join(parts or ["Zero"]) + " Rupees"
    if p:
        text += " and " + " ".join(below_1000(p)) + " Paise"
    return text + " Only"


# ------------------------------------------------------------------------------ layout 1


def classic(p: dict, total_paise: int) -> Page:
    """Plain grid table, totals box bottom right."""
    pg = Page(A4)
    w, h = A4
    pg.text(40, h - 60, p["supplier_name"], "Helvetica-Bold", 15, name="supplier_name")
    for n, line in enumerate(p["address"]):
        pg.text(40, h - 76 - n * 12, line)
    pg.text(40, h - 104, f"GSTIN: {p['supplier_gstin']}", name="supplier_gstin")
    pg.text(40, h - 116, p["email"], color=colors.HexColor("#444444"))

    pg.text(w - 40, h - 60, "TAX INVOICE", "Helvetica-Bold", 17, "right")
    y = h - 82
    meta = [
        ("Invoice No:", p["invoice_no"], "invoice_no"),
        ("Invoice Date:", p["invoice_date"], "invoice_date"),
        ("PO No:", p["po_number"], "po_number"),
    ]
    for label, value, name in meta:
        if value:
            pg.text(w - 200, y, label, "Helvetica-Bold")
            pg.text(w - 40, y, value, align="right", name=name)
            y -= 13

    pg.rule(40, h - 132, w - 40, 1)
    pg.text(40, h - 150, "Bill to:", "Helvetica-Bold")
    pg.text(40, h - 163, BUYER["name"])
    for n, line in enumerate(BUYER["address"]):
        pg.text(40, h - 175 - n * 12, line)
    pg.text(40, h - 199, f"GSTIN: {BUYER['gstin']}")

    cols = [40, 62, 285, 335, 375, 445, 480, w - 40]
    heads = ["#", "Description", "Qty", "Unit", "Rate (Rs)", "GST", "Amount (Rs)"]
    top = h - 230
    row = 18
    c = pg.c
    c.setFillColor(colors.HexColor("#EEEEEE"))
    c.rect(cols[0], top - row, cols[-1] - cols[0], row, 0, 1)
    rows = len(p["items"]) + 1
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.6)
    c.grid(cols, [top - row * r for r in range(rows + 1)])
    for i, head in enumerate(heads):
        pg.text(cols[i] + 4, top - 13, head, "Helvetica-Bold", 8.5)
    for r, item in enumerate(p["items"], 1):
        y = top - row * r - 13
        pg.text(cols[0] + 4, y, str(r))
        pg.text(cols[1] + 4, y, item["name"])
        pg.text(cols[3] - 4, y, item["qty"], align="right")
        pg.text(cols[3] + 4, y, item["unit"])
        pg.text(cols[5] - 4, y, item["unit_price"], align="right")
        pg.text(cols[6] - 4, y, item["tax_rate"], align="right")
        pg.text(cols[7] - 4, y, item["amount"], align="right")

    y = top - row * rows - 24
    tax_rows = (
        [("IGST", p["igst"])] if p["inter_state"] else [("CGST", p["cgst"]), ("SGST", p["sgst"])]
    )
    for label, value in [("Subtotal", p["subtotal"]), *tax_rows]:
        pg.text(w - 170, y, label)
        pg.text(w - 44, y, value, align="right")
        y -= 14
    pg.rule(w - 175, y + 9, w - 40)
    pg.text(w - 170, y - 4, "Total (Rs)", "Helvetica-Bold", 11)
    pg.text(w - 44, y - 4, p["total"], "Helvetica-Bold", 11, "right", name="total")

    pg.text(40, 120, "Bank: HDFC Bank, Current A/c 50200012345678, IFSC HDFC0000123", size=8)
    pg.text(40, 108, "Payment due within 30 days of the invoice date.", size=8)
    pg.text(w - 40, 80, f"For {p['supplier_name']}", align="right", size=8)
    pg.text(w - 40, 50, "Authorised Signatory", align="right", size=8)
    return pg


# ------------------------------------------------------------------------------ layout 2


def modern(p: dict, total_paise: int) -> Page:
    """Coloured banner, meta in boxes, striped table without grid lines."""
    pg = Page(A4)
    w, h = A4
    c = pg.c
    teal = colors.HexColor("#0F4C5C")
    c.setFillColor(teal)
    c.rect(0, h - 110, w, 110, 0, 1)
    pg.text(40, h - 55, p["supplier_name"], "Helvetica-Bold", 18, name="supplier_name",
            color=colors.white)  # fmt: skip
    pg.text(40, h - 74, " | ".join(p["address"]), size=8.5, color=colors.white)
    pg.text(40, h - 88, f"GSTIN {p['supplier_gstin']}  ·  {p['email']}", size=8.5,
            name="supplier_gstin", color=colors.white)  # fmt: skip
    pg.text(w - 40, h - 60, "INVOICE", "Helvetica-Bold", 24, "right", color=colors.white)

    boxes = [
        ("INVOICE NUMBER", p["invoice_no"], "invoice_no"),
        ("INVOICE DATE", p["invoice_date"], "invoice_date"),
        ("YOUR ORDER REF.", p["po_number"], "po_number"),
    ]
    x = 40
    for label, value, name in boxes:
        if not value:
            continue
        c.setStrokeColor(colors.HexColor("#B8C7CC"))
        c.roundRect(x, h - 170, 160, 42, 4, 1, 0)
        pg.text(x + 10, h - 142, label, "Helvetica-Bold", 7, color=colors.HexColor("#5B7178"))
        pg.text(x + 10, h - 160, value, "Helvetica-Bold", 11, name=name)
        x += 172

    pg.text(40, h - 198, "BILLED TO", "Helvetica-Bold", 7, color=colors.HexColor("#5B7178"))
    pg.text(40, h - 212, BUYER["name"], "Helvetica-Bold", 10)
    pg.text(40, h - 225, ", ".join(BUYER["address"]), size=8.5)
    pg.text(40, h - 237, f"GSTIN {BUYER['gstin']}", size=8.5)

    top = h - 270
    c.setFillColor(teal)
    c.rect(40, top - 4, w - 80, 20, 0, 1)
    head = [(48, "Item", "left"), (340, "Qty", "right"), (430, "Unit price", "right"),
            (480, "GST %", "right"), (w - 48, "Amount", "right")]  # fmt: skip
    for x, label, align in head:
        pg.text(x, top + 2, label, "Helvetica-Bold", 8.5, align, color=colors.white)
    y = top - 22
    for n, item in enumerate(p["items"]):
        if n % 2:
            c.setFillColor(colors.HexColor("#EEF3F4"))
            c.rect(40, y - 6, w - 80, 20, 0, 1)
        pg.text(48, y, item["name"])
        pg.text(340, y, f"{item['qty']} {item['unit']}", align="right")
        pg.text(430, y, item["unit_price"], align="right")
        pg.text(480, y, item["tax_rate"], align="right")
        pg.text(w - 48, y, item["amount"], align="right")
        y -= 20

    y -= 16
    tax_rows = (
        [("IGST", p["igst"])] if p["inter_state"] else [("CGST", p["cgst"]), ("SGST", p["sgst"])]
    )
    for label, value in [("Taxable value", p["subtotal"]), *tax_rows]:
        pg.text(w - 220, y, label, color=colors.HexColor("#333333"))
        pg.text(w - 48, y, f"Rs. {value}", align="right")
        y -= 15
    c.setFillColor(colors.HexColor("#EEF3F4"))
    c.rect(w - 230, y - 12, 190, 26, 0, 1)
    pg.text(w - 220, y - 3, "Amount due", "Helvetica-Bold", 11, color=teal)
    pg.text(w - 48, y - 3, f"Rs. {p['total']}", "Helvetica-Bold", 12, "right", name="total")

    pg.text(40, 90, "Thank you for your business.", "Helvetica-Oblique", 9)
    pg.text(40, 76, "Please pay by NEFT to ICICI Bank A/c 000405123456, IFSC ICIC0000004.", size=8)
    return pg


# ------------------------------------------------------------------------------ layout 3


def thermal(p: dict, total_paise: int) -> Page:
    """Narrow, monospaced, like a counter bill."""
    w = 230
    h = 330 + 26 * len(p["items"])
    pg = Page((w, h))
    mono, bold = "Courier", "Courier-Bold"
    y = h - 24
    for s, font, name in [(p["supplier_name"], bold, "supplier_name")] + [
        (line, mono, None) for line in p["address"]
    ]:
        pg.text(w / 2, y, s, font, 7.5, "center", name=name)
        y -= 10
    pg.text(w / 2, y, f"GSTIN:{p['supplier_gstin']}", mono, 7.5, "center", name="supplier_gstin")
    y -= 14
    pg.rule(10, y, w - 10, 0.5, [2, 2])
    y -= 14
    pg.text(w / 2, y, "TAX INVOICE", bold, 9, "center")
    y -= 14
    for label, value, name in [
        ("Bill No", p["invoice_no"], "invoice_no"),
        ("Date", p["invoice_date"], "invoice_date"),
        ("PO Ref", p["po_number"], "po_number"),
    ]:
        if value:
            pg.text(12, y, f"{label:<8}:", mono, 7.5)
            pg.text(62, y, value, mono, 7.5, name=name)
            y -= 10
    pg.text(12, y, f"To: {BUYER['name']}", mono, 7)
    y -= 12
    pg.rule(10, y, w - 10, 0.5, [2, 2])
    y -= 11
    pg.text(12, y, "Item / Qty x Rate        GST     Amt", mono, 7)
    y -= 6
    pg.rule(10, y, w - 10, 0.5, [2, 2])
    y -= 11
    for item in p["items"]:
        pg.text(12, y, item["name"][:36], mono, 7.5)
        y -= 10
        pg.text(18, y, f"{item['qty']} {item['unit']} x {item['unit_price']}", mono, 7.5)
        pg.text(170, y, f"{item['tax_rate']}%", mono, 7.5, "right")
        pg.text(w - 12, y, item["amount"], mono, 7.5, "right")
        y -= 16
    pg.rule(10, y + 6, w - 10, 0.5, [2, 2])
    y -= 8
    tax_rows = (
        [("IGST", p["igst"])] if p["inter_state"] else [("CGST", p["cgst"]), ("SGST", p["sgst"])]
    )
    for label, value in [("Taxable", p["subtotal"]), *tax_rows]:
        pg.text(12, y, label, mono, 7.5)
        pg.text(w - 12, y, value, mono, 7.5, "right")
        y -= 10
    pg.rule(10, y + 4, w - 10, 0.5)
    y -= 8
    pg.text(12, y, "NET PAYABLE", bold, 8.5)
    pg.text(w - 12, y, p["total"], bold, 8.5, "right", name="total")
    y -= 22
    pg.text(w / 2, y, "*** Thank you ***", mono, 7.5, "center")
    return pg


# ------------------------------------------------------------------------------ layout 4


def formal(p: dict, total_paise: int) -> Page:
    """Letterhead style, as accounting software prints it: HSN codes, 'Buyer's Order No.',
    the amount in words."""
    pg = Page(A4)
    w, h = A4
    c = pg.c
    serif, serif_b = "Times-Roman", "Times-Bold"
    pg.text(w / 2, h - 50, p["supplier_name"].upper(), serif_b, 17, "center", name="supplier_name")
    pg.text(w / 2, h - 66, ", ".join(p["address"]), serif, 9.5, "center")
    pg.text(w / 2, h - 79, f"GSTIN/UIN: {p['supplier_gstin']}   E-mail: {p['email']}", serif, 9,
            "center", name="supplier_gstin")  # fmt: skip
    pg.rule(36, h - 88, w - 36, 1.4)
    pg.rule(36, h - 91, w - 36, 0.5)
    pg.text(w / 2, h - 110, "TAX INVOICE", serif_b, 13, "center")

    c.setLineWidth(0.6)
    c.rect(36, h - 200, w - 72, 80)
    c.line(w / 2, h - 200, w / 2, h - 120)
    pg.text(42, h - 134, "Buyer (Bill to)", serif, 8.5)
    pg.text(42, h - 148, BUYER["name"], serif_b, 10)
    for n, line in enumerate(BUYER["address"]):
        pg.text(42, h - 161 - n * 11, line, serif, 9)
    pg.text(42, h - 190, f"GSTIN/UIN: {BUYER['gstin']}", serif, 9)
    y = h - 134
    for label, value, name in [
        ("Invoice No.", p["invoice_no"], "invoice_no"),
        ("Dated", p["invoice_date"], "invoice_date"),
        ("Buyer's Order No.", p["po_number"], "po_number"),
        ("Terms of Payment", "30 days", None),
    ]:
        if value:
            pg.text(w / 2 + 8, y, label, serif, 9)
            pg.text(w / 2 + 110, y, value, serif_b, 10, name=name)
            y -= 16

    cols = [36, 60, 255, 305, 360, 425, 455, 500, w - 36]
    heads = ["Sl", "Description of Goods", "HSN/SAC", "Quantity", "Rate", "per", "GST %",
             "Amount"]  # fmt: skip
    top = h - 214
    row = 17
    rows = len(p["items"]) + 1
    c.grid(cols, [top, top - row, top - row * rows])
    for x in cols:
        c.line(x, top - row * rows, x, top - row * rows - row * 4)
    for i, head in enumerate(heads):
        pg.text((cols[i] + cols[i + 1]) / 2, top - 12, head, serif_b, 8.5, "center")
    for r, item in enumerate(p["items"], 1):
        y = top - row * r - 12
        pg.text(cols[0] + 6, y, str(r), serif, 9)
        pg.text(cols[1] + 4, y, item["name"], serif_b, 9)
        pg.text(cols[2] + 6, y, hsn(item["name"]), serif, 9)
        pg.text(cols[4] - 4, y, f"{item['qty']} {item['unit']}", serif, 9, "right")
        pg.text(cols[5] - 4, y, item["unit_price"], serif, 9, "right")
        pg.text(cols[5] + 4, y, item["unit"], serif, 9)
        pg.text(cols[7] - 4, y, item["tax_rate"], serif, 9, "right")
        pg.text(cols[8] - 4, y, item["amount"], serif, 9, "right")
    y = top - row * rows - 12
    tax_rows = (
        [("IGST", p["igst"])] if p["inter_state"] else [("CGST", p["cgst"]), ("SGST", p["sgst"])]
    )
    pg.text(cols[2] - 4, y, "Taxable Value", serif, 9, "right")
    pg.text(cols[8] - 4, y, p["subtotal"], serif, 9, "right")
    for label, value in tax_rows:
        y -= row
        pg.text(cols[2] - 4, y, f"Output {label}", serif_b, 9, "right")
        pg.text(cols[8] - 4, y, value, serif, 9, "right")
    bottom = top - row * rows - row * 4
    c.line(36, bottom, w - 36, bottom)
    c.line(36, bottom - 20, w - 36, bottom - 20)
    c.line(36, bottom, 36, bottom - 20)
    c.line(w - 36, bottom, w - 36, bottom - 20)
    pg.text(cols[2] - 4, bottom - 14, "Total", serif_b, 10, "right")
    pg.text(cols[8] - 4, bottom - 14, f"Rs. {p['total']}", serif_b, 10, "right", name="total")
    pg.text(36, bottom - 36, "Amount Chargeable (in words)", serif, 8.5)
    pg.text(36, bottom - 50, f"INR {words(total_paise)}", serif_b, 9.5)
    pg.text(36, bottom - 80, "Declaration: We declare that this invoice shows the actual price of",
            serif, 8)  # fmt: skip
    pg.text(36, bottom - 90, "the goods described and that all particulars are true and correct.",
            serif, 8)  # fmt: skip
    pg.text(w - 36, bottom - 80, f"for {p['supplier_name']}", serif_b, 9, "right")
    pg.text(w - 36, bottom - 120, "Authorised Signatory", serif, 8.5, "right")
    pg.text(w / 2, 40, "This is a Computer Generated Invoice", serif, 8, "center")
    return pg


LAYOUTS: dict[int, Callable[[dict, int], Page]] = {1: classic, 2: modern, 3: thermal, 4: formal}


def render_pdf(p: dict, layout: int, smudged: tuple[str, ...] = (), seed: int = 0) -> bytes:
    page = LAYOUTS[layout](p, p["total_paise"])
    for name in smudged:
        page.smudge(name, seed)
    return page.finish()


# ------------------------------------------------------------------------------ scan-like copies


def _noise(img: Image.Image, amount: float, rng: random.Random) -> Image.Image:
    grey = Image.frombytes("L", img.size, rng.randbytes(img.size[0] * img.size[1]))
    grey = grey.point(lambda v: int(128 + (v - 128) * amount))
    return ImageChops.add(img, grey, 1.0, -128)


def _rotate(img: Image.Image, degrees: float) -> Image.Image:
    return img.rotate(degrees, Image.Resampling.BICUBIC, expand=True, fillcolor=255)


def _paper(img: Image.Image) -> Image.Image:
    return ImageOps.colorize(img, black="#1c1c1c", white="#f3eee2")


# kind -> (dpi, transform, JPEG quality)
MESSY: dict[str, tuple[int, Callable[[Image.Image, random.Random], Image.Image], int]] = {
    "scan": (130, lambda im, r: _paper(_noise(_rotate(im, r.uniform(-1.5, 1.5)), 0.18, r)), 62),
    "rotate": (130, lambda im, r: _rotate(im, r.choice([-1, 1]) * r.uniform(2.5, 4)), 80),
    "lowres": (72, lambda im, r: im, 70),
    "noise": (120, lambda im, r: _noise(im, 0.3, r), 75),
    "blur": (130, lambda im, r: im.filter(ImageFilter.GaussianBlur(1.3)), 75),
    "blurnoise": (120, lambda im, r: _noise(im.filter(ImageFilter.GaussianBlur(1.1)), 0.2, r), 70),
    "rotateblur": (
        130,
        lambda im, r: _rotate(im, r.uniform(1.5, 3)).filter(ImageFilter.GaussianBlur(1.2)),
        75,
    ),
}


def make_messy(pdf: bytes, kind: str, seed: int) -> bytes:
    """A JPEG of the first page that looks scanned, photographed or blurry."""
    dpi, transform, quality = MESSY[kind]
    page = pdfium.PdfDocument(pdf)[0]
    img = page.render(scale=dpi / 72).to_pil().convert("L")
    img = transform(img, random.Random(seed))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=quality, optimize=True)
    return out.getvalue()
