"""FR51 non-regression — no raw ``HTTPException`` static check (Story 4.5f).

Walks every ``.py`` file under ``src/comadre/`` and asserts:

1. No ``raise HTTPException(...)`` statement (``ast.Raise`` whose ``.exc`` is a
   ``Call`` or ``Name`` whose terminal name is ``"HTTPException"``).
2. No ``from fastapi import HTTPException`` / ``from fastapi.exceptions import
   HTTPException`` / ``from starlette.exceptions import HTTPException``
   statement (``ast.ImportFrom`` whose ``.module`` is in
   ``_IMPORT_SOURCE_MODULES`` and whose ``.names`` contains an alias named
   ``"HTTPException"``).

Inline ``# scan-allow[no-raw-httpexception]: <reason>`` on any physical
line the ``Raise`` or ``ImportFrom`` node spans suppresses the scan for
that node; the comment is reviewer-enforced at PR time. F44 enforces a
>=3 non-whitespace-char reason. F45 — the namespace bracket is mandatory,
so a comment cannot accidentally silence a sibling scan.

The scan's complement is positive: every error path must construct a
``ComadreError`` subclass from ``src/comadre/exceptions.py`` (``VoiceNotFoundError``,
``InvalidRequestError``, ``ApiKeyNotFoundError``, etc.) and let
``comadre_error_handler`` render the project envelope. See
``src/comadre/exceptions.py:18-266`` for the canonical hierarchy.

Docstring mentions of the string ``"HTTPException"`` (e.g., in
``src/comadre/main.py:250,276`` where the 404/405 handlers describe their
role) are structurally outside both rules — ``ast.Constant`` string literals
are neither ``Raise`` nor ``ImportFrom`` nodes. The scan correctly ignores
them without needing an allowlist comment.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pytest

from tests.test_non_regression._scan_common import allowlisted_lines, safe_parse

_PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
_SRC_ROOT: Path = _PROJECT_ROOT / "src" / "comadre"
_FIXTURES_ROOT: Path = (
    Path(__file__).resolve().parent / "fixtures" / "no_raw_httpexception"
)
_SCAN_LABEL: str = "no-raw-httpexception"

_HTTPEXCEPTION_NAME: str = "HTTPException"
# AC7 — all three canonical source modules are covered. FastAPI re-exports
# Starlette's ``HTTPException`` (``fastapi.HTTPException`` is a subclass with
# identical envelope-breaking semantics); ``fastapi.exceptions`` is the
# verbose path some linters suggest; ``starlette.exceptions`` is what an
# ASGI-middleware tutorial would write. Any OTHER import path would be a
# bespoke reimport that deserves its own review rather than a silent pass.
_IMPORT_SOURCE_MODULES: frozenset[str] = frozenset(
    {"fastapi", "fastapi.exceptions", "starlette.exceptions"}
)


@dataclass(frozen=True)
class _Violation:
    path: Path
    lineno: int
    kind: Literal["raise", "import"]
    source: str

    def render(self) -> str:
        rel = self.path.relative_to(_PROJECT_ROOT)
        return (
            f"{rel}:{self.lineno}: raw HTTPException {self.kind} — "
            f"{self.source.strip()}"
        )


def _terminal_function_name(node: ast.expr) -> str | None:
    """Return the terminal name of a Raise's ``.exc`` expression.

    - ``Name(id=X)`` → ``X`` (bare re-raise: ``raise HTTPException``).
    - ``Call(func=Name(id=X))`` → ``X`` (canonical: ``raise HTTPException(...)``).
    - ``Call(func=Attribute(..., attr=X))`` → ``X`` (attribute chain:
      ``raise fastapi.HTTPException(...)``; only the rightmost attr matters).
    - Anything else → ``None``.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
    return None


def _is_raw_httpexception_raise(node: ast.AST) -> bool:
    """True if ``node`` is ``raise <something-named-HTTPException>(...)``."""
    if not isinstance(node, ast.Raise):
        return False
    if node.exc is None:  # bare ``raise`` (re-raise the current exception)
        return False
    return _terminal_function_name(node.exc) == _HTTPEXCEPTION_NAME


def _is_httpexception_import(node: ast.AST) -> bool:
    """True if ``node`` is ``from <fastapi|...> import HTTPException``."""
    if not isinstance(node, ast.ImportFrom):
        return False
    if node.module not in _IMPORT_SOURCE_MODULES:
        return False
    return any(alias.name == _HTTPEXCEPTION_NAME for alias in node.names)


