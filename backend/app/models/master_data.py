import re
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, StringConstraints, field_validator

# Quantities and tax rates are Decimals (sent as strings in JSON) so no float rounding creeps in.
# Money is always integer paise (Rs 60.00 = 6000).
Quantity = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=3)]
TaxRate = Annotated[Decimal, Field(ge=0, le=28, max_digits=5, decimal_places=2)]
Paise = Annotated[int, Field(ge=0)]
NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]

# 15-character Indian GST identification number.
GSTIN_PATTERN = r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$"


class SupplierCreate(BaseModel):
    name: NonEmpty
    email: EmailStr
    gstin: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True)] | None = None

    @field_validator("gstin")
    @classmethod
    def _gstin(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        if not re.fullmatch(GSTIN_PATTERN, value):
            raise ValueError("GSTIN must be 15 characters, e.g. 27ABCDE1234F1Z5")
        return value


class Supplier(BaseModel):
    supplier_id: str
    name: str
    normalized_name: str
    email: str
    gstin: str | None = None
    created_at: datetime


class POStatus(StrEnum):
    open = "open"
    partially_billed = "partially_billed"
    fully_billed = "fully_billed"
    closed = "closed"


class POItemCreate(BaseModel):
    name: NonEmpty
    qty: Quantity
    unit: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
    unit_price_paise: Paise
    tax_rate: TaxRate = Decimal("0")


class POItem(POItemCreate):
    line_id: str


class PurchaseOrderCreate(BaseModel):
    supplier_id: str
    items: list[POItemCreate] = Field(min_length=1, max_length=100)


class POLineView(POItem):
    """A PO line together with how much of it has been delivered so far."""

    qty_received: Decimal = Decimal("0")
    line_total_paise: int
    tax_paise: int


class PurchaseOrder(BaseModel):
    po_number: str
    supplier_id: str
    supplier_name: str
    status: POStatus
    items: list[POLineView]
    subtotal_paise: int
    tax_paise: int
    total_paise: int
    created_by: str
    created_at: datetime


class GRItemCreate(BaseModel):
    line_id: str
    qty_received: Quantity


class GoodsReceiptCreate(BaseModel):
    po_number: str
    received_on: date
    items: list[GRItemCreate] = Field(min_length=1, max_length=100)
    notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] = ""


class GoodsReceipt(BaseModel):
    gr_id: str
    po_number: str
    items: list[GRItemCreate]
    received_by: str
    received_on: date
    notes: str = ""
    created_at: datetime
