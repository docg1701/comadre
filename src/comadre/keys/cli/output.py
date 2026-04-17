"""Shared rich Console singletons and rendering components for the CLI.

UX-DR6 ErrorDisplay — `render_error(title, hint)`: red-bordered Panel on stderr.
UX-DR7 ConfirmationLine — `render_confirmation(message)`: plain single line on stdout.
UX-DR9 Shared Console — singletons avoid terminal redetection between calls.
NO_COLOR compliance — rich respects the env var automatically. We do NOT set
`force_terminal=True` here — that would defeat NO_COLOR.
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel

_stdout_console: Console | None = None
_stderr_console: Console | None = None


def stdout_console() -> Console:
    """Return the shared stdout Console (singleton)."""
    global _stdout_console
    if _stdout_console is None:
        _stdout_console = Console()
    return _stdout_console


def stderr_console() -> Console:
    """Return the shared stderr Console (singleton)."""
    global _stderr_console
    if _stderr_console is None:
        _stderr_console = Console(stderr=True)
    return _stderr_console


def render_error(message: str, hint: str) -> None:
    """UX-DR6: red-bordered Panel on stderr. Caller decides the exit code."""
    stderr_console().print(Panel(hint, title=message, border_style="red", expand=False))


def render_confirmation(message: str) -> None:
    """UX-DR7: plain single-line confirmation on stdout."""
    stdout_console().print(message)


def _reset_for_tests() -> None:
    """Test-only hook: reset console singletons so fixtures can re-wire I/O."""
    global _stdout_console, _stderr_console
    _stdout_console = None
    _stderr_console = None
