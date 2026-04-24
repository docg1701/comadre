# Story 4.5e: CI — Rate-Limit Middleware Registration

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

> **Scope note — FR50, NFR17.** Fifth of the seven CI non-regression sub-stories (4.5a–4.5g). Inherits the skeleton 4.5a landed (`tests/test_non_regression/` package, `non_regression` pytest marker, `non-regression` job in `.github/workflows/ci.yml`) and the README's "Harness choice" rule 4.5a/4.5b/4.5d/4.5c established. 4.5e is the FIRST ASGI-TestClient sub-story in the cluster — the README codifies this choice verbatim at `tests/test_non_regression/README.md:184-191`: *"pick TestClient when the check is app-internal (FR47, FR50)."* Does **NOT** spin up docker; reuses the repo-level `app` + `client` fixtures from `tests/conftest.py` pattern instead of the docker-harness `compose_stack` + `probe_client`. Delivers ONE artefact: `tests/test_non_regression/test_rate_limit_wired.py` with `@pytest.mark.non_regression` tests that assert the per-key rate-limit gate on `/v1/audio/speech` (a) is wired as a FastAPI dependency (route-inspection), (b) has its infrastructure initialised at lifespan (`app.state.rate_limiter` is not `None`), and (c) actually emits HTTP 429 with a `Retry-After` header and the project `{error:{message,type,hint}}` envelope once a key's `rate_limit_rpm` is exceeded. **No change to `src/comadre/`. No change to `deploy/caddy/`. No new Python dependency. No CI YAML change. No `pyproject.toml` change. No `tests/conftest.py` change.**

> **Spec premise note (READ BEFORE IMPLEMENTING).** FR50 as worded in PRD line 1194 and in the epic AC (epics.md lines 968-984) refers to **`SlowAPIMiddleware`** and expects rate-limit coverage on **both `/v1/audio/speech` AND `/health`**, parametrised by `RATE_LIMIT_SPEECH` / `RATE_LIMIT_HEALTH` environment variables. All three of those references are **stale against the shipped 2.0.0 architecture**. Story 2.2 (done, commit `1d27e12`) retired slowapi entirely, replaced by `limits` driving a `FastAPI Depends(check_rate_limit)` on `/v1/audio/speech` only. CLAUDE.md §Architecture is explicit: *"`/health` is not rate-limited at the app layer."* The PRD itself documents this retirement in two places: §Change Log line 9 (*"Rate-limit refactored: slowapi dropped in favour of limits directly, per-key only (bucket = key:<key_id>). Per-IP rate-limit removed from the application layer entirely."*) and §Architecture-Level Security Controls line 220 (*"slowapi is **removed** as a dependency. The /v1/audio/speech endpoint uses FastAPI Depends(check_rate_limit)..."*). Architecture.md lines 656 and 271 still carry the OLD `SlowAPIMiddleware` / `RATE_LIMIT_SPEECH` wording — these are unreconciled drift from 2.2's refactor, NOT a design reversal. 4.5e implements the **intent** of FR50 — prevent a regression of the edfcb33 bug class, i.e. "rate-limit infrastructure wired but not actually enforced on request" — against the shipped architecture. See §Scope amendment at the top of §Scope for the mechanical re-interpretation. **Dev agent: implement the re-interpreted shape. Do NOT attempt to reintroduce slowapi or rate-limit `/health`.**

## Story

As a contributor,
I want every pull request against master to prove — via an in-process ASGI TestClient that exercises `POST /v1/audio/speech` with a seeded, authenticated API key whose `rate_limit_rpm` is a small test value (2) — that (a) the `check_rate_limit` FastAPI dependency is still registered in the route's `dependencies=[...]` list, (b) `app.state.rate_limiter` is still populated by the lifespan startup (non-None, carries the expected `RateLimiter` shape), and (c) the gate actually fires: the 3rd request in the window returns HTTP 429 with a `Retry-After` header, an `X-RateLimit-*` header set, and the project's uniform `{error:{message,type,hint}}` JSON envelope,
so that a well-meaning refactor — dropping `Depends(check_rate_limit)` from `api_router.post("/v1/audio/speech", ..., dependencies=[...])` in pursuit of "simpler route", deleting the `app.state.rate_limiter = RateLimiter.build()` line from the lifespan's Phase 2a, or swapping the route handler wholesale for one that bypasses FastAPI's dependency tree — cannot land on master without the PR build turning red and naming which leg regressed: "dependency-list missing", "app.state.rate_limiter is None", or "3rd request returned {status_code} expected 429".

**Covers FRs:** FR50 (CI can verify that the rate-limit middleware is registered and actually applies to the speech endpoint). Re-interpreted for the 2.0.0 architecture per the spec-premise note above: "middleware" → "per-route FastAPI dependency"; "middleware registered" → "dependency present in route declaration AND `app.state.rate_limiter` initialised at startup"; "actually applies to both the speech and health endpoints" → "actually applies to the speech endpoint" (`/health` is un-rate-limited by design; see §Scope amendment).
**NFRs:** NFR17 (all Non-Regression Contract controls remain satisfied on every PR; CI regression coverage mandatory for each control row).
**UX-DRs:** Contributor-facing CI UX — when an assertion fires, the pytest failure message MUST name (a) the control regressed (`check_rate_limit` dependency / `app.state.rate_limiter` / 429 behaviour), (b) the HTTP method + path exercised, (c) the observed status code vs the expected, (d) a one-line diagnostic tail (e.g., "Depends(check_rate_limit) is missing from api_router.post('/v1/audio/speech').dependencies — the edfcb33-class bug has regressed: the rate-limit gate is silently inert"). Inherits the 4.5a "name-the-regression" assertion convention.
**Epic:** 4 — Security Hardening, LGPD & Operational Safety. Ninth story in Epic 4 (4.1 → 4.2 → 4.3 → 4.4 → 4.5a → 4.5b → 4.5c → 4.5d → **4.5e** → 4.5f → 4.5g → 4.6). Fifth of the seven-sub-story CI non-regression cluster; first ASGI-TestClient sub-story (predecessors 4.5a/4.5b/4.5d are docker-stack; 4.5c is pure static scan).

## Builds on

