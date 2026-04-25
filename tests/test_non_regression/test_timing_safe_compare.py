"""FR48 non-regression — timing-safe key comparison static check (Story 4.5c).

Walks every ``.py`` file under ``src/comadre/`` and asserts no ``==`` / ``!=``
comparison binds to an identifier whose terminal name component matches
``_SUSPECT_IDENTIFIER_RE`` (substring match on ``hash`` / ``token`` / ``secret``,
case-insensitive). ``hmac.compare_digest(...)`` calls are structurally outside
the visitor's scope (Call node, not Compare node) and are therefore never
flagged — this is the point: the scan is a negative invariant on bare
equality, not a positive check on compare_digest presence.

Inline ``# scan-allow[timing-safe-compare]: <reason>`` on the same source
line suppresses the scan for that line only; the comment is reviewer-enforced
at PR time. F45 — the namespace bracket is mandatory, so a comment
suppressing this scan cannot accidentally silence a sibling scan
(``no-raw-httpexception``, ``sql-injection``).
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.test_non_regression._scan_common import (
    allowlisted_lines,
    safe_parse,
)

_PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
_SRC_ROOT: Path = _PROJECT_ROOT / "src" / "comadre"
_FIXTURES_ROOT: Path = (
    Path(__file__).resolve().parent / "fixtures" / "timing_safe_compare"
)
_SCAN_LABEL: str = "timing-safe-compare"

# AC4 — ``key`` is DELIBERATELY excluded from the suspect-identifier set.
# A preview grep at story-draft time (2026-04-23) showed 15+ legitimate hits
# for ``*key*`` identifiers in equality comparisons across
# ``src/comadre/keys/cli/commands/*.py`` and ``src/comadre/keys/billing.py``
# (e.g., ``key_row.billing_mode == "complimentary"``,
# ``resolved.kind == "key_ambiguous"``, ``msg == "cannot update a revoked key"``)
# — none of which compare key MATERIAL. Flagging them would force an allowlist
# comment on every line, drowning the signal. Every real key-material
# identifier in this codebase binds a ``hash``-, ``token``-, or
# ``secret``-containing name (canonical: ``token_hash``, ``key_hash``,
# ``_DUMMY_HASH``, ``bearer_token``, ``webhook_secret``), so the
# substring-match-without-``key`` rule catches the regression class cleanly.
_SUSPECT_IDENTIFIER_RE: re.Pattern[str] = re.compile(r"(?i)(hash|token|secret)")


@dataclass(frozen=True)
class _Violation:
    path: Path
    lineno: int
    identifier: str
    source: str

    def render(self) -> str:
        rel = self.path.relative_to(_PROJECT_ROOT)
        return (
            f"{rel}:{self.lineno}: bare equality compare on "
            f"'{self.identifier}' — {self.source.strip()}"
        )


def _terminal_identifier(node: ast.expr) -> str | None:
    """Return the rightmost identifier of an operand node, or ``None``.

    - ``Name`` → its ``id``.
    - ``Attribute`` → its ``attr`` (the rightmost attribute; we do NOT walk
      the chain root, so ``obj.session.token`` returns ``"token"`` not
      ``"obj"``).
    - ``Subscript`` → recurse into the subscripted value.
    - Anything else → ``None``.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _terminal_identifier(node.value)
    return None


def _find_unsafe_comparisons(path: Path) -> list[_Violation]:
    """Walk ``path`` AST for ``Compare`` nodes containing an ``Eq``/``NotEq``
    operator whose adjacent-operand terminal identifier matches
    ``_SUSPECT_IDENTIFIER_RE``.

    A ``# scan-allow[timing-safe-compare]: <reason>`` comment on any physical
    line the comparison spans (``node.lineno`` through ``node.end_lineno``)
    suppresses the violation for that node. The allowlist is detected via
    ``tokenize`` so it cannot be spoofed from string-literal content. Returns
    a list of ``_Violation`` (empty on success).
    """
    source = path.read_text(encoding="utf-8")
    source_lines = source.splitlines()
    tree = safe_parse(path)
    allowlisted = allowlisted_lines(source, label=_SCAN_LABEL)
    violations: list[_Violation] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        # ``any`` (not ``all``) — a chain like ``token_hash == x < y`` mixes
        # Eq with ordering operators and must still flag the Eq operand. Only
        # operands adjacent to an Eq/NotEq operator are checked.
        if not any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops):
            continue

        operands = [node.left, *node.comparators]
        suspect_operands: list[ast.expr] = []
        seen: set[int] = set()
        for i, op in enumerate(node.ops):
            if not isinstance(op, (ast.Eq, ast.NotEq)):
                continue
            for idx in (i, i + 1):
                operand = operands[idx]
                if id(operand) in seen:
                    continue
                seen.add(id(operand))
                suspect_operands.append(operand)

        start = node.lineno
        end = node.end_lineno or node.lineno
        if any(lineno in allowlisted for lineno in range(start, end + 1)):
            continue

        for operand in suspect_operands:
            ident = _terminal_identifier(operand)
            if ident is None:
                continue
            if not _SUSPECT_IDENTIFIER_RE.search(ident):
                continue
            line_index = node.lineno - 1
            line = (
                source_lines[line_index] if 0 <= line_index < len(source_lines) else ""
            )
            violations.append(
                _Violation(
                    path=path,
                    lineno=node.lineno,
                    identifier=ident,
                    source=line,
                )
            )
            # One violation per Compare node — the rendered failure message
            # already names the line; enumerating each operand would be noise.
            break

    return violations


