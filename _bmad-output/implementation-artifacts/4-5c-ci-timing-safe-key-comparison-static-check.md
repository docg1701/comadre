# Story 4.5c: CI — Timing-Safe Key Comparison Static Check

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

> **Scope note — FR48, NFR11, NFR17.** Third of the seven CI non-regression sub-stories (4.5a–4.5g). Inherits the skeleton 4.5a landed (`tests/test_non_regression/` package, `non_regression` pytest marker, `non-regression` job in `.github/workflows/ci.yml`) and the harness-choice convention 4.5b broadened (ASGI and static-scan tests both admitted under the marker). 4.5c asserts the FR48 contract — a PR that introduces a `==` or `!=` comparison on key material (identifiers whose name contains `hash`, `token`, or `secret`) anywhere in `src/comadre/` fails CI before reaching master, so the timing-attack-resistant contract established by Story 1.6 (`hmac.compare_digest` on every key-hash comparison in `src/comadre/keys/auth.py`) cannot silently regress. Delivers three artefacts: (1) a pure-stdlib AST-based scan helper inside the new test module (`_find_unsafe_comparisons`); (2) `tests/test_non_regression/test_timing_safe_compare.py` asserting the scan finds zero violations in `src/comadre/`; (3) three fixture files under `tests/test_non_regression/fixtures/timing_safe_compare/` driving the scan's own self-tests (flags bad pattern, respects allowlist comment, ignores `hmac.compare_digest(...)` calls). First static-scan sub-story — establishes the fixture-directory convention and the `# scan-allow: <reason>` line-comment contract that 4.5f and 4.5g reuse. **No change to `src/comadre/`. No new Python dependency. No CI YAML change.**

## Story

As a contributor,
I want every pull request against master to prove — via a pure-stdlib AST scan over `src/comadre/` — that no identifier named `*hash*`, `*token*`, or `*secret*` is compared with `==` or `!=`, so the sole permitted equality-compare primitive on key material is `hmac.compare_digest` (or an explicitly allowlisted, reviewer-approved exception),
so that a well-meaning PR that "simplifies" the auth path by swapping `hmac.compare_digest(token_hash, stored_hash)` for `token_hash == stored_hash` — or that introduces a second auth surface (e.g., admin token, webhook secret) using naive string equality — cannot land on master without the PR build turning red and naming exactly which file, line, and identifier regressed.

**Covers FRs:** FR48 (CI can verify that the auth path uses timing-safe comparison primitives exclusively and never string equality).
**NFRs:** NFR11 (all key-comparison operations must use timing-safe primitives — `hmac.compare_digest` or equivalent; string equality is prohibited in the auth path); NFR17 (all Non-Regression Contract controls remain satisfied on every PR; CI regression coverage mandatory for each control row).
**UX-DRs:** Contributor-facing CI UX — when the scan fires, the pytest failure message MUST name (a) the absolute source path, (b) the line number, (c) the offending operand identifier, (d) a one-line snippet of the offending source, and (e) a remediation hint naming `hmac.compare_digest` and the `# scan-allow: <reason>` escape hatch. Inherits the 4.5a "name-the-regression" assertion convention and the 4.5b parametrised-case-per-endpoint discipline (here: parametrised-case-per-fixture-file for the self-tests).
**Epic:** 4 — Security Hardening, LGPD & Operational Safety. Seventh story in Epic 4 (4.1 → 4.2 → 4.3 → 4.4 → 4.5a → 4.5b → **4.5c** → 4.5d–g → 4.6). Third of the seven-sub-story CI non-regression cluster; appends ONE test module + ONE fixtures subdirectory — zero CI YAML changes, zero `src/comadre/` changes, zero marker changes, per the 4.5a + 4.5b extension contract.

## Builds on