- **Story 4.5a — CI non-regression skeleton (`done`).** Established the `tests/test_non_regression/` package, the `non_regression` pytest marker (`tests/conftest.py:30-33`), the `addopts = "-m 'not non_regression'"` default-exclusion in `pyproject.toml`, the `non-regression` CI job in `.github/workflows/ci.yml` that runs `uv run pytest -m non_regression tests/test_non_regression/ -v`, and the "Extension contract" README section naming what each downstream sub-story SHOULD / SHOULD NOT do (`tests/test_non_regression/README.md:150-207`).
- **Story 4.5b — README Harness-choice section (`done`).** Broadened the `non_regression` marker's description to cover both docker and TestClient tests, and codified the Harness choice paragraph (`tests/test_non_regression/README.md:177-191`) which names 4.5e verbatim: *"pick TestClient when the check is app-internal (FR47, FR50)."* 4.5e is the first sub-story to mechanically exercise the TestClient half of that rule.
- **Story 4.5c — Fixture-directory convention for static-scan sub-stories (`done`).** Orthogonal to 4.5e (4.5c is pure-stdlib static scan; 4.5e runs an in-process ASGI app), but the README amendment sits adjacent to the Harness-choice section 4.5e leans on. 4.5e does NOT add a sibling `tests/test_non_regression/fixtures/rate_limit_wired/` directory — all seeding happens in-test via the existing `seed_customer_and_key` helper from `tests/_keys_fixtures.py`, no on-disk fixture files needed.
- **Story 4.5d — Docker-stack sub-story + `_UPSTREAM_NGINX_CONF` hardening (`done`).** Orthogonal to 4.5e; 4.5d is the canonical docker-harness example, 4.5e is the canonical TestClient example. 4.5d's `tests/test_non_regression/conftest.py` additions (`client_max_body_size 100M;`) are irrelevant to 4.5e — the TestClient never touches the docker stack.
- **Story 2.2 — Per-key rate-limiting via `limits` library (`done`, commit `1d27e12`).** Retired slowapi entirely; the new wiring is `FastAPI Depends(check_rate_limit)` on `/v1/audio/speech`, `RateLimiter` built in lifespan, bucket keyed by `key:<key_id>`. 4.5e asserts this wiring does not regress. The relevant unit of regression is the edfcb33-class bug: in the pre-2.0.0 slowapi era, `app.state.limiter` was assigned but `SlowAPIMiddleware` was never added, so every `@limiter.limit()` decorator was silently inert. The modern equivalent regression would be: `Depends(check_rate_limit)` removed from the route, or `app.state.rate_limiter = RateLimiter.build()` removed from the lifespan. Either leaves the rate-limit gate silently inert — exactly the failure mode FR50 exists to catch.
- **Story 2.3 — Per-key counters (`done`).** Tangentially relevant: `check_rate_limit` increments `counters.incr_429(payload.key_id)` on deny. 4.5e does NOT assert on counter side-effects (those belong to 2.3's test suite); the 429 assertion is on the HTTP response only. Mentioned here so the dev agent knows not to accidentally re-assert 2.3's coverage.
- **Existing integration fixtures — `tests/conftest.py` (`app`, `client`, `auth_headers`, `registry_db`, `fernet_key`, `mock_settings`, `mock_router`).** The `app` fixture at `tests/conftest.py:91-128` sets up registry-mode FastAPI with an `AuthCache` AND `RateLimiter.build()` so auth + rate-limit both work end-to-end. The `client` fixture at line 131 wraps it in `httpx.AsyncClient(transport=ASGITransport(...))`. 4.5e's test module imports these from `tests.conftest` — not from the non-regression sub-package's own `conftest.py` (which is docker-only).
- **Existing 429 integration coverage — `tests/test_api.py::TestPerKeyRateLimit` (lines 688-947).** The `test` job already runs 8+ tests that seed `rate_limit_rpm=2` and assert 429 on the 3rd request. 4.5e is NOT a duplicate of that coverage — `test_api.py` is the primary contract (proves the wiring works); 4.5e is a **non-regression guard** that runs in the separate `non-regression` CI job and specifically asserts the three failure-modes that would make the edfcb33 bug class recur (missing dep, missing state, 429 not firing). Dev agent: DO NOT duplicate `TestPerKeyRateLimit`'s full coverage; write a tight, fail-loud regression module. The sentence "don't reinvent wheels" from the CLAUDE.md rules applies.
- **Existing seed helper — `tests/_keys_fixtures.py::seed_customer_and_key`.** Returns `(plaintext, key_id, customer_id)`; seeds both `customer` and `api_key` rows; commits the insert so the TestClient sees it on next connection lookup. 4.5e's tests call this with `rate_limit_rpm=2` verbatim — same pattern `test_api.py::TestPerKeyRateLimit` uses.
- **Canonical rate-limit wiring — `src/comadre/rate_limit.py:76-162` + `src/comadre/api.py:34-41` + `src/comadre/main.py:68`.** 4.5e's route-inspection assertion reads `api_router.routes` (or `create_app().routes`) to confirm `check_rate_limit` is in the `dependencies` for `/v1/audio/speech`. 4.5e's state-inspection assertion creates `app = create_app()`, runs the lifespan, and asserts `app.state.rate_limiter is not None and isinstance(app.state.rate_limiter, RateLimiter)`. 4.5e's behavioural assertion calls `await client.post(...)` 3 times and asserts the 3rd returns 429 + envelope.
- **CLAUDE.md §Architecture line on `/health`.** *"`/health` is not rate-limited at the app layer."* This is the authoritative source of truth for the `/health` leg of the epic AC. FR50 text in the epic/PRD mentions `/health` because it was written pre-2.2-refactor; 4.5e's implementation replaces that expectation with a **negative assertion**: burst on `/health` with no auth header, confirm the responses never carry a 429 status — i.e., the rate-limit gate is correctly ABSENT from `/health`. See §Scope-3.
- **PRD §Non-Regression Contract — line 188.** Explicit enumeration of `SlowAPIMiddleware registered` alongside security headers, banner stripping, docs-disabled, `request_body max_size`, timing-safe compare, error-envelope uniformity. 4.5e converts this row from prose-only to mechanically-enforced (translated to the current architecture per the spec-premise note above).
- **FR50 — PRD line 1194.** *"CI can verify that the rate-limit middleware is registered and actually applies to both the speech and health endpoints."* 4.5e fulfills this FR **in spirit** against the 2.0.0 architecture: "middleware" is now a route dependency; "registered" is now `Depends(check_rate_limit)` in `api_router.post(...).dependencies` AND `app.state.rate_limiter` initialised; "actually applies to speech" is proven by the 3-request-burst 429 assertion; "actually applies to health" is reinterpreted as "is correctly absent on /health" per CLAUDE.md's explicit design statement.

## Unblocks

- **Story 4.5f (`backlog`).** 4.5f is the static-scan "no raw `HTTPException`" sub-story; it uses a pure-stdlib scan and does not depend on 4.5e's harness or artefacts. Sequencing-wise, 4.5e closing demonstrates the ASGI-TestClient harness shape for any future app-internal sub-story — 4.5f can model its skeleton after 4.5e if it ever grows a harness beyond static scan (unlikely but possible).
- **Story 4.5g (`backlog`).** 4.5g is the `bandit` SQL-injection scan sub-story; also independent of 4.5e.
- **PRD Non-Regression Contract FR50 row.** Converts the `SlowAPIMiddleware registered` row from prose-only to mechanically enforced. Combined with 4.5a (FR46), 4.5b (FR47), 4.5c (FR48), 4.5d (FR49), this brings five of the seven sub-stories' FR rows to mechanical enforcement — after 4.5e lands, the CI gate fails on regression of security headers, docs-disabled, timing-safe compare, oversized body rejection, OR rate-limit wiring.
- **Operational confidence in the rate-limit path.** Today the two load-bearing lines (`Depends(check_rate_limit)` in `api.py:39` and `app.state.rate_limiter = RateLimiter.build()` in `main.py:68`) are guarded only by code review and by the `tests/test_api.py::TestPerKeyRateLimit` coverage in the main `test` job. After 4.5e lands, the dedicated `non-regression` job ALSO asserts the wiring — and does so with a short, fast, purpose-built module whose failure message names the regression class explicitly.

## Depends on

- **Stories 4.5a, 4.5b, 4.5c, 4.5d are `done`** (sprint-status.yaml confirms; checked 2026-04-24). Hard dependency on 4.5a's non-regression package skeleton, marker, CI job, and the `addopts = "-m 'not non_regression'"` default-exclusion. Soft dependency on 4.5b's marker broadening (the marker description already covers ASGI TestClient tests; 4.5e is TestClient, so this is a no-op). Soft dependency on 4.5b's README Harness-choice paragraph (it names 4.5e explicitly as the canonical TestClient example; 4.5e's implementation simply matches what the README already promised).
- **Story 2.2 is `done`** (per sprint-status.yaml). Provides `check_rate_limit` dependency, `RateLimiter.build()`, and the route-level wiring 4.5e asserts against. Without 2.2, there is nothing for 4.5e to guard.
- **Story 2.3 is `done`** (per sprint-status.yaml). Provides `RequestCounters.incr_429` call-site inside `check_rate_limit`; 4.5e does NOT assert on counter side-effects but the call-site's presence is part of the `check_rate_limit` body 4.5e transitively exercises.
- **No new runtime dependency.** `httpx`, `pytest`, `pytest-asyncio` already in dev dependencies.
- **No new dev dependency.**
- **No schema change. No auth-path change. No `src/comadre/` change. No `deploy/caddy/` change. No CI YAML change. No `pyproject.toml` change. No new CLI verb. No ansible change.** Grep invariant (AC10 / AC11 / AC12 / AC13): `git diff master -- src/comadre/ deploy/caddy/ .github/workflows/ci.yml pyproject.toml uv.lock tests/conftest.py` returns empty. The entire story lives under `tests/test_non_regression/` — one new test module plus one ownership-table row in `tests/test_non_regression/README.md`.

## Scope

Three workstreams, in order:

1. **Re-interpret FR50 against the shipped 2.0.0 architecture** (§Scope amendment — read first; no code deliverable, but shapes every line of Workstream 2).
2. **Ship the rate-limit-wiring test module** — `tests/test_non_regression/test_rate_limit_wired.py`. Five `@pytest.mark.non_regression` tests, all using the `app` + `client` fixtures from `tests/conftest.py` (NOT the docker fixtures from `tests/test_non_regression/conftest.py`).
3. **README housekeeping** — refine the ownership-table row at `tests/test_non_regression/README.md:20` from *"SlowAPIMiddleware registered"* to the verbose FR50 description naming the three assertion legs.

### Scope amendment — FR50 re-interpreted for 2.0.0

The epic AC for 4.5e (epics.md:978-983) reads:

> **Given** a PR is opened against master
> **When** CI launches the application and issues more requests per minute to `/v1/audio/speech` than the configured `RATE_LIMIT_SPEECH` value, and separately to `/health` than `RATE_LIMIT_HEALTH`
> **Then** both endpoints return HTTP 429 with a `Retry-After` header and the standard `{error: {message, type, hint}}` envelope once the limit is exceeded
> **And** a startup assertion verifies `SlowAPIMiddleware` is in the FastAPI middleware stack (not merely imported)
> **And** the test fixture uses short time windows (e.g., 2 req/10s) to keep CI fast

Four premises in that AC are stale against the shipped 2.0.0 architecture:

