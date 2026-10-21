"""Internal endpoint Cloud Tasks calls to run the pipeline. Not callable by users."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response

from app.api.deps import Db
from app.core.config import get_settings
from app.models.invoice import ProcessInvoiceTask
from app.pipeline.runner import process_invoice

logger = logging.getLogger(__name__)
router = APIRouter(tags=["internal"], include_in_schema=False)


def verify_cloud_tasks_caller(authorization: Annotated[str | None, Header()] = None) -> None:
    """Accept only an OIDC token Google issued to our Cloud Tasks service account for this API.
    In inline mode (local dev) nothing calls this endpoint, so it refuses everyone."""
    s = get_settings()
    if s.tasks_mode != "cloud_tasks" or not s.tasks_service_account:
        raise HTTPException(status_code=403, detail="Task endpoint is disabled")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing task token")
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    try:
        claims = id_token.verify_oauth2_token(
            authorization.removeprefix("Bearer "),
            google_requests.Request(),
            audience=s.api_base_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid task token") from exc
    if claims.get("email") != s.tasks_service_account or not claims.get("email_verified"):
        raise HTTPException(status_code=403, detail="Caller is not the task service account")


@router.post("/tasks/process-invoice", dependencies=[Depends(verify_cloud_tasks_caller)])
def process_invoice_task(
    body: ProcessInvoiceTask,
    db: Db,
    retry_count: Annotated[int, Header(alias="X-CloudTasks-TaskRetryCount")] = 0,
) -> Response:
    attempt = retry_count + 1
    try:
        process_invoice(db, body.invoice_id, attempt, get_settings().max_processing_attempts)
    except Exception:
        # A non-2xx response makes Cloud Tasks retry with backoff.
        return Response(status_code=500)
    return Response(status_code=204)
