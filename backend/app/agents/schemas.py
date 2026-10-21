"""The JSON shape the Extraction Agent must return.

Numbers are strings exactly as printed on the invoice (e.g. "3,000.00"). The model only reads;
code converts to paise and does every calculation (app/pipeline/validate.py).
"""

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LlmLineItem(_Strict):
    name: str = Field(description="Item description as printed")
    qty: str = Field(description="Quantity as printed, digits only, e.g. 50 or 2.5")
    unit: str | None = Field(default=None, description="Unit as printed, e.g. L, kg, pcs")
    unit_price: str = Field(description="Price per unit before tax, in rupees, as printed")
    tax_rate: str | None = Field(
        default=None, description="Total GST rate for the line in percent, e.g. 18, if printed"
    )
    amount: str | None = Field(
        default=None, description="Line amount before tax, in rupees, as printed"
    )


class FieldConfidence(_Strict):
    """How sure the model is that it read each field correctly, from 0 to 1."""

    supplier_name: float = Field(ge=0, le=1)
    invoice_no: float = Field(ge=0, le=1)
    invoice_date: float = Field(ge=0, le=1)
    po_number: float = Field(ge=0, le=1)
    line_items: float = Field(ge=0, le=1)
    totals: float = Field(ge=0, le=1)


class LlmInvoice(_Strict):
    supplier_name: str | None = None
    supplier_gstin: str | None = None
    invoice_no: str | None = None
    invoice_date: str | None = Field(default=None, description="ISO format YYYY-MM-DD")
    po_number: str | None = Field(default=None, description="Buyer's purchase order number")
    items: list[LlmLineItem] = []
    subtotal: str | None = Field(default=None, description="Taxable value before GST, rupees")
    cgst: str | None = Field(default=None, description="CGST amount in rupees, if printed")
    sgst: str | None = Field(default=None, description="SGST amount in rupees, if printed")
    igst: str | None = Field(default=None, description="IGST amount in rupees, if printed")
    total: str | None = Field(default=None, description="Grand total payable, rupees")
    field_confidence: FieldConfidence
