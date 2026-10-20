import time

import pytest
from fastapi.testclient import TestClient

from app.models.invoice import InvoiceStatus as S
from app.pipeline.status import REPROCESSABLE, TRANSITIONS, can_transition
from app.services.files import MAX_BYTES, InvalidFile, sniff
from app.services.storage import LocalStorage
from tests.conftest import bearer

PDF = b"%PDF-1.7\n%test invoice\n"


# ------------------------------------------------------------- status machine


def test_happy_paths_from_the_spec_are_allowed() -> None:
    auto = [
        S.received,
        S.extracting,
        S.extracted,
        S.validated,
        S.matched,
        S.auto_approved,
        S.posted,
        S.paid,
    ]
    manual = [S.matched, S.pending_approval, S.approved, S.posted]
    for path in (auto, manual):
        for current, nxt in zip(path, path[1:], strict=False):
            assert can_transition(current, nxt), (current, nxt)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (S.received, S.auto_approved),  # can't skip the checks
        (S.matched, S.posted),  # can't post without approval
        (S.pending_approval, S.posted),
        (S.needs_review, S.approved),
        (S.on_hold, S.approved),
        (S.blocked_duplicate, S.received),  # duplicates are never reprocessed
        (S.rejected, S.approved),
        (S.paid, S.posted),
    ],
)
def test_unsafe_transitions_are_refused(current: S, target: S) -> None:
    assert not can_transition(current, target)


def test_every_status_is_in_the_machine_and_only_safe_ones_reprocess() -> None:
    assert set(TRANSITIONS) == set(S)
    assert REPROCESSABLE == {S.on_hold, S.needs_review, S.failed}
    for status in REPROCESSABLE:
        assert can_transition(status, S.received)


def test_auto_approval_and_failure_paths_never_end_in_payment_without_posting() -> None:
    assert S.paid not in {t for s, ts in TRANSITIONS.items() if s != S.posted for t in ts}


# ---------------------------------------------------------------- file checks


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (PDF, ("application/pdf", "pdf")),
        (b"\x89PNG\r\n\x1a\n....", ("image/png", "png")),
        (b"\xff\xd8\xff\xe0....", ("image/jpeg", "jpg")),
    ],
)
def test_sniff_uses_file_contents(data: bytes, expected: tuple[str, str]) -> None:
    assert sniff(data) == expected


@pytest.mark.parametrize(
    "data", [b"", b"MZ\x90\x00 an exe", b"<html>not a pdf</html>", PDF + b"x" * MAX_BYTES]
)
def test_sniff_rejects_empty_wrong_type_and_oversized(data: bytes) -> None:
    with pytest.raises(InvalidFile):
        sniff(data)


# ------------------------------------------------------------- signed links


def test_local_signed_links(tmp_path) -> None:
    store = LocalStorage(str(tmp_path), "http://api", "secret", ttl=60)
    store.save("invoices/abc.pdf", PDF, "application/pdf")
    assert store.read("invoices/abc.pdf") == PDF

    url = store.signed_url("invoices/abc.pdf", "application/pdf")
    assert url.startswith("http://api/files/invoices/abc.pdf?")
    params = dict(p.split("=", 1) for p in url.split("?", 1)[1].split("&"))
    expires, sig = int(params["expires"]), params["sig"]

    assert store.verify("invoices/abc.pdf", "application/pdf", expires, sig)
    assert not store.verify("invoices/other.pdf", "application/pdf", expires, sig)
    assert not store.verify("invoices/abc.pdf", "text/html", expires, sig)
    assert not store.verify("invoices/abc.pdf", "application/pdf", expires + 1, sig)
    assert not store.verify("invoices/abc.pdf", "application/pdf", int(time.time()) - 1, sig)


def test_local_storage_blocks_path_traversal(tmp_path) -> None:
    store = LocalStorage(str(tmp_path / "root"), "http://api", "secret", ttl=60)
    with pytest.raises(ValueError):
        store.read("../outside.txt")


# ---------------------------------------------------------------- endpoints


def test_task_endpoint_is_closed_outside_cloud_tasks_mode(client: TestClient) -> None:
    res = client.post("/tasks/process-invoice", json={"invoice_id": "INV-1"})
    assert res.status_code == 403
    res = client.post(
        "/tasks/process-invoice", json={"invoice_id": "INV-1"}, headers=bearer("admin-token")
    )
    assert res.status_code == 403


@pytest.mark.parametrize(
    ("method", "path", "token", "status"),
    [
        ("get", "/invoices", None, 401),
        ("get", "/invoices", "norole-token", 403),
        ("get", "/invoices/INV-1/file", "norole-token", 403),
        ("get", "/audit-log?invoice_id=INV-1", "norole-token", 403),
        ("post", "/invoices/INV-1/reprocess", "staff-token", 403),
    ],
)
def test_invoice_role_checks(
    client: TestClient, method: str, path: str, token: str | None, status: int
) -> None:
    headers = bearer(token) if token else {}
    assert getattr(client, method)(path, headers=headers).status_code == status


def test_upload_rejects_non_invoice_files(client: TestClient) -> None:
    res = client.post(
        "/invoices",
        files={"file": ("evil.pdf", b"<script>alert(1)</script>", "application/pdf")},
        headers=bearer("staff-token"),
    )
    assert res.status_code == 422
    assert res.json()["error"]["message"] == "Upload a PDF, PNG or JPEG file"


def test_file_link_with_bad_signature_is_refused(client: TestClient) -> None:
    res = client.get("/files/invoices/x.pdf?ct=application/pdf&expires=9999999999&sig=bad")
    assert res.status_code == 403
