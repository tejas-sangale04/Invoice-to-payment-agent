"""Builders for extraction tests: a valid LlmInvoice and a scripted fake extractor."""

import copy

from app.agents.extraction import ExtractionCall, parse_output
from app.agents.schemas import LlmInvoice

CONFIDENT = {
    "supplier_name": 0.99,
    "invoice_no": 0.98,
    "invoice_date": 0.97,
    "po_number": 0.95,
    "line_items": 0.95,
    "totals": 0.99,
}

# PO-205 from the spec: 50 L milk at Rs 60, plus 2.5 kg paneer at Rs 400 with 5% GST (intra-state).
GOOD = {
    "supplier_name": "Sharma Dairy Pvt Ltd",
    "supplier_gstin": "27abcde1234f1z5",
    "invoice_no": "SD-1042",
    "invoice_date": "2026-10-20",
    "po_number": "po-1",
    "items": [
        {
            "name": "Milk",
            "qty": "50",
            "unit": "L",
            "unit_price": "60.00",
            "tax_rate": "0",
            "amount": "3,000.00",
        },
        {
            "name": "Paneer",
            "qty": "2.5",
            "unit": "kg",
            "unit_price": "₹400",
            "tax_rate": "5%",
            "amount": "1000.00",
        },
    ],
    "subtotal": "4,000.00",
    "cgst": "25.00",
    "sgst": "25.00",
    "igst": None,
    "total": "Rs. 4,050.00",
    "field_confidence": CONFIDENT,
}


def invoice_json(**changes) -> dict:
    data = copy.deepcopy(GOOD)
    data.update(changes)
    return data


def llm_invoice(**changes) -> LlmInvoice:
    return LlmInvoice.model_validate(invoice_json(**changes))


class FakeExtractor:
    """Returns scripted responses in order and records the feedback it was given."""

    def __init__(self, *responses: dict | str | Exception) -> None:
        self.responses = list(responses)
        self.feedback: list[str | None] = []

    def extract(self, data: bytes, mime_type: str, feedback: str | None = None) -> ExtractionCall:
        self.feedback.append(feedback)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        import json

        text = response if isinstance(response, str) else json.dumps(response)
        parsed, error = parse_output(text)
        return ExtractionCall(parsed, error, input_tokens=1000, output_tokens=200, latency_ms=1500)
