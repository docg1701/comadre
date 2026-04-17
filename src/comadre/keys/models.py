"""Data models for the key registry.

`CustomerCreate` validates CLI/API input. `CustomerRecord` is the immutable
row representation used by the DB layer. Literals `TaxIdKind`, `CustomerStatus`,
`BillingMode` are the authoritative value sets for the schema's CHECK
constraints.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

TaxIdKind = Literal["cpf", "cnpj"]
CustomerStatus = Literal["active", "suspended", "revoked"]
BillingMode = Literal["manual", "complimentary", "automated"]


class CustomerCreate(BaseModel):
    """Validated input for creating a customer.

    `tax_id_digits` is digits-only post-`strip_tax_id` and already passed
    `validate_cpf` / `validate_cnpj`. Stored separately from `tax_id_kind`
    so callers don't re-validate inside the model layer.
    """

    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    tax_id_kind: TaxIdKind
    tax_id_digits: str = Field(
        min_length=11,
        max_length=14,
        pattern=r"^[0-9A-Z]+$",
    )
    notes: str = ""


@dataclass(frozen=True, slots=True)
class CustomerRecord:
    """Immutable customer row as persisted in SQLite."""

    id: str
    name: str
    email: str
    tax_id_kind: TaxIdKind
    tax_id_encrypted: bytes
    notes: str
    registered_at: datetime
    deleted_at: datetime | None


class ApiKeyCreate(BaseModel):
    """Validated input for issuing an API key (CLI-side)."""

    customer_id: str = Field(pattern=r"^cust_[0-9a-z]{26}$")
    rate_limit_rpm: int = Field(gt=0)
    billing_mode: BillingMode = "manual"
    price_monthly: float = Field(ge=0.0)
    notes: str = ""


@dataclass(frozen=True, slots=True)
class ApiKeyRecord:
    """Immutable api_key row as persisted in SQLite."""

    id: str
    customer_id: str
    key_hash: str
    key_prefix: str
    rate_limit_rpm: int
    status: CustomerStatus
    billing_mode: BillingMode
    price_monthly: float
    paid_until: str | None
    created_at: datetime
    last_used_at: datetime | None
    notes: str


@dataclass(frozen=True, slots=True)
class IssuedKey:
    """One-shot display payload for ``issue-key`` / ``rotate-key``.

    Carries the plaintext from the command body to the renderer in a
    typed container so the plaintext string is not passed around as a
    bare ``str`` — reduces the chance of accidental logging.
    """

    plaintext: str
    record: ApiKeyRecord
    customer_name: str
    first_charge_date: str | None
