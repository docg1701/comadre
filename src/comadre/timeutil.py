"""Shared UTC timestamp helpers — single source for every ISO-UTC surface.

Lives at the bottom of the import graph (stdlib only) so service,
counters, keys/db, keys/audit, keys/health, and the CLI commands can all
consume it without creating lateral or upward deps.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo


def utc_now_iso() -> str:
    """Return now as ``YYYY-MM-DDTHH:MM:SSZ`` (UTC, second precision)."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso_utc(value: object) -> datetime | None:
    """Parse an ISO 8601 UTC timestamp; ``None`` on any failure.

    Tolerates both ``Z`` and ``+HH:MM`` suffixes; naive values are coerced
    to UTC. Accepts ``object`` so JSON-decoded scalars can be passed
    directly.
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def resolve_today_in_tz(tz: ZoneInfo) -> date:
    """Return today's date resolved in ``tz``. Thin seam for tests."""
    return datetime.now(tz).date()


def iso_utc(dt: datetime) -> str:
    """Return ``dt`` as ``YYYY-MM-DDTHH:MM:SSZ`` (UTC). Naive → UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def iso_utc_or_none(dt: datetime | None) -> str | None:
    """``iso_utc`` or ``None`` — for nullable timestamp columns."""
    if dt is None:
        return None
    return iso_utc(dt)


def now_utc() -> datetime:
    """Return ``now`` as aware UTC datetime. Test seam for service sweep."""
    return datetime.now(UTC)
