"""Finding the PO of an invoice without a PO number (Setup guide, Section 7, step 4b).

The Resolution Agent searches the supplier's open POs with a tool and proposes one. Code then
checks it: the proposed PO must fit the invoice, and it must be the only open PO that does.
Anything else goes to a person. An invoice matched this way always needs a manager.
"""

import logging
from datetime import date
from decimal import Decimal

from google.cloud import firestore

from app.agents import resolution
from app.models.invoice import AiUsage, Extracted, Resolution
from app.models.invoice import MatchIssueKind as K
from app.models.master_data import POStatus
from app.pipeline import lookup
from app.pipeline.match import match_invoice, normalize_po_number, pair_lines
from app.pipeline.money import qty_text, rupees

logger = logging.getLogger(__name__)

OPEN = {POStatus.open.value, POStatus.partially_billed.value}


def open_pos(db: firestore.Client, supplier_id: str) -> list[dict]:
    docs = (
        db.collection("purchase_orders")
        .where(filter=firestore.FieldFilter("supplier_id", "==", supplier_id))
        .limit(200)
        .stream()
    )  # status is filtered here, so no composite index is needed
    pos = [d for d in (doc.to_dict() for doc in docs) if d["status"] in OPEN]
    return sorted(pos, key=lambda p: p["created_at"])


def _already_billed(po: dict, committed: dict[str, Decimal]) -> dict[str, Decimal]:
    billed = {k: Decimal(v) for k, v in po.get("billed", {}).items()}
    return {
        i["line_id"]: billed.get(i["line_id"], Decimal(0)) + committed.get(i["line_id"], Decimal(0))
        for i in po["items"]
    }


def fits(
    extracted: Extracted, po: dict, committed: dict[str, Decimal], tolerance, received: bool
) -> bool:
    """Every line is on the PO in the same unit, and no more is billed than is left to bill:
    of what was received, or (received=False) of what was ordered. Prices are left to the
    3-way match, which runs next."""
    result = match_invoice(extracted, po, tolerance, committed)
    if any(i.kind in (K.unmatched_line, K.unit) for i in result.issues):
        return False
    billed = _already_billed(po, committed)
    got = po.get("received", {})
    left = {
        i["line_id"]: Decimal(got.get(i["line_id"], "0") if received else i["qty"])
        - billed[i["line_id"]]
        for i in po["items"]
    }
    return all(line.billed_qty <= left[line.po_line_id] for line in result.per_line)


def _parse_date(raw: str) -> date | None:
    try:
        return date.fromisoformat(raw.strip()) if raw and raw.strip() else None
    except ValueError:
        return None


def search_tool(db: firestore.Client, me: dict, supplier_id: str) -> resolution.SearchTool:
    def search_open_purchase_orders(
        item_name: str = "", ordered_after: str = "", ordered_before: str = ""
    ) -> dict:
        """Search this supplier's open purchase orders.

        Args:
            item_name: Only POs with a line like this item, e.g. "milk". Empty for all.
            ordered_after: Only POs created on or after this date (YYYY-MM-DD). Empty for any.
            ordered_before: Only POs created on or before this date (YYYY-MM-DD). Empty for any.

        Returns:
            The matching POs with, per line, what was ordered, received, already billed and
            can still be billed.
        """
        after, before = _parse_date(ordered_after), _parse_date(ordered_before)
        found = []
        for po in open_pos(db, supplier_id):
            names = [i["name"] for i in po["items"]]
            ordered_on = po["created_at"].date()
            if item_name.strip() and pair_lines([item_name], names) == [None]:
                continue
            if (after and ordered_on < after) or (before and ordered_on > before):
                continue
            committed = lookup.committed_quantities(db, me, po["po_number"])
            billed = _already_billed(po, committed)
            received = po.get("received", {})
            found.append(
                {
                    "po_number": po["po_number"],
                    "ordered_on": ordered_on.isoformat(),
                    "lines": [
                        {
                            "name": i["name"],
                            "unit": i["unit"],
                            "ordered": qty_text(Decimal(i["qty"])),
                            "received": qty_text(Decimal(received.get(i["line_id"], "0"))),
                            "already_billed": qty_text(billed[i["line_id"]]),
                            "can_still_bill": qty_text(Decimal(i["qty"]) - billed[i["line_id"]]),
                            "can_bill_now": qty_text(
                                Decimal(received.get(i["line_id"], "0")) - billed[i["line_id"]]
                            ),
                            "unit_price": rupees(i["unit_price_paise"]),
                            "gst_percent": qty_text(Decimal(i["tax_rate"])),
                        }
                        for i in po["items"]
                    ],
                }
            )
        return {"purchase_orders": found}

    return search_open_purchase_orders