def _find_raw_httpexception_usages(path: Path) -> list[_Violation]:
    """Walk ``path`` AST and collect every raw-HTTPException violation.

    Respects ``# scan-allow[no-raw-httpexception]: <reason>`` comments
    spanning the violating node's lines. Returns a list of ``_Violation``
    (empty on success).
    """
    source = path.read_text(encoding="utf-8")
    source_lines = source.splitlines()
    tree = safe_parse(path)
    allowlisted = allowlisted_lines(source, label=_SCAN_LABEL)
    violations: list[_Violation] = []

    for node in ast.walk(tree):
        kind: Literal["raise", "import"]
        if _is_raw_httpexception_raise(node):
            kind = "raise"
        elif _is_httpexception_import(node):
            kind = "import"
        else:
            continue

        start = node.lineno
        end = node.end_lineno or node.lineno
        if any(lineno in allowlisted for lineno in range(start, end + 1)):
            continue

        line_index = node.lineno - 1
        line = source_lines[line_index] if 0 <= line_index < len(source_lines) else ""
        violations.append(
            _Violation(path=path, lineno=node.lineno, kind=kind, source=line)
        )

    return violations


@pytest.mark.non_regression
def test_src_comadre_has_no_raw_httpexception() -> None:
    """FR51 / NFR17 non-regression: raw ``HTTPException`` raises AND imports
    are prohibited in ``src/comadre/`` outside ``# scan-allow:``-annotated
    lines.
    """
    paths = sorted(_SRC_ROOT.rglob("*.py"))
    assert paths, (
        f"No .py files discovered under {_SRC_ROOT}. "
        f"Did the project root layout change? "
        f"Expected {_SRC_ROOT} to contain at least one .py file."
    )
    all_violations: list[_Violation] = []
    for path in paths:
        all_violations.extend(_find_raw_httpexception_usages(path))

    assert not all_violations, (
        "Raw HTTPException usage detected in src/comadre/.\n"
        "This regression breaks FR51 and the {error: {message, type, hint}}\n"
        "envelope contract. Use a ComadreError subclass from\n"
        "src/comadre/exceptions.py instead:\n"
        "  - 401   → AuthenticationError / ApiKeyNotFoundError /\n"
        "            ApiKeySuspendedError / ApiKeyRevokedError\n"
        "  - 400   → InvalidRequestError / InvalidTaxIdError\n"
        "  - 404   → VoiceNotFoundError (or add app.add_exception_handler\n"
        "            in main.py for framework-emitted 404s)\n"
        "  - 429   → RateLimitError\n"
        "  - 500   → GenerationError / KeyRegistryError\n"
        "  - 503   → ServiceUnavailableError\n"
        "If the HTTPException is intentional and bridged back into the\n"
        "envelope by a dedicated exception-bridging helper, add a trailing\n"
        "comment on the offending line (or any line the statement spans):\n"
        "    # scan-allow[no-raw-httpexception]: "
        "<why this is safe, reviewed by <initials>>\n\n"
        "Violations:\n  " + "\n  ".join(v.render() for v in all_violations)
    )


@pytest.mark.non_regression
def test_scan_self_tests_pass_all_fixture_cases() -> None:
    """Self-test: scanner flags violations + respects allowlists + ignores
    non-violations across all four fixture files."""
    # bad_raise.py: 1 raise + 1 import flagged.
    bad_raise = _find_raw_httpexception_usages(_FIXTURES_ROOT / "bad_raise.py")
    assert sorted(v.kind for v in bad_raise) == ["import", "raise"]

    # bad_import.py: 1 import flagged (even with noqa: F401).
    bad_import = _find_raw_httpexception_usages(_FIXTURES_ROOT / "bad_import.py")
    assert len(bad_import) == 1
    assert bad_import[0].kind == "import"

    # allowlisted_raise.py: scan-allow on both lines → zero violations.
    allowed = _find_raw_httpexception_usages(_FIXTURES_ROOT / "allowlisted_raise.py")
    assert allowed == []

    # comadre_error_only.py: ComadreError raises are NOT flagged; docstring
    # mentions of HTTPException are AST Constants, not Raises/ImportFroms.
    clean = _find_raw_httpexception_usages(_FIXTURES_ROOT / "comadre_error_only.py")
    assert clean == []
