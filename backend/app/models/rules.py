from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field


class BusinessRules(BaseModel):
    """Thresholds the decision step uses (Setup guide, Section 8). Editable by admins."""

    price_tolerance_percent: Annotated[Decimal, Field(ge=0, le=100, decimal_places=2)] = Decimal(
        "2.0"
    )
    auto_approve_max_paise: Annotated[int, Field(ge=0)] = 5_000_000  # Rs 50,000
    min_field_confidence: Annotated[Decimal, Field(ge=0, le=1, decimal_places=3)] = Decimal("0.85")
