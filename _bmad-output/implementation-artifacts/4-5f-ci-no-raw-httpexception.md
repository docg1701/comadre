# Story 4.5f: CI — No Raw HTTPException

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

> **Scope note — FR51, NFR17.** Sixth of the seven CI non-regression sub-stories (4.5a–4.5g). Inherits the skeleton 4.5a landed (`tests/test_non_regression/` package, `non_regression` pytest marker, `addopts = "-m 'not non_regression'"` default-exclusion in `pyproject.toml`, `non-regression` job in `.github/workflows/ci.yml`), the harness-choice convention 4.5b broadened (static-scan tests admitted under the marker), and — critically — the static-scan pattern 4.5c established (AST walk + `tokenize`-based `# scan-allow:` line-comment allowlist + fixture subdirectory per sub-story + one-self-test-per-scan-property discipline). 4.5f is the **second** static-scan sub-story and deliberately mirrors 4.5c's module structure so a reviewer familiar with 4.5c can pattern-match 4.5f in seconds. Delivers three artefacts: (1) a pure-stdlib AST-based scan helper inside the new test module (`_find_raw_httpexception_usages`); (2) `tests/test_non_regression/test_no_raw_httpexception.py` asserting the scan finds zero violations in `src/comadre/`; (3) four fixture files under `tests/test_non_regression/fixtures/no_raw_httpexception/` driving the scan's self-tests (flags bad `raise`, flags bad `import`, respects allowlist comment on both forms, ignores legitimate `ComadreError` raises and docstring mentions of the class name). **No change to `src/comadre/`. No new Python dependency. No CI YAML change. No `pyproject.toml` change. No `tests/conftest.py` change.**

> **Empirical premise (READ BEFORE IMPLEMENTING).** At story-draft time (2026-04-24), `src/comadre/` contains **zero** `raise HTTPException(...)` statements and **zero** `from fastapi import HTTPException` / `from fastapi.exceptions import HTTPException` / `from starlette.exceptions import HTTPException` imports. The entire error surface is already routed through `ComadreError` subclasses (`exceptions.py:18-220`), rendered by `comadre_error_handler` (`exceptions.py:223-245`) and `unhandled_error_handler` (`exceptions.py:248-260`), registered via `register_exception_handlers(app)` at `main.py:341`. The two `HTTPException` mentions in `src/comadre/main.py:250` and `src/comadre/main.py:276` are **docstrings** documenting that `_not_found_handler` and `_method_not_allowed_handler` convert Starlette's built-in `HTTPException(404)` / `HTTPException(405)` into the project envelope — they are `ast.Expression`/`ast.Constant` string-literal nodes, NOT `ast.ImportFrom` or `ast.Raise`, so an AST-based scan structurally ignores them. This empirical baseline means 4.5f's scan runs clean on the current codebase with zero allowlist comments. Grep invariants that must hold before 4.5f lands (and must continue to hold after):
> - `rg "raise HTTPException" src/comadre/` → 0 hits.
> - `rg "from fastapi import HTTPException" src/comadre/` → 0 hits.
> - `rg "from fastapi.exceptions import HTTPException" src/comadre/` → 0 hits.
> - `rg "from starlette.exceptions import HTTPException" src/comadre/` → 0 hits.
> - `rg "HTTPException" src/comadre/` → exactly 2 hits, both in docstrings (main.py:250, main.py:276).
>
> The architecture document pins this at `architecture.md:470`: *"The auth path must NEVER raise `HTTPException` — always use the typed subclasses."* CLAUDE.md pins the codebase-wide invariant: *"All errors via `ComadreError` subclasses with `status_code`, `error_type`, `hint` — never raw HTTPException."* 4.5f converts those prose guarantees to a mechanically-enforced PR-level gate.

## Story

As a contributor,
I want every pull request against master to prove — via a pure-stdlib AST scan over `src/comadre/**/*.py` — that no module raises a raw `HTTPException` (`ast.Raise` whose `.exc` is a Call whose terminal function name is `HTTPException`) and no module imports `HTTPException` from `fastapi`, `fastapi.exceptions`, or `starlette.exceptions` (`ast.ImportFrom` with `module in {"fastapi", "fastapi.exceptions", "starlette.exceptions"}` and `names[*].name == "HTTPException"`), so the sole permitted error surface is the `ComadreError` hierarchy (or an explicitly allowlisted, reviewer-approved exception-bridging helper),
so that a well-meaning PR that "quick-fixes" an error path by `raise HTTPException(status_code=403, detail="forbidden")` — or that imports `HTTPException` for a one-off dependency that bypasses the `comadre_error_handler` bridge — cannot land on master without the PR build turning red and naming exactly which file, line, violation kind (`raise` vs `import`), and offending source snippet regressed.

**Covers FRs:** FR51 (CI can verify that no new code raises a raw `HTTPException`; every error path uses a `ComadreError` subclass).
**NFRs:** NFR17 (all Non-Regression Contract controls remain satisfied on every PR; CI regression coverage mandatory for each control row).
**UX-DRs:** Contributor-facing CI UX — when the scan fires, the pytest failure message MUST name (a) the absolute source path, (b) the line number, (c) the violation kind (`raise HTTPException(...)` vs `from <module> import HTTPException`), (d) a one-line snippet of the offending source, (e) a remediation hint naming `ComadreError` + the project exception hierarchy (`src/comadre/exceptions.py`) and the `# scan-allow: <reason>` escape hatch. Inherits the 4.5a "name-the-regression" assertion convention and the 4.5c fixture-per-scan-property discipline (here: four fixture files, one per distinct property the scan must uphold).
**Epic:** 4 — Security Hardening, LGPD & Operational Safety. Tenth story in Epic 4 (4.1 → 4.2 → 4.3 → 4.4 → 4.5a → 4.5b → 4.5c → 4.5d → 4.5e → **4.5f** → 4.5g → 4.6). Sixth of the seven-sub-story CI non-regression cluster; second static-scan sub-story. Second occupant of the `tests/test_non_regression/fixtures/` directory (4.5c established it; 4.5f adds a sibling subdirectory `no_raw_httpexception/`). Appends ONE test module + ONE fixtures subdirectory with four source fixtures — zero CI YAML changes, zero `src/comadre/` changes, zero marker changes, per the 4.5a + 4.5b + 4.5c extension contract.

## Builds on

- **Story 4.5a — CI non-regression skeleton (`done`).** Established the `tests/test_non_regression/` package, the `non_regression` pytest marker (`tests/conftest.py:30-33`), the `addopts = "-m 'not non_regression'"` default-exclusion in `pyproject.toml`, the `non-regression` CI job in `.github/workflows/ci.yml` that runs `uv run pytest -m non_regression tests/test_non_regression/ -v`, and the "Extension contract" README section (`tests/test_non_regression/README.md:150-175`). 4.5f adds exactly one `test_<check_name>.py` plus one fixtures subdirectory — the blueprint 4.5a promised.
- **Story 4.5b — README harness-choice section (`done`).** Broadened the `non_regression` marker's description to cover both docker and in-process tests, and codified the Harness choice paragraph (`tests/test_non_regression/README.md:177-191`) which names 4.5f verbatim: *"Static-scan checks skip both harnesses."* 4.5f is a pure stdlib AST + tokenize walk; no docker, no ASGI TestClient, no HTTP traffic.
- **Story 4.5c — First static-scan sub-story (`done`).** THE canonical reference for 4.5f's shape. 4.5c established:
  - The AST-walk + `tokenize`-based-allowlist pattern — 4.5f reuses the `_allowlisted_lines(source: str) -> set[int]` helper verbatim (same `tokenize.generate_tokens` walk, same `_ALLOWLIST_TOKEN = "# scan-allow:"` constant, same multi-line-span suppression via `range(node.lineno, (node.end_lineno or node.lineno) + 1)`).
  - The fixture-subdirectory convention — `tests/test_non_regression/fixtures/<check_name>/` (4.5c uses `timing_safe_compare/`; 4.5f uses `no_raw_httpexception/`).
  - The `# scan-allow: <reason>` inline-comment contract — reviewer-enforced reason text, free-form, reviewer-blocker for empty/one-word reasons. 4.5c's README addition (`tests/test_non_regression/README.md:193-206`, "Scan allowlist convention") already names 4.5f explicitly: *"Static-scan sub-stories (4.5c, 4.5f, 4.5g) share one escape hatch..."*
  - The one-self-test-per-scan-property discipline — 4.5c's three self-tests (flag-bad, respect-allowlist, ignore-compare_digest-call) model 4.5f's four self-tests (flag-bad-raise, flag-bad-import, respect-allowlist, ignore-comadre-error-raises).
  - The `_Violation` dataclass shape (`path`, `lineno`, `identifier`, `source`, `render()` method) — 4.5f reuses this verbatim but widens `identifier` to a `kind: Literal["raise", "import"]` field PLUS retains the `identifier` string for consistency (the class name is always `"HTTPException"` for FR51 — pinned for grep-friendly failure messages).
  - The `sorted(_SRC_ROOT.rglob("*.py"))` discovery pattern, `_PROJECT_ROOT = Path(__file__).resolve().parents[2]` anchoring, `source.splitlines()` side-by-side with `ast.parse` — all inherited as-is.
- **Existing error-surface contract — `src/comadre/exceptions.py:18-266`.** The `ComadreError` base class + 11 concrete subclasses (`VoiceNotFoundError`, `InvalidRequestError`, `GenerationError`, `AuthenticationError`, `ApiKeyNotFoundError`, `ApiKeySuspendedError`, `ApiKeyRevokedError`, `RateLimitError`, `InvalidTaxIdError`, `KeyRegistryError`, `ServiceUnavailableError`), `comadre_error_handler` (renders the `{error: {message, type, hint}}` envelope with status-code-aware headers for `RateLimitError`/`ServiceUnavailableError`), `unhandled_error_handler` (logged-500 fallback), and `register_exception_handlers(app)` (centralised registration at `main.py:341`). 4.5f's scan asserts the **observable invariant** of this design: no module bypasses the hierarchy by raising or importing the FastAPI/Starlette `HTTPException` primitive.
- **Existing FastAPI handler-registration surface — `src/comadre/main.py:342-344`.** Registers three framework-sourced handlers that convert Starlette's built-in 404/405/422 responses into the project envelope WITHOUT ever importing `HTTPException` as a class name — the handlers take `exc: Exception` and the class reference is never typed. This is the canonical pattern for bridging framework-emitted errors into the project envelope: subscribe to the status code (`app.add_exception_handler(404, _not_found_handler)`) or the base `Exception`, never import `HTTPException` just to re-raise it. 4.5f pins this pattern — any future bridging helper that DOES legitimately need `HTTPException` (e.g., a custom ASGI middleware that re-raises with a mutated status) must carry a `# scan-allow: <reason>` comment AND get reviewer sign-off. Today, zero such helpers exist.
- **CLAUDE.md codebase-wide invariant.** *"All errors via `ComadreError` subclasses with `status_code`, `error_type`, `hint` — never raw HTTPException."* 4.5f is the static-enforcement partner for this gotcha.
- **Architecture §Auth-path — `architecture.md:470`.** *"The auth path must NEVER raise `HTTPException` — always use the typed subclasses."* 4.5f broadens the scope from "auth path" to "all of `src/comadre/`" — because the one-off regression risk is not confined to auth; any endpoint, any dependency, any background task could regress the envelope contract.
- **Architecture §Code Review Pre-Flight — `architecture.md:484`.** *"Verify no `HTTPException` in new code — grep for it as a sanity check."* 4.5f promotes this from a manual reviewer pre-flight step to a mechanical CI gate. The manual step remains useful (catches regressions BEFORE the PR is opened), but the mechanical gate is authoritative.
- **PRD §Non-Regression Contract — `prd.md:141, 666`.** *"Zero `HTTPException` raises; all new errors via `ComadreError` subclasses"* and *"`ComadreError` subclasses only — `exceptions.py` hierarchy — New errors … extend `ComadreError`, set `status_code`, `error_type`, `hint`."* 4.5f converts these rows from prose-only to mechanically-enforced.
- **FR51 — PRD line 1195.** *"CI can verify that no new code raises a raw `HTTPException`; every error path uses a `ComadreError` subclass."* 4.5f fulfills this FR verbatim.
- **Story 1.6 — Legacy single-API_KEY mode retirement (`done`).** Part of the 2.0.0 rewrite that eliminated any remaining `HTTPException` raises from the auth path; replaced with `ApiKeyNotFoundError`/`ApiKeySuspendedError`/`ApiKeyRevokedError` subclasses. 4.5f guards against reintroducing the pre-2.0.0 pattern where auth denials used `HTTPException(401)`.

