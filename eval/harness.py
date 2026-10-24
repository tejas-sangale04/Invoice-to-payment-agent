"""Runs one case through the real backend: the FastAPI app, the pipeline and the Firestore
emulator. The database is wiped before each run, so a case only ever sees its own world."""

import os
import time
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app
from app.services.storage import LocalStorage, get_storage

TOKENS = {
    "eval-staff": {"uid": "eval-staff", "email": "staff@eval.test", "role": "staff"},
    "eval-manager": {"uid": "eval-manager", "email": "manager@eval.test", "role": "manager"},
    "eval-admin": {"uid": "eval-admin", "email": "admin@eval.test", "role": "admin"},
}
STAFF, MANAGER, ADMIN = ({"Authorization": f"Bearer {t}"} for t in TOKENS)
RECEIVED_ON = "2026-10-19"


def verify_token(token: str) -> dict:
    if token not in TOKENS:
        raise ValueError("invalid token")
    return TOKENS[token]


def make_client(storage_dir: Path) -> tuple[TestClient, LocalStorage]:
    store = LocalStorage(str(storage_dir), "http://testserver", "eval-secret", ttl=60)
    app = create_app()
    app.dependency_overrides[get_storage] = lambda: store
    return TestClient(app), store


def clear_firestore() -> None:
    s = get_settings()
    httpx.delete(
        f"http://{os.environ['FIRESTORE_EMULATOR_HOST']}/emulator/v1/projects/"
        f"{s.firebase_project}/databases/{s.firestore_database}/documents"
    ).raise_for_status()


def call(api: TestClient, method: str, path: str, headers: dict, **kw) -> dict:
    res = api.request(method, path, headers=headers, **kw)
    if res.status_code >= 400:
        raise AssertionError(f"{method} {path} -> {res.status_code}: {res.text}")
    return res.json()


def upload(api: TestClient, data: bytes, name: str) -> tuple[dict, int]:
    """Upload as staff; in inline mode the pipeline runs before the call returns. Returns the
    invoice afterwards and the wall time in milliseconds."""
    started = time.perf_counter()
    created = call(api, "POST", "/invoices", STAFF, files={"file": (name, data)})
    wall_ms = int((time.perf_counter() - started) * 1000)
    return call(api, "GET", f"/invoices/{created['invoice_id']}", STAFF), wall_ms


def build_world(api: TestClient, world: dict) -> None:
    ids = {}
    for s in world["suppliers"]:
        body = {"name": s["name"], "email": s["email"], "gstin": s["gstin"]}
        ids[s["key"]] = call(api, "POST", "/suppliers", ADMIN, json=body)["supplier_id"]
    for po in world["purchase_orders"]:
        body = {"supplier_id": ids[po["supplier"]], "items": po["items"]}
        made = call(api, "POST", "/purchase-orders", STAFF, json=body)["po_number"]
        assert made == po["po_number"], f"expected {po['po_number']}, got {made}"
    for r in world["receipts"]:
        body = {"po_number": r["po_number"], "received_on": RECEIVED_ON, "items": r["items"]}
        call(api, "POST", "/goods-receipts", STAFF, json=body)


def run_case(api: TestClient, folder: Path, truth: dict) -> dict:
    """Build the case's world, upload its invoices as staff, approve as a manager where the
    case says a manager would, and record the end state."""
    clear_firestore()
    build_world(api, truth["world"])

    prior = []
    for p in truth["prior"]:
        inv, _ = upload(api, (folder / p["file"]).read_bytes(), p["file"])
        prior.append({"invoice_id": inv["invoice_id"], "status": inv["status"]})

    name = truth["invoice"]["file"]
    inv, wall_ms = upload(api, (folder / name).read_bytes(), name)
    approved = False
    if inv["status"] == "pending_approval" and truth["expect"]["approve"]:
        body = {"comment": "Checked against the PO (evaluation)"}
        call(api, "POST", f"/invoices/{inv['invoice_id']}/approve", MANAGER, json=body)
        inv = call(api, "GET", f"/invoices/{inv['invoice_id']}", STAFF)
        approved = True

    ledger = call(api, "GET", "/ledger?limit=100", MANAGER)["items"]
    pos = {
        po["po_number"]: call(api, "GET", f"/purchase-orders/{po['po_number']}", STAFF)["status"]
        for po in truth["world"]["purchase_orders"]
    }
    return {
        "invoice": inv,
        "prior": prior,
        "approved_by_manager": approved,
        "ledger": [
            {
                "invoice_id": e["invoice_id"],
                "invoice_no": e["invoice_no"],
                "amount_paise": e["amount_paise"],
            }
            for e in ledger
        ],  # fmt: skip
        "po_status": pos,
        "wall_ms": wall_ms,
    }
