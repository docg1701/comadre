"""SQL-injection non-regression — bandit B608 static check (Story 4.5g).

Subprocess-invokes ``bandit -r src/comadre/keys/ -t B608 -ll -c <sentinel> -f
json -q`` and asserts the ``results`` list is empty. Scoped to the bandit
``hardcoded_sql_expressions`` (B608) plugin specifically — other bandit
plugins (B101 assert_used, B404 subprocess-module-use, etc.) are explicitly
deferred to future stories; 4.5g's charter is SQL-injection prevention, not
full bandit coverage.

Severity gate: MEDIUM-or-higher via ``-ll``. ``bandit --help`` documents the
flag exactly: ``-l`` reports LOW-or-higher, ``-ll`` MEDIUM-or-higher, ``-lll``
HIGH-only. The epic AC's "HIGH-severity finding" wording is empirically wrong
for B608 (max severity is MEDIUM; a HIGH-only gate would catch zero
SQL-injection regressions). MEDIUM-or-higher is the contract this module
implements and the spec/README document.

Config isolation: ``-c tests/test_non_regression/fixtures/sql_static_bandit/
bandit_isolation.yaml`` short-circuits bandit's auto-discovery of any
``[tool.bandit]`` section that may be added to ``pyproject.toml`` in the
future. Without ``-c``, a ``skips = ["B608"]`` line landing anywhere in the
project's bandit config would silently fail this gate open.

Subprocess invocation: ``[sys.executable, "-m", "bandit", ...]`` — uses the
test interpreter's bandit module directly. This succeeds whenever the
``security`` dependency group is installed, even if the ``bandit`` script
shim is not on ``$PATH``. If bandit cannot be imported at all, the helper
fails loudly under CI and skips on developer laptops.

The four currently-legitimate B608 sites under ``src/comadre/keys/db.py``
(column-allowlist f-string splicing in UPDATE/SELECT/IN-clause construction)
carry inline ``# nosec B608  # <reason>`` two-comment annotations — bandit
reads only test-ids after ``# nosec`` until the next ``#``, so the reason
text never reaches bandit's tolerant nosec lexer and does not generate
"Test in comment: <word> is not a test name or id" stderr noise. Each reason
is reviewer-enforced per the spec's reason vocabulary rules (names the
controlled collection + its allowlist contract + the ? binding of values).

The scan's complement is positive: every new SQL query must use
``conn.execute("… WHERE x = ?", (value,))`` parameterised bindings for
VALUES; column/identifier splicing remains permitted only when annotated
with a ``# nosec B608  # <reason>`` that passes reviewer judgement at PR
time.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest


def _find_project_root() -> Path:
    """Walk parents until a directory containing ``pyproject.toml`` is found.

    Pinning by sentinel-file (rather than ``Path(__file__).parents[N]``)
    prevents a silent scope drift if the test module is ever relocated.
    """
    here = Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise RuntimeError(
        f"could not locate project root from {here}; no pyproject.toml in any parent"
    )


_PROJECT_ROOT: Path = _find_project_root()
_SRC_KEYS_ROOT: Path = _PROJECT_ROOT / "src" / "comadre" / "keys"
_FIXTURES_ROOT: Path = (
    Path(__file__).resolve().parent / "fixtures" / "sql_static_bandit"
)
_BANDIT_CONFIG: Path = _FIXTURES_ROOT / "bandit_isolation.yaml"

_BANDIT_TEST_ID: str = "B608"


@dataclass(frozen=True)
class _Finding:
    """One B608 finding, hydrated from bandit's JSON result schema."""

    test_id: str
    filename: str
    line_number: int
    severity: str  # "LOW" | "MEDIUM" | "HIGH"
    confidence: str  # "LOW" | "MEDIUM" | "HIGH"
    code: str

    def render(self) -> str:
        path = Path(self.filename)
        try:
            rel = path.relative_to(_PROJECT_ROOT)
        except ValueError:
            rel = path
        # code is a multi-line excerpt (bandit renders 3 lines of context);
        # squash to the interesting middle line for the failure message.
        excerpt = self.code.strip().splitlines()
        snippet = excerpt[len(excerpt) // 2] if excerpt else ""
        return (
            f"{rel}:{self.line_number}: [{self.test_id}] "
            f"severity={self.severity} confidence={self.confidence} — "
            f"{snippet.strip()}"
        )


def _bandit_importable() -> bool:
    """Probe whether ``python -m bandit --version`` is callable.

    More robust than ``shutil.which("bandit")``: catches the case where
    bandit is in ``site-packages`` but the script shim is missing from
    ``$PATH`` (some CI sandboxes, ``uv run`` indirection).
    """
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "bandit", "--version"],
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _run_bandit(paths: list[Path]) -> list[_Finding]:
    """Subprocess-invoke bandit on ``paths`` and return B608 findings.

    Skips the test if bandit is not importable AND we're not running in CI.
    Under CI (``CI`` env var set), missing bandit fails the test loudly so
    a dropped ``security`` dependency group cannot fail the gate open.
    """
    if not _bandit_importable():
        msg = (
            "bandit is not importable; run `uv sync` to install the "
            "security dependency group."
        )
        if os.getenv("CI"):
            pytest.fail(msg)
        pytest.skip(msg)

    missing = [p for p in paths if not p.exists()]
    if missing:
        pytest.fail(
            "bandit input path(s) missing — fixture renamed or deleted? "
            f"{[str(p) for p in missing]}"
        )

    cmd = [
        sys.executable,
        "-m",
        "bandit",
        "-c",
        str(_BANDIT_CONFIG),
        "-r",
        *[str(p) for p in paths],
        "-t",
        _BANDIT_TEST_ID,
        "-ll",
        "-f",
        "json",
        "-q",
    ]
    try:
        completed = subprocess.run(
            cmd,
            cwd=_PROJECT_ROOT,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(f"bandit exceeded 60s timeout: {exc}")

    # bandit exits 1 on findings, 0 on clean, 2 on usage error. Only treat
    # 2 (and unexpected codes outside {0, 1}) as fatal — the test's own
    # assertions handle 1 vs 0.
    if completed.returncode not in (0, 1):
        pytest.fail(
            f"bandit returned unexpected exit={completed.returncode}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        pytest.fail(
            f"Could not parse bandit stdout as JSON: {exc}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )

    if "results" not in payload:
        pytest.fail(
            "bandit JSON payload missing required 'results' key — schema "
            f"drift? top-level keys present: {sorted(payload)}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )

    findings: list[_Finding] = []
    for result in payload["results"]:
        if result.get("test_id") != _BANDIT_TEST_ID:
            # Defensive — ``-t B608`` should already filter, but belt-and-braces
            # against a future bandit tightening of the ``-t`` semantics.
            continue
        try:
            findings.append(
                _Finding(
                    test_id=result["test_id"],
                    filename=result["filename"],
                    line_number=int(result["line_number"]),
                    severity=result["issue_severity"],
                    confidence=result["issue_confidence"],
                    code=result.get("code", ""),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            pytest.fail(
                f"Unexpected bandit JSON shape ({type(exc).__name__}: {exc}); "
                f"result={result!r}"
            )
    return findings


@pytest.mark.non_regression
def test_src_comadre_keys_has_no_b608_findings() -> None:
    """Non-regression: bandit B608 (hardcoded_sql_expressions) reports zero
    findings against ``src/comadre/keys/``.

    Controlled-input column/identifier f-string splicing sites are
    annotated ``# nosec B608  # <reason>`` (two-comment form,
    reviewer-enforced). A new raw f-string / %% / + SQL construction
    lands this assertion red with the file, line, snippet, severity, and
    confidence named in the failure message.
    """
    findings = _run_bandit([_SRC_KEYS_ROOT])
    assert not findings, (
        "bandit B608 (hardcoded_sql_expressions) reported findings in "
        "src/comadre/keys/.\n"
        "This regression breaks the PRD Non-Regression Contract row "
        "'parameterized queries exclusively' (PRD §Technical Constraints "
        "line 192, §Continuity with Existing Hardening line 703). Use a "
        "parameterised query with ? placeholders instead:\n"
        '  - conn.execute("SELECT … WHERE x = ?", (value,))\n'
        '  - conn.execute("UPDATE t SET col = ? WHERE id = ?", (val, id))\n'
        "If the f-string SPLICES ONLY controlled column names or "
        "programmatically-derived ? tokens (not operator input), and "
        "every VALUE binds via a ? placeholder, annotate with a trailing "
        "two-comment block naming the controlled-input contract:\n"
        "    # nosec B608  # <which collection, why it's safe>\n"
        "Example: `# nosec B608  # set_parts is a hardcoded column-allowlist "
        '("email = ?", "name = ?", …); only ? placeholders bind values`.\n\n'
        "Findings:\n  " + "\n  ".join(f.render() for f in findings)
    )


@pytest.mark.non_regression
def test_scan_flags_bad_fstring() -> None:
    """Self-test: f-string SQL interpolation is flagged by B608."""
    findings = _run_bandit([_FIXTURES_ROOT / "bad_fstring_sql.py"])
    assert len(findings) == 1, (
        f"Expected exactly one B608 finding in bad_fstring_sql.py; got "
        f"{len(findings)}: {[f.render() for f in findings]}"
    )
    assert findings[0].test_id == "B608"
    assert "SELECT" in findings[0].code and "{" in findings[0].code, (
        f"Expected B608 finding's code excerpt to include the f-string "
        f"SELECT construction; got code={findings[0].code!r}"
    )


@pytest.mark.non_regression
def test_scan_flags_bad_concat() -> None:
    """Self-test: %-formatting SQL is flagged by B608 (same risk class)."""
    findings = _run_bandit([_FIXTURES_ROOT / "bad_concat_sql.py"])
    assert len(findings) == 1, (
        f"Expected exactly one B608 finding in bad_concat_sql.py; got "
        f"{len(findings)}: {[f.render() for f in findings]}"
    )
    assert findings[0].test_id == "B608"


@pytest.mark.non_regression
def test_scan_respects_nosec() -> None:
    """Self-test: ``# nosec B608  # <reason>`` suppresses the finding."""
    findings = _run_bandit([_FIXTURES_ROOT / "nosec_allowed_sql.py"])
    assert findings == [], (
        f"Expected zero B608 findings in nosec_allowed_sql.py (the one "
        f"f-string site carries an inline `# nosec B608  # <reason>` "
        f"two-comment annotation); got {[f.render() for f in findings]}"
    )


@pytest.mark.non_regression
def test_scan_ignores_parameterised_sql() -> None:
    """Self-test: positional ? bindings produce zero B608 findings."""
    findings = _run_bandit([_FIXTURES_ROOT / "parameterised_sql.py"])
    assert findings == [], (
        f"Expected zero B608 findings in parameterised_sql.py (both "
        f"queries use ? placeholder bindings exclusively); got "
        f"{[f.render() for f in findings]}"
    )
