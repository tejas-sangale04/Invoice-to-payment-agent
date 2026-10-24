from decimal import Decimal

from app.models.master_data import POStatus
from app.pipeline.post import ledger_key, po_status

PO = {
    "status": "open",
    "items": [{"line_id": "1", "qty": "50"}, {"line_id": "2", "qty": "2.5"}],
}


def test_ledger_key_is_supplier_and_normalised_invoice_number() -> None:
    assert ledger_key("SUP-1", "SD20260457") == "SUP-1_SD20260457"


def test_po_status_follows_what_has_been_billed() -> None:
    assert po_status(PO, {}) == POStatus.open
    assert po_status(PO, {"1": Decimal(20)}) == POStatus.partially_billed
    assert po_status(PO, {"1": Decimal(50)}) == POStatus.partially_billed
    assert po_status(PO, {"1": Decimal(50), "2": Decimal("2.5")}) == POStatus.fully_billed


def test_a_closed_po_stays_closed() -> None:
    assert po_status({**PO, "status": "closed"}, {"1": Decimal(50)}) == POStatus.closed