## Unblocks

- **Story 4.5g (`backlog`).** 4.5g is the `bandit`-based SQL-injection scan sub-story — conceptually similar (static analysis, fixture files, self-tests) but uses an external tool (`bandit`) rather than a stdlib AST walker. 4.5f closing demonstrates the second static-scan sub-story shape (after 4.5c pioneered it), reinforcing the fixture-subdirectory convention and the `# scan-allow:` contract. 4.5g can crib its README ownership-row language from 4.5f if the shape matches, though 4.5g's scan is fundamentally different (bandit takes its own config, has its own severity model, and surfaces findings via its own formatter).
- **PRD Non-Regression Contract FR51 row.** Converts the *"Zero `HTTPException` raises"* row from prose-only to mechanically enforced. Combined with 4.5a (FR46), 4.5b (FR47), 4.5c (FR48), 4.5d (FR49), and 4.5e (FR50), 4.5f brings six of the seven sub-stories' FR rows to mechanical enforcement — after 4.5f lands, the CI gate fails on regression of security headers, docs-disabled, timing-safe compare, oversized body rejection, rate-limit wiring, OR raw `HTTPException` usage.
- **Codebase-wide "ComadreError hierarchy only" invariant.** Once 4.5f lands, a PR cannot land ANY new `raise HTTPException(...)` or `from fastapi import HTTPException` anywhere under `src/comadre/` without an explicit `# scan-allow: <reason>` comment — regardless of whether the module is auth-adjacent, in the CLI tree, in a background task, or in a future async worker. The mechanical gate covers the whole risk surface, not just the auth path (which the architecture already pinned manually).
- **Operational confidence in the error-envelope contract.** Today the `{error: {message, type, hint}}` envelope is guaranteed by (a) code review, (b) the `comadre_error_handler` handler not being removable without breaking existing tests, and (c) the PRD Non-Regression Contract row cited above. After 4.5f lands, a mechanical gate catches the one regression class that those three guardrails miss — a one-off `raise HTTPException(...)` inside a new endpoint that bypasses the handler registration entirely (FastAPI routes raw HTTPExceptions through its OWN default handler, not through `comadre_error_handler`, so the envelope silently drifts to `{"detail": "..."}`).

## Depends on

- **Stories 4.5a, 4.5b, 4.5c are `done`** (sprint-status.yaml confirms; checked 2026-04-24). Hard dependency on 4.5a's non-regression package skeleton, marker, CI job, and the `addopts = "-m 'not non_regression'"` default-exclusion. Hard dependency on 4.5c's static-scan patterns (`_allowlisted_lines` tokenize helper, fixture-subdirectory convention, `# scan-allow:` contract, `_Violation` dataclass shape, one-self-test-per-property discipline). Soft dependency on 4.5b's README harness-choice paragraph (it names 4.5f as a static-scan sub-story; 4.5f's implementation simply matches what the README already promised).
- **Story 4.5d, 4.5e are `done`** (per sprint-status.yaml) — not structurally required (4.5d is docker-stack, 4.5e is TestClient), but 4.5f lands in a post-4.5e codebase so any quality-gate numbers cited downstream already include 4.5d/4.5e's contributions.
- **The `ComadreError` hierarchy is stable** (`src/comadre/exceptions.py:18-266`). 4.5f's remediation-hint text names `ComadreError` and `src/comadre/exceptions.py` explicitly. If the hierarchy were reshuffled mid-story, the remediation text would drift; no such reshuffle is planned.
- **No new runtime dependency.** `ast` is stdlib; `tokenize` is stdlib; `pathlib` is stdlib; `re` is stdlib; `dataclasses` is stdlib. Identical dependency surface to 4.5c.
- **No new dev dependency.** `pytest` already configured. `pytest-asyncio` is present but unused here (the scan is synchronous; tests are sync `def`, not `async def`).
- **No schema change. No auth-path change. No `src/comadre/` change. No `deploy/caddy/` change. No CI YAML change. No `pyproject.toml` change. No `tests/conftest.py` change. No `tests/test_non_regression/conftest.py` change. No new CLI verb. No ansible change.** Grep invariants (AC10–AC14): `git diff master -- src/comadre/ deploy/caddy/ .github/workflows/ci.yml pyproject.toml uv.lock tests/conftest.py tests/test_non_regression/conftest.py` returns empty. The entire story lives under `tests/test_non_regression/` — one new test module plus one new fixtures subdirectory with four files, and one README-row refinement.

## Scope

Three workstreams, in order:

1. **Ship the AST-based scan helper and the `src/comadre/` regression assertion** — `tests/test_non_regression/test_no_raw_httpexception.py`. Two module-local rule predicates (`_is_raw_httpexception_raise(node)`, `_is_httpexception_import(node)`) invoked by a single `_find_raw_httpexception_usages(path: Path) -> list[_Violation]` walker. One primary test that runs the scan across `src/comadre/**/*.py` and asserts zero violations.
2. **Ship the fixture files and the self-tests** — four files under `tests/test_non_regression/fixtures/no_raw_httpexception/` (`bad_raise.py`, `bad_import.py`, `allowlisted_raise.py`, `comadre_error_only.py`). Four self-tests assert: (a) the scan flags the bad-raise fixture with `kind="raise"`; (b) the scan flags the bad-import fixture with `kind="import"`; (c) the scan respects a `# scan-allow: <reason>` comment on either kind of line; (d) the scan does NOT flag `raise VoiceNotFoundError(...)` calls or docstring mentions of the string "HTTPException".
3. **README housekeeping** — refine the ownership-table row at `tests/test_non_regression/README.md:22` from *"Static check: no raw `HTTPException` outside permitted list"* to the verbose FR51 description naming the two scan shapes (raise + import) and the allowlist contract.

### 1. `_find_raw_httpexception_usages` + the primary regression assertion

**New module: `tests/test_non_regression/test_no_raw_httpexception.py`**

**The scan's two rules:**

1. **`raise HTTPException(...)` rule** — flag every `ast.Raise` node whose `.exc` is a `Call` node whose `.func` resolves to a terminal name `"HTTPException"`.
   - `raise HTTPException(403)` → `Raise(exc=Call(func=Name("HTTPException"), ...))` → **flagged**.
   - `raise fastapi.HTTPException(403)` → `Raise(exc=Call(func=Attribute(value=Name("fastapi"), attr="HTTPException"), ...))` → **flagged** (terminal attribute is `"HTTPException"`).
   - `raise starlette.exceptions.HTTPException(403)` → same shape via two Attributes → **flagged**.
   - `raise http_exc` where `http_exc` is a variable → `Raise(exc=Name("http_exc"))` → NOT flagged (no Call node; cannot statically prove the identity of the bound value). Acceptable gap — a future reviewer catches this; the `# scan-allow: <reason>` escape hatch covers the known-good case.
   - `raise HTTPException` (bare, no parentheses — re-raises the class itself; legal but weird) → `Raise(exc=Name("HTTPException"))` → **flagged** (`Name` terminal is `"HTTPException"`; the predicate treats bare-Name and Call-wrapping Name identically).
