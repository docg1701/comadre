"""Tests for comadre.keys.models."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from comadre.keys.db import generate_customer_id
from comadre.keys.models import (
    ApiKeyCreate,
    ApiKeyRecord,
    CustomerCreate,
    CustomerRecord,
    IssuedKey,
)


class TestCustomerCreate:
    def test_accepts_valid_input(self) -> None:
        c = CustomerCreate(
            name="Helena Ribeiro",
            email="helena@clinica.com",
            tax_id_kind="cpf",
            tax_id_digits="12345678909",
            notes="",
        )
        assert c.name == "Helena Ribeiro"
        assert c.tax_id_kind == "cpf"
        assert c.tax_id_digits == "12345678909"

    def test_rejects_empty_name(self) -> None:
        with pytest.raises(ValidationError):
            CustomerCreate(
                name="",
                email="x@x.com",
                tax_id_kind="cpf",
                tax_id_digits="12345678909",
            )

    def test_rejects_overlong_name(self) -> None:
        with pytest.raises(ValidationError):
            CustomerCreate(
                name="x" * 201,
                email="x@x.com",
                tax_id_kind="cpf",
                tax_id_digits="12345678909",
            )

    def test_rejects_bad_email(self) -> None:
        with pytest.raises(ValidationError):
            CustomerCreate(
                name="X",
                email="not-an-email",
                tax_id_kind="cpf",
                tax_id_digits="12345678909",
            )

    def test_rejects_invalid_tax_id_kind(self) -> None:
        with pytest.raises(ValidationError):
            CustomerCreate(
                name="X",
                email="x@x.com",
                tax_id_kind="rg",  # type: ignore[arg-type]
                tax_id_digits="12345678909",
            )

    def test_rejects_short_tax_id_digits(self) -> None:
        with pytest.raises(ValidationError):
            CustomerCreate(
                name="X",
                email="x@x.com",
                tax_id_kind="cpf",
                tax_id_digits="123",
            )

    def test_default_notes_is_empty(self) -> None:
        c = CustomerCreate(
            name="X",
            email="x@x.com",
            tax_id_kind="cnpj",
            tax_id_digits="12345678000195",
        )
        assert c.notes == ""


class TestCustomerRecord:
    def test_is_frozen(self) -> None:
        rec = CustomerRecord(
            id="cust_01abc",
            name="Helena",
            email="h@h.com",
            tax_id_kind="cpf",
            tax_id_encrypted=b"gAAAAA-ciphertext",
            notes="",
            registered_at=datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC),
            deleted_at=None,
        )
        with pytest.raises((AttributeError, TypeError)):
            rec.name = "Other"  # type: ignore[misc]

    def test_has_slots(self) -> None:
        rec = CustomerRecord(
            id="cust_01abc",
            name="H",
            email="h@h.com",
            tax_id_kind="cpf",
            tax_id_encrypted=b"x",
            notes="",
            registered_at=datetime(2026, 4, 16, tzinfo=UTC),
            deleted_at=None,
        )
        # frozen+slots dataclasses lack __dict__ — catches accidental attr set.
        assert not hasattr(rec, "__dict__")


def _valid_customer_id() -> str:
    return "cust_01j8xr3e4c5m7kn9p2qt8vwyz0"


class TestApiKeyCreate:
    def test_accepts_manual_with_price(self) -> None:
        create = ApiKeyCreate(
            customer_id=_valid_customer_id(),
            rate_limit_rpm=60,
            billing_mode="manual",
            price_monthly=149.0,
        )
        assert create.billing_mode == "manual"
        assert create.price_monthly == 149.0
        assert create.rate_limit_rpm == 60
        assert create.notes == ""

    def test_accepts_complimentary_with_zero_price(self) -> None:
        create = ApiKeyCreate(
            customer_id=_valid_customer_id(),
            rate_limit_rpm=120,
            billing_mode="complimentary",
            price_monthly=0.0,
            notes="included in infra bundle",
        )
        assert create.billing_mode == "complimentary"
        assert create.price_monthly == 0.0

    def test_default_billing_mode_manual(self) -> None:
        create = ApiKeyCreate(
            customer_id=_valid_customer_id(),
            rate_limit_rpm=60,
            price_monthly=149.0,
        )
        assert create.billing_mode == "manual"

    def test_rejects_rpm_zero(self) -> None:
        with pytest.raises(ValidationError):
            ApiKeyCreate(
                customer_id=_valid_customer_id(),
                rate_limit_rpm=0,
                price_monthly=149.0,
            )

    def test_rejects_rpm_negative(self) -> None:
        with pytest.raises(ValidationError):
            ApiKeyCreate(
                customer_id=_valid_customer_id(),
                rate_limit_rpm=-1,
                price_monthly=149.0,
            )

    def test_rejects_negative_price(self) -> None:
        with pytest.raises(ValidationError):
            ApiKeyCreate(
                customer_id=_valid_customer_id(),
                rate_limit_rpm=60,
                price_monthly=-1.0,
            )

    def test_rejects_malformed_customer_id(self) -> None:
        for bad in ("cust_nope", "customer_01jabc", "cust_UPPERCASE" + "a" * 18):
            with pytest.raises(ValidationError):
                ApiKeyCreate(
                    customer_id=bad,
                    rate_limit_rpm=60,
                    price_monthly=149.0,
                )

    def test_accepts_generated_customer_ids(self) -> None:
        for _ in range(100):
            cid = generate_customer_id()
            ApiKeyCreate(
                customer_id=cid,
                rate_limit_rpm=60,
                price_monthly=149.0,
            )


class TestApiKeyRecord:
    def _make(self) -> ApiKeyRecord:
        return ApiKeyRecord(
            id="key_01abc",
            customer_id=_valid_customer_id(),
            key_hash="a" * 64,
            key_prefix="ABCDEFGH",
            rate_limit_rpm=60,
            status="active",
            billing_mode="manual",
            price_monthly=149.0,
            paid_until=None,
            created_at=datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC),
            last_used_at=None,
            notes="",
        )

    def test_is_frozen(self) -> None:
        rec = self._make()
        with pytest.raises((AttributeError, TypeError)):
            rec.notes = "mutated"  # type: ignore[misc]

    def test_has_slots(self) -> None:
        assert not hasattr(self._make(), "__dict__")


class TestIssuedKey:
    def _make_record(self) -> ApiKeyRecord:
        return ApiKeyRecord(
            id="key_01abc",
            customer_id=_valid_customer_id(),
            key_hash="b" * 64,
            key_prefix="ABCDEFGH",
            rate_limit_rpm=60,
            status="active",
            billing_mode="manual",
            price_monthly=149.0,
            paid_until=None,
            created_at=datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC),
            last_used_at=None,
            notes="",
        )

    def test_is_frozen(self) -> None:
        issued = IssuedKey(
            plaintext="cmdr_live_example",
            record=self._make_record(),
            customer_name="Helena",
            first_charge_date="2026-05-05",
            first_charge_days_free=22,
        )
        with pytest.raises((AttributeError, TypeError)):
            issued.plaintext = "other"  # type: ignore[misc]

    def test_has_slots(self) -> None:
        issued = IssuedKey(
            plaintext="cmdr_live_example",
            record=self._make_record(),
            customer_name="Helena",
            first_charge_date=None,
            first_charge_days_free=None,
        )
        assert not hasattr(issued, "__dict__")