def _invoice_for_agent(e: Extracted, supplier: dict) -> dict:
    return {
        "supplier": supplier["name"],
        "invoice_no": e.invoice_no,
        "invoice_date": e.invoice_date.isoformat() if e.invoice_date else None,
        "lines": [
            {
                "name": i.name,
                "qty": qty_text(i.qty),
                "unit": i.unit,
                "unit_price": rupees(i.unit_price_paise),
                "gst_percent": qty_text(i.tax_rate),
            }
            for i in e.items
        ],
        "total": rupees(e.total_paise) if e.total_paise is not None else None,
    }


def resolve(
    db: firestore.Client,
    me: dict,
    extracted: Extracted,
    supplier: dict,
    tolerance,
    usage: AiUsage,
) -> tuple[dict | None, Resolution]:
    """The verified PO (or None) and the record of what happened, for the invoice."""
    no_po = "The invoice has no PO number"
    resolver = resolution.get_resolver()
    if resolver is None:
        return None, Resolution(message=no_po)
    try:
        call = resolver.resolve(
            _invoice_for_agent(extracted, supplier),
            search_tool(db, me, supplier["supplier_id"]),
        )
    except Exception:
        logger.exception("Resolution Agent failed", extra={"invoice_id": me["invoice_id"]})
        return None, Resolution(message=f"{no_po}, and the search for its PO failed")
    usage.calls += 1
    usage.input_tokens += call.input_tokens
    usage.output_tokens += call.output_tokens
    usage.latency_ms += call.latency_ms
    if call.parsed is None:
        return None, Resolution(message=f"{no_po}, and the search for its PO failed")

    # A PO whose deliveries cover the invoice is the better fit; failing that, one whose order
    # does (the 3-way match then holds the invoice for what hasn't arrived).
    candidates = [
        (po, lookup.committed_quantities(db, me, po["po_number"]))
        for po in open_pos(db, supplier["supplier_id"])
    ]
    fitting = [po for po, c in candidates if fits(extracted, po, c, tolerance, received=True)]
    if not fitting:
        fitting = [po for po, c in candidates if fits(extracted, po, c, tolerance, received=False)]
    fitting_numbers = [po["po_number"] for po in fitting]
    proposed = normalize_po_number(call.parsed.po_number)
    record = Resolution(
        proposed_po=proposed, reasoning=call.parsed.reasoning, fitting_pos=fitting_numbers
    )
    if proposed is None:
        record.message = f"{no_po}, and no single open PO from {supplier['name']} fits it"
    elif proposed not in fitting_numbers:
        record.message = (
            f"{no_po}. The agent suggested {proposed}, but its items or quantities don't fit "
            "the invoice"
        )
    elif len(fitting) > 1:
        others = ", ".join(n for n in fitting_numbers if n != proposed)
        record.message = (
            f"{no_po}. The agent suggested {proposed}, but {others} also fit, so a person "
            "needs to choose"
        )
    else:
        record.verified = True
        record.message = f"{no_po}; the agent matched it to {proposed}"
        return fitting[0], record
    return None, record
