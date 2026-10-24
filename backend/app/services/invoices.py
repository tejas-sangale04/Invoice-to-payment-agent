"""Invoice intake and lookups (Setup guide, Sections 5 to 7)."""

import hashlib
from datetime import UTC, datetime

from fastapi import HTTPException
from google.cloud import firestore

from app.models.common import Page
from app.models.invoice import (
    AiUsage,
    AuditEntry,
    EmailDraft,
    Extracted,
    Invoice,
    InvoiceStatus,
    LedgerEntry,
    MatchResult,
    SupplierEmail,
)
from app.models.master_data import Supplier
from app.models.user import CurrentUser
from app.pipeline.decide import decide
from app.pipeline.explain import explain
from app.pipeline.status import (
    REPROCESSABLE,
    InvalidTransition,
    InvoiceNotFound,
    transition,
    write_audit,
)
from app.services import mailer
from app.services import rules as rules_svc
from app.services.counters import next_id
from app.services.files import sniff
from app.services.master_data import get_supplier
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


# ------------------------------------------------------------- approvals


def _decide_as(db: firestore.Client, invoice_id: str, user: CurrentUser, verb: str) -> None:
    """Separation of duties: whoever uploaded an invoice can't approve or reject it."""
    if get_invoice_doc(db, invoice_id)["uploaded_by"] == user.uid:
        raise HTTPException(
            status_code=403,
            detail=f"You uploaded this invoice, so another manager has to {verb} it",
        )


def _not_waiting(exc: InvalidTransition, verb: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail=f"Only invoices waiting for approval can be {verb} "
        f"(this one is {exc.current.value.replace('_', ' ')})",
    )


def approve(db: firestore.Client, invoice_id: str, user: CurrentUser, comment: str | None) -> None:
    _decide_as(db, invoice_id, user, "approve")
    try:
        transition(
            db,
            invoice_id,
            InvoiceStatus.approved,
            actor=user.uid,
            action="approved",
            details=f"Approved by {user.email or user.uid}" + (f": {comment}" if comment else ""),
            expected_from=InvoiceStatus.pending_approval,
            updates={
                "approved_by": user.uid,
                "approved_by_email": user.email,
                "approval_comment": comment or None,
            },
        )
    except InvalidTransition as exc:
        raise _not_waiting(exc, "approved") from exc


def reject(db: firestore.Client, invoice_id: str, user: CurrentUser, reason: str) -> Invoice:
    _decide_as(db, invoice_id, user, "reject")
    try:
        transition(
            db,
            invoice_id,
            InvoiceStatus.rejected,
            actor=user.uid,
            action="rejected",
            details=f"Rejected by {user.email or user.uid}: {reason}",
            expected_from=InvoiceStatus.pending_approval,
            updates={
                "rejected_by": user.uid,
                "rejected_by_email": user.email,
                "rejection_reason": reason,
            },
        )
    except InvalidTransition as exc:
        raise _not_waiting(exc, "rejected") from exc
    return get_invoice(db, invoice_id)


# ------------------------------------------------------------- supplier emails

EMAILABLE = frozenset(
    {
        InvoiceStatus.pending_approval,
        InvoiceStatus.rejected,
        InvoiceStatus.on_hold,
        InvoiceStatus.needs_review,
        InvoiceStatus.blocked_duplicate,
    }
)


def email_recipient(db: firestore.Client, doc: dict) -> tuple[mailer.Mailer, Supplier]:
    """The mail sender and the supplier on file for this invoice, or the reason there is none."""
    send = mailer.get_mailer()
    if send is None:
        raise HTTPException(
            status_code=503,
            detail="Email isn't set up. Add the mail settings to backend/.env (EMAIL_MODE=smtp).",
        )
    supplier_id = (doc.get("match_result") or {}).get("supplier_id")
    supplier = get_supplier(db, supplier_id) if supplier_id else None
    if supplier is None:
        raise HTTPException(
            status_code=422,
            detail="This invoice isn't matched to a supplier on file, so there is no address "
            "to send to. Add the supplier first, or write to them yourself.",
        )
    return send, supplier


def draft_supplier_email(db: firestore.Client, invoice_id: str, rejected: bool) -> EmailDraft:
    """Ask the Explanation Agent to write the email to the supplier (the template if the agent
    is off or its text fails the amount check). Nothing is sent. The model call is added to the
    invoice's AI usage."""
    doc = get_invoice_doc(db, invoice_id)
    if not doc.get("extracted") or not doc.get("match_result"):
        raise HTTPException(
            status_code=409,
            detail="This invoice hasn't been read and matched yet, so there is nothing to write.",
        )
    extracted = Extracted(**doc["extracted"])
    result = MatchResult(**doc["match_result"])
    outcome = decide(result, extracted.total_paise or 0, rules_svc.get_rules(db))
    usage = AiUsage(**(doc.get("ai_usage") or {}))
    written = explain(extracted, result, outcome, usage, rejected)
    db.collection("invoices").document(invoice_id).update({"ai_usage": usage.model_dump()})
    return EmailDraft(email=written.supplier_email or "", source=written.source)


def email_supplier(
    db: firestore.Client, invoice_id: str, user: CurrentUser, email: SupplierEmail
) -> Invoice:
    """Email the supplier on file for this invoice, then record what happened on the invoice
    and in the audit log. A failed send is recorded and returned, not raised: the manager sees
    it on the invoice and can try again."""
    doc = get_invoice_doc(db, invoice_id)
    status = InvoiceStatus(doc["status"])
    if status not in EMAILABLE:
        raise HTTPException(
            status_code=409,
            detail="Emails to the supplier can be sent for invoices that are waiting, on hold, "
            f"rejected or need review (this one is {status.value.replace('_', ' ')})",
        )
    send, supplier = email_recipient(db, doc)

    error = None
    try:
        send.send(supplier.email, email.subject, email.body)
    except mailer.MailerError as exc:
        error = str(exc)
    now = datetime.now(UTC)
    record = {
        "to": supplier.email,
        "subject": email.subject,
        "body": email.body,
        "status": "failed" if error else "sent",
        "error": error,
        "by": user.uid,
        "by_email": user.email,
        "at": now,
    }

    @firestore.transactional
    def save(tx: firestore.Transaction) -> None:
        tx.update(
            db.collection("invoices").document(invoice_id),
            {"supplier_email": record, "updated_at": now},
        )
        write_audit(
            tx,
            db,
            invoice_id,
            "supplier_email_failed" if error else "supplier_emailed",
            user.uid,
            details=(
                f"Could not email {supplier.email}: {error}"
                if error
                else f"Emailed {supplier.email}: {email.subject}"
            ),
        )

    save(db.transaction())
    return get_invoice(db, invoice_id)


def list_ledger(db: firestore.Client, limit: int, cursor: str | None) -> Page[LedgerEntry]:
    col = db.collection("ledger_entries")
    docs, next_cursor = paginate(col, col, limit, cursor, order_field="posted_at")
    return Page(items=[LedgerEntry(**d.to_dict()) for d in docs], next_cursor=next_cursor)
