"""Suppliers, purchase orders and goods receipts in Firestore (Setup guide, Section 5)."""

import re
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException
from google.cloud import firestore

from app.models.common import Page
from app.models.master_data import (
    GoodsReceipt,
    GoodsReceiptCreate,
    POLineView,
    POStatus,
    PurchaseOrder,
    PurchaseOrderCreate,
    Supplier,
    SupplierCreate,
)
from app.pipeline.money import line_amounts
from app.services.counters import next_id
from app.services.pagination import paginate

_LEGAL_SUFFIXES = {"pvt", "private", "ltd", "limited", "llp", "inc", "co", "company", "corp"}


def normalize_name(name: str) -> str:
    """'Sharma Dairy Pvt. Ltd.' -> 'sharma dairy'. Used to spot duplicate suppliers."""
    words = re.sub(r"[^a-z0-9 ]", " ", name.lower()).split()
    while words and words[-1] in _LEGAL_SUFFIXES:
        words.pop()
    return " ".join(words)


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------- suppliers


def create_supplier(db: firestore.Client, data: SupplierCreate) -> Supplier:
    normalized = normalize_name(data.name)
    if not normalized:
        raise HTTPException(status_code=422, detail="Supplier name needs letters or digits")

    @firestore.transactional
    def run(tx: firestore.Transaction) -> Supplier:
        clash = (
            db.collection("suppliers")
            .where(filter=firestore.FieldFilter("normalized_name", "==", normalized))
            .limit(1)
            .get(transaction=tx)
        )
        if clash:
            raise HTTPException(status_code=409, detail=f"Supplier '{data.name}' already exists")
        supplier = Supplier(
            supplier_id=next_id(tx, db, "suppliers", "SUP"),
            normalized_name=normalized,
            created_at=_now(),
            **data.model_dump(),
        )
        tx.set(db.collection("suppliers").document(supplier.supplier_id), supplier.model_dump())
        return supplier

    return run(db.transaction())


def list_suppliers(db: firestore.Client, limit: int, cursor: str | None) -> Page[Supplier]:
    col = db.collection("suppliers")
    docs, next_cursor = paginate(col, col, limit, cursor)
    return Page(items=[Supplier(**d.to_dict()) for d in docs], next_cursor=next_cursor)


def get_supplier(db: firestore.Client, supplier_id: str) -> Supplier | None:
    snap = db.collection("suppliers").document(supplier_id).get()
    return Supplier(**snap.to_dict()) if snap.exists else None


# ---------------------------------------------------------- purchase orders
# Firestore has no Decimal type, so quantities and tax rates are stored as strings.


def _po_from_doc(doc: dict) -> PurchaseOrder:
    received: dict[str, str] = doc.get("received", {})
    billed: dict[str, str] = doc.get("billed", {})
    lines, subtotal, tax = [], 0, 0
    for item in doc["items"]:
        qty, rate = Decimal(item["qty"]), Decimal(item["tax_rate"])
        line_total, line_tax = line_amounts(qty, item["unit_price_paise"], rate)
        subtotal += line_total
        tax += line_tax
        lines.append(
            POLineView(
                **{**item, "qty": qty, "tax_rate": rate},
                qty_received=Decimal(received.get(item["line_id"], "0")),
                qty_billed=Decimal(billed.get(item["line_id"], "0")),
                line_total_paise=line_total,
                tax_paise=line_tax,
            )
        )
    return PurchaseOrder(
        po_number=doc["po_number"],
        supplier_id=doc["supplier_id"],
        supplier_name=doc["supplier_name"],
        status=doc["status"],
        items=lines,
        subtotal_paise=subtotal,
        tax_paise=tax,
        total_paise=subtotal + tax,
        created_by=doc["created_by"],
        created_at=doc["created_at"],
    )


