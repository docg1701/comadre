"""Tests for comadre.keys.cli.output."""

from __future__ import annotations

import re
from collections.abc import Iterator
from io import StringIO

import pytest
from rich.console import Console

import comadre.keys.cli.output as output_mod
from comadre.keys.cli.output import (
    _reset_for_tests,
    render_confirmation,
    render_error,
    stderr_console,
    stdout_console,
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
