import os

import httpx

from app.core.config import get_settings


def clear_firestore() -> None:
    project = get_settings().google_cloud_project
    httpx.delete(
        f"http://{os.environ['FIRESTORE_EMULATOR_HOST']}/emulator/v1/projects/{project}"
        "/databases/(default)/documents"
    ).raise_for_status()
