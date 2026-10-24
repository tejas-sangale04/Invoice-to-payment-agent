"""Invoice status machine (Setup guide, Section 6).

Every status change goes through `transition`, which updates the invoice and writes its audit
log entry in one Firestore transaction, so there is never a status change without its audit
record (or the other way round).
"""

from datetime import UTC, datetime
from typing import Any

from google.cloud import firestore

from app.models.invoice import InvoiceStatus as S

TRANSITIONS: dict[S, frozenset[S]] = {
    S.received: frozenset({S.extracting, S.blocked_duplicate, S.needs_review, S.failed}),
    S.extracting: frozenset({S.extracted, S.needs_review, S.failed}),
    S.extracted: frozenset({S.validated, S.needs_review, S.failed}),
    S.validated: frozenset({S.matched, S.needs_review, S.failed}),
    S.matched: frozenset(
        {
            S.auto_approved,
            S.pending_approval,
            S.on_hold,
            S.blocked_duplicate,
            S.needs_review,
            S.failed,
        }
    ),
    # Posting blocks an invoice whose supplier + invoice number is already in the ledger.
    S.auto_approved: frozenset({S.posted, S.blocked_duplicate, S.failed}),
    S.pending_approval: frozenset({S.approved, S.rejected}),
    S.approved: frozenset({S.posted, S.blocked_duplicate, S.failed}),
    S.posted: frozenset({S.paid}),
    # A manager can send these back through the pipeline ("reprocess").
    # A manager can also decide a held invoice: approve it (it is paid the correct amount, not
    # the billed one) or reject it.
    S.on_hold: frozenset({S.received, S.approved, S.rejected}),
    S.needs_review: frozenset({S.received}),
    S.failed: frozenset({S.received}),
    S.rejected: frozenset(),
    S.blocked_duplicate: frozenset(),
    S.paid: frozenset(),
}

REPROCESSABLE = frozenset({S.on_hold, S.needs_review, S.failed})


class InvalidTransition(Exception):
    def __init__(self, current: S, target: S) -> None:
        super().__init__(f"Cannot move an invoice from {current} to {target}")
        self.current, self.target = current, target


class InvoiceNotFound(Exception):
    pass


def can_transition(current: S, target: S) -> bool:
    return target in TRANSITIONS[current]


def _audit_ref(db: firestore.Client) -> firestore.DocumentReference:
    return db.collection("audit_log").document()


def write_audit(
    tx: firestore.Transaction,
    db: firestore.Client,
    invoice_id: str,
    action: str,
    actor: str,
    from_status: S | None = None,
    to_status: S | None = None,
    details: str | None = None,
) -> None:
    tx.set(
        _audit_ref(db),
        {
            "invoice_id": invoice_id,
            "action": action,
            "actor": actor,
            "from_status": from_status.value if from_status else None,
            "to_status": to_status.value if to_status else None,
            "details": details,
            "timestamp": datetime.now(UTC),
        },
    )


def apply_transition(
    tx: firestore.Transaction,
    db: firestore.Client,
    ref: firestore.DocumentReference,
    current: S,
    target: S,
    actor: str,
    action: str,
    details: str | None = None,
    updates: dict[str, Any] | None = None,
) -> None:
    """The writes of a status change, inside a transaction the caller has already checked
    `current` in. For steps that change other documents in the same transaction (posting)."""
    now = datetime.now(UTC)
    tx.update(
        ref,
        {
            **(updates or {}),
            "status": target.value,
            "status_reason": details,
            "updated_at": now,
            f"status_times.{target.value}": now,
        },
    )
    write_audit(tx, db, ref.id, action, actor, current, target, details)


def transition(
    db: firestore.Client,
    invoice_id: str,
    target: S,
    *,
    actor: str,
    action: str,
    details: str | None = None,
    expected_from: S | frozenset[S] | None = None,
    updates: dict[str, Any] | None = None,
) -> S:
    """Move an invoice to `target` and audit it, atomically. Returns the status it moved from.

    Idempotent: if the invoice is already at `target` (e.g. a retried task got here first),
    nothing is written and `target` is returned. `expected_from` guards against acting on an
    invoice that another worker has already moved on.
    """
    ref = db.collection("invoices").document(invoice_id)

    @firestore.transactional
    def run(tx: firestore.Transaction) -> S:
        snap = ref.get(transaction=tx)
        if not snap.exists:
            raise InvoiceNotFound(invoice_id)
        current = S(snap.get("status"))
        if current == target:
            return current
        allowed_from = {expected_from} if isinstance(expected_from, S) else expected_from
        if (allowed_from is not None and current not in allowed_from) or not can_transition(
            current, target
        ):
            raise InvalidTransition(current, target)
        apply_transition(tx, db, ref, current, target, actor, action, details, updates)
        return current

    return run(db.transaction())
