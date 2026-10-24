"""Master data the test set is built from: the buyer, suppliers and what each one sells.

The buyer is in Maharashtra (GSTIN state code 27), so suppliers from 27 charge CGST + SGST and
the others IGST. Prices are paise; GST rates are percent.
"""

from dataclasses import dataclass

BUYER = {
    "name": "Brew & Bake Cafes Pvt Ltd",
    "gstin": "27AAFCB4410C1Z2",
    "address": ["Unit 4, Koregaon Park Annexe", "Pune, Maharashtra 411001"],
}
BUYER_STATE = "27"


@dataclass(frozen=True)
class Product:
    name: str  # as on our PO
    unit: str
    price_paise: int
    tax_rate: str
    qty_options: tuple[str, ...]
    billed_as: str | None = None  # how the supplier names it on invoices, when different


@dataclass(frozen=True)
class Supplier:
    key: str
    name: str  # as in our supplier list
    gstin: str
    email: str
    address: tuple[str, str]
    invoice_no: str  # format with {n}
    products: tuple[Product, ...]
    printed_name: str | None = None  # how the supplier writes its own name, when different

    @property
    def inter_state(self) -> bool:
        return not self.gstin.startswith(BUYER_STATE)


def P(name, unit, price, tax, qtys, billed_as=None) -> Product:  # noqa: N802 (short table rows)
    return Product(name, unit, price, tax, tuple(qtys.split()), billed_as)


SUPPLIERS = {
    s.key: s
    for s in [
        Supplier(
            "sharma",
            "Sharma Dairy Pvt Ltd",
            "27AAPCS1234F1Z5",
            "accounts@sharmadairy.example.in",
            ("Plot 18, MIDC Bhosari", "Pune, Maharashtra 411026"),
            "SD-2026-{n:04d}",
            (
                P("Full cream milk", "L", 6000, "0", "40 50 60 80", "Milk (full cream)"),
                P("Paneer", "kg", 40000, "5", "2.5 4 5 8"),
                P("White butter", "kg", 52000, "12", "2 3 5", "Butter - white"),
                P("Fresh curd", "kg", 9000, "5", "10 15 20", "Curd"),
                P("Cow ghee", "L", 65000, "12", "2 4 5"),
            ),
            printed_name="Sharma Dairy Pvt. Ltd.",
        ),
        Supplier(
            "konkan",
            "Konkan Fresh Produce LLP",
            "27AAKFK5678M1Z2",
            "billing@konkanfresh.example.in",
            ("Gala 7, APMC Market Yard", "Navi Mumbai, Maharashtra 400703"),
            "KFP/26-27/{n}",
            (
                P("Tomatoes", "kg", 3200, "0", "20 25 40"),
                P("Onions", "kg", 2800, "0", "25 30 50"),
                P("Potatoes", "kg", 2400, "0", "20 30 40"),
                P("Coriander", "bunch", 1500, "0", "20 30 50", "Coriander bunches"),
                P("Green chillies", "kg", 8000, "0", "2 3 5"),
            ),
        ),
        Supplier(
            "bean",
            "Bengaluru Bean Roasters Pvt Ltd",
            "29AABCB4321K1Z8",
            "invoices@bbroasters.example.in",
            ("No. 42, 2nd Cross, Indiranagar", "Bengaluru, Karnataka 560038"),
            "BBR-INV-{n:05d}",
            (
                P(
                    "Arabica coffee beans",
                    "kg",
                    145000,
                    "5",
                    "5 8 10",
                    "Arabica beans, medium roast",
                ),
                P("Robusta coffee beans", "kg", 98000, "5", "4 5 10", "Robusta beans"),
                P("Cold brew concentrate", "L", 60000, "12", "5 10"),
            ),
            printed_name="Bengaluru Bean Roasters Private Limited",
        ),
        Supplier(
            "surat",
            "Surat Packaging Industries",
            "24AAGFS8765P1Z3",
            "sales@suratpack.example.in",
            ("Survey 211, Sachin GIDC", "Surat, Gujarat 394230"),
            "SPI/2026/{n}",
            (
                P("Paper cups 250 ml", "pcs", 240, "18", "1000 2000 3000"),
                P("Cup lids", "pcs", 110, "18", "1000 2000 3000"),
                P("Kraft paper bags", "pcs", 450, "18", "500 1000"),
                P("Corrugated boxes", "pcs", 1800, "12", "100 200"),
            ),
        ),
        Supplier(
            "cleanpro",
            "CleanPro Hygiene Solutions",
            "27AAECC2468H1Z6",
            "ar@cleanpro.example.in",
            ("Office 3B, Lodha Supremus", "Thane, Maharashtra 400604"),
            "CP-{n}",
            (
                P("Floor cleaner", "L", 10800, "18", "10 20 25"),
                P("Liquid hand wash", "L", 18000, "18", "5 10"),
                P("Garbage bags", "pack", 9500, "18", "10 20 30"),
                P("Hand sanitizer", "L", 22000, "18", "5 10"),
            ),
        ),
        Supplier(
            "deccan",
            "Deccan Bakers & Confectioners",
            "27AAQFD1357B1Z9",
            "orders@deccanbakers.example.in",
            ("12 Fergusson College Road", "Pune, Maharashtra 411004"),
            "DBC {n}",
            (
                P("Butter croissant", "pcs", 3500, "18", "50 100 120", "Croissant (butter)"),
                P("Sourdough loaf", "pcs", 12000, "5", "20 30 40"),
                P("Blueberry muffin", "pcs", 4000, "18", "50 60 100"),
            ),
        ),
        Supplier(
            "nilgiri",
            "Nilgiri Tea Estates Co",
            "33AADCN9753T1Z1",
            "accounts@nilgiritea.example.in",
            ("Estate Road, Kotagiri", "Nilgiris, Tamil Nadu 643217"),
            "NTE/INV/{n}",
            (
                P("Assam CTC tea", "kg", 52000, "5", "5 10 15", "CTC tea leaves"),
                P("Masala chai premix", "kg", 38000, "18", "5 10"),
            ),
        ),
        Supplier(
            "mehta",
            "Mehta Sugar & Syrups",
            "24AAJPM2580Q1Z4",
            "billing@mehtasyrups.example.in",
            ("23 Ring Road", "Ahmedabad, Gujarat 380015"),
            "MSS-26-{n:04d}",
            (
                P("Sugar", "kg", 4600, "5", "50 100"),
                P("Vanilla syrup 750 ml", "bottle", 45000, "18", "6 12"),
                P("Caramel syrup 750 ml", "bottle", 45000, "18", "6 12"),
            ),
        ),
    ]
}

# Not in our supplier list: for the "unknown supplier" case.
STRANGER = Supplier(
    "stranger",
    "Ratnagiri Mango Traders",
    "27AAHFR3141J1Z7",
    "hello@ratnagirimango.example.in",
    ("Shop 9, Maruti Mandir Road", "Ratnagiri, Maharashtra 415612"),
    "RMT-{n}",
    (P("Alphonso mango pulp", "kg", 32000, "12", "10 20"),),
)


def supplier(key: str) -> Supplier:
    return STRANGER if key == STRANGER.key else SUPPLIERS[key]
