# Story 4.5b: CI — Docs Endpoints Disabled Regression

Status: done

> **Scope note — FR47, NFR17.** Second of the seven CI non-regression sub-stories (4.5a–4.5g). Inherits the skeleton 4.5a landed: the `tests/test_non_regression/` package, the `non_regression` pytest marker, and the existing `non-regression` CI job in `.github/workflows/ci.yml`. 4.5b asserts the FR47 contract — `/docs`, `/redoc`, and `/openapi.json` return HTTP 404 with the project's standard `{error: {message, type, hint}}` envelope and carry no OpenAPI / Swagger / ReDoc content in the body. Delivers two artefacts: (1) a new `_not_found_handler` in `src/comadre/main.py` that converts FastAPI's default `{"detail": "Not Found"}` to the project envelope (closes a pre-existing gap surfaced by this story's AC review); (2) `tests/test_non_regression/test_docs_disabled.py` asserting the end-to-end contract via FastAPI's ASGI TestClient over `create_app()`. Subsumes and deletes the now-redundant `tests/test_api.py::TestDocsDisabled` class.

## Story

As a contributor,
I want every pull request against master to prove that `/docs`, `/redoc`, and `/openapi.json` return HTTP 404 with the project's standard error envelope and with zero OpenAPI content leaking into the response body,
so that a well-meaning `FastAPI(...)` edit that re-enables `docs_url`, `redoc_url`, or `openapi_url` — or a routing mistake that exposes a generated OpenAPI spec — cannot land on master without the PR build turning red and naming the exact endpoint that regressed.

**Covers FRs:** FR47 (CI can verify that `/docs`, `/redoc`, and `/openapi.json` return 404 in production-configured deployments).
**NFRs:** NFR17 (all Non-Regression Contract controls remain satisfied on every PR; CI regression coverage mandatory for each control row).
**UX-DRs:** Contributor-facing CI UX — the failure message carries the endpoint path, the observed status, and whichever assertion broke (status / envelope shape / content leak), on one line, per 4.5a's inherited convention.
**Epic:** 4 — Security Hardening, LGPD & Operational Safety. Sixth story in Epic 4 (4.1 → 4.2 → 4.3 → 4.4 → 4.5a → **4.5b** → 4.5c–g → 4.6). Second of the seven-sub-story CI non-regression cluster; appends one test module and one source-code handler — zero CI YAML changes, per the 4.5a extension contract.

## Builds on

- **Story 4.5a — CI non-regression skeleton (`done`).** 4.5a established the `tests/test_non_regression/` package, the `non_regression` pytest marker (`tests/conftest.py:30-33`), the `addopts = "-m 'not non_regression'"` default-exclusion in `pyproject.toml`, and the `non-regression` CI job in `.github/workflows/ci.yml` that runs `uv run pytest -m non_regression tests/test_non_regression/ -v`. 4.5a's extension contract (`tests/test_non_regression/README.md:144-169`) is the blueprint this story follows: add exactly one `test_<check_name>.py`, import fixtures or build lightweight ones, mark every test `@pytest.mark.non_regression`, do NOT touch CI YAML.
- **Existing `create_app()` contract — `src/comadre/main.py:277-287`.** The `FastAPI(...)` call already sets `docs_url=None, redoc_url=None, openapi_url=None`. 4.5b's test asserts the **observable consequence** of that setting (all three paths 404) rather than the setting itself, so the check survives any refactor that moves the disable to a different mechanism (e.g., middleware, sub-app mount) as long as the endpoints stay unreachable.
- **Existing `_method_not_allowed_handler` — `src/comadre/main.py:249-274`.** The symmetric 405-handler that converts FastAPI's default `{"detail": "Method Not Allowed"}` to `{"error": {"message", "type", "hint"}}`. 4.5b's new `_not_found_handler` follows this handler's shape exactly (same function signature, same `JSONResponse` return, same `error_type` naming convention — `"not_found_error"` matching `VoiceNotFoundError`'s `error_type` at `src/comadre/exceptions.py:43`).
- **Existing `ComadreError` envelope — `src/comadre/exceptions.py:223-245`.** The canonical envelope shape `{"error": {"message", "type", "hint"}}` that every error path in the codebase must emit. `VoiceNotFoundError` (line 36) already carries `status_code=404, error_type="not_found_error"`. The new 404 handler reuses `error_type="not_found_error"` for shape consistency — an unknown-path 404 and a voice-not-found 404 share the same `type` string because both mean "resource not found," distinguished by `message` and `hint`.
- **Pre-existing `tests/test_api.py::TestDocsDisabled` (lines 341-354).** Three weak assertions (`status_code == 404` only). 4.5b **subsumes and deletes** this class because the non-regression version is strictly stronger (status + envelope shape + content leak) and leaving the weaker duplicates invites drift. The deletion is part of this story's file list.
- **FastAPI ASGI TestClient pattern — `tests/conftest.py:129-136`.** The existing `client` fixture wraps `create_app()` in an `httpx.AsyncClient` over `ASGITransport`. 4.5b builds a dedicated minimal variant (no seeded customer, no rate limiter, no `auth_headers` setup) in the non-regression module because the `/docs` surface doesn't need any of that scaffolding — just a bare `create_app()` wired to a TestClient.
- **PRD Non-Regression Contract — `_bmad-output/planning-artifacts/prd.md:644`.** The canonical row: *Swagger UI / ReDoc / OpenAPI spec disabled — `docs_url=None, redoc_url=None, openapi_url=None` in `create_app()` — Test that `/docs`, `/redoc`, `/openapi.json` return 404*. 4.5b owns this row; no other sub-story revisits it.
- **Architecture §Continuity with Existing Hardening — `_bmad-output/planning-artifacts/architecture.md:188`.** Names this control in the canonical non-regression list ("`disabled docs endpoints`"). 4.5b closes the coverage gap for this line.
- **CLAUDE.md Non-Obvious Gotcha on the uniform error envelope.** "No raw `HTTPException` (use `ComadreError` hierarchy)" — 4.5f will enforce this statically over `src/`. 4.5b's 404 handler aligns with the spirit: even FastAPI's own framework-level `HTTPException(404)` (raised internally when no route matches) gets translated to the project envelope by the new handler, so `{"detail": ...}` shapes never reach clients.

## Unblocks

