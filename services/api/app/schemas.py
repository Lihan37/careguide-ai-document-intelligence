from datetime import date
from decimal import Decimal
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

Money = Annotated[Decimal, Field(allow_inf_nan=False, max_digits=20, decimal_places=6)]


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class LineItem(Strict):
    description: str | None = None
    quantity: Money | None = None
    unit_price: Money | None = None
    line_amount: Money | None = None
    tax_amount: Money | None = None
    currency: str | None = None


class Invoice(Strict):
    invoice_number: str | None = Field(default=None, max_length=255)
    invoice_date: date | None = None
    supplier_name: str | None = Field(default=None, max_length=255)
    customer_name: str | None = Field(default=None, max_length=255)
    subtotal: Money | None = None
    tax: Money | None = None
    total: Money | None = None
    currency: str | None = Field(default=None, pattern=r'^[A-Z]{3}$')
    line_items: list[LineItem] = Field(default_factory=list, max_length=5000)
    discount: Money | None = None
    shipping: Money | None = None
    credit: Money | None = None
    tax_inclusive: bool | None = None

    @field_validator('invoice_number', 'supplier_name', 'customer_name')
    @classmethod
    def nonblank(cls, value):
        return value.strip() or None if value is not None else None


class Login(Strict):
    username: str = Field(max_length=100)
    password: str = Field(max_length=256)


class Correction(Strict):
    fields: dict
    reason: str = Field(min_length=3, max_length=2000)


class CandidateAcceptance(Strict):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=2000)]


class Review(Strict):
    decision: str = Field(pattern='^(approved|follow_up)$')
    note: str = Field(min_length=3, max_length=2000)


class CompareRequest(Strict):
    document_ids: list[str] = Field(min_length=2, max_length=10)
    mappings: dict[str, dict[str, str]] = Field(default_factory=dict)
    rows: dict[str, int] = Field(default_factory=dict)
    sheets: dict[str, str] = Field(default_factory=dict)


class SemanticRequest(Strict):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=50)