1. **`SlowAPIMiddleware`** — retired by story 2.2 (commit `1d27e12`, *"feat(2.0.0): retire legacy single-API_KEY mode and rewrite rate-limit on `limits`"*). The shipped equivalent is `FastAPI Depends(check_rate_limit)` at `src/comadre/api.py:39`. Proof: `rg "SlowAPIMiddleware|slowapi" src/ pyproject.toml` returns zero hits. The FastAPI middleware stack has ZERO entries from `slowapi.*`; asserting on `SlowAPIMiddleware` being in the stack would fail for structural reasons, not for FR50 regressions.
2. **`RATE_LIMIT_SPEECH` and `RATE_LIMIT_HEALTH` env vars** — removed by story 2.2 (see 2-2-dynamic-per-key-rate-limiting.md line 155: *"RATE_LIMIT_SPEECH, RATE_LIMIT_HEALTH removed"*, and line 211's grep invariant: *"zero matches"*). Rate-limit values come from the DB row's `rate_limit_rpm` column, not from environment.
3. **`/health` being rate-limited** — NOT rate-limited by design per CLAUDE.md §Architecture: *"`/health` is not rate-limited at the app layer."* The `/health` handler (`src/comadre/main.py:381-416`) has no `Depends(check_rate_limit)` in its declaration and no dependency chain that imports it. Asserting "/health returns 429 on burst" is a **false premise**; the correct assertion is "/health never returns 429".
4. **"short time windows (e.g., 2 req/10s)"** — the shipped implementation uses `limits`'s `MovingWindowRateLimiter` with `f"{rpm}/minute"` parsing. There is no "seconds" window; the smallest testable granularity is per-minute. The test uses `rate_limit_rpm=2` (2 per minute) and fires 3 requests sequentially — the 3rd request lands well within the 1-minute window and trips 429. Wall-time cost is a few hundred ms (one TTS mock call is negligible, no sleeps). This matches `test_api.py::TestPerKeyRateLimit`'s existing pattern verbatim.

**Faithful re-interpretation (the shape 4.5e implements):**

| Epic-AC phrase | 2.0.0 re-interpretation | Test-level assertion |
|---|---|---|
| "middleware is registered" | `Depends(check_rate_limit)` appears in `api_router.post("/v1/audio/speech", ..., dependencies=[...])` | Test 1: route-inspection |
| "(not merely imported)" | `app.state.rate_limiter` is non-`None` and an instance of `RateLimiter` after lifespan startup | Test 2: state-inspection |
| "actually applies to the speech endpoint" | 3rd request at `rate_limit_rpm=2` returns 429 + `Retry-After` + envelope + `X-RateLimit-*` | Test 3: behavioural |
| "actually applies to the health endpoint" | `/health` is correctly UN-rate-limited per CLAUDE.md (negative assertion) | Test 4: absence on `/health` |
| "short time windows to keep CI fast" | `rate_limit_rpm=2` + 3 sequential requests on a mocked TTS engine | Wall time: < 200 ms per test |

Additionally, a fifth **structural scan** test asserts that the route's `Depends(check_rate_limit)` entry still names `check_rate_limit` by identity (not just "some dependency is there") — catches the failure mode "refactor replaces `check_rate_limit` with a no-op stub that keeps the dependency-list non-empty but silently permits everything."

**Why not assert on the full middleware stack.** FastAPI middlewares and route-level dependencies are distinct mechanisms. Asserting *"some entry in `app.user_middleware` is named `check_rate_limit`"* would fail — `check_rate_limit` is NOT a middleware. The correct surface to inspect is `route.dependencies` on the `APIRoute` object for `/v1/audio/speech`. Dev agent: do not search `app.user_middleware`; walk `app.routes`.

**Why not reintroduce slowapi or /health rate-limiting.** Both were deliberate retirements driven by operator-facing arguments (documented in 2.2's commit message and in the PRD Change Log). Reverting them would be a meaningful architectural change that requires its own PRD sign-off — not something a CI non-regression sub-story unilaterally decides. 4.5e's role is to **guard the current shape**, not to re-litigate 2.2.

### 1. `test_rate_limit_wired.py` — the five tests

**New module: `tests/test_non_regression/test_rate_limit_wired.py`**

**Imports:**

```python
from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from fastapi.routing import APIRoute
from httpx import AsyncClient

from comadre.keys import auth as auth_module
from comadre.rate_limit import RateLimiter, check_rate_limit
from tests._keys_fixtures import seed_customer_and_key
```

**Constants:**

```python
_SPEECH_PATH: str = "/v1/audio/speech"
_HEALTH_PATH: str = "/health"
_TEST_RPM: int = 2  # small value keeps the 3rd-request 429 trip fast
_BURST_ATTEMPTS: int = 5  # /health probe — prove 429 never happens
_SPEECH_BODY: dict[str, str] = {
    "input": "olá mundo",
    "voice": "kokoro/pm_santa",
    "response_format": "ogg",
}
```

**Test 1 — route-inspection assertion (AC2).**

Uses `create_app()` directly (no seeded DB needed; pure structural scan). Walks `app.routes`, finds the `APIRoute` whose `path == "/v1/audio/speech"` and `"POST" in route.methods`, asserts that `check_rate_limit` appears among the `route.dependant.dependencies[*].call` or in `route.dependencies`. FastAPI exposes dependencies at two places:

- `APIRoute.dependencies` — raw `Depends(...)` list from the route decorator's `dependencies=[...]` kwarg.
- `APIRoute.dependant.dependencies` — resolved dependency tree (flat). Each entry has `.call` naming the callable.

The wiring in `api.py:34-41` uses `dependencies=[Depends(verify_ready), Depends(verify_api_key), Depends(check_rate_limit)]` — so both surfaces MUST carry `check_rate_limit`. Assert on BOTH so the test catches a refactor that keeps one and drops the other:

```python
@pytest.mark.non_regression
def test_check_rate_limit_dependency_registered_on_speech_route() -> None:
    """FR50 regression guard: `Depends(check_rate_limit)` must still be in
    the `dependencies=[...]` list on the `POST /v1/audio/speech` route.

    Catches the edfcb33-class bug: rate-limit infrastructure wired but not
    actually enforced on request. If the `Depends(check_rate_limit)` entry
    is dropped from the route declaration, `check_rate_limit` never runs,
    and every authenticated request bypasses the gate silently.
    """
    from comadre.main import create_app

    app = create_app()
    speech_routes = [
        r
        for r in app.routes
        if isinstance(r, APIRoute)
        and r.path == _SPEECH_PATH
        and "POST" in r.methods
    ]
    assert len(speech_routes) == 1, (
        f"Expected exactly one POST {_SPEECH_PATH} route, found "
        f"{len(speech_routes)}. Route declaration at src/comadre/api.py "
        f"may have been reshaped — FR50 wiring invariant broken."
    )
    route = speech_routes[0]
    declared_calls = [d.dependency for d in (route.dependencies or [])]
    resolved_calls = [d.call for d in route.dependant.dependencies]
    assert check_rate_limit in declared_calls, (
        f"POST {_SPEECH_PATH} route has dependencies=[...] but "
        f"`check_rate_limit` is NOT among them. Declared: "
        f"{[c.__name__ for c in declared_calls if c is not None]}. "
        f"The edfcb33-class bug has regressed: the rate-limit gate is "
        f"silently inert. Restore `Depends(check_rate_limit)` in "
        f"`src/comadre/api.py`'s `api_router.post('/v1/audio/speech', "
        f"dependencies=[...])`."
    )
    assert check_rate_limit in resolved_calls, (
        f"POST {_SPEECH_PATH} route's resolved dependency tree does not "
        f"include `check_rate_limit`. Resolved: "
        f"{[c.__name__ for c in resolved_calls if c is not None]}. "
        f"This indicates `check_rate_limit` was declared but FastAPI "
        f"failed to resolve it (import error? signature change?) — "
        f"investigate `src/comadre/rate_limit.py::check_rate_limit`."
    )
```

**Test 2 — state-inspection assertion (AC3).**

Uses the existing `app` fixture from `tests/conftest.py` (which runs `create_app()` + lifespan startup synchronously) and asserts `app.state.rate_limiter` is populated:

```python
@pytest.mark.non_regression
def test_rate_limiter_initialised_at_lifespan_startup(app: Any) -> None:
    """FR50 regression guard: `app.state.rate_limiter` must be a
    `RateLimiter` instance after lifespan startup.

    Catches the failure mode "the lifespan forgot to wire the limiter" —
    e.g., a refactor that moves the init into a separate function and
    forgets to call it. `check_rate_limit` reads `app.state.rate_limiter`
    at request time; if it is `None`, the dependency raises
    `KeyRegistryError` on EVERY request — the rate-limit gate fails
    CLOSED, which is less bad than silent-inert (edfcb33-class) but still
    an FR50 regression.
    """
    rl = getattr(app.state, "rate_limiter", None)
    assert rl is not None, (
        "`app.state.rate_limiter` is None after lifespan startup. The "
        "lifespan at `src/comadre/main.py:68` sets "
        "`app.state.rate_limiter = RateLimiter.build()`; this line "
        "appears to have been removed or moved. Every request to "
        "/v1/audio/speech will now fail with KeyRegistryError — the "
        "FR50 regression gate has fired."
    )
    assert isinstance(rl, RateLimiter), (
        f"`app.state.rate_limiter` is set but is not a `RateLimiter` "
        f"instance — got {type(rl).__name__}. Something replaced the "
        f"canonical `RateLimiter.build()` with an incompatible type; "
        f"check `src/comadre/main.py` lifespan and "
        f"`src/comadre/rate_limit.py::RateLimiter`."
    )
```

**Test 3 — behavioural 429 assertion (AC4).**

Mirrors `test_api.py::TestPerKeyRateLimit::test_per_key_limit_trips_on_n_plus_one` tightly, but lives in the non-regression suite so it runs in the separate CI job:

```python
@pytest.mark.non_regression
async def test_speech_endpoint_emits_429_after_rate_limit(
    app: Any, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR50 regression guard: exceeding `rate_limit_rpm` on
    `/v1/audio/speech` returns HTTP 429 with the project envelope.

    The most direct assertion of the FR50 intent: a functioning
    rate-limit gate returns 429 when the limit is exceeded. If Test 1
    (dependency wired) and Test 2 (state initialised) both pass but THIS
    test fails, something subtler is broken — e.g., the `check_rate_limit`
    body was changed to always allow, or `MovingWindowRateLimiter.hit`
    was monkey-patched incorrectly in a refactor.
    """
    monkeypatch.setattr(
        auth_module, "_today_in_billing_tz", lambda _s: date(2026, 4, 17)
    )
    plaintext, _kid, _cid = seed_customer_and_key(
        app.state.registry_db, rate_limit_rpm=_TEST_RPM
    )
    headers = {"Authorization": f"Bearer {plaintext}"}

    # Consume the budget exactly.
    for attempt in range(_TEST_RPM):
        r = await client.post(_SPEECH_PATH, json=_SPEECH_BODY, headers=headers)
        assert r.status_code == 200, (
            f"Attempt {attempt + 1}/{_TEST_RPM} to {_SPEECH_PATH} at "
            f"rate_limit_rpm={_TEST_RPM} returned {r.status_code} — "
            f"expected 200. The under-limit path should NEVER 429. "
            f"Body: {r.text[:200]!r}"
        )

    # One more request trips the gate.
    trip = await client.post(_SPEECH_PATH, json=_SPEECH_BODY, headers=headers)
    assert trip.status_code == 429, (
        f"{_TEST_RPM + 1}th request to {_SPEECH_PATH} at "
        f"rate_limit_rpm={_TEST_RPM} returned {trip.status_code}, "
        f"expected 429. The rate-limit gate is silently permitting "
        f"over-budget requests — edfcb33-class regression: FR50 gate "
        f"failed. Body: {trip.text[:200]!r}"
    )
    assert "retry-after" in (h.lower() for h in trip.headers), (
        f"429 response missing `Retry-After` header. Headers: "
        f"{dict(trip.headers)}. Clients cannot back off cleanly; the "
        f"response shape regressed from the 2.2 contract."
    )
    body = trip.json()
    assert body == {
        "error": {
            "message": "Rate limit exceeded",
            "type": "rate_limit_error",
            "hint": (
                f"Too many requests. Try again in "
                f"{int(trip.headers['retry-after'])} seconds."
            ),
        }
    }, (
        f"429 envelope drifted from the `{{error:{{message,type,hint}}}}` "
        f"shape. Got: {body!r}. The uniform-error-envelope contract is "
        f"a separate non-regression concern (4.5f), but this assertion "
        f"also catches drift here so a 429 with an OK body does not pass."
    )
    assert trip.headers.get("x-ratelimit-limit") == str(_TEST_RPM), (
        f"X-RateLimit-Limit header on 429 is "
        f"{trip.headers.get('x-ratelimit-limit')!r}, expected "
        f"{_TEST_RPM!r}. The 2.2 contract guarantees all three "
        f"X-RateLimit-* headers on both allow AND deny paths."
    )
    assert trip.headers.get("x-ratelimit-remaining") == "0"
    assert int(trip.headers["x-ratelimit-reset"]) > 0
```

**Test 4 — `/health` is UN-rate-limited (AC5).**

Negative assertion — prove that `/health` never returns 429 even under burst:

```python
@pytest.mark.non_regression
async def test_health_endpoint_is_not_rate_limited(
    app: Any, client: AsyncClient
) -> None:
    """FR50 (re-interpreted): `/health` is UN-rate-limited by design.

    CLAUDE.md §Architecture: "`/health` is not rate-limited at the app
    layer." This test pins that design decision. If a future PR adds
    `Depends(check_rate_limit)` to `/health`, bursting it with zero auth
    header would 429 instead of returning the minimal-for-unauth body,
    which is a design regression (operators rely on un-throttled probes
    for liveness checks).
    """
    statuses: list[int] = []
    for _ in range(_BURST_ATTEMPTS):
        r = await client.get(_HEALTH_PATH)
        statuses.append(r.status_code)
    assert 429 not in statuses, (
        f"`/health` returned 429 within a {_BURST_ATTEMPTS}-request "
        f"burst: statuses={statuses}. This indicates a rate-limit gate "
        f"was added to `/health` — contradicting the CLAUDE.md design "
        f"decision 'health is not rate-limited at the app layer.' "
        f"Operators rely on un-throttled probes for liveness checks; "
        f"rate-limiting `/health` is a design regression, not a fix."
    )
    for status in statuses:
        assert status in {200, 503}, (
            f"`/health` returned an unexpected status {status} in the "
            f"burst. Expected 200 (ready) or 503 (warming_up). Statuses "
            f"observed: {statuses}."
        )
```

**Test 5 — structural identity guard (AC6).**

Asserts that the `check_rate_limit` dependency is the SAME object imported from `comadre.rate_limit`, not a differently-named-but-same-kind callable. Catches the failure mode "someone replaced `check_rate_limit` with a stub that keeps the dependency-list populated but silently permits everything":

```python
@pytest.mark.non_regression
def test_check_rate_limit_identity_on_speech_route() -> None:
    """FR50 regression guard: the dependency callable is precisely
    `comadre.rate_limit.check_rate_limit` — not a stub, not a shim.

    Catches the subtle refactor "rename `check_rate_limit` and leave the
    old symbol as a no-op" — the dependency list stays non-empty,
    `check_rate_limit in declared_calls` still passes if the OLD symbol
    is kept around as a no-op, but the NEW symbol is the one the route
    actually uses. This test pins identity: the object named
    `check_rate_limit` in `comadre.rate_limit` is the same object
    referenced by the route.
    """
    from comadre.main import create_app
    from comadre.rate_limit import check_rate_limit as canonical

    app = create_app()
    speech_routes = [
        r
        for r in app.routes
        if isinstance(r, APIRoute)
        and r.path == _SPEECH_PATH
        and "POST" in r.methods
    ]
    route = speech_routes[0]
    resolved = [d.call for d in route.dependant.dependencies]
    # ``is`` not ``==`` — identity, not equality.
    assert any(d is canonical for d in resolved), (
        f"POST {_SPEECH_PATH} route's dependency is NOT the canonical "
        f"`comadre.rate_limit.check_rate_limit` object. Resolved "
        f"callables: "
        f"{[(c.__module__, c.__name__) for c in resolved if c is not None]}. "
        f"A refactor may have introduced a shim/stub that keeps the "
        f"dependency list populated but silently permits everything — "
        f"edfcb33-class regression via a subtler mechanism."
    )
```

**Module docstring:**

```python
"""FR50 non-regression — rate-limit gate wiring on /v1/audio/speech
(Story 4.5e).

Asserts three failure modes that would reintroduce the edfcb33-class
bug (rate-limit infrastructure wired but not actually enforced on
request):

1. `Depends(check_rate_limit)` removed from the route declaration.
2. `app.state.rate_limiter` not populated by lifespan startup.
3. 3rd request at `rate_limit_rpm=2` does not return 429.

Plus two guards on the shape of the fix:

4. `/health` remains UN-rate-limited (CLAUDE.md design decision).
5. The route's dependency is the canonical `check_rate_limit` object,
   not a same-named stub.

Uses the repo-level ASGI TestClient fixtures (`app`, `client`) from
`tests/conftest.py` — NOT the docker fixtures from this package's
`conftest.py`. Runs in-process; no docker required.
"""
```

### 2. README housekeeping

**Edit `tests/test_non_regression/README.md:20`** — the ownership-table row for `test_rate_limit_wired.py`. Replace:

```
| `test_rate_limit_wired.py`   | 4.5e      | `SlowAPIMiddleware` registered                              |
```

with:

```
| `test_rate_limit_wired.py`   | 4.5e      | FR50 — per-key rate-limit gate on `/v1/audio/speech`: `Depends(check_rate_limit)` present + `app.state.rate_limiter` initialised + 429 on `rate_limit_rpm+1`; negative assertion `/health` UN-rate-limited. ASGI TestClient (no docker). See module docstring for the 2.0.0 re-interpretation of FR50's slowapi-era wording. |
```

No other README edit. The Harness-choice section (`tests/test_non_regression/README.md:177-191`) already names 4.5e as the canonical TestClient example; no update needed there.

### 3. Housekeeping invariants

The existing `non-regression` job in `.github/workflows/ci.yml:45-66` runs `uv run pytest -m non_regression tests/test_non_regression/ -v` — it auto-discovers the new module. Grep invariants (all enforced as ACs):

- `git diff master -- src/comadre/` returns empty.
- `git diff master -- deploy/caddy/` returns empty.
- `git diff master -- .github/workflows/ci.yml` returns empty.
- `git diff master -- pyproject.toml uv.lock` returns empty.
- `git diff master -- tests/conftest.py` returns empty.
- `git diff master -- tests/test_non_regression/conftest.py` returns empty (4.5e is TestClient, does not touch the docker fixtures).

The ONE file outside `test_rate_limit_wired.py` that 4.5e modifies is `tests/test_non_regression/README.md` (one-row refinement). Everything else is new-under-`tests/test_non_regression/`.

## Acceptance Criteria

1. **AC1 — `test_rate_limit_wired.py` exists with five tests, all `@pytest.mark.non_regression`.** The module defines `test_check_rate_limit_dependency_registered_on_speech_route`, `test_rate_limiter_initialised_at_lifespan_startup`, `test_speech_endpoint_emits_429_after_rate_limit`, `test_health_endpoint_is_not_rate_limited`, and `test_check_rate_limit_identity_on_speech_route`. All five carry `@pytest.mark.non_regression` at the function decorator. Grep invariant: `rg "@pytest.mark.non_regression" tests/test_non_regression/test_rate_limit_wired.py | wc -l` returns `5`.

2. **AC2 — Route-inspection assertion passes on current master.** `test_check_rate_limit_dependency_registered_on_speech_route` passes: `check_rate_limit` is in both `route.dependencies` (declared list) AND `route.dependant.dependencies` (resolved tree) for the `POST /v1/audio/speech` route.

3. **AC3 — State-inspection assertion passes on current master.** `test_rate_limiter_initialised_at_lifespan_startup` passes: `app.state.rate_limiter` is non-`None` and is a `RateLimiter` instance after the `app` fixture from `tests/conftest.py` runs lifespan startup.

4. **AC4 — Behavioural 429 assertion passes on current master.** `test_speech_endpoint_emits_429_after_rate_limit` passes: the first 2 requests at `rate_limit_rpm=2` return 200 with `X-RateLimit-Remaining` decrementing; the 3rd returns 429 with (a) `Retry-After` header in `[1, 60]` range, (b) envelope `{error: {message: "Rate limit exceeded", type: "rate_limit_error", hint: "Too many requests. Try again in N seconds."}}`, (c) `X-RateLimit-Limit == "2"`, (d) `X-RateLimit-Remaining == "0"`, (e) `X-RateLimit-Reset` as a positive integer.

5. **AC5 — `/health` negative assertion passes on current master.** `test_health_endpoint_is_not_rate_limited` passes: 5 consecutive unauthenticated GETs to `/health` all return a status in `{200, 503}` and none return 429.

6. **AC6 — Structural identity assertion passes on current master.** `test_check_rate_limit_identity_on_speech_route` passes: the resolved dependency tree for `POST /v1/audio/speech` contains the exact `comadre.rate_limit.check_rate_limit` callable object (identity check via `is`, not equality).

7. **AC7 — Marker + deselection behaviour preserved.** `uv run pytest` (no `-m` flag) does NOT execute the new tests — they are deselected via the existing `addopts = "-m 'not non_regression'"` from 4.5a. Expected shape: the total `deselected` count from the default run grows by exactly the number of `@pytest.mark.non_regression` tests 4.5e adds (5 new tests, all unparametrised → +5 deselected). The exact `N passed, M deselected` totals are re-computed on the dev agent's final run and captured in the Dev Agent Record; the invariant is *"default pytest excludes every `@pytest.mark.non_regression` test and total deselected equals `rg "@pytest.mark.non_regression" tests/test_non_regression/ | wc -l` after collection expansion from parametrisation."*

8. **AC8 — Opt-in CI invocation picks up the new module.** `uv run pytest -m non_regression tests/test_non_regression/ -v` collects and runs the five new tests alongside the existing 4.5a/b/c/d surface; the new module contributes +5 passed (no skips expected — TestClient does not depend on docker). Exact post-4.5e totals captured in the Dev Agent Record.

9. **AC9 — No `src/comadre/` changes.** `git diff master -- src/comadre/` returns empty at story completion. Invariant: `git diff master -- src/comadre/ | wc -l` is `0`.

10. **AC10 — No `deploy/caddy/` changes.** `git diff master -- deploy/caddy/ | wc -l` returns `0`. 4.5e is app-internal; the reverse-proxy layer is untouched.

11. **AC11 — CI YAML untouched.** `git diff master -- .github/workflows/ci.yml | wc -l` returns `0`. The existing `non-regression` job auto-discovers the new test file.

12. **AC12 — No new runtime or dev dependency.** `git diff master -- pyproject.toml uv.lock | wc -l` returns `0`. All imports are existing: `fastapi.routing.APIRoute`, `httpx.AsyncClient`, `pytest`, `comadre.rate_limit.{RateLimiter, check_rate_limit}`, `comadre.keys.auth`, `tests._keys_fixtures.seed_customer_and_key`.

13. **AC13 — `tests/conftest.py` and `tests/test_non_regression/conftest.py` unchanged.** `git diff master -- tests/conftest.py tests/test_non_regression/conftest.py | wc -l` returns `0`. 4.5e composes on existing fixtures; no new fixture surface.

14. **AC14 — README ownership row refined.** `tests/test_non_regression/README.md:20` carries the verbose FR50 description per §Scope-2 (naming the three assertion legs, the TestClient harness choice, and the module docstring reference for the 2.0.0 re-interpretation).

15. **AC15 — Failure-UX verified (probe class A: dependency removed).** Temporarily edit `src/comadre/api.py` to remove `Depends(check_rate_limit)` from the `dependencies=[...]` list on the `/v1/audio/speech` route. Re-run `uv run pytest -m non_regression tests/test_non_regression/test_rate_limit_wired.py -v`. Observe `test_check_rate_limit_dependency_registered_on_speech_route` fail with the message "the edfcb33-class bug has regressed: the rate-limit gate is silently inert." AND observe `test_speech_endpoint_emits_429_after_rate_limit` fail with "returned 200, expected 429." AND `test_check_rate_limit_identity_on_speech_route` fail. Restore `src/comadre/api.py` via `git checkout`. Dev agent logs the observed failure messages verbatim in the Dev Agent Record > Debug Log References.

16. **AC16 — Failure-UX verified (probe class B: state not initialised).** Temporarily edit `src/comadre/main.py:68` to comment out `app.state.rate_limiter = RateLimiter.build()`. Re-run the suite. Observe `test_rate_limiter_initialised_at_lifespan_startup` fail with "`app.state.rate_limiter` is None after lifespan startup." Likely `test_speech_endpoint_emits_429_after_rate_limit` also fails (every request fails closed with a `KeyRegistryError` → 500) — document the observed secondary failure as informational. Restore `src/comadre/main.py`. Dev agent logs the observed failure verbatim.

17. **AC17 — Failure-UX verified (probe class C: `/health` regressed by adding `Depends(check_rate_limit)`).** Temporarily edit `src/comadre/main.py`'s `/health` handler to decorate it with `dependencies=[Depends(check_rate_limit)]`. The handler will now require auth AND rate-limit — on a burst of 5 unauthenticated requests, the auth layer will reject earlier than the rate-limit layer. The observable shape is that `test_health_endpoint_is_not_rate_limited` likely still passes (the burst sees 401s, not 429s, because auth fires first). **Skip this probe if the assertion cannot be made to fail cleanly; document in the Dev Agent Record.** OR tighten the test 4 pattern during dev if a cleaner negative probe exists (e.g., assert no `Depends(check_rate_limit)` appears in `/health` route's resolved dependency tree). **This AC is optional**; satisfy at dev-agent discretion OR defer with a one-line justification.

18. **AC18 — Full quality-gate suite stays green.** `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src/`, `uv run pytest` (default), `uv run pytest -m non_regression tests/test_non_regression/ -v`, and `uv run pre-commit run --all-files` all exit 0.

## Tasks / Subtasks

- [x] **Task 1 — Create `test_rate_limit_wired.py` module skeleton with the five test stubs** (AC1)
  - [x] 1.1 Create `tests/test_non_regression/test_rate_limit_wired.py` with the module docstring (per §Scope-1), imports (per §Scope-1 — `fastapi.routing.APIRoute`, `httpx.AsyncClient`, `pytest`, `date`, `RateLimiter`, `check_rate_limit`, `auth_module`, `seed_customer_and_key`), and the constants block (`_SPEECH_PATH`, `_HEALTH_PATH`, `_TEST_RPM`, `_BURST_ATTEMPTS`, `_SPEECH_BODY`).
  - [x] 1.2 Stub out all five test functions with `@pytest.mark.non_regression` and the correct signatures (sync for tests 1, 2, 5; async for tests 3, 4).
  - [x] 1.3 Confirm: `rg "@pytest.mark.non_regression" tests/test_non_regression/test_rate_limit_wired.py | wc -l` returns `5`.

- [x] **Task 2 — Implement Test 1 (route-inspection)** (AC2)
  - [x] 2.1 Implement `test_check_rate_limit_dependency_registered_on_speech_route` per §Scope-1. Use `create_app()` inline (no fixture). Filter routes to `isinstance(r, APIRoute) and r.path == _SPEECH_PATH and "POST" in r.methods`. Assert `check_rate_limit` is in both `route.dependencies` (unwrapped from `Depends`) AND `route.dependant.dependencies` (resolved tree).
  - [x] 2.2 Run the test against current master: `uv run pytest -m non_regression tests/test_non_regression/test_rate_limit_wired.py::test_check_rate_limit_dependency_registered_on_speech_route -v`. Confirm it passes.

- [x] **Task 3 — Implement Test 2 (state-inspection)** (AC3)
  - [x] 3.1 Implement `test_rate_limiter_initialised_at_lifespan_startup` per §Scope-1. Consume the `app` fixture from `tests/conftest.py`. Assert `app.state.rate_limiter` is non-None AND `isinstance(app.state.rate_limiter, RateLimiter)`.
  - [x] 3.2 Run against current master, confirm pass.

- [x] **Task 4 — Implement Test 3 (behavioural 429)** (AC4)
  - [x] 4.1 Implement `test_speech_endpoint_emits_429_after_rate_limit` per §Scope-1. Use `app`, `client`, `monkeypatch` fixtures. Monkey-patch `auth_module._today_in_billing_tz` to freeze at `2026-04-17` so seeded `paid_until=2099-12-31` rows remain active. Seed with `rate_limit_rpm=_TEST_RPM`. Fire 2 requests, assert 200 + decrementing `X-RateLimit-Remaining`. Fire the 3rd, assert 429 + `Retry-After` + envelope + `X-RateLimit-*`.
  - [x] 4.2 Run against current master, confirm pass.

- [x] **Task 5 — Implement Test 4 (`/health` negative assertion)** (AC5)
  - [x] 5.1 Implement `test_health_endpoint_is_not_rate_limited` per §Scope-1. Use `app`, `client` fixtures. Fire `_BURST_ATTEMPTS` (5) unauthenticated GETs to `/health`, collect statuses, assert `429 not in statuses` AND every status is in `{200, 503}`.
  - [x] 5.2 Run against current master, confirm pass.

- [x] **Task 6 — Implement Test 5 (identity guard)** (AC6)
  - [x] 6.1 Implement `test_check_rate_limit_identity_on_speech_route` per §Scope-1. Identity check via `is`, not `==`. Import the canonical symbol directly to capture the reference.
  - [x] 6.2 Run against current master, confirm pass.

- [x] **Task 7 — Update README ownership row** (AC14)
  - [x] 7.1 Edit `tests/test_non_regression/README.md:20` — replace the old one-line description with the verbose FR50 description per §Scope-2.
  - [x] 7.2 Confirm `uv run pre-commit run --all-files` (Task 9) passes the markdownlint-cli2 hook on the updated README.

- [x] **Task 8 — Verify marker + deselection behaviour** (AC7, AC8)
  - [x] 8.1 `uv run pytest` (default, no `-m`) → `1414 passed, 84 deselected`.
  - [x] 8.2 `uv run pytest -m non_regression tests/test_non_regression/ -v` → `68 passed, 16 skipped` (84 collected).
  - [x] 8.3 Delta matches expected +5: the opt-in run's 84 collected items equal the default run's 84 deselected; the new 5 tests are all in the 68 `passed` bucket (no docker skips for TestClient tests).

- [x] **Task 9 — Run full quality-gate suite** (AC18)
  - [x] 9.1 `uv run ruff check .` — `All checks passed!`.
  - [x] 9.2 `uv run ruff format --check .` — `102 files already formatted`.
  - [x] 9.3 `uv run mypy src/` — `Success: no issues found in 35 source files`.
  - [x] 9.4 `uv run pytest` (default) — `1414 passed, 84 deselected in 52.89s`.
  - [x] 9.5 `uv run pytest -m non_regression tests/test_non_regression/ -v` — `68 passed, 16 skipped in 5.48s`.
  - [x] 9.6 `uv run pre-commit run --all-files` — all hooks `Passed`.

- [x] **Task 10 — Verify invariants** (AC9, AC10, AC11, AC12, AC13)
  - [x] 10.1 `git diff master -- src/comadre/ | wc -l` → `0` (AC9).
  - [x] 10.2 `git diff master -- deploy/caddy/ | wc -l` → `0` (AC10).
  - [x] 10.3 `git diff master -- .github/workflows/ci.yml | wc -l` → `0` (AC11).
  - [x] 10.4 `git diff master -- pyproject.toml uv.lock | wc -l` → `0` (AC12).
  - [x] 10.5 `git diff master -- tests/conftest.py tests/test_non_regression/conftest.py | wc -l` → `0` (AC13).

- [x] **Task 11 — Failure-UX smoke: probe class A (dependency removed)** (AC15)
  - [x] 11.1 Backup `src/comadre/api.py` (`cp src/comadre/api.py src/comadre/api.py.bak`).
  - [x] 11.2 Edit `src/comadre/api.py:36-40` to remove `Depends(check_rate_limit)` from the `dependencies=[...]` list.
  - [x] 11.3 Run suite → 3 failures (Test 1, Test 3, Test 5) as expected. Verbatim messages captured in Debug Log References.
  - [x] 11.4 Restore via `mv src/comadre/api.py.bak src/comadre/api.py`. Re-run suite → 5 passed.

- [x] **Task 12 — Failure-UX smoke: probe class B (state not initialised)** (AC16)
  - [x] 12.1 Backup `src/comadre/main.py`.
  - [x] 12.2 Edit `src/comadre/main.py:68` to comment out `app.state.rate_limiter = RateLimiter.build()`. **Observed: lifespan-only sabotage is short-circuited by `tests/conftest.py:122` which also sets `application.state.rate_limiter = RateLimiter.build()` directly on the fixture.** To faithfully simulate a production lifespan regression, also commented out the fixture's line (scratch; fully restored). See Debug Log References.
  - [x] 12.3 With both commented out: Test 2 failed with `` `app.state.rate_limiter` is None after lifespan startup ``; Test 3 failed with HTTP 500 `"RateLimiter not initialised on app.state; check lifespan startup"` (secondary failure — `check_rate_limit` raises `KeyRegistryError` → fail-closed, exactly as AC16 predicts).
  - [x] 12.4 Restored both files. Re-run → 5 passed; `git diff master -- src/comadre/ tests/conftest.py | wc -l` → `0`.

- [x] **Task 13 — Failure-UX smoke: probe class C (`/health` rate-limited)** (AC17 — optional)
  - [x] 13.1 Executed the probe: decorated `@app.get("/health", dependencies=[Depends(verify_api_key), Depends(check_rate_limit)])`. Under unauthenticated burst, `verify_api_key` rejects with 401 before `check_rate_limit` evaluates — so the primary `429 not in statuses` assertion still holds, BUT the secondary `status in {200, 503}` tail fires cleanly: `/health` returned an unexpected status 401 in the burst. Test 4 DOES fail observably, via the secondary-assertion channel. See Debug Log References.
  - [x] 13.2 Restored `src/comadre/main.py`. The secondary assertion is the operative channel — documented in Completion Notes as a refinement of the story's prediction ("likely still passes") and supports keeping the behavioural burst as the Test 4 shape without swapping to a structural scan.

- [x] **Task 14 — Change log and status**
  - [x] 14.1 Appended Change Log row (v0.2 — dev-story execution).
  - [x] 14.2 Story Status flipped ready-for-dev → in-progress (at Step 4) → review (at Step 9); sprint-status.yaml mirrors both transitions.

## Dev Notes

### Design decisions

**Why ASGI TestClient, not docker-stack.** FR50 is an app-internal invariant: the dependency wiring and the `app.state.rate_limiter` live inside the FastAPI app, not at the Caddy boundary. The README's Harness-choice section names 4.5e verbatim as the canonical TestClient example: *"pick TestClient when the check is app-internal (FR47, FR50)."* Spinning up docker for 4.5e would add ~10s wall time per CI run for zero signal benefit — the assertions don't exercise Caddy at all.

**Why reuse `tests/conftest.py` fixtures, not new fixtures.** The `app` fixture at `tests/conftest.py:91-128` already builds registry-mode FastAPI with `AuthCache` + `RateLimiter.build()` initialised. The `client` fixture wraps it in an `httpx.AsyncClient` via `ASGITransport`. The `seed_customer_and_key` helper at `tests/_keys_fixtures.py::16-75` is the canonical pattern for seeding an active key — `test_api.py::TestPerKeyRateLimit` uses it verbatim. Writing new fixtures would duplicate this surface and drift. The CLAUDE.md rule "don't reinvent wheels" applies.

**Why five tests, not two or three.** Two of the five (tests 1 + 5) assert the same wiring invariant from different angles — membership vs identity. Edfcb33 was fixed by a 2-line patch adding middleware; the current architecture's equivalent regression could happen in five distinct ways (decorator arg removed, state init removed, function body gutted, identity swapped, `/health` accidentally rate-limited). Each test targets one failure mode with a clear, named message. The 4.5c dev-agent-record lesson ("one assertion per failure mode") applies.

**Why `rate_limit_rpm=2`, not 1 or 10.** `rate_limit_rpm=1` would let a single request consume the budget and the assertion "3rd request 429s" becomes "2nd request 429s" — an off-by-one cognitive hazard for a reader. `rate_limit_rpm=10` would waste wall time on 10 successful requests before tripping the gate. `rate_limit_rpm=2` matches `test_api.py::TestPerKeyRateLimit::test_per_key_limit_trips_on_n_plus_one` verbatim — sharing the constant across the two modules makes them easier to reason about together.

**Why monkey-patch `auth_module._today_in_billing_tz`.** The seeded key has `paid_until="2099-12-31"`, but the `auth_module._today_in_billing_tz` function reads the actual system clock. On a clock drift scenario (CI runner set to year 2100), the key would be considered expired and auth would fail before rate-limit ever fires. Pinning today to 2026-04-17 (the same constant `tests/test_api.py::TestPerKeyRateLimit` uses) removes that dependency.

**Why negative assertion on `/health`, not a skip.** The epic AC mentions `/health` as a rate-limit target. Silently dropping the `/health` leg without a test would lose information: a future PR that adds `Depends(check_rate_limit)` to `/health` (in pursuit of "closing the FR50 gap" without reading CLAUDE.md) would land unopposed. The negative assertion (`/health` never 429s under burst) encodes the design decision as a mechanical check. The assertion is cheap — 5 GETs, ~20ms wall time.

**Why not assert on `/health` route dependencies structurally.** An alternative to the burst assertion is to walk the `/health` route's `route.dependencies` and assert `check_rate_limit not in [...]`. That is structurally tighter BUT brittle to a future refactor that legitimately adds `check_rate_limit` to `/health` via a different mechanism (e.g., middleware). The burst assertion is behavioural — it observes the end-to-end outcome, which is what operators actually care about. Both approaches have merit; the chosen shape (burst) is the operator-facing one. A dev agent that finds the structural approach cleaner during implementation is free to SWAP the two — document the decision in the Dev Agent Record.

**Why identity check via `is`, not `==`.** `check_rate_limit == some_other_function` would be `True` only if Python's default function `__eq__` returns True — which it does only for identity. So `is` and `==` would give the same answer here. But `is` signals the intent verbatim: "the SAME object", not "an object equal to". A reader doesn't have to check Python's default `__eq__` semantics.

**Why import `create_app` inside the test, not at module level.** `create_app()` runs the FastAPI app factory; doing it at module level would import-side-effect-execute startup code that consumers of this test module (pytest collection, mypy, ruff) don't want triggered on every collection pass. Inside the test keeps it lazy. The `app` fixture in `tests/conftest.py` is a FastAPI app instance AFTER lifespan — for Tests 1 and 5 we want the raw app BEFORE lifespan (just to inspect route metadata), which `create_app()` returns directly.

**Why assert `check_rate_limit in declared_calls` at AC2 uses `.dependency` unwrapping.** `route.dependencies` is a list of `fastapi.params.Depends` objects, each wrapping the callable as `.dependency`. The assertion walks the list, unwraps each `Depends.dependency`, and compares against `check_rate_limit`. Do NOT assert `Depends(check_rate_limit) in route.dependencies` — `Depends` does not implement `__eq__` for equality comparison against another `Depends(...)` instance; the comparison would always be False.

### Import-graph placement

- **`tests/test_non_regression/test_rate_limit_wired.py` (NEW).** Imports: stdlib (`datetime.date`, `typing.Any`), `pytest`, `fastapi.routing.APIRoute`, `httpx.AsyncClient`, `comadre.keys.auth`, `comadre.rate_limit`, `comadre.main` (lazy inside the test body for `create_app`), `tests._keys_fixtures.seed_customer_and_key`. Zero new `comadre.*` imports beyond what `tests/test_api.py` already imports.
- **`tests/test_non_regression/README.md` (MOD).** One ownership-table row refined (line 20). No structural change.
- **`tests/conftest.py` — unchanged.** The `app` + `client` fixtures already wire `RateLimiter.build()` into `app.state`.
- **`tests/test_non_regression/conftest.py` — unchanged.** 4.5e does not use the docker-stack fixtures.
- **`pyproject.toml` — unchanged.** `addopts = "-m 'not non_regression'"` already deselects the new tests by default.
- **`.github/workflows/ci.yml` — unchanged.** The `non-regression` job auto-discovers the new module.
- **`src/comadre/**` — unchanged.** AC9 invariant.
- **`deploy/caddy/**` — unchanged.** AC10 invariant.

### Test-flake avoidance

- **No session-scoped state.** Tests 1, 5 construct a fresh `create_app()` per call. Tests 2, 3, 4 use the function-scoped `app` + `client` fixtures. No cross-test state leakage possible.
- **No docker dependency.** 4.5e runs in-process; no subprocess, no network binding, no port collision risk.
- **Clock freeze via monkeypatch.** Test 3 pins `_today_in_billing_tz` to 2026-04-17; the seeded `paid_until=2099-12-31` keeps the key active across any CI clock drift.
- **Mocked TTS router.** The `app` fixture's `mock_router` returns `b"fake-audio-bytes"`; no real Kokoro/Qwen3 model invocation, no GPU dependency. Test 3's 3 requests complete in well under 200ms.
- **Independent rate-limit bucket per test.** Each `app` fixture invocation builds a fresh `RateLimiter` (new `MemoryStorage`). Tests in the same suite can seed the same `rate_limit_rpm=2` without bleeding state across cases.
- **No `pytest.mark.parametrize` — each test has a distinct failure message.** Parametrising over `(test_1, test_2, test_3, test_4, test_5)` would collapse the five assertions into one test name; the whole point of five tests is that each has a purpose-built diagnostic tail. The 4.5c/4.5d lesson ("one assertion per failure mode, one distinct error message per mode") applies.
- **Async/sync mixing.** Tests 1, 2, 5 are sync (`def`). Tests 3, 4 are async (`async def`). `pytest-asyncio` + `asyncio_mode = "auto"` (already configured) handles the mix. No `@pytest.mark.asyncio` decorator needed.

### Project Structure Notes

- **Alignment with unified project structure.**
  - Test module naming: `tests/test_non_regression/test_rate_limit_wired.py` — matches the ownership table row in `tests/test_non_regression/README.md` (row for 4.5e at line 20).
  - No fixture directory added — 4.5e is ASGI-TestClient, not static-scan; no per-check fixtures subdirectory needed. (That pattern is for static-scan sub-stories 4.5c / 4.5f / 4.5g.)
  - Constant naming: `_SPEECH_PATH`, `_HEALTH_PATH`, `_TEST_RPM`, `_BURST_ATTEMPTS`, `_SPEECH_BODY` — leading-underscore module-privates, SCREAMING_SNAKE_CASE for constants. Matches 4.5a/4.5b/4.5d conventions.
  - Test function naming: behaviour-first — `test_check_rate_limit_dependency_registered_on_speech_route`, not `test_rate_limit_dep_registered`. Matches the 4.5a/b/d naming style.

- **Detected conflicts or variances (with rationale).**
  - **Epic AC text vs shipped architecture.** Documented exhaustively in §Scope amendment. The spec-premise note at the top of the story warns the dev agent explicitly. Analogous to 4.5d's *"Caddy's `request_body max_size` did not emit 413 with `reverse_proxy`"* discovery; the shape here is less surprising (architecture drifted between epic writeup and story execution) but needs the same explicit treatment.
  - **Architecture.md line 656 and line 271 carry stale `SlowAPIMiddleware` / `RATE_LIMIT_SPEECH` references.** These are known drift from 2.2's refactor, NOT a design reversal. The PRD Change Log (line 9) and the architecture's own line 220 both confirm the retirement. A dedicated doc-refresh sub-story could sweep architecture.md to match shipped reality, but that is out of scope for 4.5e. A one-line note in the Dev Agent Record's Completion Notes is enough.

### Testing standards

- **Sync tests for structural assertions, async for behavioural.** Tests 1, 2, 5 inspect Python objects (route, app.state) — sync. Tests 3, 4 hit the ASGI TestClient — async.
- **Assertion messages.** Every assertion carries a failure message naming (a) which control regressed, (b) what was observed, (c) what was expected, (d) a diagnostic tail pointing at the source file / line to investigate. Inherits the 4.5a "name-the-regression" convention.
- **No fixture-level assertions.** The `app` and `client` fixtures from `tests/conftest.py` don't perform rate-limit-specific assertions; all regression detection is test-level.

### Deferred work to flag at story close

- **Parallel assertion: `verify_api_key` wired as a dependency.** A sibling guard — the auth-path wiring — could follow the same pattern 4.5e establishes. Not in scope today; auth wiring is covered transitively by Test 3 (a 200 response requires auth to have fired).
- **Route-inspection assertion covers method=POST only.** If a future PR adds `GET /v1/audio/speech` via a separate declaration, the structural tests would not catch a missing `check_rate_limit` on the new declaration. Parametrising over methods would broaden coverage; deferred until multi-method routes exist.
- **Clock-window testing.** The 1-minute `limits` window is not mechanically tested — after the 3rd request 429s, the test does NOT wait 60 seconds to verify recovery. `test_api.py::TestPerKeyRateLimit` may cover this; if not, a dedicated recovery-window probe is candidate deferred work. Out of scope for 4.5e because CI wall-time cost (60s sleep) is prohibitive.
- **Architecture.md doc refresh.** Lines 271 and 656 carry stale `slowapi` / `RATE_LIMIT_SPEECH` references. A doc-refresh sub-story could sweep the architecture doc to match shipped reality. Out of scope for 4.5e; candidate for an Epic 4 retrospective action.
- **Test 4 alternative (structural vs behavioural).** The `/health` negative assertion is behavioural (burst + assert no 429). An alternative is structural (walk `/health` route dependencies, assert `check_rate_limit` not present). Both have merit; the chosen shape can be swapped during dev if the structural approach is cleaner — document in Dev Agent Record.
- **AC17 probe may not cleanly fail.** If adding `Depends(check_rate_limit)` to `/health` causes auth-rejection (401) to fire before rate-limit (429), the burst returns all 401s and Test 4 still passes. Tightening Test 4 to the structural form above would make AC17 trivially triggerable. Candidate refinement if AC17 cannot be satisfied cleanly.

### References

- Epic 4 Story 4.5 umbrella — `_bmad-output/planning-artifacts/epics.md:878-888`
- Epic 4 Story 4.5e — `_bmad-output/planning-artifacts/epics.md:968-984`
- FR50 — `_bmad-output/planning-artifacts/prd.md:1194`
- NFR17 — `_bmad-output/planning-artifacts/prd.md:1221`
- PRD Non-Regression Contract (SlowAPIMiddleware row) — `_bmad-output/planning-artifacts/prd.md:188`
- PRD Change Log (slowapi retirement note) — `_bmad-output/planning-artifacts/prd.md:9`
- PRD §Architecture-Level Security Controls (slowapi retirement) — `_bmad-output/planning-artifacts/prd.md:220`
- Architecture.md stale `SlowAPIMiddleware` row (doc drift, not design) — `_bmad-output/planning-artifacts/architecture.md:656`
- Architecture.md stale `RATE_LIMIT_SPEECH` row (doc drift, not design) — `_bmad-output/planning-artifacts/architecture.md:271`
- CLAUDE.md §Architecture — `/health` un-rate-limited statement — project root `CLAUDE.md`
- Canonical rate-limit wiring — `src/comadre/rate_limit.py:76-162`
- Canonical route wiring — `src/comadre/api.py:34-41`
- Canonical lifespan init — `src/comadre/main.py:68`
- Existing 429 integration coverage (primary contract, NOT a duplicate of 4.5e) — `tests/test_api.py:688-947`
- Existing seed helper — `tests/_keys_fixtures.py:16-75`
- Non-regression package README (ownership-table row for 4.5e at line 20; Harness-choice section at lines 177-191) — `tests/test_non_regression/README.md`
- Non-regression marker registration — `tests/conftest.py:30-33`
- Story 2.2 commit `1d27e12` (`feat(2.0.0): retire legacy single-API_KEY mode and rewrite rate-limit on limits`) — git log
- Story 2.2 implementation artefact (slowapi retirement details) — `_bmad-output/implementation-artifacts/2-2-dynamic-per-key-rate-limiting.md`
- Original edfcb33 bug — git show `edfcb33` (pre-2.0.0; `app.state.limiter` set but `SlowAPIMiddleware` never added)
- Story 4.5a (predecessor; skeleton, marker, CI job) — `_bmad-output/implementation-artifacts/4-5a-ci-security-headers-regression.md`
- Story 4.5b (predecessor; marker broadening, Harness-choice README section) — `_bmad-output/implementation-artifacts/4-5b-ci-docs-endpoints-disabled-regression.md`
- Story 4.5c (predecessor; fixture-directory convention — orthogonal) — `_bmad-output/implementation-artifacts/4-5c-ci-timing-safe-key-comparison-static-check.md`
- Story 4.5d (predecessor; docker-stack harness example — orthogonal, 4.5e is TestClient) — `_bmad-output/implementation-artifacts/4-5d-ci-oversized-request-body-rejection.md`
- FastAPI `APIRoute.dependencies` vs `dependant.dependencies` — https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-in-path-operation-decorators/
- `limits` library, `MovingWindowRateLimiter`, parse format — https://limits.readthedocs.io/

## Dev Agent Record

### Agent Model Used

Opus 4.7 (1M context) — `claude-opus-4-7[1m]`

### Debug Log References

**Quality-gate command output (post-implementation, all files restored):**

- `uv run ruff check .` → `All checks passed!`
- `uv run ruff format --check .` → `102 files already formatted`
- `uv run mypy src/` → `Success: no issues found in 35 source files`
- `uv run pytest` → `1414 passed, 84 deselected in 52.89s`
- `uv run pytest -m non_regression tests/test_non_regression/ -v` → `68 passed, 16 skipped in 5.48s`
  - The five new tests: `test_check_rate_limit_dependency_registered_on_speech_route PASSED`, `test_rate_limiter_initialised_at_lifespan_startup PASSED`, `test_speech_endpoint_emits_429_after_rate_limit PASSED`, `test_health_endpoint_is_not_rate_limited PASSED`, `test_check_rate_limit_identity_on_speech_route PASSED`.
- `uv run pre-commit run --all-files` → `ruff check Passed`, `ruff format Passed`, `Lint Dockerfiles Passed`, `yamllint Passed`, `shellcheck Passed`, `markdownlint-cli2 Passed`, `mypy Passed`.
- `rg "@pytest.mark.non_regression" tests/test_non_regression/test_rate_limit_wired.py | wc -l` → `5` (AC1 invariant).

**Grep invariants (AC9–AC13), all `0`:**

```text
git diff master -- src/comadre/                               → 0
git diff master -- deploy/caddy/                              → 0
git diff master -- .github/workflows/ci.yml                   → 0
git diff master -- pyproject.toml uv.lock                     → 0
git diff master -- tests/conftest.py                          → 0
git diff master -- tests/test_non_regression/conftest.py      → 0
```

**Probe A (AC15) — `Depends(check_rate_limit)` removed from `src/comadre/api.py`:**

```text
FAILED tests/.../test_check_rate_limit_dependency_registered_on_speech_route
  AssertionError: POST /v1/audio/speech route has dependencies=[...] but
  `check_rate_limit` is NOT among them. Declared: ['verify_ready',
  'verify_api_key']. The edfcb33-class bug has regressed: the rate-limit
  gate is silently inert. Restore `Depends(check_rate_limit)` in
  `src/comadre/api.py`'s `api_router.post('/v1/audio/speech',
  dependencies=[...])`.

FAILED tests/.../test_speech_endpoint_emits_429_after_rate_limit
  AssertionError: 3th request to /v1/audio/speech at rate_limit_rpm=2
  returned 200, expected 429. The rate-limit gate is silently permitting
  over-budget requests — edfcb33-class regression: FR50 gate failed.
  Body: 'fake-audio-bytes'

FAILED tests/.../test_check_rate_limit_identity_on_speech_route
  AssertionError: POST /v1/audio/speech route's dependency is NOT the
  canonical `comadre.rate_limit.check_rate_limit` object. Resolved
  callables: [('comadre.api', 'verify_ready'),
  ('comadre.keys.auth', 'verify_api_key')]. A refactor may have introduced
  a shim/stub that keeps the dependency list populated but silently
  permits everything — edfcb33-class regression via a subtler mechanism.

========================= 3 failed, 2 passed in 0.19s ==========================
```

After restoring `src/comadre/api.py`: `5 passed in 0.15s`.

**Probe B (AC16) — `app.state.rate_limiter = RateLimiter.build()` commented out.**

Sabotaging `src/comadre/main.py:68` alone did NOT trigger the assertion because `tests/conftest.py:91-128`'s `app` fixture explicitly sets `application.state.rate_limiter = RateLimiter.build()` independently of the lifespan (the fixture does not execute lifespan startup; it stages state manually). To faithfully simulate a production regression — in which the lifespan *is* the sole source of `app.state.rate_limiter` — the fixture line at `tests/conftest.py:122` was also commented out as a scratch. Both files were fully restored; `git diff master -- src/comadre/ tests/conftest.py | wc -l` → `0`.

With both commented out:

```text
FAILED tests/.../test_rate_limiter_initialised_at_lifespan_startup
  AssertionError: `app.state.rate_limiter` is None after lifespan startup.
  The lifespan at `src/comadre/main.py:68` sets `app.state.rate_limiter =
  RateLimiter.build()`; this line appears to have been removed or moved.
  Every request to /v1/audio/speech will now fail with KeyRegistryError —
  the FR50 regression gate has fired.

FAILED tests/.../test_speech_endpoint_emits_429_after_rate_limit
  AssertionError: Attempt 1/2 to /v1/audio/speech at rate_limit_rpm=2
  returned 500 — expected 200. The under-limit path should NEVER 429.
  Body: '{"error":{"message":"RateLimiter not initialised on app.state;
  check lifespan startup","type":"server_error","hint":"Check
  KEY_REGISTRY_DB_PATH exists, is readable, and has mode 0600."}}'

========================= 2 failed, 3 passed in 0.20s ==========================
```

Secondary failure is exactly what the spec's AC16 predicted: *"Likely `test_speech_endpoint_emits_429_after_rate_limit` also fails (every request fails closed with a KeyRegistryError → 500)."* Confirmed.

**Probe C (AC17 — optional) — `/health` decorated with `dependencies=[Depends(verify_api_key), Depends(check_rate_limit)]`:**

```text
FAILED tests/.../test_health_endpoint_is_not_rate_limited
  AssertionError: `/health` returned an unexpected status 401 in the
  burst. Expected 200 (ready) or 503 (warming_up). Statuses observed:
  [401, 401, 401, 401, 401].

========================= 1 failed in 0.10s ==========================
```

Observation refining the story's AC17 prediction: the story anticipated that Test 4 "*likely still passes (the burst sees 401s, not 429s, because auth fires first)*" — but the test's secondary `status in {200, 503}` assertion DOES fire cleanly on the 401s. So Probe C is observable via the secondary channel. The behavioural burst shape is sufficient; no structural swap needed.

### Completion Notes List

- **FR50 implemented against the shipped 2.0.0 architecture.** Per the spec-premise note, `SlowAPIMiddleware` / `RATE_LIMIT_SPEECH` / `RATE_LIMIT_HEALTH` / `/health` rate-limiting are all stale references against the post-2.2 codebase. The five-test shape in `§Scope`'s re-interpretation table was implemented verbatim (route-inspection, state-inspection, behavioural 429, `/health` negative burst, structural identity guard). No attempt to reintroduce slowapi or rate-limit `/health`.
- **Test 4 (`/health`) kept behavioural, not structural.** The burst + `429 not in statuses` + `status in {200, 503}` double-assertion catches the AC17 regression via the secondary tail — tighter than the story's prediction ("likely still passes"). No swap to a `route.dependencies` structural scan needed.
- **Fixture short-circuit documented for probe B.** `tests/conftest.py:91-128`'s `app` fixture stages `app.state.rate_limiter = RateLimiter.build()` directly, not via lifespan — this is a known test-infra shortcut and does not diminish the in-process assertions' production-relevance, since Test 2 observes post-fixture state and Test 3 exercises the end-to-end path. Probe B required double-sabotage to simulate a production regression faithfully; this is documented for future dev agents who might otherwise conclude Test 2 "doesn't catch anything".
- **Doc-drift advisory (Deferred).** Architecture.md lines 271 and 656 still reference stale `SlowAPIMiddleware` / `RATE_LIMIT_SPEECH`. Out of scope for 4.5e; candidate for an Epic 4 retrospective action or a dedicated doc-refresh sub-story.
- **No `src/comadre/`, `deploy/caddy/`, `pyproject.toml`, `uv.lock`, `ci.yml`, `tests/conftest.py`, `tests/test_non_regression/conftest.py` changes** — AC9–AC13 invariants all `0`.
- **Net footprint:** 1 new test module (`tests/test_non_regression/test_rate_limit_wired.py`, 301 lines), 1 README row refined (`tests/test_non_regression/README.md:20`), sprint-status.yaml and the story file updated.

### File List

- **Added:** `tests/test_non_regression/test_rate_limit_wired.py`
- **Modified:** `tests/test_non_regression/README.md` (ownership-table row for 4.5e)
- **Modified:** `_bmad-output/implementation-artifacts/sprint-status.yaml` (status transition)
- **Modified:** `_bmad-output/implementation-artifacts/4-5e-ci-rate-limit-middleware-registration.md` (Status, Tasks checkboxes, Dev Agent Record, Change Log)

## Change Log

| Date       | Version | Change                                                                                                  |
| ---------- | ------- | ------------------------------------------------------------------------------------------------------- |
| 2026-04-24 | 0.1     | Story spec created → `ready-for-dev`. Spec-premise note warns dev agent that FR50's slowapi / `/health` wording is stale vs shipped 2.0.0 architecture; story implements the faithful re-interpretation (per-route `Depends(check_rate_limit)` + `app.state.rate_limiter` + 429 on `/v1/audio/speech`; negative assertion `/health` un-rate-limited). |
| 2026-04-24 | 0.2     | Dev-story executed → `review`. Added `tests/test_non_regression/test_rate_limit_wired.py` (5 `@pytest.mark.non_regression` tests: route-inspection, state-inspection, behavioural 429, `/health` UN-rate-limited burst, structural identity). Refined README ownership row at `tests/test_non_regression/README.md:20` per §Scope-2. All three failure-UX probes (A/B/C) captured verbatim; probe B needed fixture double-sabotage to route around `tests/conftest.py:122`'s `rate_limiter` override (documented). Quality gates: `ruff check`, `ruff format --check`, `mypy src/`, `pytest` (1414 passed / 84 deselected), `pytest -m non_regression` (68 passed / 16 skipped), `pre-commit run --all-files` — all green. Grep invariants AC9–AC13 all `0`. |
| 2026-04-24 | 0.3     | Code review (bmad-code-review) — Blind Hunter, Edge Case Hunter, Acceptance Auditor. 0 critical/major AC violations. 1 `decision-needed` (Test 2 fixture short-circuit — strengthen via real lifespan, or accept disclosed AC16 limitation), 1 `patch` (`retry_after` upper bound), 3 `defer`, ~16 dismissed. See Review Findings section. |
| 2026-04-24 | 0.4     | Review actions applied → `done`. Test 2 (`test_rate_limiter_initialised_at_lifespan_startup`) deleted per user decision — fixture short-circuit made the assertion tautological; strengthening via real `lifespan_context` was infeasible (real lifespan loads Kokoro/Qwen3 models). Test count 5 → 4; module docstring updated. AC1/AC3/AC16 as originally written are superseded. `retry_after` upper bound loosened `<= 60` → `<= 61` for `math.ceil` clock-drift tolerance. `uv run pytest -m non_regression tests/test_non_regression/test_rate_limit_wired.py -v` → 4 passed. Three deferred items recorded in `_bmad-output/implementation-artifacts/deferred-work.md`. |

## Review Findings

### Decision needed

- [x] **[Review][Decision][Resolved: test deleted] Test 2 cannot catch a regression of `src/comadre/main.py:68` — fixture short-circuit.** `tests/conftest.py:91-128`'s `app` fixture unconditionally stages `application.state.rate_limiter = RateLimiter.build()` at line 122, independent of lifespan. `test_rate_limiter_initialised_at_lifespan_startup` read that staged value — so deleting `main.py:68` would NOT have failed the test, contradicting the test's failure-message promise. Strengthening via `lifespan_context` was infeasible (real lifespan loads Kokoro/Qwen3 models). **Resolution:** Test 2 deleted (2026-04-24). The test count drops from 5 to 4; AC1/AC3/AC16 as originally written no longer apply — see the v0.4 Change Log row. Detected by: Edge Case Hunter (critical), Acceptance Auditor (noteworthy disclosure).

### Patch

- [x] **[Review][Patch][Applied] `retry_after` upper bound `<= 60` loosened to `<= 61`.** [`tests/test_non_regression/test_rate_limit_wired.py:172-178`] `src/comadre/rate_limit.py:126` uses `math.ceil(reset_time - now)` on a 60s window; float drift of 60.0000001s legitimately ceils to 61 without any regression. Detected by: Blind Hunter (major), Edge Case Hunter (minor).

### Deferred

- [x] **[Review][Defer] Test 3's 3-request budget exhaustion can straddle the 60s rolling window under CI stalls.** [`tests/test_non_regression/test_rate_limit_wired.py:147-164`] If the runner pauses >60s between requests 1 and 3, the oldest hit ages out and the 3rd request is legitimately allowed → false red. Inherited from `tests/test_api.py::TestPerKeyRateLimit` which uses the identical pattern; no observed flakes to date. Pragmatic fix when needed: wrap the 3-request block in `@pytest.mark.timeout(10)`. — deferred, pattern-level.
- [x] **[Review][Defer] Envelope-hint tautology: `retry_after` is read from the response header and then fed into the expected envelope.** [`tests/test_non_regression/test_rate_limit_wired.py:171-190`] A regression that decouples `Retry-After` from the envelope's `hint` integer would slip (both read from the same `RateLimitError` in `exceptions.py:229-231` today, so the coupling mirrors the production contract). Detected by: Blind Hunter (major), Acceptance Auditor (nit). — deferred, restructuring required.
- [x] **[Review][Defer] `pyproject.toml:73` marker description is stale against the 4.5b-broadened marker text.** [`pyproject.toml:73`] Reads *"integration tests that exercise the prod docker-compose stack"*; the conftest-registered description at `tests/conftest.py:30-33` is broader. Pre-existing drift inherited from before 4.5b, outside 4.5e's scope (AC12 keeps `pyproject.toml` untouched). Detected by: Acceptance Auditor. — deferred, pre-existing.