- **Stories 4.5c through 4.5g.** This story confirms the 4.5a extension contract works in practice: adding a new `test_<check>.py` file under `tests/test_non_regression/`, marking it `non_regression`, with no CI YAML edit required. The only novelty 4.5b introduces is a non-docker test inside the non-regression package — broadening the marker semantics from "always docker-based" to "CI non-regression surface; docker-required fixtures opt in on their own." That precedent is what 4.5c (static scan, no docker), 4.5f (static scan, no docker), and 4.5g (bandit, no docker) also need.
- **Uniform 404 envelope across the API surface.** A PR that later adds a new route whose 404 path bypasses ComadreError (e.g., a raw `HTTPException(404, detail="...")` in a handler, caught by Starlette) gets the consistent envelope automatically via the 404 handler — no per-route cleanup required. Deferred-work notes keep this benefit conservative (see §Deferred-work).
- **Epic 4 FR47 coverage.** This was the last PRD Non-Regression Contract row with **only** a manual verification path. After 4.5b lands, FR47 is mechanically enforced on every PR.

## Depends on

- **Story 4.5a is `done`** (sprint-status.yaml confirms, checked 2026-04-23). Hard dependency on the non-regression package skeleton and the CI job wiring. Without 4.5a's skeleton, 4.5b has nowhere to land.
- **No new runtime dependency.** `FastAPI` already ships `TestClient` via `httpx`; `httpx` is already a project dep (used in `tests/conftest.py:15`).
- **No new dev dependency.** `pytest` + `pytest-asyncio` (already configured for the existing `client` fixture shape) are sufficient.
- **No schema change. No auth-path change. No new CLI verb. No ansible change. No CI YAML change.** The story touches exactly three source trees: `src/comadre/main.py` (+handler +register), `tests/test_api.py` (-TestDocsDisabled class), `tests/test_non_regression/test_docs_disabled.py` (+new file). Plus README and gotcha-table housekeeping (see §Scope).

## Scope

Two workstreams, in order:

1. **Ship the project-envelope 404 handler in `src/comadre/main.py`.** Closes the AC gap surfaced during story drafting (FastAPI's default 404 returns `{"detail": "Not Found"}`, not the Comadre envelope). One new function (~18 lines, matching `_method_not_allowed_handler`'s shape) + one `app.add_exception_handler(404, ...)` registration line.
2. **Add the non-regression test module.** New `tests/test_non_regression/test_docs_disabled.py` with three assertions per endpoint: (a) status 404, (b) body envelope shape `{"error": {"message": str, "type": str, "hint": str}}`, (c) body contains none of the OpenAPI/Swagger/ReDoc content markers. Delete the obsolete `tests/test_api.py::TestDocsDisabled` class. Update `tests/conftest.py`'s marker docstring + `tests/test_non_regression/README.md` to reflect the broadened `non_regression` semantics.

### 1. `_not_found_handler` in `src/comadre/main.py`

**New function, placed directly above `_method_not_allowed_handler` at current line 249 (so the two handlers read in 404→405 status order):**

```python
def _not_found_handler(request: Request, exc: Exception) -> JSONResponse:
    """Convert Starlette HTTPException(404) to our standard error format.

    Without this handler, FastAPI returns ``{"detail": "Not Found"}`` which
    breaks the consistent ``{"error": {message, type, hint}}`` envelope used
    everywhere else in the API. Shares the ``"not_found_error"`` type with
    ``VoiceNotFoundError`` for shape consistency — unknown-path 404s and
    voice-not-found 404s are both "resource not found," distinguished by
    ``message`` and ``hint``.
    """
    return JSONResponse(
        status_code=404,
        content={
            "error": {
                "message": f"Not found: {request.method} {request.url.path}",
                "type": "not_found_error",
                "hint": (
                    "Check the URL. The Comadre API surface is /v1/audio/speech"
                    " and /health. See docs/api-reference.md for the full"
                    " endpoint list."
                ),
            }
        },
    )
```

**Hint-copy discipline:** the hint deliberately does NOT name `Swagger`, `ReDoc`, or `OpenAPI` as disabled surfaces. Mentioning them would false-positive the content-leak check in AC4 (the substring scan would see "redoc" inside the hint string and flag it as OpenAPI content leakage). The hint points at `/v1/audio/speech` + `/health` + the internal docs reference, which are unambiguous.

**Registration line, inserted at current line 317 immediately after the existing 405 registration:**

```python
    app.add_exception_handler(404, _not_found_handler)
    app.add_exception_handler(405, _method_not_allowed_handler)
```

(404 comes first to keep the two lines in status-code order.)

**Invariant to hold after this change:**