2. **`from <fastapi|fastapi.exceptions|starlette.exceptions> import HTTPException` rule** — flag every `ast.ImportFrom` node whose `.module` is in `_IMPORT_SOURCE_MODULES = {"fastapi", "fastapi.exceptions", "starlette.exceptions"}` AND whose `.names` contains an alias with `name == "HTTPException"`.
   - `from fastapi import HTTPException` → **flagged**.
   - `from fastapi import HTTPException as Foo` → **flagged** (the alias's `.name` is `"HTTPException"`; the asname doesn't matter — renaming doesn't make the import safe).
   - `from fastapi.exceptions import HTTPException` → **flagged** (module=`"fastapi.exceptions"`).
   - `from starlette.exceptions import HTTPException` → **flagged** (Starlette is FastAPI's base; same class).
   - `from fastapi import APIRouter, HTTPException, Depends` → **flagged** (a single ImportFrom with multiple names; the HTTPException alias is sufficient to flag the whole node).
   - `import fastapi` → NOT flagged (module-level import is fine; the `raise` rule catches any actual usage via `fastapi.HTTPException(...)`).
   - `from fastapi.exceptions import RequestValidationError` → NOT flagged (`names[0].name == "RequestValidationError"`, not `"HTTPException"`). This is exactly what `src/comadre/main.py:13` already does; the scan must ignore it.
   - `from fastapi import HTTPException  # noqa: F401` (unused import for type annotations) → **still flagged** (the import of the class name into the module namespace is the risk surface; whether it's used is irrelevant). A legitimate type-only import would need `# scan-allow: <reason>`.

**Terminal-identifier extraction for the raise rule** — inspect the raised expression:

- `ast.Name(id="HTTPException")` → `"HTTPException"` (bare re-raise form).
- `ast.Call(func=ast.Name(id="HTTPException"), ...)` → `"HTTPException"` (canonical form).
- `ast.Call(func=ast.Attribute(value=..., attr="HTTPException"), ...)` → `"HTTPException"` (attribute chain; walk only the rightmost attribute, per 4.5c's `_terminal_identifier` convention).
- Anything else (Attribute without Call, Subscript, BinOp) → not flagged.

**Allowlist comment:** reuses the `tokenize`-based helper from 4.5c verbatim. 4.5f imports the shape (re-implements it in-file per the 4.5c precedent — each scan is self-contained; no shared helper module). A `# scan-allow: <reason>` comment on any physical line the `Raise` or `ImportFrom` node spans suppresses the violation. Multi-line `raise` statements (rare in practice) and multi-line import lists (e.g., `from fastapi import (\n    APIRouter,\n    HTTPException,\n)`) correctly suppress when the comment sits on any of the spanned lines.

**Scope of the scan:** `src/comadre/**/*.py`, resolved via `Path("src/comadre").rglob("*.py")`. Test files (`tests/**/*.py`) are out of scope — test modules may legitimately `raise HTTPException` in assertion-setup fixtures or via FastAPI's TestClient internals, and the 4.5c precedent explicitly excludes `tests/` from static scans. Production code under `src/comadre/` is the risk surface.

**Skeleton:**

```python
"""FR51 non-regression — no raw ``HTTPException`` static check (Story 4.5f).

Walks every ``.py`` file under ``src/comadre/`` and asserts:

1. No ``raise HTTPException(...)`` statement (``ast.Raise`` whose ``.exc`` is a
   ``Call`` or ``Name`` whose terminal name is ``"HTTPException"``).
2. No ``from fastapi import HTTPException`` / ``from fastapi.exceptions import
   HTTPException`` / ``from starlette.exceptions import HTTPException``
   statement (``ast.ImportFrom`` whose ``.module`` is in
   ``_IMPORT_SOURCE_MODULES`` and whose ``.names`` contains an alias named
   ``"HTTPException"``).

Inline ``# scan-allow: <reason>`` on any physical line the ``Raise`` or
``ImportFrom`` node spans suppresses the scan for that node; the comment is
reviewer-enforced at PR time. Reason text is free-form — an empty or
one-word reason is a review-blocker in practice.

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
import io
import tokenize
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pytest

_PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
_SRC_ROOT: Path = _PROJECT_ROOT / "src" / "comadre"
_FIXTURES_ROOT: Path = (
    Path(__file__).resolve().parent / "fixtures" / "no_raw_httpexception"
)

_HTTPEXCEPTION_NAME: str = "HTTPException"
_IMPORT_SOURCE_MODULES: frozenset[str] = frozenset(
    {"fastapi", "fastapi.exceptions", "starlette.exceptions"}
)
_ALLOWLIST_TOKEN: str = "# scan-allow:"


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


def _allowlisted_lines(source: str) -> set[int]:
    """Return line numbers carrying a real ``# scan-allow:`` comment.

    Uses ``tokenize`` so the allowlist fires only on genuine ``COMMENT`` tokens
    and never on occurrences of the literal string inside a string or
    docstring (the same short-circuit 4.5c's scan depends on). See the 4.5c
    module-docstring rationale for why raw-substring matching on ``source``
    lines is unsafe.
    """
    allowlisted: set[int] = set()
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    for tok in tokens:
        if tok.type == tokenize.COMMENT and _ALLOWLIST_TOKEN in tok.string:
            allowlisted.add(tok.start[0])
    return allowlisted


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

    Respects ``# scan-allow:`` comments spanning the violating node's lines.
    Returns a list of ``_Violation`` (empty on success).
    """
    source = path.read_text(encoding="utf-8")
    source_lines = source.splitlines()
    tree = ast.parse(source, filename=str(path))
    allowlisted = _allowlisted_lines(source)
    violations: list[_Violation] = []

    for node in ast.walk(tree):
        kind: Literal["raise", "import"] | None
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
        line = (
            source_lines[line_index] if 0 <= line_index < len(source_lines) else ""
        )
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
        "    # scan-allow: <why this is safe, reviewed by <initials>>\n\n"
        "Violations:\n  " + "\n  ".join(v.render() for v in all_violations)
    )
```

### 2. Fixture files and self-tests

**New subdirectory: `tests/test_non_regression/fixtures/no_raw_httpexception/`** (sibling to `timing_safe_compare/` established by 4.5c). Four files — one per scan property the self-tests pin:

#### `bad_raise.py` — the scan MUST flag (kind="raise")

```python
"""Fixture — intentional FR51 violation (raw ``raise HTTPException``).

This file is a test fixture consumed by
``test_no_raw_httpexception.py::test_scan_flags_bad_raise``. It is NOT
imported at runtime and is NOT part of the production codebase. A raw
``raise HTTPException(...)`` is the exact regression pattern the scan must
catch — it bypasses the project's ComadreError hierarchy and breaks the
{error: {message, type, hint}} envelope contract (FR51).
"""

from __future__ import annotations

from fastapi import HTTPException


def forbid() -> None:
    # This line is intentionally unsafe — the scan MUST flag it.
    raise HTTPException(status_code=403, detail="forbidden")
```

**Expected violations:** exactly two — one `kind="import"` on the `from fastapi import HTTPException` line, one `kind="raise"` on the `raise HTTPException(...)` line. The self-test asserts both.

#### `bad_import.py` — the scan MUST flag (kind="import")

```python
"""Fixture — intentional FR51 violation (bare ``HTTPException`` import).

Consumed by ``test_scan_flags_bad_import``. Imports ``HTTPException``
without using it — the import ALONE is a risk surface (a subsequent diff
could add ``raise HTTPException(...)`` referencing this name, and the
reviewer might miss it if the name is already in scope). The scan flags
the import even when the class is unused in this module.
"""

from __future__ import annotations

from fastapi.exceptions import HTTPException  # noqa: F401


def noop() -> None:
    pass
```

**Expected violation:** exactly one — `kind="import"` on the `from fastapi.exceptions import HTTPException` line. The trailing `# noqa: F401` silences ruff's unused-import check but does NOT silence 4.5f's scan (different token, different line-comment semantics). Self-test asserts `len(violations) == 1` and `kind == "import"`.

#### `allowlisted_raise.py` — the scan MUST NOT flag

```python
"""Fixture — intentional FR51 violation SUPPRESSED by the allowlist comment.

Consumed by ``test_scan_respects_allowlist_on_both_kinds``. Exercises the
escape hatch: a same-line ``# scan-allow: <reason>`` comment takes a true
violation out of the scan's output. Applies to both ``raise`` and ``import``
forms; this fixture covers both in one file so a single self-test pins the
full allowlist contract.
"""

from __future__ import annotations

from fastapi import HTTPException  # scan-allow: fixture-intentional-for-4.5f


def forbid() -> None:
    raise HTTPException(status_code=403)  # scan-allow: fixture-intentional-for-4.5f
```

**Expected violation count on this file: 0.** Both the import and the raise carry valid allowlist comments. Self-test asserts `violations == []`.

#### `comadre_error_only.py` — the scan MUST NOT flag

```python
"""Fixture — the canonical safe pattern.

Consumed by ``test_scan_ignores_comadre_error_raises``. A docstring
mentioning "HTTPException" by name (``ast.Constant`` string literal) is
structurally outside both scan rules, and ``raise VoiceNotFoundError(...)``
is a raise of a different class (``_terminal_function_name`` returns
``"VoiceNotFoundError"``, which is not ``"HTTPException"``). This fixture
pins both properties in one file: the scan walks Raise and ImportFrom
nodes only; docstrings are Constants; ComadreError subclass raises are not
HTTPException raises.
"""

from __future__ import annotations


class VoiceNotFoundError(Exception):
    """Local stub — production path uses ``src/comadre/exceptions.py``.

    The production ``VoiceNotFoundError`` subclasses ``ComadreError`` and
    sets ``status_code=404``. This fixture subclasses ``Exception`` only to
    keep the file self-contained (it is not imported at runtime). The scan
    does not care about the MRO — it inspects the raised expression's
    terminal name, which is ``"VoiceNotFoundError"`` either way.

    Also note: this docstring mentions ``HTTPException`` and ``from fastapi
    import HTTPException`` as literal strings. The scan must NOT flag them —
    they are ``ast.Constant`` nodes, not ``ast.ImportFrom`` or ``ast.Raise``.
    """


def resolve(voice: str) -> None:
    raise VoiceNotFoundError(f"Voice not found: {voice}")
```

**Expected violation count on this file: 0.** The docstring mentions are string literals; the raise is of a different class. Self-test asserts `violations == []`.

**Self-test block inside `test_no_raw_httpexception.py`:**

```python
@pytest.mark.non_regression
def test_scan_flags_bad_raise() -> None:
    """Self-test: raw ``raise HTTPException(...)`` (plus its import) is flagged."""
    violations = _find_raw_httpexception_usages(_FIXTURES_ROOT / "bad_raise.py")
    kinds = sorted(v.kind for v in violations)
    assert kinds == ["import", "raise"], (
        f"Expected exactly one 'import' and one 'raise' violation in "
        f"bad_raise.py; got kinds={kinds}: "
        f"{[v.render() for v in violations]}"
    )
    raise_violations = [v for v in violations if v.kind == "raise"]
    assert "raise HTTPException" in raise_violations[0].source, (
        f"Expected the 'raise' violation's source line to include "
        f"'raise HTTPException'; got {raise_violations[0].source!r}"
    )


@pytest.mark.non_regression
def test_scan_flags_bad_import() -> None:
    """Self-test: ``from fastapi.exceptions import HTTPException`` is flagged
    even when the class is unused (``# noqa: F401`` silences ruff only).
    """
    violations = _find_raw_httpexception_usages(_FIXTURES_ROOT / "bad_import.py")
    assert len(violations) == 1, (
        f"Expected exactly one violation in bad_import.py, got "
        f"{len(violations)}: {[v.render() for v in violations]}"
    )
    violation = violations[0]
    assert violation.kind == "import", (
        f"Expected kind='import', got kind={violation.kind!r}"
    )
    assert "HTTPException" in violation.source
    assert "# noqa: F401" in violation.source, (
        f"Fixture should carry '# noqa: F401' on the import line so the "
        f"self-test also demonstrates that ruff's noqa token does NOT "
        f"suppress 4.5f's scan; got source={violation.source!r}"
    )


@pytest.mark.non_regression
def test_scan_respects_allowlist_on_both_kinds() -> None:
    """Self-test: ``# scan-allow: <reason>`` on the same source line
    suppresses BOTH a ``raise HTTPException`` and a
    ``from fastapi import HTTPException`` violation.
    """
    violations = _find_raw_httpexception_usages(
        _FIXTURES_ROOT / "allowlisted_raise.py"
    )
    assert violations == [], (
        f"Expected zero violations in allowlisted_raise.py (both the "
        f"import and the raise carry inline # scan-allow: comments); got "
        f"{[v.render() for v in violations]}"
    )


@pytest.mark.non_regression
def test_scan_ignores_comadre_error_raises() -> None:
    """Self-test: ``raise VoiceNotFoundError(...)`` is NOT an HTTPException
    raise, and docstring mentions of ``HTTPException`` / ``from fastapi
    import HTTPException`` as string literals are structurally outside the
    scan's AST rules.
    """
    violations = _find_raw_httpexception_usages(
        _FIXTURES_ROOT / "comadre_error_only.py"
    )
    assert violations == [], (
        f"Expected zero violations in comadre_error_only.py (the raise "
        f"is of VoiceNotFoundError, not HTTPException; the docstring "
        f"mentions are Constant nodes, not ImportFrom/Raise); got "
        f"{[v.render() for v in violations]}"
    )
```

**Why four self-tests instead of parametrising one:** each self-test pins a different scan property — (a) flag the raise + auto-flag the import that enables it; (b) flag a bare import even with `# noqa: F401`; (c) respect the allowlist on both kinds; (d) ignore legitimate raises and docstring mentions. A parametrised form would collapse four distinct assertions into one rubric; splitting them makes the failure message name exactly which property regressed. Matches the 4.5c precedent exactly (three fixtures → three self-tests there; four fixtures → four self-tests here).

**Why `bad_raise.py` contains BOTH an import AND a raise (yielding two violations):** simulating the most common real-world regression — a contributor adds an import, then adds a raise. The self-test pins that both are flagged (sorted `kinds == ["import", "raise"]`). Separating them into two fixtures (one import-only, one raise-only) would lose the natural-pairing signal; the `bad_import.py` fixture exists separately to cover the bare-import case specifically.

**Why `bad_import.py` carries `# noqa: F401`:** ruff will otherwise fail pre-commit on the unused import, breaking the fixture's ability to land as committed. The `# noqa: F401` is ruff-specific (F401 = unused-import); 4.5f's allowlist token is `# scan-allow:` (different token, different semantics). The self-test asserts BOTH the violation fires AND the `# noqa: F401` is present in the source line — documenting to future readers that ruff's escape-hatch does NOT suppress 4.5f's scan.

**Why `allowlisted_raise.py` covers BOTH forms in one file:** fewer files to maintain, and the test asserts the single critical invariant (`violations == []` regardless of how many lines would otherwise violate). A per-form fixture (e.g., `allowlisted_import.py` + `allowlisted_raise.py` as two separate files) would produce two self-tests that test the same escape-hatch logic; the 4.5c "one assertion per failure mode" convention admits either shape, but the consolidated shape is strictly simpler here.

**Why line-number pinning is NOT asserted:** ruff-format autoformatting can shift fixture line numbers by ±1 when docstrings reflow. The `kind`, `source`-substring, and count assertions are stable properties of the fixture's intent. This mirrors 4.5c's identical choice.

### 3. README housekeeping

**Edit `tests/test_non_regression/README.md:22`** — the ownership-table row for `test_no_raw_httpexception.py`. Replace:

```
| `test_no_raw_httpexception.py` | 4.5f    | Static check: no raw `HTTPException` outside permitted list |
```

with:

```
| `test_no_raw_httpexception.py` | 4.5f    | FR51 — static AST scan forbids ``raise HTTPException(...)`` AND ``from {fastapi, fastapi.exceptions, starlette.exceptions} import HTTPException`` in ``src/comadre/``, with ``# scan-allow: <reason>`` line-comment allowlist (same contract as 4.5c). Remediation hint names the ``ComadreError`` hierarchy at ``src/comadre/exceptions.py``. |
```

No other README edit. The "Scan allowlist convention" section (`tests/test_non_regression/README.md:193-206`) already names 4.5f as a shared participant in the `# scan-allow:` contract — no update needed there. The Harness-choice section (`tests/test_non_regression/README.md:178-191`) already names 4.5f as a static-scan sub-story — no update needed.

### 4. Housekeeping: no CI YAML change, no `src/comadre/` change

The existing `non-regression` job in `.github/workflows/ci.yml` runs `uv run pytest -m non_regression tests/test_non_regression/ -v` — it auto-discovers the new module. The new fixture files under `tests/test_non_regression/fixtures/no_raw_httpexception/` are NOT test modules (no `test_` prefix); pytest's collection rules naturally skip them. Grep invariants (all enforced as ACs):

- `git diff master -- src/comadre/ | wc -l` is `0`.
- `git diff master -- deploy/caddy/ | wc -l` is `0`.
- `git diff master -- .github/workflows/ci.yml | wc -l` is `0`.
- `git diff master -- pyproject.toml uv.lock | wc -l` is `0`.
- `git diff master -- tests/conftest.py | wc -l` is `0`.
- `git diff master -- tests/test_non_regression/conftest.py | wc -l` is `0`.

## Acceptance Criteria

1. **AC1 — `_find_raw_httpexception_usages` helper exists and is AST-based.** `tests/test_non_regression/test_no_raw_httpexception.py` defines `_find_raw_httpexception_usages(path: Path) -> list[_Violation]` that (a) calls `ast.parse(path.read_text(encoding="utf-8"))`, (b) walks the tree via `ast.walk`, (c) delegates rule evaluation to `_is_raw_httpexception_raise(node)` and `_is_httpexception_import(node)`, (d) uses `_allowlisted_lines(source)` (tokenize-based) to suppress violations on any line a `# scan-allow:` comment spans (multi-line nodes via `range(node.lineno, (node.end_lineno or node.lineno) + 1)`), (e) returns a `list[_Violation]` with `path`, `lineno`, `kind: Literal["raise", "import"]`, `source` fields.

2. **AC2 — Primary assertion: zero violations in `src/comadre/`.** `test_src_comadre_has_no_raw_httpexception` collects every `.py` file under `src/comadre/` via `sorted(_SRC_ROOT.rglob("*.py"))` and runs `_find_raw_httpexception_usages` on each. The test passes iff the combined violation list is empty. Failure message enumerates violations as `<relpath>:<lineno>: raw HTTPException <kind> — <source>` and names (a) the `ComadreError` hierarchy at `src/comadre/exceptions.py`, (b) the mapping of common status codes to subclass names, (c) the `# scan-allow: <reason>` escape hatch.

3. **AC3 — Self-test: bad-raise fixture is flagged with BOTH kinds.** `test_scan_flags_bad_raise` asserts `_find_raw_httpexception_usages(fixtures/no_raw_httpexception/bad_raise.py)` returns exactly two violations with `sorted(kinds) == ["import", "raise"]`. The `raise`-kind violation's `source` contains `"raise HTTPException"`. Line numbers are NOT pinned (brittle to autoformat reflow).

4. **AC4 — Self-test: bare import is flagged even with `# noqa: F401`.** `test_scan_flags_bad_import` asserts `_find_raw_httpexception_usages(fixtures/no_raw_httpexception/bad_import.py)` returns exactly one violation with `kind == "import"`, `"HTTPException"` in `source`, AND `"# noqa: F401"` in `source` (to document that ruff's token does not suppress 4.5f's scan).

5. **AC5 — Self-test: allowlist comment suppresses BOTH kinds.** `test_scan_respects_allowlist_on_both_kinds` asserts `_find_raw_httpexception_usages(fixtures/no_raw_httpexception/allowlisted_raise.py)` returns an empty list. The fixture contains both a `from fastapi import HTTPException` line AND a `raise HTTPException(...)` line, each ending with `# scan-allow: fixture-intentional-for-4.5f`.

6. **AC6 — Self-test: `ComadreError`-subclass raises and docstring mentions are structurally ignored.** `test_scan_ignores_comadre_error_raises` asserts `_find_raw_httpexception_usages(fixtures/no_raw_httpexception/comadre_error_only.py)` returns an empty list. The fixture's docstring mentions both `HTTPException` and `from fastapi import HTTPException` as string literals; the only `raise` statement uses a non-`HTTPException` class name.

7. **AC7 — Import rule covers all three canonical source modules.** `_IMPORT_SOURCE_MODULES` equals `frozenset({"fastapi", "fastapi.exceptions", "starlette.exceptions"})`. A module-level comment above the constant explains why all three are included (the same `HTTPException` class is re-exported by FastAPI from Starlette; a direct import from any of the three paths is equivalent for regression purposes).

8. **AC8 — Raise rule covers bare-Name, Call-on-Name, and Call-on-Attribute forms.** `_terminal_function_name` (helper) returns `"HTTPException"` for: `ast.Name(id="HTTPException")` (bare re-raise), `ast.Call(func=ast.Name(id="HTTPException"))` (canonical form), and `ast.Call(func=ast.Attribute(attr="HTTPException"))` (attribute-access form like `fastapi.HTTPException(...)`). Returns `None` for anything else. At least one inline comment in the helper documents the three forms.

9. **AC9 — `non_regression` marker applied to every test.** All five tests in `test_no_raw_httpexception.py` (one primary + four self-tests) carry `@pytest.mark.non_regression`. Grep invariant: `rg "@pytest.mark.non_regression" tests/test_non_regression/test_no_raw_httpexception.py | wc -l` returns `5`. The AC15 grep invariant from 4.5a (no `@pytest.mark.non_regression` outside `tests/test_non_regression/`) continues to hold.

10. **AC10 — No `src/comadre/` changes.** `git diff master -- src/comadre/ | wc -l` is `0` at story completion.

11. **AC11 — CI YAML untouched.** `git diff master -- .github/workflows/ci.yml | wc -l` is `0`. The existing `non-regression` job auto-discovers the new test file.

12. **AC12 — No new runtime or dev dependency.** `git diff master -- pyproject.toml uv.lock | wc -l` is `0`. Scan is pure stdlib (`ast`, `tokenize`, `io`, `pathlib`, `dataclasses`, `typing.Literal`).

13. **AC13 — `tests/conftest.py` marker registration unchanged.** `git diff master -- tests/conftest.py | wc -l` is `0`. The broadened marker description landed in 4.5b is already sufficient.

14. **AC14 — `tests/test_non_regression/conftest.py` unchanged.** `git diff master -- tests/test_non_regression/conftest.py | wc -l` is `0`. 4.5f is a static scan; no docker or ASGI fixtures are consumed.

15. **AC15 — Default `pytest` run excludes the new module.** `uv run pytest` (no `-m` flag) does NOT execute the new tests — they are deselected via the existing `addopts = "-m 'not non_regression'"`. The default run's `deselected` count grows by exactly 5 vs the pre-4.5f baseline (5 new tests, all unparametrised).

16. **AC16 — Opt-in CI invocation picks up the new module.** `uv run pytest -m non_regression tests/test_non_regression/ -v` collects and runs the five new tests alongside the existing 4.5a/b/c/d/e surface; the new module contributes +5 passed (no skips — stdlib AST parsing has no docker/network preconditions). Exact post-4.5f totals captured in the Dev Agent Record; the invariant is *"the opt-in run's post-4.5f `passed` count equals the pre-4.5f `passed` count + 5."*

17. **AC17 — Fixture-directory convention honoured.** Fixtures live under `tests/test_non_regression/fixtures/no_raw_httpexception/`, sibling to `fixtures/timing_safe_compare/` from 4.5c. No files under `tests/test_non_regression/fixtures/` are at the flat level (every fixture is inside a per-scan-story subdirectory). The fixtures have no `test_` prefix and no `Test*` class, so pytest's default collection rules skip them (verified: `uv run pytest -m non_regression tests/test_non_regression/ --collect-only` reports zero items from `fixtures/`).

18. **AC18 — README ownership row refined.** `tests/test_non_regression/README.md:22` carries the verbose FR51 description per §Scope-3 (names both rule shapes — `raise` and `import` — both allowlist contract source modules, and the `ComadreError`-hierarchy remediation hint). The `Scan allowlist convention` section (lines 193-206) is NOT modified (already names 4.5f correctly). The `Harness choice` section (lines 178-191) is NOT modified.

19. **AC19 — Failure-UX verified with probe class A (bad raise).** Temporarily insert a minimal flaggable statement at the top of a sacrificial file under `src/comadre/` — recommended: at the bottom of `src/comadre/config.py`, inside a no-op `if False:` block:
    ```python
    if False:  # scratch for 4.5f failure-UX probe
        from fastapi import HTTPException
        raise HTTPException(status_code=403)
    ```
    Run `uv run pytest -m non_regression tests/test_non_regression/test_no_raw_httpexception.py::test_src_comadre_has_no_raw_httpexception -v`. Observe TWO violations named in the failure message: `src/comadre/config.py:<N>: raw HTTPException import — ...` and `src/comadre/config.py:<N+1>: raw HTTPException raise — ...`. Observe the remediation hint names `ComadreError`, `src/comadre/exceptions.py`, the status-code-to-subclass table, AND the `# scan-allow: <reason>` escape hatch. Restore via `git checkout -- src/comadre/config.py`. Dev agent logs the observed failure message verbatim in the Dev Agent Record > Debug Log References.

20. **AC20 — Failure-UX verified with probe class B (allowlist ON the probe).** Re-apply the AC19 probe but append `# scan-allow: probe-for-4.5f-AC20` to BOTH the import line and the raise line. Re-run the same test. Observe zero violations (scan runs clean). Restore via `git checkout`. Logs the observed success verbatim in the Dev Agent Record. This probe pins the end-to-end allowlist contract on real source (not just on fixture files).

21. **AC21 — Full quality-gate suite stays green.** `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src/`, `uv run pytest` (default), `uv run pytest -m non_regression tests/test_non_regression/ -v`, and `uv run pre-commit run --all-files` all exit 0.

## Tasks / Subtasks

- [x] **Task 1 — Scaffold fixtures directory and four fixture files** (AC3, AC4, AC5, AC6, AC17)
  - [x] 1.1 Create `tests/test_non_regression/fixtures/no_raw_httpexception/` (no `__init__.py` — fixtures are source samples, not a Python package; mirrors 4.5c's `timing_safe_compare/` convention).
  - [x] 1.2 Create `bad_raise.py` per §Scope-2. `from fastapi import HTTPException` + `def forbid(): raise HTTPException(status_code=403, detail="forbidden")`. Docstring explicitly flags the file as a fixture (not production code) and names the FR51 regression class it exhibits.
  - [x] 1.3 Create `bad_import.py` per §Scope-2. `from fastapi.exceptions import HTTPException  # noqa: F401` + `def noop(): pass`. The `# noqa: F401` silences ruff's unused-import hook so the fixture passes pre-commit without needing a per-file exclusion.
  - [x] 1.4 Create `allowlisted_raise.py` per §Scope-2. Both import and raise lines end with `# scan-allow: fixture-intentional-for-4.5f`. Verify ruff does NOT auto-strip the trailing comment (it shouldn't — ruff preserves comments).
  - [x] 1.5 Create `comadre_error_only.py` per §Scope-2. Local-stub `VoiceNotFoundError` subclass, `resolve()` function raising it, docstring explicitly mentioning the string `"HTTPException"` and `"from fastapi import HTTPException"` as literal content.
  - [x] 1.6 Verify fixtures lint clean: `uv run ruff check tests/test_non_regression/fixtures/no_raw_httpexception/` exits 0. If any fixture requires a per-file ignore (unexpected — the `# noqa: F401` in `bad_import.py` should be sufficient), DO NOT add to `pyproject.toml` (AC12 invariant); add a trailing `# noqa: <rule>` on the offending line instead.

- [x] **Task 2 — Implement the scan helper and the primary regression assertion** (AC1, AC2, AC7, AC8)
  - [x] 2.1 Create `tests/test_non_regression/test_no_raw_httpexception.py` per §Scope-1. Module docstring naming both rules, the tokenize-based allowlist, the `ComadreError` remediation surface, and the AST-structural reason docstring mentions are ignored.
  - [x] 2.2 Define the constants: `_PROJECT_ROOT`, `_SRC_ROOT`, `_FIXTURES_ROOT`, `_HTTPEXCEPTION_NAME = "HTTPException"`, `_IMPORT_SOURCE_MODULES = frozenset({"fastapi", "fastapi.exceptions", "starlette.exceptions"})`, `_ALLOWLIST_TOKEN = "# scan-allow:"`. AC7 comment block documenting the three source modules.
  - [x] 2.3 Define the `_Violation` dataclass with `kind: Literal["raise", "import"]` (AC1) and a `render()` method emitting `<relpath>:<lineno>: raw HTTPException <kind> — <source>`.
  - [x] 2.4 Define `_terminal_function_name(node)` covering bare-Name, Call-on-Name, Call-on-Attribute (AC8) with inline-comment documentation.
  - [x] 2.5 Define `_allowlisted_lines(source)` using `tokenize.generate_tokens(io.StringIO(source).readline)` — copy the shape from `tests/test_non_regression/test_timing_safe_compare.py:78-97` (4.5c's helper).
  - [x] 2.6 Define `_is_raw_httpexception_raise(node)` and `_is_httpexception_import(node)` predicates per §Scope-1.
  - [x] 2.7 Define `_find_raw_httpexception_usages(path)` walking the AST with both predicates, applying allowlist suppression via the line-range sweep (`range(node.lineno, (node.end_lineno or node.lineno) + 1)`).
  - [x] 2.8 Define `test_src_comadre_has_no_raw_httpexception` per §Scope-1. Failure message contains all three of: (a) `ComadreError` and `src/comadre/exceptions.py`, (b) status-code-to-subclass table, (c) `# scan-allow: <reason>` escape hatch.
  - [x] 2.9 Run `uv run pytest tests/test_non_regression/test_no_raw_httpexception.py::test_src_comadre_has_no_raw_httpexception -m non_regression -v` — passes with zero violations (empirically verified at story-draft time via `rg "raise HTTPException|from (fastapi|fastapi.exceptions|starlette.exceptions) import HTTPException" src/comadre/` returning zero hits).

- [x] **Task 3 — Add the four self-tests** (AC3, AC4, AC5, AC6, AC9)
  - [x] 3.1 Append `test_scan_flags_bad_raise` per §Scope-2. Asserts two violations, `sorted(kinds) == ["import", "raise"]`, raise-source contains `"raise HTTPException"`.
  - [x] 3.2 Append `test_scan_flags_bad_import` per §Scope-2. Asserts one violation, `kind == "import"`, source contains both `"HTTPException"` AND `"# noqa: F401"`.
  - [x] 3.3 Append `test_scan_respects_allowlist_on_both_kinds` per §Scope-2. Asserts `violations == []`.
  - [x] 3.4 Append `test_scan_ignores_comadre_error_raises` per §Scope-2. Asserts `violations == []`.
  - [x] 3.5 Verify every test carries `@pytest.mark.non_regression`: `grep -c "@pytest.mark.non_regression" tests/test_non_regression/test_no_raw_httpexception.py` returns `5` (one primary + four self-tests).

- [x] **Task 4 — Verify marker + deselection behaviour** (AC15, AC16)
  - [x] 4.1 `uv run pytest` (default) — captures the pre-4.5f `passed` + `deselected` baseline from a fresh `git checkout` of master BEFORE applying Task 1-3 changes. Expected post-4.5f: `+5 deselected`.
  - [x] 4.2 `uv run pytest -m non_regression tests/test_non_regression/ -v` — captures the pre-4.5f `passed` + `skipped` baseline. Expected post-4.5f: `+5 passed` (no skips — stdlib AST has no docker preconditions).
  - [x] 4.3 Record the exact pre- and post-4.5f counts in the Dev Agent Record > Completion Notes for future-story reference (4.5g will cite these). The expected delta is `+5` on both the opt-in run's `passed` and the default run's `deselected`.

- [x] **Task 5 — Verify fixtures are not collected as tests** (AC17)
  - [x] 5.1 Run `uv run pytest -m non_regression tests/test_non_regression/ -v --collect-only 2>&1 | rg "fixtures/no_raw_httpexception"` — returns empty (fixture files have no `test_` prefix; pytest's default collection skips them).
  - [x] 5.2 Run `uv run pytest -m non_regression tests/test_non_regression/fixtures/no_raw_httpexception/ -v` — reports "collected 0 items" / "no tests ran."

- [x] **Task 6 — Update README** (AC18)
  - [x] 6.1 Edit `tests/test_non_regression/README.md:22` — replace the placeholder ownership-row description with the verbose FR51 description per §Scope-3.
  - [x] 6.2 Verify the `Scan allowlist convention` section (lines 193-206) is NOT modified — it already names 4.5f correctly. Same for the `Harness choice` section (lines 178-191).
  - [x] 6.3 Markdown lint covered by Task 8's `pre-commit run --all-files` hook (markdownlint-cli2).

- [x] **Task 7 — Verify invariants** (AC10, AC11, AC12, AC13, AC14)
  - [x] 7.1 `git diff master -- src/comadre/ | wc -l` → `0` (AC10).
  - [x] 7.2 `git diff master -- .github/workflows/ci.yml | wc -l` → `0` (AC11).
  - [x] 7.3 `git diff master -- pyproject.toml uv.lock | wc -l` → `0` (AC12).
  - [x] 7.4 `git diff master -- tests/conftest.py | wc -l` → `0` (AC13).
  - [x] 7.5 `git diff master -- tests/test_non_regression/conftest.py | wc -l` → `0` (AC14).
  - [x] 7.6 Bonus invariant: `rg "HTTPException" src/comadre/ | wc -l` → exactly `2` (the two docstring mentions in `main.py`); no regression introduced by the story.

- [x] **Task 8 — Run full quality-gate suite** (AC21)
  - [x] 8.1 `uv run ruff check .` — exits 0.
  - [x] 8.2 `uv run ruff format --check .` — exits 0.
  - [x] 8.3 `uv run mypy src/` — exits 0; `Success: no issues found in N source files` (note: 4.5f touches NO `src/` files, so N is unchanged).
  - [x] 8.4 `uv run pytest` (default) — exits 0; `deselected` count up by `+5` vs pre-4.5f baseline.
  - [x] 8.5 `uv run pytest -m non_regression tests/test_non_regression/ -v` — exits 0; `passed` count up by `+5` vs pre-4.5f baseline.
  - [x] 8.6 `uv run pre-commit run --all-files` — all hooks `Passed` (ruff check, ruff format, hadolint, yamllint, shellcheck, markdownlint-cli2, mypy).

- [x] **Task 9 — Failure-UX probe A: bad raise + bad import** (AC19)
  - [x] 9.1 Backup `src/comadre/config.py` (`cp src/comadre/config.py src/comadre/config.py.bak`).
  - [x] 9.2 Append a no-op `if False:` block to the bottom of `src/comadre/config.py` containing `from fastapi import HTTPException` on one line and `raise HTTPException(status_code=403)` on the next. Use `if False:` so the block is dead-code-eliminable and leaves no runtime surface (the AST scan does NOT care about runtime reachability — it walks every node).
  - [x] 9.3 Run `uv run pytest -m non_regression tests/test_non_regression/test_no_raw_httpexception.py::test_src_comadre_has_no_raw_httpexception -v`. Observe TWO violations named verbatim in the failure message (`src/comadre/config.py:<N>: raw HTTPException import — ...` and `src/comadre/config.py:<N+1>: raw HTTPException raise — ...`). Capture the failure message verbatim in the Dev Agent Record > Debug Log References.
  - [x] 9.4 Verify the failure message contains all three required remediation-hint elements (AC19): `ComadreError` + `src/comadre/exceptions.py`, the status-code-to-subclass mini-table, AND `# scan-allow: <reason>`.
  - [x] 9.5 Restore `src/comadre/config.py` via `mv src/comadre/config.py.bak src/comadre/config.py`. Re-run the scan; confirm it passes. Verify `git diff master -- src/comadre/config.py | wc -l` → `0`.

- [x] **Task 10 — Failure-UX probe B: allowlist suppresses a real-source violation** (AC20)
  - [x] 10.1 Re-apply the Task 9 probe but append `  # scan-allow: probe-for-4.5f-AC20` to BOTH the import line and the raise line.
  - [x] 10.2 Re-run the same test. Observe the scan passes with zero violations reported. Capture the success verbatim (`PASSED` line + elapsed time).
  - [x] 10.3 Restore `src/comadre/config.py`. Re-run; confirm it still passes. `git diff master -- src/comadre/config.py | wc -l` → `0`.

- [x] **Task 11 — Change log and status**
  - [x] 11.1 Append a Change Log row to this story file (version `0.2 — dev-story execution`) with date, summary of the scan delivered, and the pre/post-4.5f quality-gate numbers from Task 4.
  - [x] 11.2 Flip story Status ready-for-dev → in-progress (on starting implementation) → review (on completing Tasks 1-10); update `_bmad-output/implementation-artifacts/sprint-status.yaml` entry `4-5f-ci-no-raw-httpexception` to mirror both transitions and bump `last_updated`.

## Dev Notes

### Design decisions

**Why AST over ripgrep.** The epic AC admits either ("ripgrep-backed or AST-based"). AST wins on four axes (expanding on 4.5c's three): (a) zero false-positives from `raise` or `from fastapi import` patterns inside docstrings / comments / string literals — the two existing docstring mentions at `src/comadre/main.py:250,276` would trip a naive regex; (b) robust to multi-line imports (`from fastapi import (\n    APIRouter,\n    HTTPException,\n)`) that regex would need lookahead for; (c) operand-name resolution gives us exact module identity (`ImportFrom.module == "fastapi"` vs `"fastapi.exceptions"` vs something else) without parsing the captured substring; (d) the `Raise.exc` node walk correctly handles both `raise HTTPException(...)` (Call-on-Name), `raise fastapi.HTTPException(...)` (Call-on-Attribute), and the bare `raise HTTPException` (Name-only, no Call) in one predicate. AST also validates the file is syntactically valid Python — a syntax error in `src/comadre/` surfaces with a clear `SyntaxError` before any scan runs.

**Why reuse 4.5c's `_allowlisted_lines` shape instead of sharing a helper module.** 4.5c's implementation is self-contained — it neither exports the helper nor depends on any other test module. Cloning the ~15-line function into `test_no_raw_httpexception.py` keeps each scan's coupling flat: a scan fails if and only if something in ITS own file regresses, never because a shared helper was refactored elsewhere. The cost is ~15 duplicated lines across 4.5c, 4.5f, and 4.5g; the benefit is no shared test-helper module to maintain. If a fourth static-scan sub-story ever lands, consolidating is a candidate housekeeping task, not a 4.5f concern.

**Why three import-source modules, not just `fastapi`.** FastAPI re-exports Starlette's `HTTPException` unchanged — `fastapi.HTTPException is starlette.exceptions.HTTPException` evaluates to `True` (FastAPI subclasses it and re-exports the subclass, but the subclass has identical semantics for the FR51 concern: it breaks the `{error: ...}` envelope). `from fastapi.exceptions import HTTPException` is just a more verbose import path that some linters suggest for clarity. `from starlette.exceptions import HTTPException` is what someone copying an ASGI-middleware tutorial would write. All three are equivalent risk surfaces; the scan covers all three. Any OTHER path — `from some.third_party import HTTPException` — would be a bespoke reimport that deserves its own review rather than a silent pass; the scan's current 3-module scope is the right precision/recall trade.

**Why flag imports even when the class is unused.** An unused import puts `HTTPException` in the module's namespace. A subsequent PR diff might add `raise HTTPException(...)` referencing this name; if the import is already landed, the second PR's diff has ONLY the raise line, and a reviewer scanning the diff might miss that the name is in scope from a pre-existing import. Flagging at import time catches the regression the moment the name enters the module. The `# scan-allow:` escape hatch handles the legitimate-but-rare case (e.g., a type-only import via `TYPE_CHECKING`).

**Why the bare-Name raise form matters (`raise HTTPException`).** Unusual but valid Python: re-raises the class itself, which Python then converts to `raise HTTPException()` (no args). Semantically equivalent to `raise HTTPException(status_code=500)` (or whatever the default is), and `_terminal_function_name` treats bare-Name and Call-on-Name identically. This catches a subtle regression pattern — a contributor who "cleans up" `raise HTTPException(status_code=500)` to `raise HTTPException` (thinking they're simplifying).

**Why NOT flag `raise some_http_exc_variable`.** `_terminal_function_name(Name(id="some_http_exc_variable"))` returns `"some_http_exc_variable"`, which does not equal `"HTTPException"`. The scan is name-based — it cannot statically prove the identity of a value bound to a variable. Catching this case would require type inference or a whole-program flow analysis — 10x complexity for a regression class that a PR reviewer catches with a single grep. Acceptable gap; documented as deferred work.

**Why four self-tests instead of parametrising one.** Four distinct properties — flag-raise, flag-import, respect-allowlist, ignore-safe-forms. Parametrising would collapse the four failure messages into one rubric; splitting them names exactly which property regressed at a glance. 4.5c precedent: three properties → three self-tests. Same discipline here.

**Why `bad_raise.py` fixture contains BOTH an import AND a raise (yielding two violations).** Real-world regressions typically come as a pair: import the class, then use it. Asserting that the scan surfaces BOTH matches the end-user signal the scan must produce. Separating into two fixtures (import-only + raise-only) would double the file count for the same informational content — and the `bad_import.py` fixture already covers the import-only case specifically (bare import without a raise, the subtler regression).

**Why the allowlist fixture covers BOTH forms in one file.** Simpler test, same assertion (`violations == []`). If a future contributor breaks the allowlist for the import form but not the raise form, the self-test still fires (the broken form produces violations, the test asserts empty list). No information loss.

**Why the `ComadreError`-only fixture carries a long docstring with literal mentions.** Pinning the "docstrings are structurally outside the scan" property via an explicit fixture. The current codebase happens to have this property at `main.py:250,276` — but without a fixture pinning it, a future refactor of the scan (e.g., switching from AST to regex) could silently break the property without the main assertion firing (the main assertion doesn't fail because the current codebase has no docstring-mention regressions; the property is silently maintained). The fixture makes the property mechanically enforced.

**Why `_HTTPEXCEPTION_NAME` is a constant, not a string literal inline.** Makes the scan extensible: if a future class ever matters (e.g., FastAPI introduces `HTTPXException` or similar), the name-set expands to a `frozenset[str]`. Today it's a single constant — explicit, grep-friendly, and easy to widen.

**Why no `starlette.responses` scan.** Someone could theoretically bypass the envelope by directly returning `JSONResponse(status_code=400, content={"detail": "..."})` from a route. That IS the same regression class but is OUTSIDE FR51's wording ("no new code raises a raw `HTTPException`"). A follow-up story could broaden the scan to include bare `JSONResponse(content={...})` returns without the project envelope, but it's out of scope for 4.5f. The `unhandled_error_handler` at `exceptions.py:248` catches unhandled exceptions, but cannot intercept a route that explicitly returns a non-envelope JSONResponse. Acknowledged gap; deferred.

### Import-graph placement

- **`tests/test_non_regression/test_no_raw_httpexception.py` (NEW).** Imports: stdlib (`ast`, `tokenize`, `io`, `dataclasses.dataclass`, `pathlib.Path`, `typing.Literal`), `pytest`. No `comadre.*` imports — the scan reads files by path, not by Python import.
- **`tests/test_non_regression/fixtures/no_raw_httpexception/bad_raise.py` (NEW).** Imports: `from fastapi import HTTPException`. This is a LEGITIMATE import-path contract in the fixture — the fixture intentionally regresses; the scan is expected to flag it. The fixture file MUST live under `tests/test_non_regression/fixtures/` which is OUTSIDE the `src/comadre/` scan scope, so the fixture's own `from fastapi import HTTPException` does not cause a circular-regression situation.
- **`tests/test_non_regression/fixtures/no_raw_httpexception/bad_import.py` (NEW).** Imports: `from fastapi.exceptions import HTTPException  # noqa: F401`. The `# noqa: F401` silences ruff's unused-import check (the fixture has no use site; its sole purpose is to demonstrate the scan catches bare imports).
- **`tests/test_non_regression/fixtures/no_raw_httpexception/allowlisted_raise.py` (NEW).** Imports: `from fastapi import HTTPException  # scan-allow: fixture-intentional-for-4.5f`.
- **`tests/test_non_regression/fixtures/no_raw_httpexception/comadre_error_only.py` (NEW).** No `fastapi`/`starlette` imports. Locally-defined `VoiceNotFoundError(Exception)` stub.
- **`tests/test_non_regression/README.md` (MOD).** Prose-only edit to ownership-table row (line 22).
- **`tests/conftest.py` — unchanged.** `non_regression` marker registration is already correct.
- **`tests/test_non_regression/conftest.py` — unchanged.** 4.5f does not use docker fixtures.
- **`pyproject.toml` — unchanged.** `addopts = "-m 'not non_regression'"` already deselects the new tests.
- **`.github/workflows/ci.yml` — unchanged.** The `non-regression` job auto-discovers the new module.
- **`src/comadre/**` — unchanged.** AC10 invariant.
- **`deploy/caddy/**` — unchanged.** N/A for a static scan.

### Test-flake avoidance

- **Deterministic file discovery.** `sorted(_SRC_ROOT.rglob("*.py"))` yields alphabetically-stable iteration.
- **No `tmp_path` or `tmp_path_factory`.** The scan reads fixture files by absolute path (`_FIXTURES_ROOT / "bad_raise.py"`), anchored to the test module's location via `Path(__file__).resolve().parent`.
- **No shared mutable state.** Each test invokes `_find_raw_httpexception_usages` on its own input. No module-level cache, no `lru_cache` on the scan.
- **No asyncio.** All five tests are sync `def`. No event-loop fixture needed.
- **AST + tokenize stability across Python versions.** `ast.Raise`, `ast.ImportFrom`, `ast.alias`, `ast.Name`, `ast.Call`, `ast.Attribute`, `ast.walk`, `tokenize.generate_tokens`, `tokenize.COMMENT` — all stable stdlib API since 3.0. Project targets 3.12; no compat shim.
- **`ast.parse` with the file path as `filename=`.** Any `SyntaxError` in `src/comadre/` surfaces with the real source path in its traceback rather than an opaque `<string>`.
- **Fixture files do NOT execute at collection time.** pytest's default collection walks `*.py` files looking for `test_` prefix; the fixture files don't match, so pytest never imports them. The scan reads them via `Path.read_text()`, which also doesn't execute Python code.
- **`noqa: F401` on `bad_import.py` is ruff-specific and inert to 4.5f.** 4.5f's allowlist token is `# scan-allow:`; ruff's is `# noqa:`. No collision — the two systems are orthogonal.

### Project Structure Notes

- **Alignment with unified project structure.**
  - Test module naming: `tests/test_non_regression/test_no_raw_httpexception.py` — matches the ownership table row in `tests/test_non_regression/README.md` (row 22 for 4.5f).
  - Fixture directory: `tests/test_non_regression/fixtures/no_raw_httpexception/` — sibling to `fixtures/timing_safe_compare/` from 4.5c (AC17, 4.5c's AC11). Convention: each static-scan sub-story owns one subdirectory named after its scan identifier.
  - Helper naming: `_find_raw_httpexception_usages`, `_is_raw_httpexception_raise`, `_is_httpexception_import`, `_terminal_function_name`, `_allowlisted_lines`, `_Violation` (leading-underscore module-privates, snake_case functions, PascalCase dataclass) — matches 4.5c's conventions verbatim.
  - Allowlist comment token: `# scan-allow:` — shared across 4.5c/4.5f/4.5g (reviewer-enforceable, grep-friendly via `rg "scan-allow:"`).

- **Detected conflicts or variances (with rationale).**
  - **`ast.ImportFrom` is NOT an expression node** (unlike `ast.Compare` in 4.5c), so there's no operand-pair to inspect. The rule is simpler: check `node.module` against the source-modules set and `node.names[*].name` for `"HTTPException"`. This produces a one-predicate rule vs 4.5c's two-predicate compound (operator + identifier). Acknowledged; no divergence from the 4.5c pattern beyond what the node type dictates.
  - **The `bad_raise.py` fixture intentionally yields TWO violations** (one import, one raise), unlike 4.5c's `bad_example.py` which yields ONE (the Compare node). This matches the real-world regression shape — an HTTPException raise almost always comes with an import. The self-test `test_scan_flags_bad_raise` asserts both kinds are present; any attempt to normalise the fixture to yield one violation would lose this signal.
  - **No line-number pinning on any self-test.** 4.5c's precedent. Ruff-format may shift fixture line numbers by ±1 under docstring reflow.

### Testing standards

- **Sync tests, not async.** The scan is I/O-bound but synchronous (`path.read_text()`, `ast.parse`). Using `async def` would force a `pytest-asyncio` loop for no gain.
- **Assertion messages.** Every assertion carries a failure message naming (a) which property broke, (b) the expected vs observed state, (c) a diagnostic tail. The primary assertion additionally carries remediation text naming `ComadreError`, `src/comadre/exceptions.py`, the status-code-to-subclass table, and `# scan-allow:`.
- **No fixture-level assertions.** The helper functions do NOT raise on malformed input — they return violation lists (possibly empty).
- **One assertion per failure mode.** Four self-tests, four distinct properties.

### Deferred work to flag at story close

- **Flow-aware scan: track variables bound to `HTTPException(...)`.** Currently `raise some_exc_variable` where `some_exc_variable = HTTPException(...)` is NOT flagged. Catching this requires local-flow analysis (track `Assign` → `Raise`) or type inference. Out of scope today; the `# scan-allow:` escape hatch covers known-good variable-based raises via reviewer enforcement on the `HTTPException(...)` assignment site itself (which IS a Call-node that `_terminal_function_name` would evaluate — but the scan only walks `Raise` and `ImportFrom`, so the Call alone isn't flagged; a follow-up story could add an `Assign`-walker rule).
- **Scan raw `JSONResponse(content={...})` without the project envelope.** A route could bypass the envelope by returning `JSONResponse(status_code=400, content={"detail": "..."})` directly — structurally outside FR51's wording but inside the envelope-contract's spirit. Candidate for a follow-up story (call it FR51.5).
- **Extend scan to `deploy/`, `scripts/`, or `tests/` trees.** Today 4.5f scans `src/comadre/` only. `deploy/` is ansible YAML + Jinja2 (no Python); `scripts/*.py` (`loadtest.py`, `capacity_test.py`) currently have no `HTTPException` risk surface; `tests/**/*.py` is deliberately out of scope. Broaden `_SRC_ROOT` to a list if that changes.
- **Track `# scan-allow:` entries across the codebase.** A future housekeeping scan could count allowlist comments per-file and flag files with > N — early warning for scan-policy drift. Zero such entries exist at story close. Same deferred-work note 4.5c carries.
- **Consolidate `_allowlisted_lines` across 4.5c/4.5f/4.5g.** If a fourth static-scan lands, extract into `tests/test_non_regression/_scan_utils.py` (or similar). Trade-off: reduces duplication by ~15 lines per scan; adds one test-only helper module to maintain. Today the two occupants (4.5c and 4.5f) don't justify it.
- **Broaden the import-source module set.** If a future release of FastAPI or Starlette moves `HTTPException` to a new path (unlikely; these are stable public APIs), extend `_IMPORT_SOURCE_MODULES`. Flag in the dev agent record if any drift is observed during implementation.
- **Bridge-helper pattern.** If a future architecture story introduces a legitimate `HTTPException`-bridging helper (e.g., a custom ASGI middleware that intercepts framework-emitted 422s and re-raises as `InvalidRequestError`), the helper would need a `# scan-allow: <reason>` comment on each bypass line. The convention already exists; the first use site will pin the reason vocabulary.

### References

- Epic 4 Story 4.5 umbrella — `_bmad-output/planning-artifacts/epics.md:878-888`
- Epic 4 Story 4.5f — `_bmad-output/planning-artifacts/epics.md:987-1003`
- FR51 — `_bmad-output/planning-artifacts/prd.md:100, 259, 1195`
- NFR17 — `_bmad-output/planning-artifacts/prd.md:1221`
- PRD Non-Regression Contract — "Zero `HTTPException` raises" row — `_bmad-output/planning-artifacts/prd.md:141, 666`
- Architecture §Auth-path "never raise HTTPException" — `_bmad-output/planning-artifacts/architecture.md:470`
- Architecture §Code Review Pre-Flight "grep for HTTPException" — `_bmad-output/planning-artifacts/architecture.md:484`
- CLAUDE.md codebase invariant ("All errors via ComadreError subclasses... never raw HTTPException") — project root `CLAUDE.md`
- Story 4.5a (predecessor; skeleton + marker + CI job) — `_bmad-output/implementation-artifacts/4-5a-ci-security-headers-regression.md`
- Story 4.5b (predecessor; marker broadening, Harness-choice README) — `_bmad-output/implementation-artifacts/4-5b-ci-docs-endpoints-disabled-regression.md`
- Story 4.5c (predecessor; first static-scan — THE canonical reference for 4.5f) — `_bmad-output/implementation-artifacts/4-5c-ci-timing-safe-key-comparison-static-check.md`
- Story 4.5c scan helper (source of the `_allowlisted_lines` pattern) — `tests/test_non_regression/test_timing_safe_compare.py:78-97, 100-168`
- Story 4.5d (predecessor; docker-stack — orthogonal) — `_bmad-output/implementation-artifacts/4-5d-ci-oversized-request-body-rejection.md`
- Story 4.5e (predecessor; ASGI TestClient — orthogonal) — `_bmad-output/implementation-artifacts/4-5e-ci-rate-limit-middleware-registration.md`
- `ComadreError` hierarchy (the allowlisted error surface) — `src/comadre/exceptions.py:18-266`
- `register_exception_handlers` (canonical registration site) — `src/comadre/main.py:341`
- `_not_found_handler` (status-code handler, NOT an HTTPException import) — `src/comadre/main.py:249-273`
- `_method_not_allowed_handler` (status-code handler, NOT an HTTPException import) — `src/comadre/main.py:276-305`
- FastAPI `HTTPException` class — https://fastapi.tiangolo.com/reference/exceptions/#fastapi.HTTPException
- Starlette `HTTPException` class (FastAPI's base) — https://www.starlette.io/exceptions/
- Non-regression package README (ownership-table row at line 22; `Scan allowlist convention` at lines 193-206) — `tests/test_non_regression/README.md`
- Non-regression marker registration — `tests/conftest.py:30-33` (broadened by 4.5b)
- `pyproject.toml` `addopts = "-m 'not non_regression'"` — established by 4.5a; unchanged by 4.5f
- Empirical preview grep (zero current `HTTPException` raises/imports in src) — `rg "raise HTTPException|from (fastapi|fastapi.exceptions|starlette.exceptions) import HTTPException" src/comadre/` returns 0 matches on 2026-04-24
- Baseline `HTTPException` reference count — `rg "HTTPException" src/comadre/` returns exactly 2 hits (both docstrings at `main.py:250, 276`) on 2026-04-24

## Dev Agent Record

### Agent Model Used

Claude Opus 4.7 (1M context) (claude-opus-4-7)

### Debug Log References

**Probe A (AC19) — raw HTTPException import + raise injected into `src/comadre/config.py:224-225`:**

```
E       AssertionError: Raw HTTPException usage detected in src/comadre/.
E         This regression breaks FR51 and the {error: {message, type, hint}}
E         envelope contract. Use a ComadreError subclass from
E         src/comadre/exceptions.py instead:
E           - 401   → AuthenticationError / ApiKeyNotFoundError /
E                     ApiKeySuspendedError / ApiKeyRevokedError
E           - 400   → InvalidRequestError / InvalidTaxIdError
E           - 404   → VoiceNotFoundError (or add app.add_exception_handler
E                     in main.py for framework-emitted 404s)
E           - 429   → RateLimitError
E           - 500   → GenerationError / KeyRegistryError
E           - 503   → ServiceUnavailableError
E         If the HTTPException is intentional and bridged back into the
E         envelope by a dedicated exception-bridging helper, add a trailing
E         comment on the offending line (or any line the statement spans):
E             # scan-allow: <why this is safe, reviewed by <initials>>
E
E         Violations:
E           src/comadre/config.py:224: raw HTTPException import — from fastapi import HTTPException
E           src/comadre/config.py:225: raw HTTPException raise — raise HTTPException(status_code=403)
```

Failure message contains all three required AC19 elements: (a) `ComadreError` + `src/comadre/exceptions.py`, (b) the status-code-to-subclass table, (c) the `# scan-allow: <reason>` escape hatch. Both violations named with exact path, line number, kind, and source snippet.

**Probe B (AC20) — same two lines with `# scan-allow: probe-for-4.5f-AC20` appended to each:**

```
tests/test_non_regression/test_no_raw_httpexception.py::test_src_comadre_has_no_raw_httpexception PASSED [100%]

============================== 1 passed in 0.13s ===============================
```

Allowlist contract verified end-to-end on real `src/comadre/` source — same two lines that produced two violations in probe A produce zero violations when each carries a `# scan-allow:` comment. `git diff master -- src/comadre/config.py | wc -l` → `0` after restore.

### Completion Notes List

- **Artefacts shipped.** One new test module (`tests/test_non_regression/test_no_raw_httpexception.py`, 5 tests all marked `@pytest.mark.non_regression`), four fixture files under `tests/test_non_regression/fixtures/no_raw_httpexception/`, one ownership-table row refined in `tests/test_non_regression/README.md:21`.
- **Pre-4.5f baselines (captured fresh on master before Task 1).** `uv run pytest` (default): **1414 passed, 83 deselected** in 56.21 s. `uv run pytest -m non_regression tests/test_non_regression/ -v`: **67 passed, 16 skipped** in 5.19 s.
- **Post-4.5f counts.** `uv run pytest` (default): **1414 passed, 88 deselected** in 50.53 s → Δ `+5 deselected` as AC15 predicted (1 primary + 4 self-tests). `uv run pytest -m non_regression tests/test_non_regression/ -v`: **72 passed, 16 skipped** in 5.43 s → Δ `+5 passed` as AC16 predicted (all 5 new tests are pure-stdlib synchronous AST walks; no docker preconditions, zero skips).
- **AC9 grep invariant holds.** `grep -c "@pytest.mark.non_regression" tests/test_non_regression/test_no_raw_httpexception.py` → `5`.
- **AC10–AC14 + deploy/caddy invariants hold.** `git diff master -- src/comadre/ .github/workflows/ci.yml pyproject.toml uv.lock tests/conftest.py tests/test_non_regression/conftest.py deploy/caddy/ | wc -l` → `0` at story close.
- **AC17 — fixture collection isolation.** `uv run pytest -m non_regression tests/test_non_regression/ --collect-only 2>&1 | rg "fixtures/no_raw_httpexception"` → exit 1 (no matches). `uv run pytest -m non_regression tests/test_non_regression/fixtures/no_raw_httpexception/` reports `collected 0 items`.
- **Bonus invariant.** `rg "HTTPException" src/comadre/ | wc -l` → exactly `2` (the two docstring mentions at `main.py:250,276`). No regression introduced by the story.
- **AC21 — full quality gate.** `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src/` (Success: no issues found in 35 source files), `uv run pytest` (1414 passed, 88 deselected), `uv run pytest -m non_regression tests/test_non_regression/ -v` (72 passed, 16 skipped), and `uv run pre-commit run --all-files` (ruff check / ruff format / hadolint / yamllint / shellcheck / markdownlint-cli2 / mypy — all `Passed`).
- **One ruff-format reflow.** After initial Write, `uv run ruff format --check .` flagged `test_no_raw_httpexception.py`; running `uv run ruff format` collapsed a multi-line ternary for `source_lines[line_index] if 0 <= line_index < len(source_lines) else ""` onto a single line. Zero behavioural change; AC-relevant line numbers are not pinned anywhere in the module (4.5c precedent on line-number non-pinning holds).
- **Design choice confirmations.** (a) `_allowlisted_lines` duplicated in-file per 4.5c precedent (no shared-helper module across 4.5c/4.5f); (b) `_Violation` reuses 4.5c's dataclass shape but adds `kind: Literal["raise", "import"]` instead of `identifier` (the class name is always `"HTTPException"` for FR51); (c) `bad_raise.py` fixture deliberately yields two violations (one `"import"`, one `"raise"`) matching the natural-regression shape; (d) `bad_import.py` carries `# noqa: F401` to pass ruff while the scan still flags the import — the self-test asserts both the violation fires AND the `# noqa: F401` is present, documenting to future readers that ruff's escape-hatch does not suppress this scan.

### File List

- **NEW.** `tests/test_non_regression/test_no_raw_httpexception.py` — primary test module (scan helper + 1 primary assertion + 4 self-tests; 230 lines post-format).
- **NEW.** `tests/test_non_regression/fixtures/no_raw_httpexception/bad_raise.py` — fixture: import + raw raise (the canonical regression; expected to produce 2 violations).
- **NEW.** `tests/test_non_regression/fixtures/no_raw_httpexception/bad_import.py` — fixture: bare `from fastapi.exceptions import HTTPException  # noqa: F401` (the subtler regression; expected to produce 1 violation).
- **NEW.** `tests/test_non_regression/fixtures/no_raw_httpexception/allowlisted_raise.py` — fixture: both forms with inline `# scan-allow:` comments (expected to produce 0 violations).
- **NEW.** `tests/test_non_regression/fixtures/no_raw_httpexception/comadre_error_only.py` — fixture: docstring mentions of `HTTPException` as string literals + a `raise VoiceNotFoundError(...)` (expected to produce 0 violations).
- **MOD.** `tests/test_non_regression/README.md` — ownership-table row at line 21 (4.5f) refined per §Scope-3 to name both rule shapes (raise + import), the three allowlist-contract source modules, and the `ComadreError`-hierarchy remediation hint.
- **MOD.** `_bmad-output/implementation-artifacts/sprint-status.yaml` — `4-5f-ci-no-raw-httpexception` transitioned `ready-for-dev → in-progress → review`; header comment + body `last_updated` bumped to 2026-04-24.
- **MOD.** `_bmad-output/implementation-artifacts/4-5f-ci-no-raw-httpexception.md` (this file) — `Status`, Dev Agent Record (Debug Log, Completion Notes, File List), Tasks/Subtasks checkboxes, and Change Log updated per the dev-story workflow.

**Untouched (AC10–AC14 invariants):** `src/comadre/**`, `deploy/caddy/**`, `.github/workflows/ci.yml`, `pyproject.toml`, `uv.lock`, `tests/conftest.py`, `tests/test_non_regression/conftest.py`.

## Change Log

| Date       | Version | Change                                                                                                  |
| ---------- | ------- | ------------------------------------------------------------------------------------------------------- |
| 2026-04-24 | 0.1     | Story spec created → `ready-for-dev`. Scan design mirrors 4.5c's static-scan pattern: AST walk over `src/comadre/**/*.py` with two rule predicates (`_is_raw_httpexception_raise`, `_is_httpexception_import`); tokenize-based `# scan-allow: <reason>` line-comment allowlist (reuses 4.5c's `_allowlisted_lines` shape); fixture subdirectory `tests/test_non_regression/fixtures/no_raw_httpexception/` with four source fixtures (bad raise, bad bare import, allowlisted both-forms, ComadreError-only-with-docstring-mentions); four self-tests pinning one scan property each. Empirical baseline: `rg "raise HTTPException\|from (fastapi\|fastapi.exceptions\|starlette.exceptions) import HTTPException" src/comadre/` → 0 hits at story-draft time; two docstring `HTTPException` mentions at `main.py:250,276` are AST-structurally ignored. |
| 2026-04-24 | 0.2     | dev-story execution. Shipped `tests/test_non_regression/test_no_raw_httpexception.py` (1 primary + 4 self-tests, all `@pytest.mark.non_regression`), four fixtures under `tests/test_non_regression/fixtures/no_raw_httpexception/`, and the refined README ownership-table row at `tests/test_non_regression/README.md:21`. Pre-4.5f baseline: `pytest` default = 1414 passed / 83 deselected; `pytest -m non_regression` = 67 passed / 16 skipped. Post-4.5f: default = 1414 passed / 88 deselected (Δ +5 deselected, AC15); `-m non_regression` = 72 passed / 16 skipped (Δ +5 passed, AC16). AC10–AC14 + `deploy/caddy/` diffs against master all 0. `rg "HTTPException" src/comadre/` = 2 (unchanged; the two docstring mentions at `main.py:250,276`). Full quality gate (ruff/mypy/pytest default/pytest opt-in/pre-commit) green. Failure-UX probes A + B executed against `src/comadre/config.py` and restored (diff against master = 0); probe logs captured in Dev Agent Record → Debug Log References. Status → `review`. |
| 2026-04-24 | 0.3     | Code review (bmad-code-review) — Blind Hunter, Edge Case Hunter, Acceptance Auditor. All 21 ACs PASS (18 static PASS + 3 trust-only PARTIAL per audit rubric — AC15/AC16/AC21 quality-gate runs trusted from Dev Agent Record). 0 `decision-needed`, 0 `patch`, 4 `defer`, 13 dismissed as noise / design-documented / AC-mandated. See Review Findings section. |

## Review Findings

### Decision needed

_None._

### Patch

_None — no blocking or unambiguously-fixable issues._

### Deferred

- [x] **[Review][Defer] `from fastapi import *` star-import evades the scan.** [`tests/test_non_regression/test_no_raw_httpexception.py:122`] `_is_httpexception_import` iterates `node.names` matching `alias.name == "HTTPException"`, but a star-import has a single `alias(name='*')` that pulls `HTTPException` into scope invisibly. A subsequent `raise HTTPException(...)` in the same file is still caught by the raise rule, but bare references (e.g., `except HTTPException:`) slip through. Not currently exercised in the codebase; patch is a one-line extension (`any(alias.name in {"*", _HTTPEXCEPTION_NAME} ...)` plus a fixture). Detected by: Edge Case Hunter (minor). — deferred, known gap.
- [x] **[Review][Defer] `tokenize.generate_tokens` / `ast.parse` raise on malformed source rather than failing the test with a named path.** [`tests/test_non_regression/test_no_raw_httpexception.py:108, 139`] An unterminated string or SyntaxError in `src/comadre/` surfaces as a raw `TokenError` / `SyntaxError` traceback rather than a `pytest.fail(f"Cannot tokenize/parse {path}: {exc}")`. Inherited verbatim from 4.5c's `_allowlisted_lines` shape; fix belongs in the future shared-helper consolidation (see §Deferred-work "Consolidate `_allowlisted_lines` across 4.5c/4.5f/4.5g"). In practice, a broken-source file would already red the CI elsewhere (ruff, mypy). Detected by: Blind Hunter (minor), Edge Case Hunter (minor, merged). — deferred, shared-helper concern.
- [x] **[Review][Defer] `# scan-allow:` empty-reason / trivial-reason enforcement is documentation-only.** [`tests/test_non_regression/test_no_raw_httpexception.py:13-16`] Module docstring promises an empty or one-word reason is a "review-blocker in practice," but the scan never inspects the post-colon text — a bare `# scan-allow:` with no reason suppresses the violation. Same policy shape as 4.5c (inherited); mechanizing it (e.g., `≥ 3 non-whitespace chars` after the colon + a self-test) is worth doing once across 4.5c/4.5f/4.5g simultaneously. Detected by: Blind Hunter (minor). — deferred, cross-scan policy.
- [x] **[Review][Defer] `# scan-allow:` token is shared verbatim across 4.5c/4.5f/4.5g; a single comment can silence multiple unrelated scans on the same line.** [`tests/test_non_regression/test_no_raw_httpexception.py:58`, `tests/test_non_regression/test_timing_safe_compare.py` (4.5c)] A line that happens to trip both the timing-safe compare scan AND the HTTPException-raise scan would be cleared by one comment. Low probability (the two scan shapes rarely coincide on a single line), but the policy is undocumented at README level. Candidate fix: namespace the token (`# scan-allow[4.5f]:`) or document the shared-token semantics in the README's `Scan allowlist convention` section. Detected by: Blind Hunter (minor). — deferred, cross-scan policy.

### Dismissed (noise / design-documented / AC-mandated)

- `import fastapi` at module level not flagged — documented as intentional in spec §Dev-Notes ("module-level import is fine; the raise rule catches any actual usage via `fastapi.HTTPException(...)`").
- Aliased raise (`HE = HTTPException; raise HE(...)`), ternary `raise (x if c else HTTPException(...))`, walrus `raise (e := HTTPException(...))` evade the scan — explicit deferred work in spec §Deferred-work ("Flow-aware scan: track variables bound to `HTTPException(...)`").
- `node.module is None` defensive guard for relative imports — current code is already correct (None not in frozenset → False); the suggested hardening adds no behaviour.
- `_Violation.render()` doesn't join multi-line source spans — not in any AC; single-line fragment + `lineno` is sufficient diagnostic surface. Multi-line `raise HTTPException(...)` is vanishingly rare.
- `sorted(kinds) == ["import", "raise"]` in `test_scan_flags_bad_raise` — correct assertion; proposed `set` rewrite doesn't improve correctness.
- Fixture argument-list inconsistency (`status_code=403, detail="forbidden"` vs bare `status_code=403`) — cosmetic; the property under test is the `# scan-allow:` suffix, not the argument list.
- `rglob("*.py")` might pick up misplaced fixtures if a future refactor moves them under `src/` — hypothetical; `src/comadre/` is contractually fixture-free.
- `# noqa: F401` coupling in `test_scan_flags_bad_import`'s source-line assertion — AC4 mandates this exact assertion text to document to future readers that ruff's noqa is orthogonal to the scan's allowlist.
- Name-collision with a hypothetical non-FastAPI `HTTPException` class (e.g., `mylib.exceptions.HTTPException`) — no such class exists in the project; the name-match policy is documented in spec §Dev-Notes.
- README ownership-row cell length — AC18 mandates the verbose FR51 description naming both rule shapes, the three source modules, and the `ComadreError` remediation hint.
- `UnicodeDecodeError` on non-UTF-8 `.py` file — Python source is spec'd UTF-8; a non-conforming file would break ruff/mypy/import machinery before reaching the scan.
- `SyntaxError` aborts the walk on the first bad file — a SyntaxError in `src/comadre/` would already red ruff/mypy/`pytest` collection; the scan's loud failure is acceptable.
- README column visual alignment — Markdown tables don't require visual alignment; row parses correctly.
