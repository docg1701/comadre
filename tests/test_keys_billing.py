"""Tests for comadre.keys.billing — first-charge math + payment currency."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from comadre.keys.billing import days_until, first_charge_date, is_payment_current
from comadre.keys.models import ApiKeyRecord


def _record(
    *, billing_mode: str = "manual", paid_until: str | None = None
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


@pytest.mark.parametrize(
    ("today", "billing_day", "expected"),
    [
        (date(2026, 4, 13), 5, date(2026, 5, 5)),  # mid-month → next month
        (date(2026, 4, 5), 5, date(2026, 5, 5)),  # same-day → next month (AC5)
        (date(2026, 12, 31), 5, date(2027, 1, 5)),  # year rollover
        (date(2026, 1, 4), 5, date(2026, 1, 5)),  # before billing day → same month
    ],
)
def test_first_charge_date_table(today: date, billing_day: int, expected: date) -> None:
    assert first_charge_date(today=today, billing_day=billing_day) == expected


def test_days_until_positive_and_zero() -> None:
    assert days_until(date(2026, 5, 5), from_date=date(2026, 4, 13)) == 22
    assert days_until(date(2026, 4, 13), from_date=date(2026, 4, 13)) == 0


def test_payment_currency_branches() -> None:
    """Complimentary always current; manual depends on paid_until vs today.

    ``paid_until is None`` is the trial window: the ``issue-key`` panel
    advertises a free runway and the auth path honours it. A regression
    here would 401 every freshly-issued manual key (B10, 2026-04-26).
    """
    today = date(2026, 4, 15)
    assert is_payment_current(_record(billing_mode="complimentary"), today=today)
    assert is_payment_current(_record(paid_until=None), today=today)
    assert is_payment_current(_record(paid_until="2026-04-15"), today=today)
    assert not is_payment_current(_record(paid_until="2026-04-14"), today=today)


def test_automated_billing_mode_refused() -> None:
    """No PSP adapter exists — ``automated`` rows fail loudly, never fall
    back to the manual ``paid_until`` semantics."""
    with pytest.raises(ValueError, match="automated"):
        is_payment_current(_record(billing_mode="automated"), today=date(2026, 4, 15))
