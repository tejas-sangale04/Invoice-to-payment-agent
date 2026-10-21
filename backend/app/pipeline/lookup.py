"""Firestore lookups for matching: duplicates, the supplier and the purchase order.

Duplicate rules (Setup guide, Section 7, step 1):
- the same file, or the same supplier + invoice number, as an earlier invoice -> block;
- the same supplier and total within 7 days under a different number -> possible duplicate.
Only "live" invoices count: one that was rejected, or was itself blocked as a duplicate, is
not an original. "Earlier" is by upload time, so of two copies the first one survives.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from google.cloud import firestore

from app.models.invoice import Extracted
from app.models.invoice import InvoiceStatus as S
from app.services.master_data import normalize_name

NOT_ORIGINALS = {S.blocked_duplicate.value, S.rejected.value}
POSSIBLE_DUPLICATE_DAYS = 7


def normalize_invoice_no(raw: str | None) -> str | None:
    """'SD/2026/0457' and 'sd-2026-0457' are the same invoice number."""
    key = re.sub(r"[^A-Z0-9]", "", (raw or "").upper())
    return key or None


def _id_number(invoice_id: str) -> int:
    digits = re.sub(r"\D", "", invoice_id)
    return int(digits) if digits else 0


def _sort_key(doc: dict) -> tuple[datetime, int]:
    return doc["created_at"], _id_number(doc["invoice_id"])


def _earlier_live(db: firestore.Client, me: dict, field: str, value: str) -> dict | None:
    """The earliest live invoice, uploaded before `me`, whose `field` equals `value`."""
    docs = (
        db.collection("invoices")
        .where(filter=firestore.FieldFilter(field, "==", value))
        .limit(50)
        .stream()
    )
    earlier = [
        d
        for d in (doc.to_dict() for doc in docs)
        if d["invoice_id"] != me["invoice_id"]
        and d["status"] not in NOT_ORIGINALS
        and _sort_key(d) < _sort_key(me)
    ]
    return min(earlier, key=_sort_key) if earlier else None


def duplicate_file(db: firestore.Client, me: dict) -> dict | None:
    return _earlier_live(db, me, "file_hash", me["file_hash"])


def duplicate_number(db: firestore.Client, me: dict, duplicate_key: str) -> dict | None:
    return _earlier_live(db, me, "duplicate_key", duplicate_key)


def possible_duplicate(
    db: firestore.Client, me: dict, supplier_key: str, total_paise: int, invoice_date: date
) -> dict | None:
    """Another live invoice from the same supplier for the same total, dated within 7 days."""
    docs = (
        db.collection("invoices")
        .where(filter=firestore.FieldFilter("supplier_key", "==", supplier_key))
        .limit(200)
        .stream()
    )
    for d in (doc.to_dict() for doc in docs):
        other = Extracted(**d["extracted"]) if d.get("extracted") else None
        if (
            d["invoice_id"] != me["invoice_id"]
            and d["status"] not in NOT_ORIGINALS
            and other is not None
            and other.total_paise == total_paise
            and other.invoice_date is not None
            and abs((other.invoice_date - invoice_date).days) <= POSSIBLE_DUPLICATE_DAYS
        ):
            return d
    return None


@dataclass
class SupplierMatch:
    supplier: dict | None
    problem: str | None = None  # why the supplier couldn't be confirmed

    @property
    def key(self) -> str | None:
        return self.supplier["supplier_id"] if self.supplier else None


def resolve_supplier(db: firestore.Client, extracted: Extracted) -> SupplierMatch:
    """Find the supplier by GSTIN first, then by name ('Sharma Dairy Pvt. Ltd.' matches
    'Sharma Dairy'). A name match with a different GSTIN on file is not trusted."""
    suppliers = db.collection("suppliers")
    gstin = (extracted.supplier_gstin or "").strip().upper() or None
    name = normalize_name(extracted.supplier_name or "")
    by_name = (
        suppliers.where(filter=firestore.FieldFilter("normalized_name", "==", name)).limit(1).get()
        if name
        else []
    )
    named = by_name[0].to_dict() if by_name else None

    if gstin:
        found = suppliers.where(filter=firestore.FieldFilter("gstin", "==", gstin)).limit(1).get()
        if found:
            supplier = found[0].to_dict()
            if named and named["supplier_id"] != supplier["supplier_id"]:
                return SupplierMatch(
                    None,
                    f"The invoice is from {extracted.supplier_name}, but its GSTIN {gstin} "
                    f"belongs to {supplier['name']}",
                )
            return SupplierMatch(supplier)

    if not name:
        return SupplierMatch(None, "The invoice doesn't show a supplier name we can match")
    if not named:
        return SupplierMatch(
            None, f"Supplier '{extracted.supplier_name}' is not in the supplier list"
        )
    if gstin and named.get("gstin") and named["gstin"] != gstin:
        return SupplierMatch(
            None,
            f"The invoice GSTIN {gstin} doesn't match {named['name']}'s GSTIN {named['gstin']}",
        )
    return SupplierMatch(named)


def supplier_key(match: SupplierMatch, extracted: Extracted) -> str:
    """Groups an invoice with others from the same supplier, even an unknown one."""
    return match.key or f"name:{normalize_name(extracted.supplier_name or '')}"


# Approved or waiting for approval, but not yet posted to the ledger (posting moves the
# quantities into the PO's `billed` totals).
COMMITTED = {S.auto_approved.value, S.pending_approval.value, S.approved.value}


def committed_quantities(db: firestore.Client, me: dict, po_number: str) -> dict[str, Decimal]:
    """Per PO line, the quantity other unposted invoices already bill against `po_number`."""
    docs = (
        db.collection("invoices")
        .where(filter=firestore.FieldFilter("match_result.matched_po", "==", po_number))
        .stream()
    )  # status is filtered here rather than in the query, so no composite index is needed
    totals: dict[str, Decimal] = {}
    for d in (doc.to_dict() for doc in docs):
        if d["invoice_id"] == me["invoice_id"] or d["status"] not in COMMITTED:
            continue
        for line in d["match_result"]["per_line"]:
            if line.get("po_line_id"):
                qty = Decimal(line["billed_qty"])
                totals[line["po_line_id"]] = totals.get(line["po_line_id"], Decimal(0)) + qty
    return totals


def get_po(db: firestore.Client, po_number: str) -> dict | None:
    snap = db.collection("purchase_orders").document(po_number).get()
    return snap.to_dict() if snap.exists else None