def create_purchase_order(
    db: firestore.Client, data: PurchaseOrderCreate, created_by: str
) -> PurchaseOrder:
    supplier = get_supplier(db, data.supplier_id)
    if supplier is None:
        raise HTTPException(status_code=422, detail="Unknown supplier")

    @firestore.transactional
    def run(tx: firestore.Transaction) -> dict:
        po_number = next_id(tx, db, "purchase_orders", "PO")
        doc = {
            "po_number": po_number,
            "supplier_id": supplier.supplier_id,
            "supplier_name": supplier.name,
            "status": POStatus.open.value,
            "items": [
                {
                    "line_id": str(i),
                    "name": item.name,
                    "qty": str(item.qty),
                    "unit": item.unit,
                    "unit_price_paise": item.unit_price_paise,
                    "tax_rate": str(item.tax_rate),
                }
                for i, item in enumerate(data.items, start=1)
            ],
            "received": {},
            "created_by": created_by,
            "created_at": _now(),
        }
        tx.set(db.collection("purchase_orders").document(po_number), doc)
        return doc

    return _po_from_doc(run(db.transaction()))


def list_purchase_orders(
    db: firestore.Client, limit: int, cursor: str | None, status: POStatus | None = None
) -> Page[PurchaseOrder]:
    col = db.collection("purchase_orders")
    query = col.where(filter=firestore.FieldFilter("status", "==", status.value)) if status else col
    docs, next_cursor = paginate(query, col, limit, cursor)
    return Page(items=[_po_from_doc(d.to_dict()) for d in docs], next_cursor=next_cursor)


def get_purchase_order(db: firestore.Client, po_number: str) -> PurchaseOrder | None:
    snap = db.collection("purchase_orders").document(po_number).get()
    return _po_from_doc(snap.to_dict()) if snap.exists else None


# ----------------------------------------------------------- goods receipts


def create_goods_receipt(
    db: firestore.Client, data: GoodsReceiptCreate, received_by: str
) -> GoodsReceipt:
    """Record a delivery. The PO's running received totals are updated in the same transaction,
    so two deliveries recorded at once can never push a line past its ordered quantity."""
    po_ref = db.collection("purchase_orders").document(data.po_number)

    @firestore.transactional
    def run(tx: firestore.Transaction) -> GoodsReceipt:
        snap = po_ref.get(transaction=tx)
        if not snap.exists:
            raise HTTPException(status_code=404, detail=f"{data.po_number} not found")
        po = snap.to_dict()
        if po["status"] == POStatus.closed.value:
            raise HTTPException(status_code=409, detail=f"{data.po_number} is closed")

        ordered = {item["line_id"]: (item["name"], Decimal(item["qty"])) for item in po["items"]}
        received = {k: Decimal(v) for k, v in po.get("received", {}).items()}
        seen: set[str] = set()
        for item in data.items:
            if item.line_id not in ordered:
                raise HTTPException(status_code=422, detail=f"Line {item.line_id} is not on the PO")
            if item.line_id in seen:
                raise HTTPException(status_code=422, detail=f"Line {item.line_id} appears twice")
            seen.add(item.line_id)
            name, qty_ordered = ordered[item.line_id]
            new_total = received.get(item.line_id, Decimal("0")) + item.qty_received
            if new_total > qty_ordered:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"'{name}': receiving {item.qty_received} would bring the total to "
                        f"{new_total}, more than the {qty_ordered} ordered"
                    ),
                )
            received[item.line_id] = new_total

        receipt = GoodsReceipt(
            gr_id=next_id(tx, db, "goods_receipts", "GR"),
            po_number=data.po_number,
            items=data.items,
            received_by=received_by,
            received_on=data.received_on,
            notes=data.notes,
            created_at=_now(),
        )
        tx.set(
            db.collection("goods_receipts").document(receipt.gr_id),
            {
                **receipt.model_dump(exclude={"items", "received_on"}),
                "items": [
                    {"line_id": i.line_id, "qty_received": str(i.qty_received)} for i in data.items
                ],
                "received_on": data.received_on.isoformat(),
            },
        )
        tx.update(po_ref, {"received": {k: str(v) for k, v in received.items()}})
        return receipt

    return run(db.transaction())


def list_goods_receipts(
    db: firestore.Client, limit: int, cursor: str | None, po_number: str | None = None
) -> Page[GoodsReceipt]:
    col = db.collection("goods_receipts")
    query = (
        col.where(filter=firestore.FieldFilter("po_number", "==", po_number)) if po_number else col
    )
    docs, next_cursor = paginate(query, col, limit, cursor)
    return Page(items=[GoodsReceipt(**d.to_dict()) for d in docs], next_cursor=next_cursor)
