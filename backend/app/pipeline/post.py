"""Posting an approved invoice to the ledger (Setup guide, Section 7, step 9).

One Firestore transaction creates the ledger entry, adds the billed quantities to the PO and
moves the invoice to `posted`. The entry's id is the idempotency key, supplier + invoice
number, so an invoice can be posted only once: if the key is already in the ledger, nothing is
posted. Running this twice for the same invoice is harmless.
"""

from datetime import UTC, datetime
from decimal import Decimal

from google.cloud import firestore

from app.models.invoice import Decision, MatchResult
from app.models.invoice import InvoiceStatus as S
from app.models.master_data import POStatus
from app.pipeline.money import rupees
from app.pipeline.status import InvalidTransition, InvoiceNotFound, apply_transition

POSTABLE = frozenset({S.auto_approved, S.approved})


def ledger_key(supplier_id: str, invoice_no_key: str) -> str:
    # The normalised invoice number: 'SD/2026/0457' and 'sd-2026-0457' are one key, and a
    # Firestore document id can't contain '/'.
    return f"{supplier_id}_{invoice_no_key}"


def po_status(po: dict, billed: dict[str, Decimal]) -> POStatus:
    if po["status"] == POStatus.closed.value:
        return POStatus.closed
    if all(billed.get(i["line_id"], Decimal(0)) >= Decimal(i["qty"]) for i in po["items"]):
        return POStatus.fully_billed
    if any(qty > 0 for qty in billed.values()):
        return POStatus.partially_billed
    return POStatus.open


def post_invoice(db: firestore.Client, invoice_id: str, actor: str) -> S:
    """Post an approved invoice. Returns its status afterwards: posted, or blocked_duplicate
    when another invoice with the same supplier and number is already in the ledger."""
    ref = db.collection("invoices").document(invoice_id)

    @firestore.transactional
    def run(tx: firestore.Transaction) -> S:
        snap = ref.get(transaction=tx)
        if not snap.exists:
            raise InvoiceNotFound(invoice_id)
        inv = snap.to_dict()
        current = S(inv["status"])
        if current == S.posted:
            return current
        if current not in POSTABLE:
            raise InvalidTransition(current, S.posted)

        match = MatchResult(**inv["match_result"])
        key = ledger_key(match.supplier_id, inv["invoice_no_key"])
        entry_ref = db.collection("ledger_entries").document(key)
        po_ref = db.collection("purchase_orders").document(match.matched_po)
        entry = entry_ref.get(transaction=tx)  # every read before any write
        po = po_ref.get(transaction=tx).to_dict()
        extracted = inv["extracted"]

        if entry.exists and entry.get("invoice_id") == invoice_id:
            # Can't happen (the entry and the status change are written together), but if it
            # did, the PO already has this invoice's quantities: only finish the status.
            apply_transition(tx, db, ref, current, S.posted, actor, "posted", "Already posted")
            return S.posted
        if entry.exists:
            reason = (
                f"Invoice {extracted['invoice_no']} from {extracted['supplier_name']} is already "
                f"in the ledger as {entry.get('invoice_id')}, so it was not posted again."
            )
            apply_transition(
                tx,
                db,
                ref,
                current,
                S.blocked_duplicate,
                actor,
                "duplicate_blocked",
                reason,
                {
                    "decision": Decision.block.value,
                    "decision_rule": "duplicate",
                    "decision_reason": reason,
                    "duplicate_of": entry.get("invoice_id"),
                },
            )
            return S.blocked_duplicate

        billed = {k: Decimal(v) for k, v in po.get("billed", {}).items()}
        for line in match.per_line:
            if line.po_line_id:
                billed[line.po_line_id] = billed.get(line.po_line_id, Decimal(0)) + line.billed_qty
        amount = match.correct_amount_paise
        tx.set(
            entry_ref,
            {
                "idempotency_key": key,
                "invoice_id": invoice_id,
                "invoice_no": extracted["invoice_no"],
                "supplier_id": match.supplier_id,
                "supplier_name": po["supplier_name"],
                "amount_paise": amount,
                "po_number": match.matched_po,
                "posted_by": actor,
                "posted_at": datetime.now(UTC),
            },
        )
        tx.update(
            po_ref,
            {
                "billed": {k: str(v) for k, v in billed.items()},
                "status": po_status(po, billed).value,
            },
        )
        apply_transition(
            tx,
            db,
            ref,
            current,
            S.posted,
            actor,
            "posted",
            f"Posted {rupees(amount)} to the ledger against {match.matched_po}",
            {"ledger_key": key, "posted_by": actor},
        )
        return S.posted

    return run(db.transaction())
