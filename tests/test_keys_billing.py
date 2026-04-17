"""Tests for comadre.keys.billing — first-charge math + ManualBillingProvider."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from comadre.keys.billing import (
    BillingProvider,
    ManualBillingProvider,
    days_until,
    first_charge_date,
)
from comadre.keys.models import ApiKeyRecord

_TZ = "America/Sao_Paulo"


def _record(
    *,
    billing_mode: str = "manual",
    paid_until: str | None = None,
) -> ApiKeyRecord:
    return ApiKeyRecord(
        id="key_01abc",
        customer_id="cust_01j8xr3e4c5m7kn9p2qt8vwyz0",
        key_hash="a" * 64,
        key_prefix="ABCDEFGH",
        rate_limit_rpm=60,
        status="active",
        billing_mode=billing_mode,  # type: ignore[arg-type]
        price_monthly=149.0 if billing_mode == "manual" else 0.0,
        paid_until=paid_until,
        created_at=datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC),
        last_used_at=None,
        notes="",
    )


class TestFirstChargeDate:
    @pytest.mark.parametrize(
        ("today", "billing_day", "expected"),
        [
            # Mid-month after billing day — rolls to next month's billing day.
            (date(2026, 4, 13), 5, date(2026, 5, 5)),
            # Same-day — AC5 rule: rolls to next month.
            (date(2026, 4, 5), 5, date(2026, 5, 5)),
            (date(2026, 5, 5), 5, date(2026, 6, 5)),
            # Day-after — rolls to next month.
            (date(2026, 4, 6), 5, date(2026, 5, 5)),
            # Year rollover when today is in December after billing day.
            (date(2026, 12, 31), 5, date(2027, 1, 5)),
            (date(2026, 12, 5), 5, date(2027, 1, 5)),
            # End-of-February -> March billing day.
            (date(2026, 2, 28), 5, date(2026, 3, 5)),
            # Before billing day in January — stays in January.
            (date(2026, 1, 4), 5, date(2026, 1, 5)),
        ],
    )
    def test_table(self, today: date, billing_day: int, expected: date) -> None:
        result = first_charge_date(today=today, billing_day=billing_day, tz=_TZ)
        assert result == expected


class TestDaysUntil:
    def test_positive(self) -> None:
        assert days_until(date(2026, 5, 5), from_date=date(2026, 4, 13)) == 22

    def test_zero(self) -> None:
        assert days_until(date(2026, 4, 13), from_date=date(2026, 4, 13)) == 0


class TestManualBillingProvider:
    def test_complimentary_always_current(self) -> None:
        provider = ManualBillingProvider()
        rec = _record(billing_mode="complimentary")
        assert provider.is_payment_current(rec, today=date(2026, 4, 13)) is True

    def test_manual_paid_until_none_not_current(self) -> None:
        provider = ManualBillingProvider()
        rec = _record(billing_mode="manual", paid_until=None)
        assert provider.is_payment_current(rec, today=date(2026, 4, 13)) is False

    def test_manual_paid_until_equals_today_is_current(self) -> None:
        provider = ManualBillingProvider()
        rec = _record(billing_mode="manual", paid_until="2026-04-15")
        assert provider.is_payment_current(rec, today=date(2026, 4, 15)) is True

    def test_manual_paid_until_past_not_current(self) -> None:
        provider = ManualBillingProvider()
        rec = _record(billing_mode="manual", paid_until="2026-04-14")
        assert provider.is_payment_current(rec, today=date(2026, 4, 15)) is False

    def test_on_key_issued_noop(self) -> None:
        provider = ManualBillingProvider()
        rec = _record()
        assert provider.on_key_issued(rec) is None

    def test_on_key_revoked_noop(self) -> None:
        provider = ManualBillingProvider()
        rec = _record()
        assert provider.on_key_revoked(rec) is None

    def test_is_billing_provider_subclass(self) -> None:
        assert issubclass(ManualBillingProvider, BillingProvider)

    def test_abc_cannot_be_instantiated(self) -> None:
        with pytest.raises(TypeError):
            BillingProvider()  # type: ignore[abstract]
