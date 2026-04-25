"""Fixture — intentional FR48 violation SUPPRESSED by the allowlist comment.

Consumed by ``test_scan_respects_allowlist_comment``. Exercises the escape
hatch: a same-line ``# scan-allow: <reason>`` comment takes a true violation
out of the scan's output. Reviewer-enforced at PR time.
"""

from __future__ import annotations


def authenticate(token_hash: str, stored_hash: str) -> bool:
    return (
        token_hash == stored_hash
    )  # scan-allow[timing-safe-compare]: fixture-intentional-for-4.5c
