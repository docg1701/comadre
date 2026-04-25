"""F41 — shared helpers for ``tests/test_keys_cli_*.py`` files.

Each test file used to define its own copy of ``_buffers()`` and
``_clear_buffers()`` against the singleton ``Console`` objects in
``comadre.keys.cli.output``. The local copies have been removed; this
module is the single source of truth.

The autouse ``_reset_cli_consoles_to_buffers`` fixture in
``tests/conftest.py`` swaps the singleton consoles for in-memory
buffers before each test runs, so callers can use these helpers
unconditionally.
"""

from __future__ import annotations

from comadre.keys.cli import output as _keys_cli_output


def buffers() -> tuple[str, str]:
    """Return ``(stdout_text, stderr_text)`` from the in-memory consoles."""
    stdout_file = _keys_cli_output._stdout_console.file  # type: ignore[union-attr]
    stderr_file = _keys_cli_output._stderr_console.file  # type: ignore[union-attr]
    return stdout_file.getvalue(), stderr_file.getvalue()


def clear_buffers() -> None:
    """Truncate the stdout/stderr in-memory buffers in place."""
    for attr in ("_stdout_console", "_stderr_console"):
        console = getattr(_keys_cli_output, attr)
        console.file.seek(0)  # type: ignore[union-attr]
        console.file.truncate()  # type: ignore[union-attr]
