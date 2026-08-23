"""Manual-billing payment check and first-charge math.

Single billing mode today (operator-driven); a PSP adapter would introduce
the provider abstraction when it actually exists.
"""

from __future__ import annotations

from datetime import date

from comadre.keys.models import ApiKeyRecord


def is_payment_current(key: ApiKeyRecord, *, today: date) -> bool:
    """Return True when the key is currently paid / allowed to serve."""
    if key.billing_mode == "complimentary":
        return True
    if key.billing_mode == "automated":
        # No PSP adapter exists yet; an `automated` row was either
        # planted by a future-version write or by direct SQL edit. Refuse
        # rather than silently treating as `manual` — the manual paid_until
        # field is meaningless for automated billing.
        raise ValueError(
            "billing_mode='automated' is not supported "
            "(no PSP adapter installed); use 'manual' or 'complimentary'."
        )
    if key.paid_until is None:
        # Never marked paid — trial window. The ``issue-key`` panel
        # advertises a free runway up to ``first_charge_date`` and the
        # auth path honours it (allow-while-active SLA). Story 3.3's
        # sweep also leaves NULL rows alone (predicate is strict
        # ``paid_until < ?`` — NULL compares as NULL, not true). The
        # operator transitions out of trial via ``mark-paid``, which
        # writes a concrete date that this branch then evaluates.
        return True
    # Malformed paid_until raises ``ValueError``; the auth path catches
    # it, logs ERROR, and fails closed via ``ApiKeySuspendedError`` —
    # see ``comadre.keys.auth.verify_api_key_registry``.
    return date.fromisoformat(key.paid_until) >= today


def first_charge_date(*, today: date, billing_day: int) -> date:
    """Next occurrence of ``billing_day`` strictly after ``today``.

    Rule: if ``today.day == billing_day`` the next charge is next month's
    billing day (issuing on day 05 gives the rest of the month free; see
    Story 1.2 AC5).
    """
    if today.day < billing_day:
        return today.replace(day=billing_day)
    if today.month == 12:
        return date(today.year + 1, 1, billing_day)
    return date(today.year, today.month + 1, billing_day)


def days_until(d: date, *, from_date: date) -> int:
    """Whole-day delta from ``from_date`` to ``d``."""
    return (d - from_date).days
