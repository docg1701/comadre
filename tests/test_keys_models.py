"""Tests for comadre.keys.models."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from comadre.keys.db import generate_customer_id
from comadre.keys.models import (
    ApiKeyCreate,
    ApiKeyListRow,
    ApiKeyRecord,
    AuditEventRow,
    AuthPayload,
    CustomerCreate,
    CustomerDetailRow,
    CustomerListRow,
    CustomerRecord,
    IssuedKey,
    KeyDetailRow,
    RevenueReport,
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


class TestCustomerListRow:
    def _make(self) -> CustomerListRow:
        return CustomerListRow(
            id="cust_01abc",
            name="Helena Ribeiro",
            email="helena@clinica.com",
            tax_id_kind="cpf",
            key_count=2,
            registered_at="2026-04-15T12:34:56Z",
            deleted_at=None,
            notes="",
        )

    def test_round_trip_fields(self) -> None:
        row = self._make()
        assert row.id == "cust_01abc"
        assert row.name == "Helena Ribeiro"
        assert row.email == "helena@clinica.com"
        assert row.tax_id_kind == "cpf"
        assert row.key_count == 2
        assert row.registered_at == "2026-04-15T12:34:56Z"
        assert row.deleted_at is None
        assert row.notes == ""

    def test_is_frozen(self) -> None:
        row = self._make()
        with pytest.raises((AttributeError, TypeError)):
            row.name = "Other"  # type: ignore[misc]

    def test_has_slots(self) -> None:
        row = self._make()
        assert not hasattr(row, "__dict__")


class TestApiKeyListRow:
    def _make(self, notes: str = "") -> ApiKeyListRow:
        return ApiKeyListRow(
            id="key_01abc",
            customer_id="cust_01abc",
            customer_name="Helena Ribeiro",
            key_prefix="EVb4xk8B",
            status="active",
            billing_mode="manual",
            rate_limit_rpm=60,
            price_monthly=149.0,
            paid_until=None,
            created_at="2026-04-15T12:34:56Z",
            last_used_at=None,
            notes=notes,
        )

    def test_round_trip_fields(self) -> None:
        row = self._make()
        assert row.id == "key_01abc"
        assert row.customer_id == "cust_01abc"
        assert row.customer_name == "Helena Ribeiro"
        assert row.key_prefix == "EVb4xk8B"
        assert row.status == "active"
        assert row.billing_mode == "manual"
        assert row.rate_limit_rpm == 60
        assert row.price_monthly == 149.0
        assert row.paid_until is None
        assert row.created_at == "2026-04-15T12:34:56Z"
        assert row.last_used_at is None
        assert row.notes == ""

    def test_accepts_notes_field(self) -> None:
        row = self._make(notes="bundled R$ 850/mo")
        assert row.notes == "bundled R$ 850/mo"

    def test_is_frozen(self) -> None:
        row = self._make()
        with pytest.raises((AttributeError, TypeError)):
            row.customer_name = "Other"  # type: ignore[misc]

    def test_has_slots(self) -> None:
        row = self._make()
        assert not hasattr(row, "__dict__")


class TestCustomerDetailRow:
    def _make(self) -> CustomerDetailRow:
        return CustomerDetailRow(
            id="cust_01abc",
            name="Helena Ribeiro",
            email="helena@clinica.com",
            tax_id_kind="cpf",
            key_count=2,
            registered_at="2026-04-15T12:34:56Z",
            notes="VIP",
        )

    def test_round_trip_fields(self) -> None:
        row = self._make()
        assert row.id == "cust_01abc"
        assert row.name == "Helena Ribeiro"
        assert row.email == "helena@clinica.com"
        assert row.tax_id_kind == "cpf"
        assert row.key_count == 2
        assert row.registered_at == "2026-04-15T12:34:56Z"
        assert row.notes == "VIP"

    def test_is_frozen(self) -> None:
        row = self._make()
        with pytest.raises((AttributeError, TypeError)):
            row.name = "Other"  # type: ignore[misc]

    def test_has_slots(self) -> None:
        assert not hasattr(self._make(), "__dict__")


class TestKeyDetailRow:
    def _make(self) -> KeyDetailRow:
        return KeyDetailRow(
            id="key_01abc",
            customer_id="cust_01abc",
            customer_name="Helena Ribeiro",
            key_prefix="EVb4xk8B",
            status="active",
            billing_mode="manual",
            rate_limit_rpm=60,
            price_monthly=149.0,
            paid_until=None,
            created_at="2026-04-15T12:34:56Z",
            last_used_at=None,
            age_days=2,
            notes="",
        )

    def test_round_trip_fields(self) -> None:
        row = self._make()
        assert row.id == "key_01abc"
        assert row.customer_id == "cust_01abc"
        assert row.customer_name == "Helena Ribeiro"
        assert row.key_prefix == "EVb4xk8B"
        assert row.status == "active"
        assert row.billing_mode == "manual"
        assert row.rate_limit_rpm == 60
        assert row.price_monthly == 149.0
        assert row.paid_until is None
        assert row.created_at == "2026-04-15T12:34:56Z"
        assert row.last_used_at is None
        assert row.age_days == 2
        assert row.notes == ""

    def test_is_frozen(self) -> None:
        row = self._make()
        with pytest.raises((AttributeError, TypeError)):
            row.customer_name = "Other"  # type: ignore[misc]

    def test_has_slots(self) -> None:
        assert not hasattr(self._make(), "__dict__")


class TestAuditEventRow:
    def _make(self) -> AuditEventRow:
        return AuditEventRow(
            id=42,
            occurred_at="2026-04-15T10:30:00Z",
            actor="cli:ricardo",
            action="issue_key",
            target_type="api_key",
            target_id="key_01abc",
            details_json='{"billing_mode": "manual", "rate_limit_rpm": 60}',
        )

    def test_round_trip_fields(self) -> None:
        ev = self._make()
        assert ev.id == 42
        assert ev.occurred_at == "2026-04-15T10:30:00Z"
        assert ev.actor == "cli:ricardo"
        assert ev.action == "issue_key"
        assert ev.target_type == "api_key"
        assert ev.target_id == "key_01abc"
        assert ev.details_json == '{"billing_mode": "manual", "rate_limit_rpm": 60}'

    def test_allows_null_details(self) -> None:
        ev = AuditEventRow(
            id=1,
            occurred_at="2026-04-15T10:30:00Z",
            actor="cli:ricardo",
            action="create_customer",
            target_type="customer",
            target_id="cust_01abc",
            details_json=None,
        )
        assert ev.details_json is None

    def test_is_frozen(self) -> None:
        ev = self._make()
        with pytest.raises((AttributeError, TypeError)):
            ev.actor = "Other"  # type: ignore[misc]

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


class TestAuthPayload:
    def _make(self) -> AuthPayload:
        return AuthPayload(
            customer_id="cust_01abc",
            key_id="key_01abc",
            status="active",
            billing_mode="manual",
            rate_limit_rpm=60,
            paid_until="2099-12-31",
        )

    def test_is_frozen_and_hashable(self) -> None:
        payload_a = self._make()
        payload_b = self._make()
        assert payload_a == payload_b
        assert hash(payload_a) == hash(payload_b)
        with pytest.raises((AttributeError, TypeError)):
            payload_a.status = "suspended"  # type: ignore[misc]

    def test_rejects_extra_attributes(self) -> None:
        payload = self._make()
        assert not hasattr(payload, "__dict__")
        for forbidden in ("name", "email", "tax_id_encrypted", "key_hash", "plaintext"):
            assert not hasattr(payload, forbidden)
        with pytest.raises((AttributeError, TypeError)):
            payload.name = "leak"  # type: ignore[attr-defined]

    def test_paid_until_none_accepted_for_complimentary(self) -> None:
        payload = AuthPayload(
            customer_id="cust_01abc",
            key_id="key_01abc",
            status="active",
            billing_mode="complimentary",
            rate_limit_rpm=120,
            paid_until=None,
        )
        assert payload.paid_until is None
        assert payload.billing_mode == "complimentary"


class TestRevenueReport:
    def _make(self) -> RevenueReport:
        return RevenueReport(
            month_label="May 2026",
            month_iso="2026-05",
            paid_count=12,
            pending_count=2,
            suspended_count=0,
            complimentary_count=1,
            mrr=1788.0,
            projected=2086.0,
            next_charge_date="2026-06-05",
            complimentary_rows=(),
        )

    def test_round_trip_fields(self) -> None:
        r = self._make()
        assert r.month_label == "May 2026"
        assert r.month_iso == "2026-05"
        assert r.paid_count == 12
        assert r.pending_count == 2
        assert r.suspended_count == 0
        assert r.complimentary_count == 1
        assert r.mrr == 1788.0
        assert r.projected == 2086.0
        assert r.next_charge_date == "2026-06-05"
        assert r.complimentary_rows == ()

    def test_is_frozen(self) -> None:
        r = self._make()
        with pytest.raises((AttributeError, TypeError)):
            r.mrr = 0.0  # type: ignore[misc]

    def test_has_slots(self) -> None:
        r = self._make()
        assert not hasattr(r, "__dict__")