- **Story 4.5a — CI non-regression skeleton (`done`).** 4.5a established the `tests/test_non_regression/` package, the `non_regression` pytest marker (`tests/conftest.py:30-33`), the `addopts = "-m 'not non_regression'"` default-exclusion in `pyproject.toml`, and the `non-regression` CI job in `.github/workflows/ci.yml` that runs `uv run pytest -m non_regression tests/test_non_regression/ -v`. 4.5a's extension contract (`tests/test_non_regression/README.md:150-175`) is the blueprint this story follows: add exactly one `test_<check_name>.py`, mark every test `@pytest.mark.non_regression`, do NOT touch CI YAML.
- **Story 4.5b — non-regression marker broadened + first non-docker test (`done`).** 4.5b broadened the `non_regression` marker semantics from "always docker-based" to "CI non-regression surface; docker-required fixtures opt in on their own," and added the README's "Harness choice" section explicitly admitting static scans (`tests/test_non_regression/README.md:177-191`). 4.5c is the first **static-scan** sub-story and the direct beneficiary of that broadening — no docker, no ASGI TestClient, no network, no filesystem beyond reading `src/comadre/**/*.py` and the story's own fixture files.
- **Existing auth-path contract — `src/comadre/keys/auth.py:47-48, 125, 136-137`.** The three canonical `hmac.compare_digest` call sites: (a) `_DUMMY_HASH` pre-computation at module load (`hash_api_key("__dummy_for_timing_equalisation__")`); (b) the non-ASCII-token rejection path that runs a dummy compare before `raise ApiKeyNotFoundError()`; (c) the cache-miss + DB-miss path that runs a dummy compare before the same raise. 4.5c's scan asserts the **observable invariant** of this design (no `==`/`!=` on `*hash*`/`*token*`/`*secret*` identifiers in `src/comadre/`) rather than the positive presence of `compare_digest` calls, so the check survives any refactor that moves the compare_digest calls into a helper module as long as bare equality on key material stays prohibited.
- **Existing `hash_api_key` contract — `src/comadre/keys/tokens.py:43-50`.** Returns `hashlib.sha256(plaintext.encode("ascii")).hexdigest()` — a 64-char lowercase hex string. Every downstream caller stores or compares this hash; no downstream caller should ever use `==` or `!=` on the return value. The scan's `hash`-substring rule catches any identifier bound to `hash_api_key(...)` (canonical names: `token_hash`, `key_hash`, `_DUMMY_HASH`) that lands on the left or right of a Compare node with `Eq`/`NotEq`.
- **Existing test coverage — `tests/test_keys_auth.py::TestDbMissPath`.** Asserts `compare_digest` is called exactly once on the DB-miss path, with the expected `(token_hash, _DUMMY_HASH)` operands. Complementary to 4.5c: the unit test asserts the positive call exists; 4.5c's scan asserts no `==`/`!=` regression alternative ever replaces it. Both checks run on every PR (the unit test in the `test` job, the scan in the `non-regression` job); together they close the regression surface.
- **PRD §Technical Constraints — timing-safe key comparison — `_bmad-output/planning-artifacts/prd.md:132, 190, 654, 700, 751, 829, 838`.** The canonical row: *Timing-safe API-key comparison — `hmac.compare_digest` in `verify_api_key` — All new key-comparison code paths use `hmac.compare_digest`, never `==`*. 4.5c owns this row; no other sub-story revisits it.
- **Architecture §Auth path — `_bmad-output/planning-artifacts/architecture.md:208, 472, 673`.** Names `hmac.compare_digest(hash, dummy_hash)` in the auth-sequence diagram as the explicit timing-equalisation primitive. 4.5c closes the non-regression gap for this architecture assertion.
- **PRD Non-Regression Contract — `_bmad-output/planning-artifacts/prd.md:644-654`.** Row-by-row list of controls that must not regress; the timing-safe-compare row names `hmac.compare_digest` + "never `==`". 4.5c converts this row from prose-only to mechanically-enforced.
- **Harness-choice README section — `tests/test_non_regression/README.md:177-191`.** 4.5b's addition explicitly names static-scan checks (4.5c, 4.5f, 4.5g) as a valid third harness shape alongside docker-stack and ASGI TestClient. 4.5c's implementation is the first test that needs neither the `compose_stack` nor a `bare_client` fixture — pure `ast.parse` + `pathlib.Path.rglob` over `src/comadre/`.
- **CLAUDE.md Non-Obvious Gotcha on the uniform error envelope and auth path.** "All errors via `ComadreError` subclasses with `status_code`, `error_type`, `hint` — never raw HTTPException" (enforced statically by Story 4.5f); "No raw `os.environ` (use pydantic-settings)"; "Timing-safe comparison (`hmac.compare_digest`) on hash match; dummy comparison on miss to equalize timing" (this story's scope). 4.5c is the static-enforcement partner for the third gotcha.

## Unblocks

- **Stories 4.5f and 4.5g.** 4.5c is the first static-scan story and establishes the fixture-directory convention (`tests/test_non_regression/fixtures/<check_name>/`) and the `# scan-allow: <reason>` inline-comment allowlist contract. 4.5f (no raw `HTTPException`) and 4.5g (bandit SQL-injection analysis) both face the same shape — scan source, produce violations, self-test via fixtures. They can clone 4.5c's module structure line-for-line and swap the identifier rule + fixture content. The one thing 4.5c pins is that fixture files live under a subdirectory per-check (`fixtures/timing_safe_compare/`), not flat under `fixtures/`, so a future static-scan sub-story's fixture set does not collide.
- **Codebase-wide "no bare equality on key material" invariant.** Once 4.5c lands, a PR cannot land ANY new identifier named `*hash*`, `*token*`, or `*secret*` with a bare `==`/`!=` comparison without an explicit allowlist comment — regardless of whether that code path is reached by the current auth middleware. This prevents the class of regression where a new endpoint (admin, webhook, internal debug) is added with naive key-comparison, bypassing the `verify_api_key` dependency entirely.
- **Epic 4 FR48 coverage.** This was one of the three remaining PRD Non-Regression Contract rows (alongside FR51 for 4.5f and the cross-cutting SQL-injection check for 4.5g) with **only** prose guidance and a unit test. After 4.5c lands, FR48 is mechanically enforced on every PR.

## Depends on

- **Stories 4.5a and 4.5b are `done`** (sprint-status.yaml confirms, checked 2026-04-23). Hard dependency on 4.5a's non-regression package skeleton, marker, and CI job. Soft dependency on 4.5b's precedent for non-docker tests under the `non_regression` marker — without 4.5b's README broadening and marker-description amendment, 4.5c would need to re-litigate "can a non-docker test live in this module?" That conversation is settled.
- **No new runtime dependency.** `ast` is stdlib; `pathlib` is stdlib; `re` is stdlib.
- **No new dev dependency.** `pytest` + `pytest-asyncio` (unused here — the scan is synchronous; tests are sync functions, not `async def`) already configured.
- **No schema change. No auth-path change. No `src/comadre/` change. No new CLI verb. No ansible change. No CI YAML change.** Grep invariant (AC12): `git diff master -- src/comadre/` returns empty. The entire story lives under `tests/test_non_regression/` — exactly one new test module plus one new fixtures subdirectory with three files.

## Scope

Three workstreams, in order:

1. **Ship the AST-based scan helper and the `src/comadre/` regression assertion** — `tests/test_non_regression/test_timing_safe_compare.py`. One module-local helper `_find_unsafe_comparisons(path: Path) -> list[_Violation]` that walks `ast.parse(path.read_text())` for `Compare` nodes with `Eq`/`NotEq` operators whose operand-name terminal identifier matches `_SUSPECT_IDENTIFIER_RE`. One primary test that runs the scan across `src/comadre/**/*.py` and asserts zero violations.
2. **Ship the fixture files and the self-tests** — `tests/test_non_regression/fixtures/timing_safe_compare/bad_example.py`, `allowlisted_example.py`, `compare_digest_only.py`. Three parametrised tests assert: (a) the scan flags the bad fixture on the expected line with the expected identifier; (b) the scan respects a `# scan-allow: <reason>` comment on the same line; (c) the scan does NOT flag `hmac.compare_digest(a, b)` calls (Call node, not Compare node — structurally outside the visitor's scope).
3. **README housekeeping** — amend `tests/test_non_regression/README.md` to mark the `test_timing_safe_compare.py` ownership row as delivered (FR48 final description), and add a short "Scan allowlist convention" note under "Extension contract" so 4.5f and 4.5g inherit the same `# scan-allow: <reason>` contract without re-design.

### 1. `_find_unsafe_comparisons` + the primary regression assertion

**New module: `tests/test_non_regression/test_timing_safe_compare.py`**

**Identifier rule (the scan's core policy):**

```python
# Match any identifier whose *terminal name component* contains the substring
# ``hash``, ``token``, or ``secret`` (case-insensitive). ``key`` is deliberately
# excluded from the substring set: ``key`` appears legitimately in dozens of
# non-sensitive contexts across the codebase (``key_row.billing_mode``,
# ``key_prefix``, ``key_id``, dict-iteration ``for key in mapping:``), and
# flagging those would produce a false-positive footprint the allowlist would
# have to paper over. Every real key-material regression necessarily binds to
# an identifier containing ``hash``, ``token``, or ``secret`` (canonical names:
# ``token_hash``, ``key_hash``, ``_DUMMY_HASH``, ``bearer_token``,
# ``webhook_secret``), so the substring-match-without-``key`` rule catches the
# regression class without the noise. See AC4 for the explicit exclusion
# rationale.
_SUSPECT_IDENTIFIER_RE: re.Pattern[str] = re.compile(
    r"(?i)(hash|token|secret)"
)
```

**Terminal-identifier extraction:** the scan inspects each operand of a `Compare` node and extracts its terminal name component:

- `ast.Name(id="token_hash")` → `"token_hash"`.
- `ast.Attribute(value=..., attr="token_hash")` → `"token_hash"` (walk up the attribute chain; we only check the rightmost attribute, not the chain root).
- `ast.Subscript(value=..., slice=...)` → recurse into `value` (the subscripted collection's terminal name).
- Anything else (Constant, Call, BinOp, etc.) → no identifier, not flaggable as an operand (but the OTHER side of the compare is still checked independently).

**Compare-node rule:**

- Only `ast.Eq` and `ast.NotEq` operators trip the scan. `ast.Is`/`ast.IsNot` don't — `x is None` patterns are ubiquitous and don't hold key material.
- All pairwise operands of the node are checked (Python allows `a == b == c` — rare in this codebase, but semantically two comparisons).
- If ANY operand in the Compare expression has a suspect terminal identifier, the line is a violation.

**Allowlist comment:** the scan reads the source file line-by-line (alongside the AST walk) and treats any line ending with `# scan-allow: <reason>` (exact token `scan-allow`, colon, arbitrary trailing prose) as allowlisted. The `reason` is free-form but reviewer-enforced — treat an empty or one-word reason as a review-blocker in practice. A rule-comment scheme lets the scan stay policy-free (no identifier exemptions hard-coded in the scanner).

**Scope of the scan:** `src/comadre/**/*.py`, resolved via `Path("src/comadre").rglob("*.py")`. Test files (`tests/**/*.py`) are explicitly out of scope — they often use `==` on hashes for **assertion** purposes (e.g., `assert token_hash == hash_api_key("known-plaintext")`), which is legitimate and orthogonal to the timing-leak concern. Production code is the risk surface; tests are the signal.

**Skeleton:**

```python
"""FR48 non-regression — timing-safe key comparison static check (Story 4.5c).

Walks every ``.py`` file under ``src/comadre/`` and asserts no ``==`` / ``!=``
comparison binds to an identifier whose terminal name component matches
``_SUSPECT_IDENTIFIER_RE`` (substring match on ``hash`` / ``token`` / ``secret``,
case-insensitive). ``hmac.compare_digest(...)`` calls are structurally outside
the visitor's scope (Call node, not Compare node) and are therefore never
flagged — this is the point: the scan is a negative invariant on bare
equality, not a positive check on compare_digest presence.

Inline ``# scan-allow: <reason>`` on the same source line suppresses the scan
for that line only; the comment is reviewer-enforced at PR time.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

_PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
_SRC_ROOT: Path = _PROJECT_ROOT / "src" / "comadre"
_FIXTURES_ROOT: Path = Path(__file__).resolve().parent / "fixtures" / "timing_safe_compare"

_SUSPECT_IDENTIFIER_RE: re.Pattern[str] = re.compile(r"(?i)(hash|token|secret)")
_ALLOWLIST_TOKEN: str = "# scan-allow:"


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
    """Return the rightmost identifier of an operand node, or None.

    - ``Name`` → its ``id``.
    - ``Attribute`` → its ``attr`` (the rightmost attribute; we do NOT walk
      the chain root, so ``obj.session.token`` returns ``"token"`` not
      ``"obj"``).
    - ``Subscript`` → recurse into the subscripted value.
    - Anything else → None.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _terminal_identifier(node.value)
    return None


def _find_unsafe_comparisons(path: Path) -> list[_Violation]:
    """Walk ``path`` AST for ``Compare`` nodes with ``Eq``/``NotEq`` ops whose
    operand terminal identifier matches ``_SUSPECT_IDENTIFIER_RE``.

    Respects inline ``# scan-allow: <reason>`` on the same source line.
    Returns a list of ``_Violation`` (empty on success).
    """
    source = path.read_text(encoding="utf-8")
    source_lines = source.splitlines()
    tree = ast.parse(source, filename=str(path))
    violations: list[_Violation] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        if not all(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops):
            continue
        operands = [node.left, *node.comparators]
        for operand in operands:
            ident = _terminal_identifier(operand)
            if ident is None:
                continue
            if not _SUSPECT_IDENTIFIER_RE.search(ident):
                continue
            line_index = node.lineno - 1
            if 0 <= line_index < len(source_lines):
                line = source_lines[line_index]
            else:
                line = ""
            if _ALLOWLIST_TOKEN in line:
                continue
            violations.append(
                _Violation(
                    path=path,
                    lineno=node.lineno,
                    identifier=ident,
                    source=line,
                )
            )
            # One violation per Compare node is sufficient — the rendered
            # failure message already names the line; enumerating each
            # operand would be noise.
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
        "    # scan-allow: <why this is safe, reviewed by <initials>>\n\n"
        "Violations:\n  " + "\n  ".join(v.render() for v in all_violations)
    )
```

**Why AST-based, not regex-based:** a regex on the raw source text would false-positive on `==` inside string literals, docstrings, and comments. `"hmac.compare_digest(token_hash, stored_hash)"` inside a docstring would trip a regex but not an AST walk. AST is the only way to get "this equality operator is semantically active, applied to an identifier that binds key material." Also: `ast.parse` validates the file is syntactically valid Python; a syntax error in `src/comadre/` would be caught by the scan with a clear `SyntaxError` message before any violation detection runs.

**Why terminal-identifier extraction stops at the rightmost attribute:** an attribute chain like `request.state.auth_payload.token_hash` has multiple "suspect words" in the chain (e.g., `request`, `state`, `auth_payload`, `token_hash`). We only care whether the COMPARED value is key material, which is determined by the rightmost attribute. `request.state.auth_payload.token_hash == other` compares `token_hash` (suspect). `settings.auth_mode == "strict"` compares `auth_mode` (not suspect). The root name (`request`, `settings`) is not diagnostic. This matches how Python evaluates attribute access — the final step is the value being compared.

**Why `key` is excluded from the substring set:** a preview grep across `src/comadre/` for identifiers containing `key` in equality comparisons returned 15+ hits, all on DB-row attribute checks like `key_row.billing_mode == "complimentary"`, `resolved.kind == "key_ambiguous"`, `msg == "cannot update a revoked key"`. None of these compare key material; each flag would require an allowlist comment. The substring set `hash | token | secret` returns zero hits in the current codebase — every legitimate key-material compare already goes through `hmac.compare_digest` — so the scan runs clean without a starting allowlist footprint. AC4 pins this exclusion with the rationale so a future reviewer does not "fix" it by adding `key` and drowning the codebase in allowlist comments.

**Why substring match instead of suffix-only (e.g., `\b(hash|token|secret)s?$`):** a suffix-only rule would miss `_DUMMY_HASH`, `bearer_token_header`, `secret_material_bytes` — identifiers where the suspect word is not the trailing component. Substring match catches all of these. False-positive risk is bounded by the exclusion of `key` (which is the only word in the natural `*key*|*hash*|*token*|*secret*` set that produces noise in the current codebase — see `rg -in "(hash|token|secret).*(==|!=)|(==|!=).*(hash|token|secret)" src/comadre/` returning zero hits at story-draft time, 2026-04-23).

### 2. Fixture files and self-tests

**New directory: `tests/test_non_regression/fixtures/`** (first sub-story to introduce it). Holds per-scan-story subdirectories; 4.5f and 4.5g will land siblings at `fixtures/no_raw_httpexception/` and `fixtures/sql_static_bandit/` respectively.

**New subdirectory: `tests/test_non_regression/fixtures/timing_safe_compare/`** with three files:

#### `bad_example.py` — the scan MUST flag

```python
"""Fixture — intentional FR48 violation for self-test coverage.

This file is a test fixture consumed by
``test_timing_safe_compare.py::test_scan_flags_bad_example``. It is NOT
imported at runtime and is NOT part of the production codebase. A bare
equality compare on ``token_hash`` is the exact regression pattern the scan
must catch.
"""

from __future__ import annotations


def authenticate(token_hash: str, stored_hash: str) -> bool:
    # This line is intentionally unsafe — the scan MUST flag it.
    return token_hash == stored_hash
```

**Expected violation:** path ends with `fixtures/timing_safe_compare/bad_example.py`, line 11 (the `return` line — adjust if editor whitespace shifts), identifier either `token_hash` or `stored_hash` (scan returns whichever it encountered first on the operand list — canonically `token_hash`, the left operand).

#### `allowlisted_example.py` — the scan MUST NOT flag

```python
"""Fixture — intentional FR48 violation SUPPRESSED by the allowlist comment.

Consumed by ``test_scan_respects_allowlist_comment``. Exercises the escape
hatch: a same-line ``# scan-allow: <reason>`` comment takes a true violation
out of the scan's output. Reviewer-enforced at PR time.
"""

from __future__ import annotations


def authenticate(token_hash: str, stored_hash: str) -> bool:
    return token_hash == stored_hash  # scan-allow: fixture-intentional-for-4.5c-self-test
```

**Expected violation count on this file: 0.**

#### `compare_digest_only.py` — structurally not a Compare node

```python
"""Fixture — the canonical safe pattern.

Consumed by ``test_scan_ignores_compare_digest_calls``. ``hmac.compare_digest``
is a ``Call`` node, not a ``Compare`` node, so the scan's visitor structurally
skips it. This fixture exists to pin that structural property in an explicit
test rather than rely on it being self-evident from the scan's implementation.
"""

from __future__ import annotations

import hmac


def authenticate(token_hash: str, stored_hash: str) -> bool:
    return hmac.compare_digest(token_hash, stored_hash)
```

**Expected violation count on this file: 0.**

**Self-test block inside `test_timing_safe_compare.py`:**

```python
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
```

**Why three self-tests instead of parametrising one:** each self-test pins a different scan property — (a) flag on bad pattern; (b) respect allowlist comment; (c) ignore compare_digest call. A parametrised form would collapse three distinct assertions into one rubric; splitting them makes the failure message name exactly which property regressed. Matches the 4.5a "one assertion per failure mode" convention.

**Why pin `identifier == "token_hash"` on the bad fixture but not the line number:** editor autoformatting (ruff-format, IDE-on-save) can shift fixture line counts by ±1 line when docstrings are reflowed. The identifier is a stable property of the fixture's intent. Line-number pinning would make the self-test brittle for zero assertion power.

### 3. README housekeeping

**Edit `tests/test_non_regression/README.md`:**

1. Ownership-table row for `test_timing_safe_compare.py` (line 18) — already placeholder-final ("Static check: API-key comparison uses `hmac.compare_digest`"). Refine to: `FR48 — static AST scan forbids bare ``==``/``!=`` on ``*hash*``/``*token*``/``*secret*`` identifiers in ``src/comadre/``, with ``# scan-allow: <reason>`` line-comment allowlist`.
2. Append a short "Scan allowlist convention" paragraph under "Extension contract" (after the "Harness choice" section added by 4.5b):

```markdown
### Scan allowlist convention

Static-scan sub-stories (4.5c, 4.5f, 4.5g) share one escape hatch: a
trailing ``# scan-allow: <reason>`` comment on the offending source line
suppresses the scan for that line only. The reason is free-form but
reviewer-enforced — an empty or one-word reason is a review-blocker in
practice. Each scan owns its own reason vocabulary; a reason accepted by
4.5c's timing-safe scan is not automatically accepted by 4.5f's
no-raw-``HTTPException`` scan (they exist on different lines anyway).

Fixture files driving each scan's self-tests live under
``tests/test_non_regression/fixtures/<check_name>/`` — e.g., 4.5c uses
``fixtures/timing_safe_compare/``. This keeps fixture surface partitioned
per-sub-story so a future scan can land without collision.
```

3. No change to the "Known-leak exclusions" section (the 404/405 and 308 Caddy exclusions are docker-stack-only; static scans are unaffected).

No `tests/conftest.py` change (the `non_regression` marker description is already broadened by 4.5b). No `pyproject.toml` change. No CI YAML change.

### 4. Housekeeping: no CI YAML change, no `src/comadre/` change

The existing `non-regression` job in `.github/workflows/ci.yml` runs `uv run pytest -m non_regression tests/test_non_regression/ -v` — it auto-discovers the new module. The new fixture files under `tests/test_non_regression/fixtures/timing_safe_compare/` are NOT test modules (no `test_` prefix; they are `.py` source samples); pytest's collection rules naturally skip them. Grep invariants: `git diff master -- .github/workflows/ci.yml | wc -l` is `0`; `git diff master -- src/comadre/ | wc -l` is `0`; `git diff master -- pyproject.toml uv.lock | wc -l` is `0` at story completion.

## Acceptance Criteria

1. **AC1 — `_find_unsafe_comparisons` helper exists and is AST-based.** `tests/test_non_regression/test_timing_safe_compare.py` defines `_find_unsafe_comparisons(path: Path) -> list[_Violation]` that (a) calls `ast.parse(path.read_text(encoding="utf-8"))`, (b) walks the tree via `ast.walk`, (c) inspects `ast.Compare` nodes with `ast.Eq` / `ast.NotEq` operators only, (d) extracts the terminal identifier of each operand via `_terminal_identifier` (supports `Name`, `Attribute`, `Subscript`), (e) tests the identifier against `_SUSPECT_IDENTIFIER_RE` (substring match on `hash|token|secret`, case-insensitive), (f) returns a `list[_Violation]` with `path`, `lineno`, `identifier`, `source` fields.

2. **AC2 — Primary assertion: zero violations in `src/comadre/`.** `test_src_comadre_has_no_unsafe_key_comparisons` collects every `.py` file under `src/comadre/` via `rglob("*.py")` and runs `_find_unsafe_comparisons` on each. The test passes iff the combined violation list is empty. Failure message enumerates violations as `<relpath>:<lineno>: bare equality compare on '<identifier>' — <source>` and names the `# scan-allow:` escape hatch.

3. **AC3 — Self-test: bad fixture is flagged.** `test_scan_flags_bad_example` asserts `_find_unsafe_comparisons(fixtures/timing_safe_compare/bad_example.py)` returns exactly one violation with `identifier == "token_hash"`, `"=="` in `source`, and `"token_hash"` in `source`. Line number is NOT pinned (brittle to autoformat reflow); the identifier and source-substring checks prove the correct line was flagged.

4. **AC4 — `_SUSPECT_IDENTIFIER_RE` matches `hash | token | secret` and NOT `key`.** The regex source is exactly `r"(?i)(hash|token|secret)"`. `key` is deliberately excluded. Rationale documented in a module-level comment block of ≥3 lines naming (a) the false-positive footprint `key` would create (preview grep at story-draft time showed 15+ benign hits in `src/comadre/keys/cli/commands/*.py` and `src/comadre/keys/billing.py`), and (b) the empirical invariant that every legitimate key-material identifier in the codebase binds a `hash`-, `token`-, or `secret`-containing name.

5. **AC5 — Self-test: allowlist comment suppresses a violation.** `test_scan_respects_allowlist_comment` asserts `_find_unsafe_comparisons(fixtures/timing_safe_compare/allowlisted_example.py)` returns an empty list. The fixture's offending line ends with `# scan-allow: fixture-intentional-for-4.5c-self-test`.

6. **AC6 — Self-test: `hmac.compare_digest` calls are structurally ignored.** `test_scan_ignores_compare_digest_calls` asserts `_find_unsafe_comparisons(fixtures/timing_safe_compare/compare_digest_only.py)` returns an empty list. The fixture's only non-import statement is `return hmac.compare_digest(token_hash, stored_hash)`. The test's docstring explicitly names the AST-structural reason (Call node, not Compare node).

7. **AC7 — `non_regression` marker applied to every test.** All four tests in `test_timing_safe_compare.py` (one primary + three self-tests) carry `@pytest.mark.non_regression`. Grep invariant (inherited from 4.5a AC15): `rg "pytest.mark.non_regression" tests/` outside `tests/test_non_regression/` returns zero matches.

8. **AC8 — Default `pytest` run excludes the new module.** `uv run pytest` (no `-m` flag, no marker filter) does NOT execute the new tests. They're deselected via the existing `addopts = "-m 'not non_regression'"` from 4.5a — no change needed to `pyproject.toml`. Verified by running `uv run pytest` and observing the new file's four tests show as "deselected," consistent with 4.5a and 4.5b's behaviour.

9. **AC9 — Opt-in CI invocation picks up the new module.** `uv run pytest -m non_regression tests/test_non_regression/ -v` collects and runs the four new tests alongside 4.5a's `test_security_headers.py` (25 passed, 16 skipped at 4.5b close) and 4.5b's `test_docs_disabled.py` (9 passed). Expected new total: **38 passed, 16 skipped** (25 + 9 + 4). Verified locally before PR.

10. **AC10 — Fixtures are not collected as tests.** The three fixture files under `fixtures/timing_safe_compare/` have no `test_` prefix and no `Test` class, so pytest's default collection rules skip them. `uv run pytest -m non_regression tests/test_non_regression/ -v --collect-only` reports zero items from the `fixtures/` subdirectory. No `pyproject.toml` `tool.pytest.ini_options.norecursedirs` or `testpaths` narrowing required.

11. **AC11 — Fixture-directory convention established.** The fixtures live under `tests/test_non_regression/fixtures/timing_safe_compare/`, NOT directly under `tests/test_non_regression/fixtures/`. Convention: each static-scan sub-story owns one subdirectory, named after its story's scan identifier. This reserves sibling directories for 4.5f (`fixtures/no_raw_httpexception/`) and 4.5g (`fixtures/sql_static_bandit/`). The README's new "Scan allowlist convention" paragraph pins this contract.

12. **AC12 — No `src/comadre/` changes.** `git diff master -- src/comadre/` returns empty at story completion. Invariant: `git diff master -- src/comadre/ | wc -l` is `0`.

13. **AC13 — CI YAML untouched.** `git diff master -- .github/workflows/ci.yml | wc -l` returns `0`. The existing `non-regression` job auto-discovers the new test file.

14. **AC14 — No new runtime or dev dependency.** `git diff master -- pyproject.toml uv.lock | wc -l` returns `0`. Scan is pure stdlib (`ast`, `re`, `pathlib`, `dataclasses`).

15. **AC15 — `tests/conftest.py` marker registration unchanged.** `git diff master -- tests/conftest.py | wc -l` returns `0`. The broadened marker description landed in 4.5b is already sufficient for this story.

16. **AC16 — README ownership row finalised; allowlist convention documented.** `tests/test_non_regression/README.md` ownership-table row for `test_timing_safe_compare.py` carries the final FR48 description (verbatim or materially equivalent to the text in §Scope-3). A new "Scan allowlist convention" paragraph sits under "Extension contract" (after 4.5b's "Harness choice" section) documenting the `# scan-allow: <reason>` contract AND the per-sub-story fixture-directory convention.

17. **AC17 — Failure-UX verified with a localised regression.** Temporarily insert a minimal flaggable statement (e.g., `_PROBE_HASH = "x"; assert _PROBE_HASH == _PROBE_HASH`) into a sacrificial location under `src/comadre/` (recommended: a private no-op block at the top of `src/comadre/config.py`). Run `uv run pytest -m non_regression tests/test_non_regression/test_timing_safe_compare.py::test_src_comadre_has_no_unsafe_key_comparisons`. Observe a failure message of the form `src/comadre/<file>.py:<lineno>: bare equality compare on '_PROBE_HASH' — <source>`, with a remediation hint naming `hmac.compare_digest` and `# scan-allow: <reason>`. Restore the file (`git checkout -- src/comadre/config.py`) immediately. Dev agent logs the observed failure message verbatim in the Dev Agent Record > Debug Log References.

18. **AC18 — Full quality-gate suite stays green.** `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src/`, `uv run pytest` (default), `uv run pytest -m non_regression tests/test_non_regression/ -v`, and `uv run pre-commit run --all-files` all exit 0.

## Tasks / Subtasks

- [x] **Task 1 — Scaffold fixtures directory and three fixture files** (AC3, AC5, AC6, AC10, AC11)
  - [x] 1.1 Create `tests/test_non_regression/fixtures/` (no `__init__.py` — not a package; pytest must not collect it as such).
  - [x] 1.2 Create `tests/test_non_regression/fixtures/timing_safe_compare/bad_example.py` per §Scope-2. One `authenticate(token_hash, stored_hash) -> bool` function with `return token_hash == stored_hash`. Docstring explicitly flags the file as a fixture (not production code).
  - [x] 1.3 Create `allowlisted_example.py` per §Scope-2. Same body shape as `bad_example.py` but the `return` line ends with `# scan-allow: fixture-intentional-for-4.5c` (shortened from `-self-test` suffix to fit ruff's 88-char line-length; the functional contract — presence of the `# scan-allow:` token — is unchanged).
  - [x] 1.4 Create `compare_digest_only.py` per §Scope-2. `return hmac.compare_digest(token_hash, stored_hash)` — Call node, not Compare node. Docstring names the AST-structural rationale.
  - [x] 1.5 Verify the fixture files lint clean under `uv run ruff check tests/test_non_regression/fixtures/` (should auto-pass; the files are syntactically minimal).

- [x] **Task 2 — Implement the scan helper and the primary regression assertion** (AC1, AC2, AC4)
  - [x] 2.1 Create `tests/test_non_regression/test_timing_safe_compare.py` per §Scope-1. One `_Violation` dataclass, one `_terminal_identifier`, one `_find_unsafe_comparisons`, one primary test `test_src_comadre_has_no_unsafe_key_comparisons`.
  - [x] 2.2 Inline the AC4 exclusion-rationale comment block (≥3 lines) above `_SUSPECT_IDENTIFIER_RE`.
  - [x] 2.3 Run `uv run pytest tests/test_non_regression/test_timing_safe_compare.py::test_src_comadre_has_no_unsafe_key_comparisons -m non_regression -v` — passes with zero violations in the current codebase (empirically verified at story-draft time via `rg -in "(hash|token|secret).*(==|!=)|(==|!=).*(hash|token|secret)" src/comadre/` returning zero hits).

- [x] **Task 3 — Add the three self-tests** (AC3, AC5, AC6)
  - [x] 3.1 Append `test_scan_flags_bad_example`, `test_scan_respects_allowlist_comment`, `test_scan_ignores_compare_digest_calls` per §Scope-2.
  - [x] 3.2 Run `uv run pytest tests/test_non_regression/test_timing_safe_compare.py -m non_regression -v` — all four tests pass.
  - [x] 3.3 Parametrisation is NOT used — each self-test pins one scan property in its own function (per §Scope-2 rationale).

- [x] **Task 4 — Verify marker + deselection behaviour** (AC7, AC8, AC9)
  - [x] 4.1 Confirm every new test carries `@pytest.mark.non_regression` via `grep -c "@pytest.mark.non_regression" tests/test_non_regression/test_timing_safe_compare.py` → `4`.
  - [x] 4.2 Run `uv run pytest` (default) — observed `1414 passed, 54 deselected` (4.5b close: 1414 passed / 50 deselected → +4 deselected as expected).
  - [x] 4.3 Run `uv run pytest -m non_regression tests/test_non_regression/ -v` — observed `38 passed, 16 skipped` (25 from 4.5a + 9 from 4.5b + 4 from 4.5c).

- [x] **Task 5 — Verify fixtures are not collected as tests** (AC10)
  - [x] 5.1 Run `uv run pytest -m non_regression tests/test_non_regression/ -v --collect-only | rg fixtures/` — returns empty. Fixture files have no `test_` prefix, so pytest's default collection skips them.
  - [x] 5.2 Run `uv run pytest -m non_regression tests/test_non_regression/fixtures/ -v` — reports "collected 0 items" / "no tests ran."

- [x] **Task 6 — Update README** (AC16)
  - [x] 6.1 Edit `tests/test_non_regression/README.md` ownership-table row for `test_timing_safe_compare.py` to the final FR48 description per §Scope-3.
  - [x] 6.2 Append the "Scan allowlist convention" paragraph under "Extension contract," after the existing "Harness choice" section.
  - [x] 6.3 Markdown lint covered by the Task 7 `pre-commit run --all-files` step.

- [x] **Task 7 — Verify invariants and the full quality-gate suite** (AC12, AC13, AC14, AC15, AC18)
  - [x] 7.1 `git diff master -- src/comadre/ | wc -l` returns `0` (AC12).
  - [x] 7.2 `git diff master -- .github/workflows/ci.yml | wc -l` returns `0` (AC13).
  - [x] 7.3 `git diff master -- pyproject.toml uv.lock | wc -l` returns `0` (AC14).
  - [x] 7.4 `git diff master -- tests/conftest.py | wc -l` returns `0` (AC15).
  - [x] 7.5 `uv run ruff check .` — all checks pass.
  - [x] 7.6 `uv run ruff format --check .` — 97 files already formatted.
  - [x] 7.7 `uv run mypy src/` — "Success: no issues found in 35 source files."
  - [x] 7.8 `uv run pytest` (default) — 1414 passed, 54 deselected.
  - [x] 7.9 `uv run pytest -m non_regression tests/test_non_regression/ -v` — 38 passed, 16 skipped.
  - [x] 7.10 `uv run pre-commit run --all-files` — ruff / ruff-format / hadolint / yamllint / shellcheck / markdownlint-cli2 / mypy all Passed.

- [x] **Task 8 — Failure-UX smoke** (AC17)
  - [x] 8.1 Temporarily added `_PROBE_HASH = "abc"` + `assert _PROBE_HASH == _PROBE_HASH` at the top of `src/comadre/config.py`.
  - [x] 8.2 Ran `uv run pytest -m non_regression tests/test_non_regression/test_timing_safe_compare.py::test_src_comadre_has_no_unsafe_key_comparisons`. Observed failure message (see Debug Log References) names relpath, line number, identifier, source line, and remediation hint per AC17.
  - [x] 8.3 Discarded the change with `git checkout -- src/comadre/config.py`; re-ran the scan — passes. Invariant `git diff master -- src/comadre/config.py | wc -l == 0` holds.

- [x] **Task 9 — Change log and status**
  - [x] 9.1 Change Log row appended (2026-04-24).
  - [x] 9.2 Status flipped `in-progress` → `review` at story-file head.

### Review Findings

- [x] [Review][Patch] Allowlist-token substring match accepts in-string occurrences — **resolved 2026-04-24.** `_find_unsafe_comparisons` now derives the allowlisted line set via a new `_allowlisted_lines` helper that walks `tokenize.generate_tokens` and records only real `tokenize.COMMENT` tokens whose payload contains `# scan-allow:`. STRING-token occurrences no longer suppress. New fixture `fixtures/timing_safe_compare/string_literal_allowlist_bypass.py` + new self-test `test_scan_rejects_string_literal_allowlist_bypass` prevent regression. [test_timing_safe_compare.py:82-97]
- [x] [Review][Patch] Multi-line `Compare` allowlist only checks `node.lineno` line — **resolved 2026-04-24.** The suppression check now sweeps `range(node.lineno, (node.end_lineno or node.lineno) + 1)` against the allowlisted-line set, so a `# scan-allow:` comment placed on any physical line the comparison spans correctly suppresses. New fixture `fixtures/timing_safe_compare/multiline_allowlist_example.py` (with `# fmt: off` to preserve the split) + new self-test `test_scan_allowlist_spans_multi_line_compare` prevent regression. [test_timing_safe_compare.py:139-142]
- [x] [Review][Patch] Operator-gating uses `all`, not `any` — **resolved 2026-04-24.** Quantifier flipped to `any(isinstance(op, (Eq, NotEq)) for op in node.ops)` and operand collection refined so only operands adjacent to an Eq/NotEq operator in the chain are checked (`for i, op in enumerate(node.ops): ... for idx in (i, i + 1): ...`). Concretely: `token_hash == x < y` now flags `token_hash`. New fixture `fixtures/timing_safe_compare/chained_mixed_ops_example.py` + new self-test `test_scan_flags_chained_mixed_ops` prevent regression. [test_timing_safe_compare.py:120-137]

> **Dismissed (8 originating + ~10 edge-case findings):** Walrus / `Call` / `BinOp` / `Starred` operands → spec's "Deferred work to flag at story close" item explicitly defers the local-flow analysis required to flag these. `*_type`/`*_algorithm`/`*_path` substring over-fire → spec line 244 + empirical preview-grep showed zero false positives in the current `src/comadre/` tree, and the `# scan-allow:` escape hatch handles any single future occurrence. Dead defensive bounds-check on `source_lines` → harmless. Single-violation-per-Compare on dual-operand cases → explicit design choice, comment at test file:158-161. `ast.parse` `SyntaxError` un-caught → cannot occur in a tree that mypy + pytest collection already accept. Match-case patterns / `Subscript` literal-key indexing / `.pyi` stubs / symlink traversal / non-UTF-8 BOM / fixture-exclusion guard / 4.5f–4.5g token-collision → all hypothetical with zero current incidence in the codebase, and either spec-deferred or README-addressed. Self-test colon-pinning + ruff-format reflow fragility → adding the assertions is cheap but the practical risk is near zero given ruff is CI-enforced and the existing fixture has the colon. Docstring claim "terminal name component matches" → re-read shows the docstring's parenthetical "(substring match on hash/token/secret, case-insensitive)" already disambiguates. README-omits-`key`-exclusion → README's ownership-table row explicitly enumerates `*hash*`/`*token*`/`*secret*` (precise about what IS covered; doesn't claim `*key*`).

## Dev Notes

### Design decisions

**Why AST over ripgrep.** The epic AC admits either ("ripgrep-backed or AST-based"). AST wins on three axes: (a) zero false-positives from `==` inside docstrings / comments / string literals (a regex would need hand-crafted negative lookbehinds that are fragile under docstring formatting changes); (b) robust to line-continuation and multi-line expressions that split `a\n    == b` across two lines (regex would miss or mis-flag depending on flags); (c) operand-identifier extraction is the whole point — `ast.walk` gives us `ast.Compare.left` and `ast.Compare.comparators` with exact name resolution, whereas ripgrep would force us to parse the captured substring with a mini-lexer. AST also parses the file as valid Python, which catches upstream syntax errors with a clear failure message — a regex scan would silently accept a file that's partially unparseable.

**Why the `hash|token|secret` substring rule without `key`.** Empirical observation from `rg -in "(hash|token|secret).*(==|!=)|(==|!=).*(hash|token|secret)" src/comadre/` at story-draft time: zero hits. The current auth path uses `hmac.compare_digest` everywhere, and no other identifier ending in `hash`/`token`/`secret` participates in a bare `==`/`!=`. Adding `key` to the substring set would flag ~15 legitimate lines (`key_row.billing_mode == "complimentary"`, `resolved.kind == "key_ambiguous"`, etc.) — each would need an allowlist comment, polluting the codebase and diluting the "a scan-allow comment is a red flag" review signal. The story's scope is timing-safe comparison on key **material**; key-material identifiers always contain `hash`/`token`/`secret` — the exclusion of `key` is a precision/recall trade the story accepts with open eyes.

**Why substring match instead of suffix-only.** A suffix-only rule (`r"(hash|token|secret)s?$"`) would miss `_DUMMY_HASH` (ends in `HASH` but uppercase; case-insensitive suffix fixes that), `hash_api_key` (ends in `key`, not `hash`), `bearer_token_header` (ends in `header`, not `token`). Substring catches all three. Current codebase has no false-positives under substring-match-without-`key`, so the precision cost of broadening to substring is zero and the recall gain is real.

**Why `ast.Eq`/`ast.NotEq` only, not `ast.Is`/`ast.IsNot`.** `is`/`is not` comparisons in Python are identity checks, not value checks, and are constant-time by construction (they compare `id()` values, not content). `x is None` / `x is not None` patterns are ubiquitous and semantically orthogonal to the timing-safe-compare contract. Excluding `Is`/`IsNot` from the scan keeps the rule focused on the actual risk surface (value-equality) without noise.

**Why we flag only ONE violation per Compare node (not per operand).** A compare like `token_hash == other_hash` has two suspect operands; both flag independently, but the rendered failure message already names the line, and enumerating each operand would produce "line 42: token_hash" + "line 42: other_hash" duplicates. One-per-node halves the noise and still names the identifier (whichever operand the walker hit first).

**Why fixtures live in `tests/test_non_regression/fixtures/timing_safe_compare/` and not flat under `fixtures/`.** 4.5f and 4.5g will need fixture files too. Each sub-story should own its own subdirectory to avoid namespace collision. `timing_safe_compare/bad_example.py` + `no_raw_httpexception/bad_example.py` can safely coexist; flat `fixtures/bad_example.py` + `fixtures/bad_example_2.py` would be a mess. AC11 pins this convention explicitly so the next static-scan sub-story (4.5f) doesn't re-litigate.

**Why no `__init__.py` in the fixtures directory.** The fixture files are `.py` source samples, not importable modules. Adding `__init__.py` would make `tests.test_non_regression.fixtures.timing_safe_compare` an importable package, which (a) adds zero value, (b) risks pytest's rootdir-discovery seeing the fixtures as part of the test tree and collecting them, (c) couples the fixture namespace to Python import mechanics that are irrelevant to the scan (the scan reads files by path, not by import). Omitting `__init__.py` keeps fixtures inert at import time.

**Why the scan reads `source_lines` separately from the AST.** The allowlist check is a line-level concern (is there a `# scan-allow:` comment on the same line?). `ast.parse` strips comments; `ast.Compare` carries a line number but not the raw source line. Reading `source.splitlines()` once per file is O(n) in file size and adds negligible overhead. Alternative: re-parsing with `tokenize` to capture comments — more complex, no accuracy gain.

**Why one primary test + three self-tests, not one parametrised test.** Each self-test pins a distinct property. Parametrisation would collapse the failure messages ("bad_example should have 1 violation; got 0" vs "allowlisted_example should have 0 violations; got 1" vs "compare_digest_only should have 0 violations; got 1") into three cases of one test — the failure output would still be three lines, but the test-name column would read the same, obscuring which property regressed at a glance.

### Import-graph placement

- **`tests/test_non_regression/test_timing_safe_compare.py` (NEW).** Imports: stdlib (`ast`, `re`, `dataclasses.dataclass`, `pathlib.Path`), `pytest`. No `comadre.*` imports — the scan reads files by path, not by Python import (so a syntax error in `src/comadre/` surfaces as a `SyntaxError` from `ast.parse` rather than as an `ImportError` at test-module-import time).
- **`tests/test_non_regression/fixtures/timing_safe_compare/bad_example.py` (NEW).** Pure source-only fixture; the only import is `from __future__ import annotations`.
- **`tests/test_non_regression/fixtures/timing_safe_compare/allowlisted_example.py` (NEW).** Same shape as `bad_example.py`.
- **`tests/test_non_regression/fixtures/timing_safe_compare/compare_digest_only.py` (NEW).** Imports `hmac`; nothing else.
- **`tests/test_non_regression/README.md` (MOD).** Prose-only edits (ownership-row description + new "Scan allowlist convention" paragraph).
- **`tests/conftest.py` — unchanged.** The `non_regression` marker registration landed by 4.5a and broadened by 4.5b is already correct for this story.
- **`pyproject.toml` — unchanged.** `addopts = "-m 'not non_regression'"` already deselects the new tests by default.
- **`.github/workflows/ci.yml` — unchanged.** The `non-regression` job auto-discovers the new module.
- **`src/comadre/**` — unchanged.** AC12 invariant.

### Test-flake avoidance

- **Deterministic file discovery.** `sorted(_SRC_ROOT.rglob("*.py"))` yields an alphabetically stable iteration order. A future test-run on a filesystem with non-deterministic directory ordering (some network-mounted FS) still produces identical failure-message ordering.
- **No `tmp_path` or `tmp_path_factory`.** The scan reads paths under the repository — if the working directory differs from the repo root, `_PROJECT_ROOT = Path(__file__).resolve().parents[2]` resolves correctly because the test module's location is fixed relative to the repo.
- **No shared mutable state.** Each test invokes `_find_unsafe_comparisons` on its own input. No module-level cache, no `lru_cache` on the scan.
- **No asyncio.** All four tests are sync `def`. No event-loop fixture needed.
- **AST stability across Python versions.** `ast.Compare`, `ast.Eq`, `ast.NotEq`, `ast.Name`, `ast.Attribute`, `ast.Subscript`, `ast.walk` are all stable stdlib API since Python 3.0. The project targets 3.12; no compat shim needed.
- **`ast.parse` with the file path as `filename=`.** Makes any `SyntaxError` carry the real source path in its traceback — the test failure message names the file that failed to parse, not an opaque `<string>`.

### Project Structure Notes

- **Alignment with unified project structure.**
  - Test module naming: `tests/test_non_regression/test_timing_safe_compare.py` — matches the ownership table in `tests/test_non_regression/README.md` (row for 4.5c).
  - Fixture directory: `tests/test_non_regression/fixtures/timing_safe_compare/` — new convention, pinned by AC11 and documented in the README's new "Scan allowlist convention" paragraph.
  - Helper naming: `_find_unsafe_comparisons`, `_terminal_identifier`, `_Violation` (leading-underscore module-privates, snake_case functions, PascalCase dataclass) — matches existing codebase convention (e.g., `_method_not_allowed_handler` in `src/comadre/main.py`; `_Violation`-style dataclasses in `src/comadre/keys/db.py`).
  - Allowlist comment token: `# scan-allow:` (colon, one word before the colon, exact token `scan-allow`) — chosen for grep-friendliness (`rg "scan-allow:"` enumerates every allowlisted line in the codebase at review time).

- **Detected conflicts or variances (with rationale).**
  - The fixtures sit under `tests/test_non_regression/fixtures/` rather than inline as string literals in the test module (e.g., `ast.parse(dedent("..."))`). Rationale: inline-string fixtures would work for `bad_example` and `allowlisted_example` (few lines each), but the trade-off is readability — the fixture intent is clearer as a standalone `.py` file that a reviewer can open, lint-check, and diff against. The precedent also matters for 4.5f and 4.5g, which may need longer fixture modules that are awkward as string literals. AC11 and the README's new section pin the convention.

### Testing standards

- **Sync tests, not async.** The scan is I/O-bound but synchronous (`path.read_text()`, `ast.parse`). Using `async def` would force a `pytest-asyncio` loop for no gain.
- **Assertion messages.** Every assertion carries a failure message naming (a) which property broke, (b) the expected vs observed state, (c) a diagnostic tail. Inherits the 4.5a + 4.5b "name-the-regression" convention. The primary assertion additionally carries remediation text naming `hmac.compare_digest` and `# scan-allow:`.
- **No fixture-level assertions.** The helper functions (`_find_unsafe_comparisons`, `_terminal_identifier`) do NOT raise on malformed input — they return violation lists (possibly empty). Fixture-level `assert` would mask test identity in the failure output.

### Deferred work to flag at story close

- **Expand the scan's identifier set to include `key` under a narrower operand-type gate.** If a future regression lands a `*key*` identifier comparison that the current rule misses, the fix is to narrow the operand-type gate (e.g., only flag when the operand is a `Name` bound to a `hash_api_key(...)` return value, via a local-flow analysis). Out of scope today because no observed regression surface needs it and the local-flow analysis is a 10x complexity bump over the current AST walk.
- **Track `# scan-allow:` allowlist entries across the codebase.** A future housekeeping story can add a secondary scan that counts `# scan-allow:` comments per-file and flags any file with > N allowlists. Serves as an early warning for scan-policy drift. Out of scope today — zero allowlist entries exist at story close.
- **Cross-link the scan with bandit's existing `B105`/`B106`/`B107` hardcoded-password checks.** Bandit catches a subset of the risk surface (hardcoded passwords in code); 4.5c catches the comparison-operator regression. A future integration story can route 4.5c's violation list through bandit's issue format for CodeQL / SARIF upload on the GitHub security tab. Out of scope — adds tooling complexity without changing the PR-level gate.
- **Whitelist-based operand-type gate (positive list).** Currently the scan flags every `==`/`!=` on a suspect identifier. A positive-list variant could flag ONLY when the operand is assigned from a known-sensitive source (`hash_api_key(...)`, `secrets.token_*`, `hmac.digest(...)`). This would tighten precision at the cost of a flow analysis; today's substring rule is sufficient and false-positive-free.
- **Extend scan scope to `deploy/` scripts or `scripts/`.** No active key-comparison lives in those trees today; `deploy/` is ansible YAML + Jinja2, not Python; `scripts/loadtest.py` and `scripts/capacity_test.py` don't handle key material. If that changes, broaden `_SRC_ROOT` to a list. Noted for awareness.
- **Line-number pinning on the bad-fixture self-test.** Currently the self-test asserts the identifier and source-substring, not the exact line. A stable-format pre-commit hook on the fixture file would make line-number pinning safe; but it's a pre-commit-hook story, not 4.5c's.

### References

- Epic 4 Story 4.5 umbrella — `_bmad-output/planning-artifacts/epics.md:878-888`
- Epic 4 Story 4.5c — `_bmad-output/planning-artifacts/epics.md:930-945`
- FR48 — `_bmad-output/planning-artifacts/prd.md:97, 256, 1192`
- NFR11 — `_bmad-output/planning-artifacts/prd.md:120, 1215`
- NFR17 — `_bmad-output/planning-artifacts/prd.md:1221`
- PRD Non-Regression Contract (timing-safe-compare row) — `_bmad-output/planning-artifacts/prd.md:654`
- PRD §Architecture-Level Security Controls — `_bmad-output/planning-artifacts/prd.md:700, 751, 829-838`
- Architecture timing-safe-compare in auth sequence — `_bmad-output/planning-artifacts/architecture.md:208, 472, 673`
- Story 4.5a (predecessor; skeleton + marker + CI job) — `_bmad-output/implementation-artifacts/4-5a-ci-security-headers-regression.md`
- Story 4.5b (predecessor; non-docker-test precedent, README harness-choice) — `_bmad-output/implementation-artifacts/4-5b-ci-docs-endpoints-disabled-regression.md`
- `hmac.compare_digest` call sites — `src/comadre/keys/auth.py:47-48, 125, 136-137`
- `hash_api_key` contract — `src/comadre/keys/tokens.py:43-50`
- `AuthCache` (no equality comparisons on hashes) — `src/comadre/keys/cache.py`
- Unit-test coverage of the positive call (`compare_digest`) — `tests/test_keys_auth.py::TestDbMissPath::test_db_miss_runs_dummy_compare_and_raises_not_found` (lines 203-235)
- Non-regression marker registration — `tests/conftest.py:30-33` (broadened by 4.5b)
- Non-regression package README — `tests/test_non_regression/README.md` (ownership-table row for 4.5c at line 18; new "Scan allowlist convention" paragraph appended by this story)
- `pyproject.toml` `addopts = "-m 'not non_regression'"` — established by 4.5a; unchanged by 4.5c
- Empirical preview grep (zero false positives at story-draft time) — `rg -in "(hash|token|secret).*(==|!=)|(==|!=).*(hash|token|secret)" src/comadre/` returns 0 matches on 2026-04-23

## Dev Agent Record

### Agent Model Used

claude-opus-4-7 (1M context)

### Debug Log References

**AC17 failure-UX probe — observed pytest output (verbatim, 2026-04-24):**

```
E       AssertionError: Bare equality comparison on key material detected in src/comadre/.
E         This regression breaks NFR11 (timing-safe key comparison contract).
E         Use ``hmac.compare_digest(a, b)`` instead of ``a == b`` when either
E         operand holds hashed/tokenised key material. If the comparison is
E         intentional and does NOT handle key material (e.g., an equality
E         check on a non-sensitive field that incidentally contains the word
E         'hash' or 'token'), add a trailing comment on the same line:
E             # scan-allow: <why this is safe, reviewed by <initials>>
E
E         Violations:
E           src/comadre/config.py:6: bare equality compare on '_PROBE_HASH' — assert _PROBE_HASH == _PROBE_HASH
E       assert not [_Violation(path=PosixPath('/home/galvani/dev/comadre/src/comadre/config.py'), lineno=6, identifier='_PROBE_HASH', source='assert _PROBE_HASH == _PROBE_HASH')]
```

The message satisfies AC17 on all five required elements: (a) source path `src/comadre/config.py`, (b) line number `6`, (c) identifier `_PROBE_HASH`, (d) source snippet `assert _PROBE_HASH == _PROBE_HASH`, (e) remediation hint naming both `hmac.compare_digest(a, b)` and the `# scan-allow: <reason>` escape hatch.

### Completion Notes List

- All 18 ACs satisfied. Four new tests under the `non_regression` marker (1 primary regression assertion over `src/comadre/**/*.py` + 3 self-tests over fixtures) pass in 0.11s.
- `tests/test_non_regression/` gained one test module + one fixtures subdirectory with three source fixtures. Zero changes to `src/comadre/`, CI YAML, `pyproject.toml`, `uv.lock`, or `tests/conftest.py` (grep invariants AC12–AC15 all return `0`).
- **Minor deviation from AC5's example reason text.** The allowlisted fixture uses `# scan-allow: fixture-intentional-for-4.5c` instead of the story-spec's longer `fixture-intentional-for-4.5c-self-test`. Rationale: ruff's 88-char line-length would reject the longer form, and adding a per-file `noqa` or a `pyproject.toml` per-file-ignore would either pollute the scan-allow comment parsing or break AC14's no-diff invariant on `pyproject.toml`. AC5's programmatic contract (`violations == []` because a `# scan-allow:` substring is present on the line) is unaffected — the scan uses a substring check (`_ALLOWLIST_TOKEN in line`), not a reason-text match. Flagged here so a reviewer can confirm the deviation is acceptable.
- No new runtime or dev dependency. Scan is pure stdlib (`ast`, `re`, `pathlib`, `dataclasses`).
- README's "Scan allowlist convention" paragraph pins the shared contract so 4.5f / 4.5g can inherit the same `# scan-allow:` token + `fixtures/<check_name>/` subdirectory shape without re-design.
- Full `pre-commit run --all-files` suite green (ruff, ruff-format, hadolint, yamllint, shellcheck, markdownlint-cli2, mypy).
- **Code-review patches (2026-04-24, post-`review`).** Three decision-needed findings from `bmad-code-review` all resolved as patches: tokenize-based allowlist detection (Finding #1), multi-line Compare allowlist sweep (Finding #2), operator-gating `all`→`any` refinement (Finding #3). Three new self-tests and three new fixture files landed under `tests/test_non_regression/fixtures/timing_safe_compare/` (string_literal_allowlist_bypass.py, chained_mixed_ops_example.py, multiline_allowlist_example.py). Non-regression opt-in run now reports **41 passed, 16 skipped** (up from 38/16 at story close); default `uv run pytest` reports **1414 passed, 57 deselected** (up from 1414/54, +3 new deselected tests as expected). All quality gates re-verified green (ruff check, ruff format --check, mypy src/, pytest default, pytest non_regression). AC9's numeric expectation (38 passed) is superseded by the patched count (41 passed); AC1's operand-gating description is tightened (only Eq/NotEq-adjacent operands checked); AC5's programmatic contract still holds (tokenize sees the real COMMENT token on the allowlisted fixture's line); no other AC is materially affected.

### File List

**New:**

- `tests/test_non_regression/test_timing_safe_compare.py`
- `tests/test_non_regression/fixtures/timing_safe_compare/bad_example.py`
- `tests/test_non_regression/fixtures/timing_safe_compare/allowlisted_example.py`
- `tests/test_non_regression/fixtures/timing_safe_compare/compare_digest_only.py`
- `tests/test_non_regression/fixtures/timing_safe_compare/string_literal_allowlist_bypass.py` (added 2026-04-24 during code review — Finding #1 regression guard)
- `tests/test_non_regression/fixtures/timing_safe_compare/chained_mixed_ops_example.py` (added 2026-04-24 during code review — Finding #3 regression guard)
- `tests/test_non_regression/fixtures/timing_safe_compare/multiline_allowlist_example.py` (added 2026-04-24 during code review — Finding #2 regression guard)

**Modified:**

- `tests/test_non_regression/README.md` (ownership-table row for 4.5c refined; new "Scan allowlist convention" paragraph appended under "Extension contract")
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (4.5c status transition ready-for-dev → in-progress → review; `last_updated` bumped)
- `_bmad-output/implementation-artifacts/4-5c-ci-timing-safe-key-comparison-static-check.md` (Tasks/Subtasks checkboxes, Dev Agent Record, File List, Change Log, Status only — no changes to Story, Acceptance Criteria, Dev Notes, Scope, Builds on, Unblocks, Depends on sections)

## Change Log

| Date       | Change                                                                                                                          |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------- |
| 2026-04-23 | Story spec drafted (status `ready-for-dev`). Scan design finalised: AST-based over `src/comadre/**/*.py`, substring rule `hash\|token\|secret` (case-insensitive, `key` excluded with rationale), `# scan-allow: <reason>` inline-comment allowlist, three fixture files driving self-tests under `tests/test_non_regression/fixtures/timing_safe_compare/`. First static-scan sub-story; establishes the fixture-directory convention 4.5f and 4.5g inherit. |
| 2026-04-24 | Story implemented — scan helper + primary regression assertion + 3 self-tests landed in `tests/test_non_regression/test_timing_safe_compare.py`; fixture subdirectory `tests/test_non_regression/fixtures/timing_safe_compare/` created with 3 source fixtures; README ownership row refined and "Scan allowlist convention" paragraph appended under "Extension contract". All 18 ACs satisfied. Non-regression opt-in run reports 38 passed / 16 skipped; default `uv run pytest` reports 1414 passed / 54 deselected (+4 vs 4.5b close); `pre-commit run --all-files` green. Status flipped `ready-for-dev` → `in-progress` → `review`. |
| 2026-04-24 | Code-review patches applied — three decision-needed findings from `bmad-code-review` all resolved as patches. (1) Allowlist detection switched from raw substring match to `tokenize.generate_tokens` COMMENT-token filtering via new `_allowlisted_lines` helper — closes string-literal bypass (Finding #1). (2) Allowlist suppression now sweeps `node.lineno..node.end_lineno` — comment on any physical line spanned by a multi-line Compare correctly suppresses (Finding #2). (3) Operator-gating quantifier flipped `all`→`any` and operand collection restricted to operands adjacent to an Eq/NotEq operator — closes chained-mixed-ops gap where `token_hash == x < y` was silently passed (Finding #3). Three new regression-guard fixtures (`string_literal_allowlist_bypass.py`, `chained_mixed_ops_example.py`, `multiline_allowlist_example.py`) and three new self-tests (`test_scan_rejects_string_literal_allowlist_bypass`, `test_scan_flags_chained_mixed_ops`, `test_scan_allowlist_spans_multi_line_compare`) prevent regression on each. Quality gates re-verified green: ruff check, ruff format --check, mypy src/, default pytest (1414 passed / 57 deselected), non_regression pytest (41 passed / 16 skipped). Status flipped `review` → `done`. |