- `rg "detail.*Not Found\|\"detail\"" src/comadre/` returns zero hits (no source path emits Starlette's default 404 shape).
- `comadre.exceptions.VoiceNotFoundError` continues to be raised and handled by `comadre_error_handler` (no path change; `ComadreError` subclasses take priority over the generic 404 handler per FastAPI's handler-resolution rules).

### 2. `tests/test_non_regression/test_docs_disabled.py`

**Skeleton:**

```python
"""FR47 non-regression — /docs, /redoc, /openapi.json disabled (Story 4.5b).

The production Caddyfile's ``@api`` matcher routes only /v1/* and /health to
FastAPI; paths like /docs are served by Caddy's file_server and never reach
the app. This test exercises the app directly via ASGI TestClient so a PR
that re-enables ``docs_url`` / ``redoc_url`` / ``openapi_url`` in
``create_app()`` — or that ships an OpenAPI sub-app — fails CI even before
Caddy is consulted. The Caddy-level enforcement is a separate belt-and-braces
layer; see §Deferred-work for a full-stack variant.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient

from comadre.config import get_settings
from comadre.main import create_app

DISABLED_ENDPOINTS: tuple[str, ...] = ("/docs", "/redoc", "/openapi.json")

# Substrings that would indicate FastAPI's OpenAPI / Swagger UI / ReDoc
# machinery is leaking into the response body. Match is case-insensitive
# and done on the decoded text. Markers are chosen to be specific enough
# that the project's own envelope (a JSON body with message/type/hint
# strings) cannot accidentally trigger them — e.g., ``"openapi":`` is
# the JSON key in a served openapi.json spec, not a word that would
# appear inside a hint string.
_CONTENT_LEAK_MARKERS: tuple[str, ...] = (
    "swagger-ui-bundle",
    "swagger-ui.css",
    "redoc.standalone",
    "redoc-container",
    '"openapi":',
    "<!doctype html",
    "<html",
)


@pytest.fixture()
async def bare_client(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[AsyncClient]:
    """Minimal ASGI client over a bare ``create_app()`` instance.

    No seeded customer, no router mock, no rate-limiter — the /docs
    surface doesn't route through any of that. Only what the FastAPI
    ``startup`` path insists on: a valid Fernet key for the key-registry
    settings validator.
    """
    monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


@pytest.mark.non_regression
@pytest.mark.parametrize("path", DISABLED_ENDPOINTS)
async def test_docs_endpoint_returns_404(bare_client: AsyncClient, path: str) -> None:
    resp = await bare_client.get(path)
    assert resp.status_code == 404, (
        f"{path} returned {resp.status_code}, expected 404. "
        f"If this is green because docs_url/redoc_url/openapi_url was re-enabled "
        f"in create_app(), close that gap before merging."
    )


@pytest.mark.non_regression
@pytest.mark.parametrize("path", DISABLED_ENDPOINTS)
async def test_docs_endpoint_uses_project_envelope(
    bare_client: AsyncClient, path: str
) -> None:
    resp = await bare_client.get(path)
    body = resp.json()
    assert "error" in body, (
        f"{path} 404 body missing 'error' key: {body!r}. "
        f"Did FastAPI's default 404 handler win the exception-handler race?"
    )
    error = body["error"]
    for key in ("message", "type", "hint"):
        assert key in error, (
            f"{path} 404 envelope missing '{key}' field: {error!r}"
        )
        assert isinstance(error[key], str), (
            f"{path} 404 envelope '{key}' is not a string: {error[key]!r}"
        )
    assert error["type"] == "not_found_error", (
        f"{path} 404 envelope type='{error['type']}', expected 'not_found_error'"
    )


@pytest.mark.non_regression
@pytest.mark.parametrize("path", DISABLED_ENDPOINTS)
async def test_docs_endpoint_body_has_no_openapi_content(
    bare_client: AsyncClient, path: str
) -> None:
    resp = await bare_client.get(path)
    body_lower = resp.text.lower()
    leaks = [marker for marker in _CONTENT_LEAK_MARKERS if marker in body_lower]
    assert not leaks, (
        f"{path} 404 body leaks OpenAPI / Swagger / ReDoc content "
        f"(markers found: {leaks}). Body: {resp.text[:500]!r}"
    )
```

**Why a per-file `bare_client` fixture instead of reusing `tests/conftest.py::client`:** The existing `client` fixture builds a fully-populated app (mock router, seeded state, AuthCache, rate limiter) — expensive scaffolding for a test that only needs `create_app()` and a wire protocol. The per-file fixture keeps this module self-contained and avoids coupling to the main `conftest.py`'s evolving `app` shape. Matches the 4.5a pattern (the non-regression package intentionally builds its own minimal fixtures rather than reaching up into `tests/conftest.py`).

**Why `monkeypatch.setenv` + `Fernet.generate_key()` rather than a hard-coded key:** The `KEY_REGISTRY_ENCRYPTION_KEY` setting is required at `create_app()` time (validated by pydantic-settings at `src/comadre/config.py`). Generating a throwaway key per test is the same pattern `tests/conftest.py::app` uses; a hard-coded key would drift if the settings validator ever tightens (e.g., rejects known-weak values).

**Why not hit the compose stack instead:** Through Caddy, `/docs` hits `file_server` (because Caddyfile's `@api path /v1/* /health` matcher doesn't match `/docs`), returning Caddy's 404 page, NOT the app's envelope. That's a different regression surface (Caddyfile routing), orthogonal to FR47. FR47 is "the app returns 404 for these paths" — TestClient is the right harness.

### 3. Delete the obsolete `tests/test_api.py::TestDocsDisabled` class (lines 341-354)

Strictly subsumed by the non-regression module. Keeping both duplicates the 404-check but loses drift protection (the main-suite assertions never pick up the envelope-shape or content-leak checks this story introduces). Dev agent removes the class entirely — not just the weaker tests inside it. The surrounding `TestDocsDisabled` docstring / class scaffolding goes too.

### 4. Update the `non_regression` marker description (`tests/conftest.py:30-33`)

Current text: `"non_regression: integration tests that exercise the prod docker-compose stack"`.

Replace with: `"non_regression: CI non-regression suite (PRD Non-Regression Contract coverage; some tests spawn docker, others use ASGI TestClient)"`.

The docker-only phrasing from 4.5a was accurate for the FR46 story but pre-supposes all sub-stories need docker. 4.5b, 4.5c, 4.5f, 4.5g do not — they're static scans or TestClient-based checks. The broadened wording matches what the CI job will actually run.

### 5. Update `tests/test_non_regression/README.md`

Three edits:

- The "Opt-in contract" section (currently says "they need `docker compose` and bind privileged ports") — amend to "some tests need `docker compose`; others use ASGI TestClient. The common contract is: they run in the CI `non-regression` job and are excluded from the default developer `pytest` invocation."
- The ownership table row for `test_docs_disabled.py` already exists (line 14) — flip its "Controls covered" description from placeholder to final: `FR47 — /docs, /redoc, /openapi.json 404 + project envelope + no OpenAPI content leak`.
- Add a short "Harness choice" section under "Extension contract" explicitly noting that sub-stories may pick `compose_stack` + `probe_client` (docker path) OR a dedicated per-module TestClient fixture (ASGI path), and listing the decision heuristic: "pick TestClient when the check is app-internal (FR47, FR50); pick docker when the check crosses the Caddy↔FastAPI boundary (FR46, FR49)."

No CLAUDE.md gotcha addition required; the non-regression semantics are already documented and this story just sharpens them in the package's own README.

### 6. Housekeeping: no CI YAML change

The existing `non-regression` job in `.github/workflows/ci.yml` runs `uv run pytest -m non_regression tests/test_non_regression/ -v` — it auto-discovers the new module. Grep invariant: `git diff master -- .github/workflows/ci.yml | wc -l` is `0` at story completion.

## Acceptance Criteria

1. **AC1 — `_not_found_handler` exists and is registered.** `src/comadre/main.py` defines `_not_found_handler(request, exc)` returning a `JSONResponse(status_code=404, ...)` with the project envelope. `create_app()` registers it via `app.add_exception_handler(404, _not_found_handler)` in status-code order with the existing 405 handler.

2. **AC2 — Three disabled endpoints return 404.** For each of `/docs`, `/redoc`, `/openapi.json`, the FastAPI ASGI TestClient receives `response.status_code == 404`. Each assertion names the specific endpoint in its failure message.

3. **AC3 — 404 body is the project envelope.** Each of the three responses decodes to JSON with shape `{"error": {"message": str, "type": str, "hint": str}}`. The `type` field equals `"not_found_error"` exactly. All three fields are non-empty strings. Assertion failures identify the endpoint AND which key is missing / mistyped.

4. **AC4 — 404 body has no OpenAPI / Swagger / ReDoc content.** Case-insensitive substring search over the response text finds NONE of `swagger-ui-bundle`, `swagger-ui.css`, `redoc.standalone`, `redoc-container`, `"openapi":`, `<!doctype html`, `<html`. Markers are deliberately specific enough that the project envelope's own text (message / type / hint strings) cannot false-positive them. Assertion failure lists the specific markers found plus a body excerpt.

5. **AC5 — `non_regression` marker applied.** Every new test in `tests/test_non_regression/test_docs_disabled.py` carries `@pytest.mark.non_regression`. Grep invariant (inherited from 4.5a AC15): `rg "pytest.mark.non_regression" tests/` outside `tests/test_non_regression/` returns zero matches.

6. **AC6 — Default `pytest` run still excludes the new module.** `uv run pytest` (no `-m` flag, no marker filter) does NOT execute the new tests. They're deselected via the existing `addopts = "-m 'not non_regression'"` from 4.5a — no change needed to `pyproject.toml`. Verified by running `uv run pytest` and observing the new file's tests show as "deselected."

7. **AC7 — Opt-in CI invocation picks up the new module.** `uv run pytest -m non_regression tests/test_non_regression/ -v` collects and runs the new tests alongside 4.5a's `test_security_headers.py`. Verified locally before PR.

8. **AC8 — Obsolete duplicate removed.** `tests/test_api.py` no longer contains the `TestDocsDisabled` class. `rg "TestDocsDisabled" tests/` returns zero matches. The three former inline tests (`test_docs_returns_404`, `test_redoc_returns_404`, `test_openapi_json_returns_404`) return zero matches as well — they are superseded, not renamed.

9. **AC9 — Handler-registration order is explicit in `create_app()`.** The exception-handler registrations in `create_app()` list the 404 handler immediately before the 405 handler in status-code order: `app.add_exception_handler(RequestValidationError, ...)` → `app.add_exception_handler(404, _not_found_handler)` → `app.add_exception_handler(405, _method_not_allowed_handler)`. Verified by inspection of the diff on `src/comadre/main.py`. (Rationale: makes the pairing obvious to a reader; FastAPI's handler resolution doesn't care about registration order for status-code handlers, but the source-order signal helps future maintainers.)

10. **AC10 — `VoiceNotFoundError` path unchanged.** A regression check via the existing unit tests: the `VoiceNotFoundError` → `comadre_error_handler` path continues to return its own envelope (`type="not_found_error"`, voice-specific message). `uv run pytest tests/test_api.py -k "unknown_voice"` stays green. The new 404 handler does not shadow `ComadreError` subclasses because FastAPI resolves `ComadreError` handlers before generic status-code handlers.

11. **AC11 — CI YAML untouched.** `git diff master -- .github/workflows/ci.yml` returns empty. The existing `non-regression` job auto-discovers the new test file.

12. **AC12 — No new runtime or dev dependency.** `uv.lock` diff against master is empty (or shows only lockfile re-hashing without package additions). `pyproject.toml` `[project]` and `[tool.uv]` sections are unchanged.

13. **AC13 — Marker description reflects broadened semantics.** `tests/conftest.py`'s `non_regression` marker registration (line ~30) no longer reads "integration tests that exercise the prod docker-compose stack"; it names the CI non-regression surface with both docker-based and ASGI-TestClient-based tests permitted.

14. **AC14 — README reflects the harness-choice convention.** `tests/test_non_regression/README.md` opt-in contract explicitly names both the docker fixture path and the ASGI TestClient path as valid within the marker; the ownership table row for `test_docs_disabled.py` carries the final description (not the placeholder).

15. **AC15 — Full quality-gate suite stays green.** `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src/`, `uv run pytest` (default), `uv run pytest -m non_regression tests/test_non_regression/ -v`, and `uv run pre-commit run --all-files` all exit 0.

## Tasks / Subtasks

- [x] **Task 1 — Ship the project-envelope 404 handler** (AC1, AC9, AC10)
  - [x] 1.1 In `src/comadre/main.py`, add `_not_found_handler(request, exc)` directly above `_method_not_allowed_handler` following the existing handler's docstring + `JSONResponse` shape. Use `error_type="not_found_error"` and a hint that names the public API surface (`/v1/audio/speech`, `/health`) and the intentional doc-disable.
  - [x] 1.2 In `create_app()`, immediately after the existing `app.add_exception_handler(RequestValidationError, ...)` line, add `app.add_exception_handler(404, _not_found_handler)` ABOVE the existing `app.add_exception_handler(405, _method_not_allowed_handler)` line — status-code order.
  - [x] 1.3 Run `uv run pytest tests/test_api.py -k "unknown_voice"` — `VoiceNotFoundError` path stays green (AC10).
  - [x] 1.4 Inspect the diff on `src/comadre/main.py` and confirm the three exception-handler registrations read top-to-bottom: RequestValidationError → 404 → 405 (AC9).

- [x] **Task 2 — Add the non-regression test module** (AC2, AC3, AC4, AC5, AC6, AC7)
  - [x] 2.1 Create `tests/test_non_regression/test_docs_disabled.py` per §Scope-2. Three parametrised tests (status / envelope / content-leak), one `bare_client` fixture per module, marker on every test.
  - [x] 2.2 Run `uv run pytest tests/test_non_regression/test_docs_disabled.py -m non_regression -v` — all 9 test cases pass (3 endpoints × 3 assertions).
  - [x] 2.3 Run `uv run pytest` (default) — new file's tests show as deselected, zero executed (AC6).
  - [x] 2.4 Run `uv run pytest -m non_regression tests/test_non_regression/ -v` — new module runs alongside 4.5a's `test_security_headers.py` (AC7).
  - [x] 2.5 Failure-UX smoke: temporarily revert the 404 handler registration (`git stash` partial), run `uv run pytest -m non_regression tests/test_non_regression/test_docs_disabled.py`, observe failure message names the endpoint + the missing `error` key. Restore immediately.

- [x] **Task 3 — Subsume and delete `tests/test_api.py::TestDocsDisabled`** (AC8)
  - [x] 3.1 Remove the `TestDocsDisabled` class entirely (lines 341-354 per current file layout — the dev agent should re-locate via `rg "class TestDocsDisabled" tests/test_api.py` in case line numbers have drifted).
  - [x] 3.2 Verify `rg "TestDocsDisabled|test_docs_returns_404|test_redoc_returns_404|test_openapi_json_returns_404" tests/` returns zero matches.
  - [x] 3.3 Run `uv run pytest tests/test_api.py -v` — rest of `test_api.py` passes; no orphaned imports surface.

- [x] **Task 4 — Update marker description and package README** (AC13, AC14)
  - [x] 4.1 Edit `tests/conftest.py` marker registration per §Scope-4 (broadened wording; retain the `slow` marker line unchanged).
  - [x] 4.2 Edit `tests/test_non_regression/README.md` per §Scope-5 (opt-in contract text, ownership table row for `test_docs_disabled.py`, new harness-choice paragraph under "Extension contract").

- [x] **Task 5 — Verify invariants and the full quality-gate suite** (AC11, AC12, AC15)
  - [x] 5.1 `git diff master -- .github/workflows/ci.yml` returns empty (AC11).
  - [x] 5.2 `git diff master -- uv.lock pyproject.toml` — pyproject changes ONLY cover (a) no changes (expected) or (b) unrelated-to-deps edits if any. No new package entries (AC12).
  - [x] 5.3 `uv run ruff check .` — all checks pass.
  - [x] 5.4 `uv run ruff format --check .` — zero drift.
  - [x] 5.5 `uv run mypy src/` — "Success: no issues found."
  - [x] 5.6 `uv run pytest` — default-run test count = previous count − 3 (the deleted `TestDocsDisabled` cases) + 0 (new tests are marker-excluded by default). Expected net: −3. Confirm.
  - [x] 5.7 `uv run pytest -m non_regression tests/test_non_regression/ -v` — 4.5a's 25 passed / 16 skipped PLUS 9 new passed from 4.5b. Expected total: 34 passed, 16 skipped.
  - [x] 5.8 `uv run pre-commit run --all-files` — all hooks pass (ruff / mypy / hadolint / yamllint / shellcheck / markdownlint-cli2).

- [x] **Task 6 — Change log and status**
  - [x] 6.1 Append a row to this story's Change Log with the implementation date.
  - [x] 6.2 Flip Status at the top of this file from `ready-for-dev` → `review` at PR-open time; then → `done` after adversarial review patches land (per 4.5a's workflow).

### Review Findings

Adversarial code review on 2026-04-23 (Blind Hunter + Edge Case Hunter + Acceptance Auditor). Acceptance Auditor verified all 15 ACs pass, no spec deviations. The 9 deferred items below are real but non-gating — either pre-existing patterns shared with the symmetric `_method_not_allowed_handler`, or already enumerated in this story's §Deferred-work, or scope-creep beyond the FR47 AC. Re-triage on a future hardening pass.

- [x] [Review][Defer] Path/method reflection in 404 message body without sanitisation [`src/comadre/main.py:263`] — deferred, pre-existing pattern in `_method_not_allowed_handler` (line ~265); JSON-encoded so XSS-safe. Not 4.5b-introduced.
- [x] [Review][Defer] Hint references repo-relative `docs/api-reference.md` instead of public URL [`src/comadre/main.py:267-269`] — deferred, identical convention to the existing 405 handler. Cross-handler housekeeping, not 4.5b-specific.
- [x] [Review][Defer] Default `uv run pytest` no longer covers FR47 (deleted `TestDocsDisabled` was unmarker-gated) [`tests/test_api.py`] — deferred, spec-intentional per §Scope-3 (the non-regression CI job catches it); revisit if local-feedback latency proves painful.
- [x] [Review][Defer] `_CONTENT_LEAK_MARKERS` could miss future docs UIs (rapidoc, stoplight-elements, openapi-explorer) [`tests/test_non_regression/test_docs_disabled.py:183-191`] — deferred, already in spec §Deferred-work ("Content-leak markers list evolution"); the failure message names the body excerpt so a real leak would be loud.
- [x] [Review][Defer] HEAD-method body framing not asserted [`src/comadre/main.py:249-272`] — deferred, Starlette normally strips bodies on HEAD; not exercised by these tests, would warrant a separate cross-handler RFC-compliance story.
- [x] [Review][Defer] Future required-env-var addition would silently break `bare_client` [`tests/test_non_regression/test_docs_disabled.py:194-212`] — deferred, architectural concern shared by every test that calls `create_app()` (including `tests/conftest.py::app`), not 4.5b-introduced.
- [x] [Review][Defer] `/docs/oauth2-redirect` not in `DISABLED_ENDPOINTS` [`tests/test_non_regression/test_docs_disabled.py:124`] — deferred, out of FR47 AC scope (PRD names exactly three endpoints); the realistic regression scenario (re-enabling `docs_url`) is already caught by the existing `/docs` assertion.
- [x] [Review][Defer] Method-variance not tested (only GET) [`tests/test_non_regression/test_docs_disabled.py:165-211`] — deferred, already in spec §Deferred-work ("Test matrix expansion to cover method variance"); FR47 explicitly names GET as the surface.
- [x] [Review][Defer] README ownership cell may overpromise FR47 since Caddy-layer is uncovered [`tests/test_non_regression/README.md:17`] — deferred, spec §Deferred-work explicitly names a Caddy-level belt-and-braces test as candidate follow-up; today the Caddy `file_server` 404 transitively satisfies the control.

**Dismissed as noise / verified-handled:**

- VoiceNotFoundError shadowing concern (B6/E4) — verified false: `uv run pytest tests/test_api.py -k unknown_voice` stays green. FastAPI resolves `ComadreError` class handlers before generic status-code handlers, and the spec's AC10 documents this invariant.
- `# type: ignore[arg-type]` missing on the 404 registration (B1) — mypy strict passes per AC15; matches the existing 405 registration's shape exactly.
- Handler ignores `exc` parameter (B2) — codebase-wide rule "no raw `HTTPException`" (CLAUDE.md gotcha; enforced statically by Story 4.5f) means custom-detail HTTPExceptions never reach this handler.
- Hint advertises only `/v1/audio/speech` + `/health` (B5) — correct: these ARE the entire public API surface per the Caddyfile `@api` matcher.
- Settings-cache mutation without per-test teardown (B7/E13) — the autouse `_clear_settings_cache` fixture in `tests/conftest.py:37-38` runs on every test, providing the symmetric clear.
- Per-fixture `Fernet.generate_key()` cost (B8/E14) — empirically irrelevant: 9 cases run in 0.05s.
- `resp.json()` may raise on non-JSON body (B9) — by design: a `JSONDecodeError` surfaces as a loud test failure, not a silent pass; the regression is detected, just via traceback rather than `assert` message.
- No `Content-Type: application/json` assertion (B12/E19) — spec §Dev-Notes explicitly justifies the omission as duplicative with the envelope-shape check.
- `exc: Exception` typing rigidity (E1) — matches existing 405 handler convention.
- StreamingResponse mid-flight 404 (E6) — no streaming route at `/docs`/`/redoc`/`/openapi.json`; out of scope.
- `'"openapi":'` could false-positive on future hint edits (E8) — handler hint is fixed code; spec §Scope explicitly steers the hint clear of these tokens; a regression would be loud, not silent.
- `'<!doctype html'` could match a future HTML 404 page (E9) — by design: an HTML 404 IS the regression to catch (FR47 contract is JSON envelope only).
- `bare_client` runs full lifespan / KEY_REGISTRY_DB_PATH not isolated (E10/E11) — verified false: tests run in 0.05s, confirming `httpx.ASGITransport` does not invoke FastAPI lifespan startup. No model download, no DB write.

## Dev Notes

### Design decisions

**Why ship the 404 handler as part of 4.5b rather than defer to a separate story.** The epic's AC3 explicitly requires the project envelope on these 404 responses. FastAPI's default shape (`{"detail": "Not Found"}`) does not match; without a handler, AC3 is unreachable. The handler is ~18 lines and mirrors the existing `_method_not_allowed_handler` exactly — shipping it here keeps the story self-sufficient and avoids a "story 4.5b blocked on a predecessor that only 4.5b needs" dependency cycle. It also delivers a side benefit outside FR47: any future unmatched path (say `/v2/audio/speech` before a v2 ships) also gets the consistent envelope.

**Why TestClient and not the existing `compose_stack` fixture.** Through production Caddy, `/docs`, `/redoc`, and `/openapi.json` hit `file_server` (not reverse_proxy — the Caddyfile's `@api` matcher is `path /v1/* /health`). Caddy's file_server returns its own 404 page, which does NOT carry the project envelope — it is a Caddy static response. Asserting the envelope via the Caddy stack would always fail; FR47's AC is about the app, not the proxy. A Caddy-level belt-and-braces test that asserts "Caddy also returns 404 on these paths" is valuable but orthogonal — deferred (see §Deferred-work).

**Why `error_type="not_found_error"` (shared with `VoiceNotFoundError`).** Consistency across the codebase: all 404-class errors use the same `type` string. Clients that discriminate on `type` can still discriminate on `message` + `hint` to distinguish "unknown voice" from "unknown URL." Inventing a new `type` (e.g., `"route_not_found_error"`) would proliferate the vocabulary without a concrete consumer asking for it.

**Why a dedicated `bare_client` fixture in the test module, not reuse `tests/conftest.py::client`.** The existing `client` fixture pulls in `mock_router`, seeded `registry_db_path`, `auth_cache`, `rate_limiter`, an `asyncio.Lock`, and a `start_time`. For `/docs` 404 probes, every one of these is dead weight. The per-module fixture is ~12 lines and insulates the test from evolution in `tests/conftest.py`'s `app` fixture shape. Matches the 4.5a convention where the non-regression package owns its own fixture surface.

**Why substring-based content-leak detection instead of JSON schema validation.** The negative assertion "response contains no HTML / no Swagger UI / no OpenAPI spec structure" is more directly expressed as "none of these well-known markers appear in the decoded body." A positive envelope-shape assertion already lives in AC3 via the `test_docs_endpoint_uses_project_envelope` check; AC4 is its complement — "and ALSO no OpenAPI leak slipped in alongside." A leaked spec would carry at least one of the markers (`"openapi":` as the generated spec's root JSON key at minimum; `swagger-ui-bundle` / `swagger-ui.css` for the Swagger UI HTML; `redoc-container` / `redoc.standalone` for ReDoc); enumerating markers beats trying to parse the body as the shape it "shouldn't be."

**Why the marker list uses specific asset/key strings rather than bare words like `swagger` or `redoc`.** The new 404 handler's hint / message fields are user-facing English — they could legitimately mention the word "swagger" or "redoc" (e.g., a future hint revision explaining the disable). A bare-word marker would false-positive the check the moment that happens. The chosen markers (`swagger-ui-bundle`, `redoc-container`, `"openapi":` with the colon) only appear in actual Swagger UI / ReDoc / OpenAPI output, never in prose. The hint shipped in 4.5b's `_not_found_handler` deliberately steers clear of these words for belt-and-braces; the marker discipline survives even if a future hint edit isn't as careful.

**Why the marker description change instead of a new marker.** A second marker (`non_regression_app`, `non_regression_docker`) would multiply the CI matrix and the mental model for zero real benefit — the CI job runs `-m non_regression` across both shapes today, and the skip-on-no-docker guard lives inside the `compose_stack` fixture itself (so ASGI tests never hit the guard). Broadening the marker's docstring is the minimum-viable rephrase.

**Why NOT assert `Content-Type: application/json` on the 404 responses.** The envelope assertion in AC3 already proves the content is JSON (it's decoded via `resp.json()`). A separate header assertion would be duplicative and couple to a specific framework choice (FastAPI's `JSONResponse` sets the header; a future refactor using `ORJSONResponse` or similar would have to update the test for zero behavior change).

### Import-graph placement

- **`src/comadre/main.py` (MOD).** One new function `_not_found_handler` + one new `app.add_exception_handler(404, ...)` registration line. No new imports (`JSONResponse` and `Request` are already imported at the top).
- **`tests/test_non_regression/test_docs_disabled.py` (NEW).** Imports: stdlib (`collections.abc.AsyncIterator`), `pytest`, `cryptography.fernet.Fernet`, `httpx` (`ASGITransport`, `AsyncClient`), and from `comadre.config` / `comadre.main`. No imports from `tests/test_non_regression/conftest.py` (this module doesn't need the docker fixtures).
- **`tests/test_api.py` (MOD, delete-only).** Removes three test methods and one class scaffold. No import changes likely — `AsyncClient` is used by the remaining tests in the file.
- **`tests/conftest.py` (MOD).** One-line marker-description edit. No import changes, no new fixture.
- **`tests/test_non_regression/README.md` (MOD).** Prose-only edits.
- **`src/comadre/exceptions.py` — unchanged.** The new 404 handler lives in `main.py` alongside the 405 handler (symmetry), not in `exceptions.py`. If this pair of handlers ever grows to three or more, a future housekeeping story can migrate them into `exceptions.py` — deferred.

### Test-flake avoidance

- **Settings cache.** `get_settings()` is LRU-cached. The `bare_client` fixture clears it via `get_settings.cache_clear()` AFTER setting `KEY_REGISTRY_ENCRYPTION_KEY` so the new value wins. The existing `_clear_settings_cache` autouse fixture in `tests/conftest.py` ALSO clears the cache at test-start — belt-and-braces, no conflict.
- **ASGI transport.** `AsyncClient` over `ASGITransport` runs the app in-process — no network, no port binding, no docker. Zero flake surface from the transport layer.
- **Fernet key freshness.** `Fernet.generate_key()` each fixture call — no cross-test contamination on the encryption-key setting.
- **Parametrised independence.** Each `@pytest.mark.parametrize("path", DISABLED_ENDPOINTS)` test case is fully independent (fresh fixture per case). A failure on `/docs` does NOT mask `/redoc` — both assertions run.
- **Handler resolution order.** FastAPI resolves exception handlers by specificity: custom `ComadreError` subclass handlers win over generic status-code handlers, which in turn win over framework defaults. The new 404 handler catches `StarletteHTTPException` with status 404 but does NOT intercept `ComadreError(status_code=404)` like `VoiceNotFoundError` — `comadre_error_handler` is bound to `ComadreError` (more specific) and wins. AC10 verifies this invariant via the existing `test_unknown_voice_returns_404` test.

### Project Structure Notes

- **Alignment with unified project structure.**
  - Test module naming: `tests/test_non_regression/test_docs_disabled.py` — matches the ownership table in `tests/test_non_regression/README.md` (row for 4.5b).
  - Handler naming: `_not_found_handler` — mirrors `_method_not_allowed_handler`'s leading-underscore convention (module-private helpers).
  - `error_type` string: `"not_found_error"` — matches `VoiceNotFoundError` (`src/comadre/exceptions.py:43`). No new vocabulary.
  - Hint copy: names the public API surface (`/v1/audio/speech`, `/health`) AND mentions the intentional doc-disable, so clients debugging a 404 get context — matches the hint-copy density in `_method_not_allowed_handler` ("Use POST for /v1/audio/speech and GET for /health. See docs/api-reference.md...").

- **Detected conflicts or variances (with rationale).**
  - The `bare_client` fixture lives in the test module, not in `tests/test_non_regression/conftest.py` (where `compose_stack` and `probe_client` live). Rationale: `conftest.py`-level fixtures apply to every test in the package, which would load the Fernet key and build an app for 4.5a's docker tests too — pure overhead. Module-scoped fixture keeps the surface clean. If 4.5e (rate-limit middleware registration) also needs an ASGI client, it can either duplicate `bare_client` (cheap, ~12 lines) or — if three modules end up needing it — migrate to the package `conftest.py` as part of 4.5e's own scope.

### Testing standards

- **Async tests.** All three new tests are `async def` with `pytest-asyncio` auto-discovery (already configured project-wide per existing `tests/test_api.py` usage). No new `@pytest.mark.asyncio` required if the project uses `asyncio_mode = "auto"` — verify via the existing `test_api.py` test shape before adding explicit marks.
- **Assertion messages.** Every assertion carries a failure message naming (a) the endpoint path, (b) the specific invariant that broke, (c) a diagnostic tail (response body / observed value). Inherits the 4.5a "name-the-regression" convention.
- **No fixture-level assertions.** The fixture yields the client; assertions live in the test body. A fixture-level `assert` would mask test identity in the failure output.

### Deferred work to flag at story close

- **Caddy-level belt-and-braces: `/docs` / `/redoc` / `/openapi.json` 404 through the full compose stack.** Orthogonal to FR47's app-level contract, but worth adding as a defense-in-depth check: if a future Caddyfile edit accidentally broadens the `@api` matcher to include `/docs*`, this app-level test still passes (because the app disables docs) — but the regression would be that docs now reach the app at all. A compose-stack-based test asserting `probe_client.get("/docs").status_code == 404` closes that gap. Deferred because: (a) `/docs` via Caddy's file_server returns 404 today (the request never reaches the app — it hits file_server and finds no matching file), so the control is already transitively satisfied; (b) adding the test to 4.5b inflates scope without closing an observed regression. Candidate for a follow-up hardening story or a rolled-into-4.5d companion if the Caddy `@api` matcher gets touched.
- **Envelope-shape invariant for ALL 4xx / 5xx responses, not just 404 / 405.** FastAPI can surface 500s in shapes other than the project envelope if `unhandled_error_handler` is bypassed (e.g., an uncaught `Exception` in a middleware chain). A broader invariant "every HTTP error response from the app is JSON with `{error: {...}}` shape" is a natural NFR17 expansion but would require a test that exhaustively enumerates error paths. Deferred as a separate hardening story once 4.5b–g ship.
- **Migrate the 404 + 405 handlers into `src/comadre/exceptions.py`.** Currently `_method_not_allowed_handler` and the new `_not_found_handler` live in `main.py`, while the `ComadreError` handler lives in `exceptions.py`. If a third status-code handler ever materialises, consolidating into `exceptions.py` makes sense. One-handler-pair isn't enough to justify the move today; flagged so a future contributor facing a third-handler addition has the historical rationale.
- **Content-leak markers list evolution.** `_CONTENT_LEAK_MARKERS` is a conservative set today. If FastAPI's Swagger UI or ReDoc templates change their signature strings in a future release, the list may need a refresh. The test's failure message names the observed body excerpt, so a mismatch will be loud — not silent. Deferred absent a specific observed gap.
- **Assertion on `Content-Type: application/json` header on the 404 responses.** Skipped deliberately (duplicative with the envelope assertion), but a future "strict MIME-type regression" story could add it across the error-response surface.
- **Test matrix expansion to cover method variance.** 4.5b probes `GET /docs`, `GET /redoc`, `GET /openapi.json` only. A PR that adds a `POST` route to one of these paths (nonsensical but possible) would not be caught. Deferred — FR47 explicitly names `GET` as the surface.

### References

- Epic 4 Story 4.5 umbrella — `_bmad-output/planning-artifacts/epics.md:878-888`
- Epic 4 Story 4.5b — `_bmad-output/planning-artifacts/epics.md:912-926`
- FR47 — `_bmad-output/planning-artifacts/prd.md:96, 255, 1191`
- NFR17 — `_bmad-output/planning-artifacts/prd.md:1221`
- PRD Non-Regression Contract (docs-disabled row) — `_bmad-output/planning-artifacts/prd.md:644`
- Architecture Non-Regression list — `_bmad-output/planning-artifacts/architecture.md:188`
- Story 4.5a (predecessor; skeleton + marker + CI job) — `_bmad-output/implementation-artifacts/4-5a-ci-security-headers-regression.md`
- `create_app()` — `src/comadre/main.py:277-287` (docs-disabled FastAPI args) and `src/comadre/main.py:315-317` (exception-handler registration block)
- Existing 405 handler — `src/comadre/main.py:249-274`
- `ComadreError` hierarchy and envelope handler — `src/comadre/exceptions.py:18-245`
- `VoiceNotFoundError` — `src/comadre/exceptions.py:36-52` (precedent for `error_type="not_found_error"`)
- Existing `TestDocsDisabled` class (to be deleted) — `tests/test_api.py:341-354`
- Existing `client` fixture pattern — `tests/conftest.py:129-136`
- Non-regression marker registration — `tests/conftest.py:30-33`
- Non-regression package README — `tests/test_non_regression/README.md`
- `pyproject.toml` `addopts = "-m 'not non_regression'"` — established by 4.5a

## Dev Agent Record

### Agent Model Used

claude-opus-4-7[1m]

### Debug Log References

- Failure-UX smoke: temporarily removed `app.add_exception_handler(404, _not_found_handler)` and re-ran `uv run pytest tests/test_non_regression/test_docs_disabled.py -m non_regression`. Observed three parametrised envelope failures with assertion messages of the form: `/docs 404 body missing 'error' key: {'detail': 'Not Found'}. Did FastAPI's default 404 handler win the exception-handler race?` — endpoint path named, missing key identified, diagnostic body included. Restored the registration immediately.

### Completion Notes List

- **AC1, AC9** — `_not_found_handler` added above `_method_not_allowed_handler` in `src/comadre/main.py` (mirrors the 405 handler's shape, same `error_type="not_found_error"` as `VoiceNotFoundError`). Registration block now reads RequestValidationError → 404 → 405 in top-to-bottom status-code order.
- **AC2, AC3, AC4, AC5** — `tests/test_non_regression/test_docs_disabled.py` added with a per-module `bare_client` fixture (ASGI TestClient over bare `create_app()`, Fernet key minted per test) plus three parametrised tests (status, envelope shape, content-leak). Every test carries `@pytest.mark.non_regression`. 9 test cases (3 endpoints × 3 assertions) — all green. Added a non-empty-string assertion to the envelope check so empty `message`/`type`/`hint` would be caught alongside the type-check mandated by AC3.
- **AC6** — default `uv run pytest` reports `1414 passed, 50 deselected`; the 9 new cases are in the deselected group.
- **AC7** — `uv run pytest -m non_regression tests/test_non_regression/ -v` reports `34 passed, 16 skipped` (25 passed + 16 skipped from 4.5a `test_security_headers.py` plus 9 new from this story) — matching the spec's expected total.
- **AC8** — `TestDocsDisabled` class removed from `tests/test_api.py`. `rg "TestDocsDisabled|test_docs_returns_404|test_redoc_returns_404|test_openapi_json_returns_404" tests/` returns empty. Remaining `test_api.py` tests: 48 passed (was 51 before removal; −3 as expected).
- **AC10** — `uv run pytest tests/test_api.py -k "unknown_voice"` passes. The `VoiceNotFoundError` → `comadre_error_handler` path is unchanged because FastAPI resolves `ComadreError` subclass handlers before generic status-code handlers.
- **AC11** — `git diff master -- .github/workflows/ci.yml` returns 0 lines.
- **AC12** — `git diff master -- pyproject.toml uv.lock` returns 0 lines. No new runtime or dev dependency.
- **AC13** — `tests/conftest.py` marker description now reads: `"non_regression: CI non-regression suite (PRD Non-Regression Contract coverage; some tests spawn docker, others use ASGI TestClient)"`. The docker-only phrasing from 4.5a is gone.
- **AC14** — `tests/test_non_regression/README.md` updated: opening paragraph broadened, Opt-in contract amended to name both docker and TestClient paths, ownership row for `test_docs_disabled.py` carries the final FR47 description, new "Harness choice" section under "Extension contract" documents the TestClient-vs-docker decision heuristic.
- **AC15** — `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src/`, `uv run pytest`, `uv run pytest -m non_regression tests/test_non_regression/ -v`, and `uv run pre-commit run --all-files` all exit 0.
- **Source invariant** — `rg 'detail.*Not Found|"detail"' src/comadre/` returns only (a) two docstring references in `main.py` explaining what FastAPI's default shape is (documentation, not emission) and (b) one hit in `keys/health.py` inside an unrelated health-summary dict key. No source path emits Starlette's default 404 shape to a client.

### File List

- `src/comadre/main.py` (MOD) — added `_not_found_handler`; added `app.add_exception_handler(404, _not_found_handler)` registration in status-code order.
- `tests/test_non_regression/test_docs_disabled.py` (NEW) — FR47 non-regression module (bare_client fixture + 3 parametrised tests).
- `tests/test_api.py` (MOD) — removed the obsolete `TestDocsDisabled` class (subsumed by the non-regression module).
- `tests/conftest.py` (MOD) — broadened `non_regression` marker description to cover both docker and ASGI TestClient tests.
- `tests/test_non_regression/README.md` (MOD) — updated opening paragraph, opt-in contract, ownership-table row for `test_docs_disabled.py`, and added a "Harness choice" section under "Extension contract".
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (MOD) — story 4.5b status: `ready-for-dev` → `in-progress` → `review`.
- `_bmad-output/implementation-artifacts/4-5b-ci-docs-endpoints-disabled-regression.md` (MOD) — Dev Agent Record populated, tasks checked, status flipped to `review`.

## Change Log

| Date       | Change                                                                                                                          |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------- |
| 2026-04-23 | Story spec drafted (status `ready-for-dev`). AC gap surfaced during drafting: FastAPI's default 404 shape `{"detail": "Not Found"}` does not match the project envelope AC requires; scope expanded to include a new `_not_found_handler` in `src/comadre/main.py` mirroring the existing 405 handler. Non-regression marker semantics broadened to admit ASGI-TestClient-based tests alongside docker-based tests. |
| 2026-04-23 | Story implemented. Shipped `_not_found_handler` + 404 registration in `src/comadre/main.py`; added `tests/test_non_regression/test_docs_disabled.py` (9 parametrised cases, all green); deleted obsolete `TestDocsDisabled` class from `tests/test_api.py`; broadened `non_regression` marker description in `tests/conftest.py`; updated `tests/test_non_regression/README.md` opening + opt-in contract + ownership row + new "Harness choice" section. Full quality gate green (ruff check/format, mypy, default pytest 1414 passed / 50 deselected, non-regression 34 passed / 16 skipped, pre-commit all hooks). Status → `review`. |
| 2026-04-23 | Adversarial code review (Blind Hunter + Edge Case Hunter + Acceptance Auditor). Auditor: all 15 ACs pass, no spec deviations. Triage: 0 patches, 0 decisions-needed, 9 deferred (logged in `_bmad-output/implementation-artifacts/deferred-work.md`), 14 dismissed (incl. verified-false VoiceNotFoundError-shadowing concern via live `unknown_voice` re-run). Status → `done`. |