@pytest.mark.non_regression
def test_src_comadre_has_no_unsafe_key_comparisons() -> None:
    """FR48 / NFR11 non-regression: bare ``==``/``!=`` on key material is
    prohibited in ``src/comadre/`` outside ``# scan-allow:``-annotated lines.
    """
    paths = sorted(_SRC_ROOT.rglob("*.py"))
    assert paths, (
        f"No .py files discovered under {_SRC_ROOT}. "
        f"Did the project root layout change? "
        f"Expected {_SRC_ROOT} to contain at least one .py file."
    )
    all_violations: list[_Violation] = []
    for path in paths:
        all_violations.extend(_find_unsafe_comparisons(path))

    assert not all_violations, (
        "Bare equality comparison on key material detected in src/comadre/.\n"
        "This regression breaks NFR11 (timing-safe key comparison contract).\n"
        "Use ``hmac.compare_digest(a, b)`` instead of ``a == b`` when either\n"
        "operand holds hashed/tokenised key material. If the comparison is\n"
        "intentional and does NOT handle key material (e.g., an equality\n"
        "check on a non-sensitive field that incidentally contains the word\n"
        "'hash' or 'token'), add a trailing comment on the same line:\n"
        "    # scan-allow[timing-safe-compare]: "
        "<why this is safe, reviewed by <initials>>\n\n"
        "Violations:\n  " + "\n  ".join(v.render() for v in all_violations)
    )


@pytest.mark.non_regression
def test_scan_flags_bad_example() -> None:
    """Self-test: the scan's own correctness is exercised via a fixture."""
    violations = _find_unsafe_comparisons(_FIXTURES_ROOT / "bad_example.py")
    assert len(violations) == 1, (
        f"Expected exactly one violation in bad_example.py, "
        f"got {len(violations)}: {[v.render() for v in violations]}"
    )
    violation = violations[0]
    assert violation.identifier == "token_hash", (
        f"Expected identifier 'token_hash', got '{violation.identifier}'"
    )
    # We don't pin the exact line number — editor autoformatting may shift
    # the fixture's line count. We DO pin that the source line carries
    # ``==`` and ``token_hash`` as evidence the right line was flagged.
    assert "==" in violation.source
    assert "token_hash" in violation.source


@pytest.mark.non_regression
def test_scan_respects_allowlist_comment() -> None:
    """Self-test: ``# scan-allow: <reason>`` suppresses the scan on that line."""
    violations = _find_unsafe_comparisons(_FIXTURES_ROOT / "allowlisted_example.py")
    assert violations == [], (
        f"Expected zero violations in allowlisted_example.py (inline "
        f"# scan-allow: comment suppresses); got "
        f"{[v.render() for v in violations]}"
    )


@pytest.mark.non_regression
def test_scan_ignores_compare_digest_calls() -> None:
    """Self-test: ``hmac.compare_digest(a, b)`` is a Call node, not a Compare
    node, and so is structurally outside the visitor's scope.
    """
    violations = _find_unsafe_comparisons(_FIXTURES_ROOT / "compare_digest_only.py")
    assert violations == [], (
        f"Expected zero violations in compare_digest_only.py (Call node, "
        f"not Compare node); got {[v.render() for v in violations]}"
    )


@pytest.mark.non_regression
def test_scan_rejects_string_literal_allowlist_bypass() -> None:
    """Self-test (Review Finding #1): ``# scan-allow:`` inside a string literal
    does NOT suppress a real violation. The tokenize-based allowlist detection
    distinguishes STRING tokens from COMMENT tokens, so a bypass of the form
    ``(_msg := "# scan-allow:") and token_hash == stored`` is correctly flagged.
    """
    violations = _find_unsafe_comparisons(
        _FIXTURES_ROOT / "string_literal_allowlist_bypass.py"
    )
    assert len(violations) == 1, (
        f"Expected 1 violation in string_literal_allowlist_bypass.py — the "
        f"string-literal occurrence of '# scan-allow:' must not suppress the "
        f"adjacent ``==``; got {len(violations)}: "
        f"{[v.render() for v in violations]}"
    )
    assert violations[0].identifier == "token_hash"


@pytest.mark.non_regression
def test_scan_flags_chained_mixed_ops() -> None:
    """Self-test (Review Finding #3): a chain mixing ``==`` with an ordering
    operator (``token_hash == x < y``) must flag, not silently pass. The
    operator gating is ``any``, not ``all``: any Eq/NotEq in the chain causes
    the adjacent operands to be checked.
    """
    violations = _find_unsafe_comparisons(
        _FIXTURES_ROOT / "chained_mixed_ops_example.py"
    )
    assert len(violations) == 1, (
        f"Expected 1 violation in chained_mixed_ops_example.py — bare ``==`` "
        f"on 'token_hash' inside a chained comparison must flag; got "
        f"{len(violations)}: {[v.render() for v in violations]}"
    )
    assert violations[0].identifier == "token_hash"


@pytest.mark.non_regression
def test_scan_allowlist_spans_multi_line_compare() -> None:
    """Self-test (Review Finding #2): a ``# scan-allow:`` on any physical line
    spanned by a multi-line ``Compare`` (``node.lineno`` through
    ``node.end_lineno``) suppresses the node — the comment does not have to
    land on ``node.lineno`` specifically.
    """
    violations = _find_unsafe_comparisons(
        _FIXTURES_ROOT / "multiline_allowlist_example.py"
    )
    assert violations == [], (
        f"Expected zero violations in multiline_allowlist_example.py — the "
        f"``# scan-allow:`` on the closing line of a multi-line Compare must "
        f"suppress; got {[v.render() for v in violations]}"
    )
