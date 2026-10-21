"""Hands invoices to the background pipeline.

Production uses Cloud Tasks (retries with backoff, survives restarts). Locally, "inline" mode
runs the pipeline in this process right after the upload response, with the same retry logic.
"""

import json
import logging

from fastapi import BackgroundTasks

from app.core.config import get_settings
from app.pipeline.runner import process_invoice
from app.services.firestore import get_db

logger = logging.getLogger(__name__)


def _run_inline(invoice_id: str) -> None:
    max_attempts = get_settings().max_processing_attempts
    for attempt in range(1, max_attempts + 1):
        try:
            process_invoice(get_db(), invoice_id, attempt, max_attempts)
            return
        except Exception:  # already logged; retry like Cloud Tasks would
            continue


def _enqueue_cloud_task(invoice_id: str) -> None:
    from google.cloud import tasks_v2

    s = get_settings()
    client = tasks_v2.CloudTasksClient()
    client.create_task(
        parent=client.queue_path(s.google_cloud_project, s.tasks_location, s.tasks_queue),
        task={
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": f"{s.api_base_url}/tasks/process-invoice",
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"invoice_id": invoice_id}).encode(),
                "oidc_token": {
                    "service_account_email": s.tasks_service_account,
                    "audience": s.api_base_url,
                },
            }
        },
    )


def enqueue_processing(invoice_id: str, background: BackgroundTasks) -> None:
    if get_settings().tasks_mode == "cloud_tasks":
        _enqueue_cloud_task(invoice_id)
    else:
        background.add_task(_run_inline, invoice_id)
    logger.info("Queued for processing", extra={"invoice_id": invoice_id})
