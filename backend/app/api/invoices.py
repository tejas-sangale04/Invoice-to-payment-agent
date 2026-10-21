import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile

from app.api.deps import Cursor, Db, Limit
from app.core.config import get_settings
from app.models.common import Page
from app.models.invoice import AuditEntry, FileLink, Invoice, InvoiceStatus
from app.models.user import CurrentUser, Role
from app.pipeline.runner import AGENT
from app.pipeline.status import transition
from app.services import invoices as svc
from app.services.auth import require_role
from app.services.files import MAX_BYTES, InvalidFile
from app.services.storage import Storage, get_storage
from app.services.tasks import enqueue_processing

logger = logging.getLogger(__name__)
router = APIRouter(tags=["invoices"])

Staff = Depends(require_role(Role.staff))
Manager = Depends(require_role(Role.manager))
StorageDep = Annotated[Storage, Depends(get_storage)]


def _enqueue_or_fail(db: Db, invoice_id: str, background: BackgroundTasks) -> None:
    try:
        enqueue_processing(invoice_id, background)
    except Exception:
        logger.exception("Could not queue invoice", extra={"invoice_id": invoice_id})
        transition(
            db,
            invoice_id,
            InvoiceStatus.failed,
            actor=AGENT,
            action="queue_failed",
            details="The invoice was saved but could not be queued for processing. "
            "Reprocess it to try again.",
        )


@router.post("/invoices", response_model=Invoice, status_code=201)
async def upload_invoice(
    db: Db,
    storage: StorageDep,
    background: BackgroundTasks,
    file: Annotated[UploadFile, File(description="Invoice PDF, PNG or JPEG, up to 10 MB")],
    user: CurrentUser = Staff,
) -> Invoice:
    """Saves the file, creates the invoice in `received` and queues it. Returns immediately."""
    data = await file.read(MAX_BYTES + 1)
    try:
        invoice = svc.create_invoice(db, storage, data, file.filename or "", user.uid)
    except InvalidFile as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _enqueue_or_fail(db, invoice.invoice_id, background)
    return invoice


@router.get("/invoices", response_model=Page[Invoice])
def list_invoices(
    db: Db,
    status: InvoiceStatus | None = None,
    limit: Limit = 50,
    cursor: Cursor = None,
    _: CurrentUser = Staff,
) -> Page[Invoice]:
    return svc.list_invoices(db, limit, cursor, status)


@router.get("/invoices/{invoice_id}", response_model=Invoice)
def get_invoice(invoice_id: str, db: Db, _: CurrentUser = Staff) -> Invoice:
    return svc.get_invoice(db, invoice_id)


@router.get("/invoices/{invoice_id}/file", response_model=FileLink)
def get_invoice_file(
    invoice_id: str, db: Db, storage: StorageDep, _: CurrentUser = Staff
) -> FileLink:
    """A short-lived signed link to the original file."""
    doc = svc.get_invoice_doc(db, invoice_id)
    return FileLink(
        url=storage.signed_url(doc["file_path"], doc["content_type"]),
        content_type=doc["content_type"],
        expires_in_seconds=get_settings().file_url_ttl_seconds,
    )


@router.post("/invoices/{invoice_id}/reprocess", response_model=Invoice)
def reprocess_invoice(
    invoice_id: str, db: Db, background: BackgroundTasks, user: CurrentUser = Manager
) -> Invoice:
    invoice = svc.reprocess(db, invoice_id, user.uid)
    _enqueue_or_fail(db, invoice_id, background)
    return invoice


@router.get("/audit-log", response_model=Page[AuditEntry], tags=["audit"])
def audit_log(
    db: Db, invoice_id: Annotated[str, Query(min_length=1)], _: CurrentUser = Staff
) -> Page[AuditEntry]:
    return svc.list_audit(db, invoice_id)
