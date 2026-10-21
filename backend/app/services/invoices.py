"""Invoice intake and lookups (Setup guide, Sections 5 to 7)."""

import hashlib
from datetime import UTC, datetime

from fastapi import HTTPException
from google.cloud import firestore

from app.models.common import Page
from app.models.invoice import AuditEntry, Invoice, InvoiceStatus
from app.pipeline.status import (
    REPROCESSABLE,
    InvalidTransition,
    InvoiceNotFound,
    transition,
    write_audit,
)
from app.services.counters import next_id
from app.services.files import sniff
from app.services.pagination import paginate
from app.services.storage import Storage


def file_key(file_hash: str, ext: str) -> str:
    # Content-addressed: the same bytes always map to the same object, so saving is idempotent
    # and happens before the invoice record exists (no record ever points at a missing file).
    return f"invoices/{file_hash}.{ext}"


def create_invoice(
    db: firestore.Client, storage: Storage, data: bytes, file_name: str, uploaded_by: str
) -> Invoice:
    content_type, ext = sniff(data)
    file_hash = hashlib.sha256(data).hexdigest()
    storage.save(file_key(file_hash, ext), data, content_type)

    @firestore.transactional
    def run(tx: firestore.Transaction) -> dict:
        invoice_id = next_id(tx, db, "invoices", "INV")
        now = datetime.now(UTC)
        doc = {
            "invoice_id": invoice_id,
            "status": InvoiceStatus.received.value,
            "status_reason": None,
            "file_name": file_name[:200] or f"invoice.{ext}",
            "file_path": file_key(file_hash, ext),
            "content_type": content_type,
            "file_size": len(data),
            "file_hash": file_hash,
            "uploaded_by": uploaded_by,
            "processing_attempts": 0,
            "created_at": now,
            "updated_at": now,
            "status_times": {InvoiceStatus.received.value: now},
        }
        tx.set(db.collection("invoices").document(invoice_id), doc)
        write_audit(
            tx,
            db,
            invoice_id,
            "uploaded",
            uploaded_by,
            None,
            InvoiceStatus.received,
            f"{doc['file_name']} ({len(data)} bytes)",
        )
        return doc

    return Invoice(**run(db.transaction()))


def get_invoice_doc(db: firestore.Client, invoice_id: str) -> dict:
    snap = db.collection("invoices").document(invoice_id).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail=f"{invoice_id} not found")
    return snap.to_dict()


def get_invoice(db: firestore.Client, invoice_id: str) -> Invoice:
    return Invoice(**get_invoice_doc(db, invoice_id))


def list_invoices(
    db: firestore.Client, limit: int, cursor: str | None, status: InvoiceStatus | None = None
) -> Page[Invoice]:
    col = db.collection("invoices")
    query = col.where(filter=firestore.FieldFilter("status", "==", status.value)) if status else col
    docs, next_cursor = paginate(query, col, limit, cursor)
    return Page(items=[Invoice(**d.to_dict()) for d in docs], next_cursor=next_cursor)


def list_audit(db: firestore.Client, invoice_id: str) -> Page[AuditEntry]:
    docs = (
        db.collection("audit_log")
        .where(filter=firestore.FieldFilter("invoice_id", "==", invoice_id))
        .order_by("timestamp")
        .limit(500)
        .stream()
    )
    return Page(items=[AuditEntry(**d.to_dict()) for d in docs])


def reprocess(db: firestore.Client, invoice_id: str, actor: str) -> Invoice:
    try:
        transition(
            db,
            invoice_id,
            InvoiceStatus.received,
            actor=actor,
            action="reprocess_requested",
            details="Sent back through the pipeline by a manager",
            expected_from=REPROCESSABLE,
            updates={"processing_attempts": 0},
        )
    except InvoiceNotFound as exc:
        raise HTTPException(status_code=404, detail=f"{invoice_id} not found") from exc
    except InvalidTransition as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Only invoices on hold, needing review or failed can be reprocessed "
            f"(this one is {exc.current.value.replace('_', ' ')})",
        ) from exc
    return get_invoice(db, invoice_id)
