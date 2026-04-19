"""Shared humanizers used across the keys CLI and health collector.

Sits below ``cli.output`` and ``keys.health`` in the import graph so both
can consume the same renderer without creating a cycle. Kept minimal:
only helpers that are genuinely used in more than one module live here.
"""

from __future__ import annotations


def format_seconds_ago(seconds: int) -> str:
    """Render an age in seconds as a compact human duration.

    Clamps negatives to zero so a small clock skew never produces
    ``-1s ago``. Output shape: ``Ns ago``, ``Nm ago``, ``Nh MMm ago``,
    ``Nd HHh ago``.
    """
    seconds = max(0, seconds)
    if seconds < 60:
        return f"{seconds}s ago"
    minutes, _ = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m ago"
    hours, remaining_minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {remaining_minutes:02d}m ago"
    days, remaining_hours = divmod(hours, 24)
    return f"{days}d {remaining_hours:02d}h ago"
