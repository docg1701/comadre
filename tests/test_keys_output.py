"""Tests for comadre.keys.cli.output."""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime
from io import StringIO

import pytest
from rich.console import Console

import comadre.keys.cli.output as output_mod
from comadre.keys.cli.output import (
    _reset_for_tests,
    _status_label,
    render_confirmation,
    render_customer_list,
    render_empty_state,
    render_error,
    render_json,
    render_key_list,
    render_key_panel,
    stderr_console,
    stdout_console,
)
from comadre.keys.models import (
    ApiKeyListRow,
    ApiKeyRecord,
    CustomerListRow,
    IssuedKey,
)

ANSI_ESCAPE = re.compile(r"\x1b\[")


@pytest.fixture(autouse=True)
def _reset_consoles() -> Iterator[None]:
    _reset_for_tests()
    yield
    _reset_for_tests()


class TestConsoleSingletons:
    def test_stdout_singleton(self) -> None:
        first = stdout_console()
        second = stdout_console()
        assert first is second

    def test_stderr_singleton(self) -> None:
        first = stderr_console()
        second = stderr_console()
        assert first is second

    def test_stdout_and_stderr_are_distinct(self) -> None:
        assert stdout_console() is not stderr_console()


class TestRenderConfirmation:
    def test_writes_to_stdout_with_captured_console(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        buf = StringIO()
        fake = Console(file=buf, force_terminal=False, no_color=True, width=120)
        monkeypatch.setattr(output_mod, "_stdout_console", fake)
        render_confirmation("Customer created: cust_01abc (Helena)")
        out = buf.getvalue()
        assert "Customer created: cust_01abc (Helena)" in out
        # No Rich border characters
        assert "╭" not in out and "╰" not in out


class TestRenderError:
    def test_writes_panel_with_title_and_hint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        buf = StringIO()
        fake = Console(file=buf, force_terminal=False, no_color=True, width=120)
        monkeypatch.setattr(output_mod, "_stderr_console", fake)
        render_error("Invalid CPF: checksum verification failed", "Verify the digits.")
        out = buf.getvalue()
        assert "Invalid CPF: checksum verification failed" in out
        assert "Verify the digits." in out

    def test_no_color_produces_no_ansi(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With NO_COLOR, rich emits no ANSI escape sequences."""
        monkeypatch.setenv("NO_COLOR", "1")
        buf = StringIO()
        # Let rich pick up NO_COLOR via env; do not pass no_color explicitly.
        fake = Console(file=buf, force_terminal=False, width=120)
        monkeypatch.setattr(output_mod, "_stderr_console", fake)
        render_error("Configuration error", "KEY_REGISTRY_ENCRYPTION_KEY missing.")
        out = buf.getvalue()
        assert not ANSI_ESCAPE.search(out)


_MANUAL_PLAINTEXT = "cmdr_live_KQjPz8vR9NwT3MxAbYcH5dLeFgJ2nSsU_ab"


def _manual_issued(plaintext: str = _MANUAL_PLAINTEXT) -> IssuedKey:
    rec = ApiKeyRecord(
        id="key_01abcdefghijklmnopqrstuvwx",
        customer_id="cust_01j8xr3e4c5m7kn9p2qt8vwyz0",
        key_hash="a" * 64,
        key_prefix="KQjPz8vR",
        rate_limit_rpm=60,
        status="active",
        billing_mode="manual",
        price_monthly=149.0,
        paid_until=None,
        created_at=datetime(2026, 4, 13, 12, 0, 0, tzinfo=UTC),
        last_used_at=None,
        notes="",
    )
    return IssuedKey(
        plaintext=plaintext,
        record=rec,
        customer_name="Helena Ribeiro",
        first_charge_date="2026-05-05",
        first_charge_days_free=22,
    )


def _complimentary_issued() -> IssuedKey:
    rec = ApiKeyRecord(
        id="key_01xyzabcdefghijklmnopqrst",
        customer_id="cust_01j8xr3e4c5m7kn9p2qt8vwyz0",
        key_hash="b" * 64,
        key_prefix="COMP1234",
        rate_limit_rpm=120,
        status="active",
        billing_mode="complimentary",
        price_monthly=0.0,
        paid_until=None,
        created_at=datetime(2026, 4, 13, 12, 0, 0, tzinfo=UTC),
        last_used_at=None,
        notes="infra bundle",
    )
    return IssuedKey(
        plaintext="cmdr_live_complimentary_token_sample_abcdef_12",
        record=rec,
        customer_name="Infra Bundle Co",
        first_charge_date=None,
        first_charge_days_free=None,
    )


class TestRenderKeyPanelManual:
    def test_plaintext_line_has_no_border_or_indent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC4 surrogate: the plaintext line is ONLY the key, no borders or indent."""
        buf = StringIO()
        fake = Console(file=buf, force_terminal=False, no_color=True, width=120)
        monkeypatch.setattr(output_mod, "_stdout_console", fake)
        issued = _manual_issued()
        render_key_panel(issued)

        lines = buf.getvalue().split("\n")
        plaintext_lines = [line for line in lines if issued.plaintext in line]
        assert len(plaintext_lines) == 1, (
            f"Expected exactly 1 plaintext line, got {len(plaintext_lines)}"
        )
        line = plaintext_lines[0]
        # AC4: .strip() == plaintext (no border chars on the line).
        assert line.strip() == issued.plaintext
        # AC4: line[0] is not whitespace (starts with the key at column 0).
        assert line[0] not in (" ", "\t", "\u00a0", "\u2551", "\u2502")
        # Key itself starts the line exactly.
        assert line.startswith(issued.plaintext)

    def test_plaintext_appears_exactly_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        buf = StringIO()
        fake = Console(file=buf, force_terminal=False, no_color=True, width=120)
        monkeypatch.setattr(output_mod, "_stdout_console", fake)
        issued = _manual_issued()
        render_key_panel(issued)
        out = buf.getvalue()
        assert out.count(issued.plaintext) == 1

    def test_contains_copy_now_warning(self, monkeypatch: pytest.MonkeyPatch) -> None:
        buf = StringIO()
        fake = Console(file=buf, force_terminal=False, no_color=True, width=120)
        monkeypatch.setattr(output_mod, "_stdout_console", fake)
        render_key_panel(_manual_issued())
        out = buf.getvalue()
        assert "copy now" in out
        assert "shown only once" in out

    def test_double_border_characters_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Double-border Panel should render with ║/═ Unicode box chars."""
        buf = StringIO()
        fake = Console(file=buf, force_terminal=False, no_color=True, width=120)
        monkeypatch.setattr(output_mod, "_stdout_console", fake)
        render_key_panel(_manual_issued())
        out = buf.getvalue()
        assert "\u2551" in out  # ║
        assert "\u2550" in out  # ═

    def test_manual_shows_price_and_first_charge(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        buf = StringIO()
        fake = Console(file=buf, force_terminal=False, no_color=True, width=120)
        monkeypatch.setattr(output_mod, "_stdout_console", fake)
        render_key_panel(_manual_issued())
        out = buf.getvalue()
        # pt-BR number format: comma decimal separator.
        assert "R$ 149,00/month" in out
        assert "first charge: 2026-05-05 (22 days free until then)" in out

    def test_manual_price_uses_ptbr_thousands_separator(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Brazilian format: dot thousands, comma decimal (R$ 1.234,56)."""
        buf = StringIO()
        fake = Console(file=buf, force_terminal=False, no_color=True, width=120)
        monkeypatch.setattr(output_mod, "_stdout_console", fake)
        rec = ApiKeyRecord(
            id="key_01pricey",
            customer_id="cust_01j8xr3e4c5m7kn9p2qt8vwyz0",
            key_hash="c" * 64,
            key_prefix="HIGHCOST",
            rate_limit_rpm=600,
            status="active",
            billing_mode="manual",
            price_monthly=12345.67,
            paid_until=None,
            created_at=datetime(2026, 4, 13, 12, 0, 0, tzinfo=UTC),
            last_used_at=None,
            notes="",
        )
        issued = IssuedKey(
            plaintext="cmdr_live_HIGHCOST_KEY_TOKEN_abcdefghijklmnopqrst_a",
            record=rec,
            customer_name="Enterprise Co",
            first_charge_date="2026-05-05",
            first_charge_days_free=22,
        )
        render_key_panel(issued)
        out = buf.getvalue()
        assert "R$ 12.345,67/month" in out

    def test_labels_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        buf = StringIO()
        fake = Console(file=buf, force_terminal=False, no_color=True, width=120)
        monkeypatch.setattr(output_mod, "_stdout_console", fake)
        render_key_panel(_manual_issued())
        out = buf.getvalue()
        for label in (
            "prefix:",
            "customer:",
            "rate limit:",
            "billing mode:",
            "price:",
            "first charge:",
        ):
            assert label in out

    def test_blank_line_between_plaintext_and_context_panel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC1: a blank line must separate the plaintext from the labeled rows."""
        buf = StringIO()
        fake = Console(file=buf, force_terminal=False, no_color=True, width=120)
        monkeypatch.setattr(output_mod, "_stdout_console", fake)
        issued = _manual_issued()
        render_key_panel(issued)

        lines = buf.getvalue().split("\n")
        pt_idx = next(i for i, line in enumerate(lines) if issued.plaintext in line)
        # The line immediately after the plaintext must be empty (no content,
        # no border chars — a clean visual gap before the context Panel).
        assert lines[pt_idx + 1].strip() == ""

    def test_customer_name_and_id_on_customer_row(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        buf = StringIO()
        fake = Console(file=buf, force_terminal=False, no_color=True, width=120)
        monkeypatch.setattr(output_mod, "_stdout_console", fake)
        render_key_panel(_manual_issued())
        out = buf.getvalue()
        assert "Helena Ribeiro (cust_01j8xr3e4c5m7kn9p2qt8vwyz0)" in out

    def test_no_color_env_produces_no_ansi(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """NO_COLOR compliance: rich must emit no ANSI escape sequences."""
        monkeypatch.setenv("NO_COLOR", "1")
        buf = StringIO()
        # Do NOT pass no_color explicitly — force rich to honour the env var.
        fake = Console(file=buf, force_terminal=False, width=120)
        monkeypatch.setattr(output_mod, "_stdout_console", fake)
        render_key_panel(_manual_issued())
        out = buf.getvalue()
        assert not ANSI_ESCAPE.search(out)


class TestRenderKeyPanelComplimentary:
    def test_complimentary_variant_labels(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        buf = StringIO()
        fake = Console(file=buf, force_terminal=False, no_color=True, width=120)
        monkeypatch.setattr(output_mod, "_stdout_console", fake)
        render_key_panel(_complimentary_issued())
        out = buf.getvalue()
        # pt-BR number format: comma decimal separator.
        assert "R$ 0,00 (bundled externally)" in out
        assert "paid until:" in out
        # AC2: em-dash (U+2014), not hyphen-minus.
        assert "\u2014 (not applicable)" in out
        # AC2: no "first charge:" line for complimentary.
        assert "first charge:" not in out

    def test_complimentary_does_not_show_price_month_suffix(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        buf = StringIO()
        fake = Console(file=buf, force_terminal=False, no_color=True, width=120)
        monkeypatch.setattr(output_mod, "_stdout_console", fake)
        render_key_panel(_complimentary_issued())
        out = buf.getvalue()
        # Manual variant says "R$ 149.00/month"; complimentary must not use /month.
        assert "/month" not in out

    def test_complimentary_plaintext_line_has_no_border(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        buf = StringIO()
        fake = Console(file=buf, force_terminal=False, no_color=True, width=120)
        monkeypatch.setattr(output_mod, "_stdout_console", fake)
        issued = _complimentary_issued()
        render_key_panel(issued)
        lines = buf.getvalue().split("\n")
        [line] = [line for line in lines if issued.plaintext in line]
        assert line.strip() == issued.plaintext
        assert line[0] not in (" ", "\t", "\u00a0")


class TestStatusLabel:
    """UX-DR8 — four-color palette with text-first labeling."""

    def test_active_manual(self) -> None:
        assert _status_label("active", "manual") == ("active", "green")

    def test_active_complimentary_shows_complimentary(self) -> None:
        # The blue complimentary badge supersedes active/green because it
        # carries the operator-meaningful "bundled, not billed" signal.
        assert _status_label("active", "complimentary") == ("complimentary", "blue")

    def test_suspended(self) -> None:
        assert _status_label("suspended", "manual") == ("suspended", "yellow")

    def test_revoked(self) -> None:
        assert _status_label("revoked", "manual") == ("revoked", "red")

    def test_suspended_complimentary_still_renders_as_complimentary(self) -> None:
        # Edge case: if a complimentary key is later suspended (Story 3.1
        # territory), the complimentary label still wins because the
        # billing-mode signal is the operator's scan target.
        assert _status_label("suspended", "complimentary") == (
            "complimentary",
            "blue",
        )


def _customer_rows() -> list[CustomerListRow]:
    return [
        CustomerListRow(
            id="cust_01helena000000000000000000",
            name="Helena Ribeiro",
            email="helena@clinica.com",
            tax_id_kind="cpf",
            key_count=2,
            registered_at="2026-04-10T10:00:00Z",
            deleted_at=None,
            notes="",
        ),
        CustomerListRow(
            id="cust_01bruno0000000000000000000",
            name="Bruno Aragao",
            email="bruno@boteco.com",
            tax_id_kind="cnpj",
            key_count=0,
            registered_at="2026-04-11T10:00:00Z",
            deleted_at=None,
            notes="",
        ),
    ]


class TestRenderCustomerList:
    def test_populated_table_contents(self, monkeypatch: pytest.MonkeyPatch) -> None:
        buf = StringIO()
        fake = Console(file=buf, force_terminal=False, no_color=True, width=120)
        monkeypatch.setattr(output_mod, "_stdout_console", fake)
        render_customer_list("Customers", _customer_rows())
        out = buf.getvalue()
        # Title, column headers, row contents.
        assert "Customers" in out
        for header in ("Customer ID", "Name", "Email", "Keys", "Registered"):
            assert header in out
        assert "Helena Ribeiro" in out
        assert "helena@clinica.com" in out
        assert "cust_01helena000000000000000000" in out
        assert "cust_01bruno0000000000000000000" in out
        # ISO date truncation — not the full timestamp.
        assert "2026-04-10" in out
        assert "12:00:00" not in out
        # Trailer with count.
        assert "2 customers found." in out


class TestRenderKeyList:
    def _rows(self) -> list[ApiKeyListRow]:
        return [
            ApiKeyListRow(
                id="key_01active00000000000000000",
                customer_id="cust_01helena000000000000000000",
                customer_name="Helena Ribeiro",
                key_prefix="EVb4xk8B",
                status="active",
                billing_mode="manual",
                rate_limit_rpm=60,
                price_monthly=149.0,
                paid_until=None,
                created_at="2026-04-10T10:00:00Z",
                last_used_at=None,
            ),
            ApiKeyListRow(
                id="key_01suspend000000000000000",
                customer_id="cust_01helena000000000000000000",
                customer_name="Helena Ribeiro",
                key_prefix="SUSpENdd",
                status="suspended",
                billing_mode="manual",
                rate_limit_rpm=60,
                price_monthly=1234.56,
                paid_until="2026-04-01",
                created_at="2026-04-11T10:00:00Z",
                last_used_at=None,
            ),
            ApiKeyListRow(
                id="key_01revoked00000000000000",
                customer_id="cust_01bruno0000000000000000000",
                customer_name="Bruno Aragao",
                key_prefix="REvOKEdd",
                status="revoked",
                billing_mode="manual",
                rate_limit_rpm=60,
                price_monthly=99.0,
                paid_until="2026-05-01",
                created_at="2026-04-12T10:00:00Z",
                last_used_at=None,
            ),
            ApiKeyListRow(
                id="key_01comp000000000000000000",
                customer_id="cust_01bruno0000000000000000000",
                customer_name="Bruno Aragao",
                key_prefix="COMPlmnt",
                status="active",
                billing_mode="complimentary",
                rate_limit_rpm=120,
                price_monthly=0.0,
                paid_until=None,
                created_at="2026-04-13T10:00:00Z",
                last_used_at=None,
            ),
        ]

    def test_populated_has_all_labels(self, monkeypatch: pytest.MonkeyPatch) -> None:
        buf = StringIO()
        fake = Console(file=buf, force_terminal=False, no_color=True, width=120)
        monkeypatch.setattr(output_mod, "_stdout_console", fake)
        render_key_list("Keys", self._rows())
        out = buf.getvalue()
        for header in ("Prefix", "Customer", "Status", "RPM", "Price", "Paid Until"):
            assert header in out
        # Each status label renders as plain text (NO_COLOR strips the style).
        for label in ("active", "suspended", "revoked", "complimentary"):
            assert label in out
        assert "4 keys found." in out

    def test_price_formatting(self, monkeypatch: pytest.MonkeyPatch) -> None:
        buf = StringIO()
        fake = Console(file=buf, force_terminal=False, no_color=True, width=120)
        monkeypatch.setattr(output_mod, "_stdout_console", fake)
        render_key_list("Keys", self._rows())
        out = buf.getvalue()
        # pt-BR format for manual keys.
        assert "R$ 149,00/month" in out
        assert "R$ 1.234,56/month" in out
        # Complimentary keys show R$ 0,00 with no /month suffix.
        assert "R$ 0,00" in out
        # And no complimentary row ends in /month.
        comp_lines = [line for line in out.split("\n") if "COMPlmnt" in line]
        assert comp_lines, "complimentary row missing"
        for line in comp_lines:
            assert "/month" not in line

    def test_paid_until_emdash_for_null_and_complimentary(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        buf = StringIO()
        fake = Console(file=buf, force_terminal=False, no_color=True, width=120)
        monkeypatch.setattr(output_mod, "_stdout_console", fake)
        render_key_list("Keys", self._rows())
        out = buf.getvalue()
        # U+2014 em-dash (not hyphen-minus).
        assert "\u2014" in out
        # ISO-date slice for the dated rows.
        assert "2026-04-01" in out
        assert "2026-05-01" in out


class TestRenderJson:
    def test_matches_payload_shape(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import json

        buf = StringIO()
        fake = Console(file=buf, force_terminal=False, no_color=True, width=120)
        monkeypatch.setattr(output_mod, "_stdout_console", fake)
        payload: list[dict[str, object]] = [
            {"id": "cust_01abc", "name": "Helena", "key_count": 2},
            {"id": "cust_01xyz", "name": "Bruno", "key_count": 0},
        ]
        render_json(payload)
        out = buf.getvalue()
        parsed = json.loads(out)
        assert parsed == payload

    def test_empty_is_empty_array(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import json

        buf = StringIO()
        fake = Console(file=buf, force_terminal=False, no_color=True, width=120)
        monkeypatch.setattr(output_mod, "_stdout_console", fake)
        render_json([])
        assert json.loads(buf.getvalue()) == []


class TestRenderEmptyState:
    def test_two_lines(self, monkeypatch: pytest.MonkeyPatch) -> None:
        buf = StringIO()
        fake = Console(file=buf, force_terminal=False, no_color=True, width=120)
        monkeypatch.setattr(output_mod, "_stdout_console", fake)
        render_empty_state(
            [
                "No customers registered yet.",
                'To get started: comadre-keys create-customer --name "Name" '
                '--email "email@example.com" --cpf "000.000.000-00"',
            ]
        )
        out = buf.getvalue()
        assert "No customers registered yet." in out
        assert "To get started: comadre-keys create-customer" in out
        # No Rich panel characters (plain confirmation lines only).
        assert "╭" not in out
        assert "╰" not in out

    def test_single_line(self, monkeypatch: pytest.MonkeyPatch) -> None:
        buf = StringIO()
        fake = Console(file=buf, force_terminal=False, no_color=True, width=120)
        monkeypatch.setattr(output_mod, "_stdout_console", fake)
        render_empty_state(["No suspended keys found."])
        assert "No suspended keys found." in buf.getvalue()
