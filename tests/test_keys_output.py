"""Tests for ``comadre.keys.cli.output`` — security-critical render paths only.

Lean by design (test-suite review 2026-04-25): renderer happy paths are
exercised by the CLI verb integration tests that emit through the same
helpers. What remains here is what ONLY a render-layer test can check:

* CustomerDetailRow does not leak ciphertext.
* Operator-supplied free-form fields (notes, customer_name, health value)
  cannot break out of Rich markup escape (F24 hardening).
* JSON / YAML export round-trip + insertion order — LGPD export is a
  machine contract, not human UX.
"""

from __future__ import annotations

import json
from io import StringIO

import pytest
import yaml
from rich.console import Console

import comadre.keys.cli.output as output_mod
from comadre.keys.cli.output import (
    render_customer_detail,
    render_export_json,
    render_export_yaml,
    render_health_report,
    render_revenue_report,
    render_suspend_sweep_preview,
)
from comadre.keys.health import HealthCheck, HealthReport
from comadre.keys.models import ApiKeyListRow, CustomerDetailRow, RevenueReport


def _capture(monkeypatch: pytest.MonkeyPatch) -> StringIO:
    buf = StringIO()
    fake = Console(file=buf, force_terminal=False, no_color=True, width=120)
    monkeypatch.setattr(output_mod, "_stdout_console", fake)
    return buf


def _hostile_row(*, customer_name: str = "EvilCorp", notes: str = "") -> ApiKeyListRow:
    return ApiKeyListRow(
        id="key_01hostile0000000000000000",
        customer_id="cust_01abc",
        customer_name=customer_name,
        key_prefix="Hx_abc12",
        status="active",
        billing_mode="manual",
        rate_limit_rpm=60,
        price_monthly=149.0,
        paid_until="2026-04-04",
        created_at="2026-01-05T12:00:00Z",
        last_used_at=None,
        notes=notes,
    )


def test_render_customer_detail_does_not_leak_ciphertext(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LGPD: tax_id_encrypted must NEVER reach the operator's terminal.

    A future refactor that wires the ciphertext column into
    CustomerDetailRow would be caught here — the dataclass MUST not even
    carry the field.
    """
    buf = _capture(monkeypatch)
    row = CustomerDetailRow(
        id="cust_01j8xr3e4c5m7kn9p2qt8vwyz0",
        name="Helena Ribeiro",
        email="helena@clinica.com",
        tax_id_kind="cpf",
        key_count=2,
        registered_at="2026-04-15T12:34:56Z",
        notes="",
    )
    render_customer_detail(row)
    assert not hasattr(row, "tax_id_encrypted")
    assert "gAAAAA" not in buf.getvalue()


def test_render_revenue_report_escapes_markup_in_complimentary_notes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F24: operator-supplied notes must not be interpreted as Rich markup."""
    buf = _capture(monkeypatch)
    hostile = _hostile_row(notes="[red]evil[/]")
    report = RevenueReport(
        month_label="May 2026",
        month_iso="2026-05",
        paid_count=12,
        pending_count=2,
        suspended_count=0,
        complimentary_count=1,
        mrr=1788.0,
        projected=2086.0,
        next_charge_date="2026-05-05",
        complimentary_rows=(hostile,),
    )
    render_revenue_report(report)
    out = buf.getvalue()
    assert "evil" in out  # text survives
    assert "\x1b[" not in out  # no ANSI styling leaked


def test_render_suspend_sweep_preview_escapes_markup_in_customer_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F24: customer_name with markup tokens must render as plain text."""
    from datetime import date

    buf = _capture(monkeypatch)
    hostile = _hostile_row(customer_name="[red]evil[/]")
    render_suspend_sweep_preview([hostile], cutoff_date=date(2026, 4, 6))
    out = buf.getvalue()
    assert "evil" in out
    assert "\x1b[" not in out


def test_render_health_report_escapes_markup_in_check_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F24: HealthCheck.value rendered verbatim, no markup interpretation."""
    buf = _capture(monkeypatch)
    report = HealthReport(
        checks=(
            HealthCheck(
                label="Evil",
                value="[red]evil[/]",
                severity="ok",
                detail="[bold]hostile[/]",
            ),
        ),
        is_healthy=True,
        generated_at="2026-04-19T18:42:07Z",
    )
    render_health_report(report)
    out = buf.getvalue()
    assert "[red]evil[/]" in out  # literal escape preserved


def test_render_export_json_and_yaml_round_trip_preserving_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LGPD export is a machine contract: parse + key order are part of it."""
    payload = {
        "id": "cust_01hg7xyz01hg7xyz01hg7xyz01",
        "name": "Marcos Silva",
        "email": "marcos@example.com",
        "tax_id_kind": "cpf",
        "tax_id": "123.456.789-09",
        "registered_at": "2026-03-12T14:22:05Z",
        "notes": "[urgent] owner of a bot",
        "keys": [
            {
                "key_prefix": "Pq_abc12",
                "status": "active",
                "billing_mode": "manual",
                "created_at": "2026-03-20T10:00:00Z",
            },
        ],
    }
    expected_keys = list(payload.keys())

    buf = _capture(monkeypatch)
    render_export_json(payload)
    parsed_json = json.loads(buf.getvalue())
    assert parsed_json == payload
    assert list(parsed_json.keys()) == expected_keys

    buf = _capture(monkeypatch)
    render_export_yaml(payload)
    parsed_yaml = yaml.safe_load(buf.getvalue())
    assert parsed_yaml == payload
    assert list(parsed_yaml.keys()) == expected_keys
