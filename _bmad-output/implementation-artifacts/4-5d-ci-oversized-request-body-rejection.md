# Story 4.5d: CI — Oversized Request Body Rejection

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

> **Scope note — FR49, NFR17.** Fourth of the seven CI non-regression sub-stories (4.5a–4.5g). Inherits the skeleton 4.5a landed (`tests/test_non_regression/` package, `non_regression` pytest marker, `non-regression` job in `.github/workflows/ci.yml`, session-scoped `compose_stack` + function-scoped `probe_client` fixtures) and the "docker stack when the check crosses the Caddy↔FastAPI boundary" harness rule 4.5a/4.5b/4.5c codified in the README. 4.5d asserts the FR49 contract — a PR that drops the `request_body { max_size 1MB }` directive from `deploy/caddy/Caddyfile` (or raises / reshapes it beyond recognition) fails CI before reaching master, proving oversized bodies are still rejected at the reverse-proxy layer before reaching the application. Delivers two artefacts: (1) `tests/test_non_regression/test_request_body_limit.py` with five `@pytest.mark.non_regression` tests driven by the existing `probe_client` fixture; (2) a one-line defensive hardening of the stub nginx config inside `tests/test_non_regression/conftest.py` (`client_max_body_size 100M;`) so that a 413 response can ONLY originate from Caddy — never ambiguously from the upstream stub — closing a false-pass path where a Caddy regression that forwards oversized bodies would still appear "rejected" because nginx's default 1M limit triggered instead. **No change to `src/comadre/`. No change to `deploy/caddy/Caddyfile`. No new Python dependency. No CI YAML change. No `pyproject.toml` change.**

## Story

As a contributor,
I want every pull request against master to prove — via a live docker probe of the production Caddy image with the production `Caddyfile`, loaded against a nginx stub whose own body-size limit has been raised to 100 MB so only Caddy can reject — that a POST of 2 MB to `/v1/audio/speech` is rejected with HTTP 413 before the bytes reach upstream, and complementarily that a sub-boundary POST of just under 1 MB is proxied through to the stub (observable via the stub's canonical `non-regression-stub\n` response body), so the `request_body { max_size 1MB }` directive in the `@api` handle block remains enforced and its boundary stays within the operational SLA shape the PRD committed to,
so that a well-meaning refactor — say, moving the `reverse_proxy` directive into a `@api_v1`/`@api_health` split that accidentally drops the `request_body` block on one path, or a "clean up the Caddyfile" PR that replaces `max_size 1MB` with a higher limit in pursuit of larger audio uploads — cannot land on master without the PR build turning red and naming exactly which endpoint regressed, which status code was observed vs expected, and whether the oversized request visibly reached the upstream stub.

**Covers FRs:** FR49 (CI can verify that oversized request bodies are rejected at the reverse-proxy layer before reaching the application).
**NFRs:** NFR17 (all Non-Regression Contract controls remain satisfied on every PR; CI regression coverage mandatory for each control row).
**UX-DRs:** Contributor-facing CI UX — when an assertion fires, the pytest failure message MUST name (a) the HTTP method + path probed, (b) the observed status code vs the expected status, (c) the payload size in bytes (explicit, not "large"), (d) a one-line diagnostic tail (e.g., "upstream stub signature present in response body — 413 came from nginx fallback, not from Caddy's max_size directive"). Inherits the 4.5a "name-the-regression" assertion convention and the 4.5a parametrised-case-per-endpoint discipline (here: parametrised over the two `@api`-matched paths `/v1/audio/speech` and `/health`).
**Epic:** 4 — Security Hardening, LGPD & Operational Safety. Eighth story in Epic 4 (4.1 → 4.2 → 4.3 → 4.4 → 4.5a → 4.5b → 4.5c → **4.5d** → 4.5e–g → 4.6). Fourth of the seven-sub-story CI non-regression cluster; second docker-stack sub-story (after 4.5a); extends `conftest.py`'s stub config by one defensive line — zero CI YAML changes, zero `src/comadre/` changes, zero `deploy/caddy/Caddyfile` changes, zero marker changes.

## Builds on

- **Story 4.5a — CI non-regression skeleton + docker-stack harness (`done`).** 4.5a established the `tests/test_non_regression/` package, the `non_regression` pytest marker (`tests/conftest.py:30-33`), the `addopts = "-m 'not non_regression'"` default-exclusion in `pyproject.toml`, the `non-regression` CI job in `.github/workflows/ci.yml` that runs `uv run pytest -m non_regression tests/test_non_regression/ -v`, AND the session-scoped `compose_stack` + function-scoped `probe_client` fixtures (`tests/test_non_regression/conftest.py`). 4.5d is the SECOND docker-stack sub-story (after 4.5a itself) and the direct consumer of both fixtures with zero new fixture surface — exactly the "pick fixtures from this module's conftest.py (no new fixtures needed for the common case)" path the README codified in §Extension contract item 2.
- **Story 4.5b — non-regression marker broadened, first non-docker test (`done`).** 4.5b broadened the `non_regression` marker semantics from "always docker-based" to "CI non-regression surface; docker-required fixtures opt in on their own," and codified the "Harness choice" section in the README (`tests/test_non_regression/README.md:177-191`) that explicitly names 4.5d as docker-stack: *"pick docker when the check crosses the Caddy↔FastAPI boundary (FR46, FR49)."* 4.5d is the first sub-story after 4.5b that mechanically exercises that rule — it has to use docker because the control lives in Caddy's request-body handler, and no ASGI TestClient can cover it.
- **Story 4.5c — first static-scan sub-story + fixture-directory convention (`done`).** Orthogonal to 4.5d mechanically (4.5c is pure-stdlib static scan; 4.5d spawns docker), but 4.5c's README amendment — the "Scan allowlist convention" paragraph — sits adjacent to the "Harness choice" section 4.5d's design leans on, so the two sub-stories share the same README footprint. 4.5d does NOT touch 4.5c's fixture subdirectory (`tests/test_non_regression/fixtures/timing_safe_compare/`) and does NOT add a sibling subdirectory under `fixtures/` — the body-size probes are synthesised inline (`b"x" * _ONE_MB`), not read from disk.
- **Existing Caddy `request_body` control — `deploy/caddy/Caddyfile:22-24` (primary), `deploy/caddy/Caddyfile-no-landing:19-21` (no-landing variant).** The canonical directive: `request_body { max_size 1MB }` inside `handle @api { ... }`. Applies to every request routed to the API handler (`/v1/*` and `/health` via `@api path /v1/* /health`). 4.5d's oversized-POST probe fires `/v1/audio/speech` (the headline payload-sized endpoint per PRD) AND `/health` (a second path under the same handler, proves the directive applies at the handler level, not per-path). The `Caddyfile-no-landing` variant is byte-identical on the `request_body` directive, covered transitively by the primary per the 4.5a README convention (§Extension contract: *"Exercise `Caddyfile-no-landing` unless the two files diverge"*).
- **Existing stub config — `tests/test_non_regression/conftest.py:34-46`.** The current `_UPSTREAM_NGINX_CONF` block returns 200 on every path via `return 200 "non-regression-stub\n";`. 4.5d adds exactly one defensive directive — `client_max_body_size 100M;` inside the `http { ... }` block — so the stub cannot generate its own 413 from nginx's default 1M limit. Rationale in §Scope-2: without this guard, a Caddy regression that drops `max_size 1MB` and forwards a 2 MB body to upstream would be silently covered by nginx's fallback 413, and the suite would see "413 is still returned" and pass — a false-pass on exactly the regression class the story is meant to catch.
- **PRD §Architecture-Level Security Controls — `request_body max_size 1MB` row — `_bmad-output/planning-artifacts/prd.md:643`.** Canonical: *"`request_body max_size 1MB` in Caddy reverse_proxy | Caddyfile `request_body` directive | Test sending 2MB payload, expect 413 before reaching app."* 4.5d owns this row; no other sub-story revisits it. The "expect 413" and "2MB payload" values are verbatim from the PRD; 4.5d pins them to a mechanical assertion.
- **PRD §Non-Regression Contract — `_bmad-output/planning-artifacts/prd.md:188`.** Explicit listing of `request_body max_size` in the PR-regression-suite enumeration alongside security headers, banner stripping, docs-endpoints-404, timing-safe comparison, middleware registration, error-envelope uniformity. 4.5d converts this row from prose-only to mechanically-enforced.
- **FR49 — `_bmad-output/planning-artifacts/prd.md:1193`.** Verbatim: *"CI can verify that oversized request bodies are rejected at the reverse-proxy layer before reaching the application."* 4.5d fulfills this FR directly; the "before reaching the application" half is proved by the stub-signature-absence assertion (`non-regression-stub` not in the 413 body — if the upstream had been reached, the 413 response body would carry the stub's signature OR the response would have been 200).
- **PRD §Security-hardening hand-off — `_bmad-output/planning-artifacts/prd.md:700, 709, 741, 829-838`.** Request-body-size limits are mentioned alongside HSTS, CSP, docs-404, and structured-logging in the security-hardening hand-off. 4.5d is part of the final mechanical seal on that hand-off; once 4.5d lands, the hand-off has only FR50 (4.5e), FR51 (4.5f), and the SQL-injection bandit check (4.5g) remaining.
- **CLAUDE.md §Architecture — "HTTPS via Caddy".** *"Caddy reverse proxy terminates TLS... Caddy is the sole external access point (ports 80/443) — the TTS service is not exposed on the host network."* 4.5d mechanically proves a consequence of this: because Caddy is the sole ingress, any control Caddy enforces (including `max_size`) is the ONLY path for that concern. If this architecture ever changes (e.g., TTS service exposed directly for a health-check bypass), 4.5d's assertion would stop being representative — but by that point the architectural change itself would trip other non-regression checks first.

## Unblocks

- **Story 4.5e (`backlog`).** 4.5e introduces the first ASGI TestClient sub-story (no docker, `SlowAPIMiddleware` registration + 429 behaviour). 4.5d's completion closes the last remaining docker-stack sub-story in the cluster — after 4.5d lands, every FR49/FR46/FR47 check that needs to cross the Caddy↔FastAPI boundary is accounted for, and the later sub-stories (4.5e–g) are all app-internal or static-scan. Sequencing-wise, 4.5e does not depend on 4.5d's artefacts; the unblock is scheduling: "docker cluster is closed, free to pivot to TestClient shape."
- **PRD Non-Regression Contract FR49 row.** Converts the `request_body max_size 1MB` row from prose-only to mechanically enforced. Combined with 4.5a (FR46), 4.5b (FR47), 4.5c (FR48), this brings four of the seven sub-stories' FR rows to mechanical enforcement — the CI gate now fails on any regression in security headers, docs-disabled, timing-safe compare, OR oversized body rejection.
- **Operational confidence for the Caddyfile.** Today the `request_body` directive in the Caddyfile is guarded only by code review. After 4.5d lands, any PR that touches the `handle @api { ... }` block is automatically checked against the oversized-rejection contract; a reviewer can merge with confidence that a subtle reshape didn't drop the directive.

## Depends on

- **Stories 4.5a, 4.5b, 4.5c are `done`** (sprint-status.yaml confirms, checked 2026-04-24). Hard dependency on 4.5a's non-regression package skeleton, marker, CI job, and the `compose_stack` + `probe_client` fixtures. Soft dependency on 4.5b's marker broadening (the marker description is already worded to include docker-stack AND non-docker tests; 4.5d is docker-stack, so this is a no-op). Soft dependency on 4.5c's README amendment (it sits adjacent to the "Harness choice" paragraph 4.5d implements; no content collision).
- **No new runtime dependency.** `httpx` is already a dev dependency (`pyproject.toml:41`).
- **No new dev dependency.** `pytest` + `pytest-asyncio` already configured.
- **No schema change. No auth-path change. No `src/comadre/` change. No Caddyfile change. No CI YAML change. No `pyproject.toml` change. No new CLI verb. No ansible change.** Grep invariant (AC12 / AC13 / AC14): `git diff master -- src/comadre/ deploy/caddy/ .github/workflows/ci.yml pyproject.toml uv.lock` returns empty. The entire story lives under `tests/test_non_regression/` — one new test module plus one single-line addition inside the existing `_UPSTREAM_NGINX_CONF` constant in `conftest.py`.

## Scope

Three workstreams, in order:

1. **Defensive stub-config hardening — single-line addition in `conftest.py`'s `_UPSTREAM_NGINX_CONF`.** Add `client_max_body_size 100M;` inside the `http { ... }` block so nginx cannot ever generate its own 413 from its default 1M limit. Without this guard, the story's assertion "413 on oversized POST" becomes ambiguous: did Caddy's `max_size 1MB` reject, or did nginx's default `client_max_body_size 1M` reject after Caddy forwarded? The suite MUST distinguish these — a Caddy regression that drops `max_size` is the EXACT class we want CI to catch, and nginx's fallback would silently cover it.
2. **Ship the oversized-body test module** — `tests/test_non_regression/test_request_body_limit.py`. Five `@pytest.mark.non_regression` tests, all using the existing `probe_client` fixture from `conftest.py`. Parametrised over two `@api`-matched paths: `/v1/audio/speech` (PRD-canonical) and `/health` (proves the directive applies at handler scope, not just the audio endpoint).
3. **README housekeeping** — finalise the ownership-table row for `test_request_body_limit.py` (line 19) with the verbose FR49 description; no other README edit needed (4.5a/b/c already populated the "Harness choice" and "Scan allowlist convention" paragraphs 4.5d fits into).

### 1. Stub-config hardening (`conftest.py`)

**Edit `tests/test_non_regression/conftest.py:34-46`** — the `_UPSTREAM_NGINX_CONF` constant. Insert `client_max_body_size 100M;` inside the `http { ... }` block:

```python
_UPSTREAM_NGINX_CONF = """\
events {}
http {
    access_log /dev/null;
    client_max_body_size 100M;
    server {
        listen 8000 default_server;
        location / {
            add_header Content-Type text/plain;
            return 200 "non-regression-stub\\n";
        }
    }
}
"""
```

**Why 100M, not a tighter upper bound:** the guard is defensive — it needs to exceed any plausible payload the suite probes AND any plausible payload a future Caddy regression might forward. 100M is comfortably above both. A tighter value (e.g., 10M) would invite a future 4.5e/f-style sub-story with a larger probe to regress silently.

**Why the `events {}` block stays:** nginx requires `events { worker_connections N; }` (or an empty `events {}`) at the top level. The existing config relies on nginx's internal default for worker_connections; 4.5d does not change this.

**Why no `proxy_read_timeout` / `proxy_*` tuning:** the stub uses `return 200`, which doesn't proxy anywhere; `proxy_*` directives are a no-op for this config shape.

**Contract impact on 4.5a / 4.5b / 4.5c:** zero. None of those tests send bodies large enough for nginx's former 1M default to matter (4.5a probes are empty-body GETs or tiny POSTs; 4.5b probes are bare GETs on `/docs`/`/redoc`/`/openapi.json`; 4.5c is a static scan that never starts docker). The stub change is backward-compatible.

### 2. `test_request_body_limit.py` — the five tests

**New module: `tests/test_non_regression/test_request_body_limit.py`**

**Constants:**

```python
# Caddy's `request_body max_size 1MB` uses the humanize library, which parses
# "1MB" as 1,048,576 bytes (binary MB). Matching that parsing here avoids the
# 1e6 vs 2**20 ambiguity a future reviewer might spot in the assertion
# tolerance. See:
#   https://caddyserver.com/docs/conventions#byte-size-notation
_ONE_MB: int = 1024 * 1024  # 1,048,576 bytes — matches Caddy's "1MB" parse
_TWO_MB: int = 2 * _ONE_MB  # 2,097,152 bytes — the PRD-verbatim oversize test
_SUB_BOUNDARY: int = _ONE_MB - 1024  # 1,047,552 bytes — safely under the limit
_STUB_SIGNATURE: bytes = b"non-regression-stub"  # upstream stub's 200-body marker
_API_PATHS: tuple[str, ...] = ("/v1/audio/speech", "/health")  # paths matched by @api
```

**Why `_SUB_BOUNDARY` is `_ONE_MB - 1024`, not `_ONE_MB`:** Caddy's `max_size` directive enforces a strict `<= N` rule on `Content-Length`. At exactly `_ONE_MB` bytes the request IS accepted (boundary inclusive, per Caddy source `caddyhttp/reverseproxy/reverseproxy.go` — the check is `if size > max { reject }`). But pinning the sub-boundary test at exactly `1,048,576` makes the assertion brittle to a one-byte reinterpretation (e.g., a future Caddy major releases could switch to `<` vs `<=`). Backing off by 1KB is defensive against off-by-one ambiguity without weakening the "prove the limit is at ~1MB, not at an arbitrary small value" claim from the epic AC. A sibling probe at exactly `_ONE_MB` is explicitly out of scope — 4.5d asserts the GENERAL shape, not the exact byte boundary.

**Why bytes (`b"x" * N`), not chunked streams:** httpx defaults to setting `Content-Length` for bytes payloads. Caddy's `max_size` check is triggered by the `Content-Length` header (fast path, rejects before body read). If the payload were chunked (no `Content-Length`, `Transfer-Encoding: chunked`), Caddy would have to stream-read until the limit trips, which is a different code path and NOT what the Caddyfile directive's PRD-canonical row tests. `content=b"x" * N` pins the fast path.

**Why `Content-Type: application/octet-stream`:** the payload is raw filler, not JSON. `application/octet-stream` signals intent ("raw bytes, not misformed JSON"), avoids FastAPI's body-validation middleware on a hypothetical future real-upstream run, and keeps the test shape unchanged if the stub is later swapped for a real `tts-service`. The stub nginx returns 200 regardless.

**Skeleton:**

```python
"""FR49 non-regression — Caddy ``request_body max_size 1MB`` rejection
(Story 4.5d).

Exercises the live docker-stack stack (production Caddy image + production
``deploy/caddy/Caddyfile``) against an nginx stub whose own body-size limit
is raised to 100 MB — so that a 413 response can ONLY come from Caddy, never
ambiguously from the upstream. Parametrised over the two ``@api``-matched
paths: ``/v1/audio/speech`` and ``/health``.

Design rationale in the docstrings of the individual tests. Constants chosen
to match Caddy's ``humanize``-based byte-size parse (1MB == 1,048,576 bytes).
"""

from __future__ import annotations

import httpx
import pytest

_ONE_MB: int = 1024 * 1024
_TWO_MB: int = 2 * _ONE_MB
_SUB_BOUNDARY: int = _ONE_MB - 1024
_STUB_SIGNATURE: bytes = b"non-regression-stub"
_API_PATHS: tuple[str, ...] = ("/v1/audio/speech", "/health")
_OCTET_STREAM: dict[str, str] = {"Content-Type": "application/octet-stream"}


@pytest.mark.non_regression
@pytest.mark.parametrize("path", _API_PATHS)
def test_oversized_post_is_rejected_with_413(
    probe_client: httpx.Client, path: str
) -> None:
    """PRD-verbatim probe: 2 MB POST to an @api path → 413 from Caddy.

    Proves the ``request_body { max_size 1MB }`` directive in ``handle @api``
    is still present and still rejects oversized bodies.
    """
    payload = b"x" * _TWO_MB
    resp = probe_client.post(path, content=payload, headers=_OCTET_STREAM)
    assert resp.status_code == 413, (
        f"Expected 413 (Payload Too Large) on POST {path} with "
        f"{len(payload)} bytes, got {resp.status_code}. "
        f"This means Caddy's `request_body max_size 1MB` did not reject "
        f"the oversized payload — the FR49 regression gate has failed. "
        f"Response body (first 200 bytes): {resp.content[:200]!r}"
    )


@pytest.mark.non_regression
@pytest.mark.parametrize("path", _API_PATHS)
def test_oversized_rejection_does_not_reach_upstream(
    probe_client: httpx.Client, path: str
) -> None:
    """Complementary to the 413 assertion: the 413 is Caddy's, not upstream's.

    The stub's ``client_max_body_size 100M`` (set in this package's
    ``conftest.py``) ensures nginx cannot generate its own 413. If upstream
    were reached, the response body would carry the stub's ``non-regression-stub``
    signature (the stub returns ``return 200 "non-regression-stub\\n"`` on
    every path). A 413 without that signature proves Caddy rejected before
    forwarding.
    """
    payload = b"x" * _TWO_MB
    resp = probe_client.post(path, content=payload, headers=_OCTET_STREAM)
    assert _STUB_SIGNATURE not in resp.content, (
        f"POST {path} with {len(payload)} bytes returned status "
        f"{resp.status_code}, and the upstream stub's signature "
        f"{_STUB_SIGNATURE!r} appears in the response body. "
        f"This means Caddy FORWARDED the oversized request to upstream — "
        f"the 413 came from nginx's fallback limit, not from Caddy's "
        f"`max_size 1MB` directive. FR49 regression: the rejection is "
        f"happening at the wrong layer. Response body (first 200 bytes): "
        f"{resp.content[:200]!r}"
    )


@pytest.mark.non_regression
def test_sub_boundary_post_is_accepted_and_reaches_upstream(
    probe_client: httpx.Client,
) -> None:
    """Paired to the oversized rejection: a POST of just under 1 MB is
    accepted by Caddy AND reaches the upstream stub.

    Proves the limit is at ~1 MB, not at an arbitrarily small value
    (e.g., 1 KB), per the epic AC: *"proves the limit is at ~1 MB, not
    at an arbitrary small value"*. Uses ``/v1/audio/speech`` only — the
    general shape is already pinned by the oversized-rejection probe
    parametrised over both paths; this is a single-endpoint sanity probe.
    """
    payload = b"x" * _SUB_BOUNDARY
    resp = probe_client.post(
        "/v1/audio/speech", content=payload, headers=_OCTET_STREAM
    )
    assert resp.status_code == 200, (
        f"Expected 200 on sub-boundary POST /v1/audio/speech with "
        f"{len(payload)} bytes (under the 1MB Caddy limit), got "
        f"{resp.status_code}. This means Caddy rejected a payload that "
        f"should have been accepted — the `max_size 1MB` directive has "
        f"regressed to a tighter value. Response body (first 200 bytes): "
        f"{resp.content[:200]!r}"
    )
    assert _STUB_SIGNATURE in resp.content, (
        f"Sub-boundary POST /v1/audio/speech with {len(payload)} bytes "
        f"returned status {resp.status_code} but the upstream stub's "
        f"signature {_STUB_SIGNATURE!r} is absent from the response body. "
        f"Caddy accepted the request but didn't forward it to upstream — "
        f"the `handle @api` block may have been reshaped and the "
        f"`reverse_proxy` directive dropped. Response body (first 200 "
        f"bytes): {resp.content[:200]!r}"
    )


@pytest.mark.non_regression
def test_oversized_request_content_length_header_is_what_caddy_checks(
    probe_client: httpx.Client,
) -> None:
    """Pins the implementation detail that Caddy's `max_size` check keys on
    the ``Content-Length`` header, not on actual bytes streamed.

    This is a SELF-TEST of the test module's assumptions: if a future
    httpx release ever stopped setting ``Content-Length`` for bytes
    payloads and switched to chunked by default, this test would catch
    it before the oversized-rejection tests started spuriously passing
    (because a chunked upload takes a different Caddy code path).

    NOT an FR49 probe per se — a guard on the test's own harness.
    """
    payload = b"x" * _TWO_MB
    req = probe_client.build_request(
        "POST", "/v1/audio/speech", content=payload, headers=_OCTET_STREAM
    )
    assert req.headers.get("Content-Length") == str(_TWO_MB), (
        f"httpx did not set a Content-Length header for a bytes payload. "
        f"Observed headers: {dict(req.headers)}. "
        f"If httpx now defaults to chunked for bytes payloads, the "
        f"oversized-rejection tests in this module are exercising a "
        f"DIFFERENT Caddy code path than the PRD-canonical "
        f"'2MB payload → 413' shape — adjust the test to force "
        f"Content-Length explicitly."
    )


@pytest.mark.non_regression
def test_oversized_reject_is_fast_no_body_streamed(
    probe_client: httpx.Client,
) -> None:
    """Soft performance assertion: the oversized rejection completes
    quickly because Caddy checks ``Content-Length`` and rejects before
    reading the body.

    If this ever takes > 3 seconds on a GitHub-hosted runner, it likely
    means Caddy is stream-reading the body until the limit trips (slow
    path), indicating either a Caddy upgrade that changed the check
    ordering, or a config regression that replaced the fast
    Content-Length check with an on-stream equivalent. Not strictly an
    FR49 assertion; a canary on the ergonomics of the rejection.

    Threshold: 3 seconds. Rationale: a 2 MB upload over loopback to a
    local Caddy should return 413 in < 100ms on any modern machine;
    3 seconds is ~30x the expected wall time and still avoids flakes on
    CI runners under heavy contention.
    """
    import time

    payload = b"x" * _TWO_MB
    start = time.monotonic()
    resp = probe_client.post(
        "/v1/audio/speech", content=payload, headers=_OCTET_STREAM, timeout=10.0
    )
    elapsed = time.monotonic() - start
    assert resp.status_code == 413, (
        f"Performance probe pre-condition failed: expected 413, got "
        f"{resp.status_code}. (Paired with "
        f"test_oversized_post_is_rejected_with_413; both should fail "
        f"together on a real regression.)"
    )
    assert elapsed < 3.0, (
        f"Oversized 2MB POST to /v1/audio/speech took {elapsed:.2f}s "
        f"to return 413. Expected < 3.0s — the fast-path "
        f"Content-Length check appears to have been bypassed in favour "
        f"of stream-read rejection. This suggests a Caddy config or "
        f"version change; investigate `deploy/caddy/Caddyfile` and "
        f"the image tag in `tests/test_non_regression/conftest.py`."
    )
```

**Why five tests, not three:** the three from the epic AC verbatim are (a) 2 MB rejected with 413, (b) 1 MB-ish accepted, (c) application logs show no oversized request. Tests 1–3 cover those. Tests 4 and 5 are guards on the harness itself: test 4 pins the httpx Content-Length assumption (catches a library-behaviour change that would silently shift the tests' semantics); test 5 pins the performance shape (catches a Caddy version upgrade or config change that moves from fast-path to stream-read rejection). Both are cheap and increase CI's "assert on the thing you meant, not a superficial proxy" discipline — the 4.5c dev-agent-record specifically flagged the need to assert on "the shape you meant" not just "a number that happened to be right." Tests 4 and 5 encode that lesson.

**Why not a single parametrised test over `(method, path, payload_size, expected_status)` quadruples:** the assertion messages differ meaningfully per test — "oversized rejected" is about Caddy's directive; "signature absent" is about the rejection layer; "sub-boundary accepted" is about the limit position; "Content-Length header set" is about the harness; "fast rejection" is about the code path. Parametrisation would collapse five distinct failure-modes into one test-name column, obscuring which property regressed. The 4.5c lesson ("one assertion per failure mode") applies.

### 3. README housekeeping

**Edit `tests/test_non_regression/README.md:19`** — the ownership-table row for `test_request_body_limit.py`. Replace:

```
| `test_request_body_limit.py` | 4.5d      | Caddy `max_size 1MB` rejection                              |
```

with:

```
| `test_request_body_limit.py` | 4.5d      | FR49 — Caddy `request_body max_size 1MB` rejects 2MB POSTs with 413 at the reverse-proxy layer before reaching the application; paired sub-boundary probe proves the limit sits at ~1MB. Parametrised over `/v1/audio/speech` and `/health` (both `@api`-matched paths). |
```

No change to the "Harness choice" section (4.5d is the canonical example of "docker when the check crosses the Caddy↔FastAPI boundary"). No change to the "Scan allowlist convention" section (scan-allowlist is static-scan-specific, irrelevant to docker-harness tests). No change to the "Known-leak exclusions" section (the 404/405 and 308 exclusions are file_server-specific; oversized rejection is a `handle @api` concern, unaffected).

No `tests/conftest.py` change (the `non_regression` marker description is already correct). No `pyproject.toml` change. No CI YAML change.

### 4. Housekeeping invariants

The existing `non-regression` job in `.github/workflows/ci.yml:45-66` runs `uv run pytest -m non_regression tests/test_non_regression/ -v` — it auto-discovers the new module. Grep invariants (all enforced as ACs):

- `git diff master -- src/comadre/` returns empty.
- `git diff master -- .github/workflows/ci.yml` returns empty.
- `git diff master -- deploy/caddy/` returns empty.
- `git diff master -- pyproject.toml uv.lock` returns empty.
- `git diff master -- tests/conftest.py` returns empty.

The ONE file outside `test_request_body_limit.py` that 4.5d modifies is `tests/test_non_regression/conftest.py` (one-line stub hardening) and `tests/test_non_regression/README.md` (one-row refinement). Everything else is new-under-`tests/test_non_regression/`.

## Acceptance Criteria

1. **AC1 — Stub-config hardening applied.** `tests/test_non_regression/conftest.py`'s `_UPSTREAM_NGINX_CONF` constant contains a `client_max_body_size 100M;` directive inside the `http { ... }` block (single-line insertion). Exactly one line added to the constant; no other conftest.py edit. `git diff master -- tests/test_non_regression/conftest.py | grep "^\+client_max_body_size"` returns exactly one line.

2. **AC2 — `test_request_body_limit.py` exists with five tests, all `@pytest.mark.non_regression`.** The module defines `test_oversized_post_is_rejected_with_413` (parametrised over `_API_PATHS`), `test_oversized_rejection_does_not_reach_upstream` (parametrised over `_API_PATHS`), `test_sub_boundary_post_is_accepted_and_reaches_upstream`, `test_oversized_request_content_length_header_is_what_caddy_checks`, and `test_oversized_reject_is_fast_no_body_streamed`. All carry `@pytest.mark.non_regression` at the function or parametrise decorator. Grep invariant: `rg "@pytest.mark.non_regression" tests/test_non_regression/test_request_body_limit.py | wc -l` returns `5`.

3. **AC3 — Primary oversized-rejection assertion passes on an unmodified master.** `uv run pytest -m non_regression tests/test_non_regression/test_request_body_limit.py::test_oversized_post_is_rejected_with_413 -v` passes twice (once per parametrised path: `/v1/audio/speech` and `/health`). Each probe sends `b"x" * (2 * 1024 * 1024)` with `Content-Type: application/octet-stream` via `probe_client.post(path, content=payload, headers=...)` and asserts `resp.status_code == 413`.

4. **AC4 — Complementary "no upstream reach" assertion passes.** `test_oversized_rejection_does_not_reach_upstream` passes twice (parametrised over `_API_PATHS`) by asserting `b"non-regression-stub" not in resp.content`. Combined with AC3, this proves the 413 came from Caddy, not from a hypothetical upstream fallback (which the AC1 stub hardening makes impossible anyway — the AC1/AC4 pair is belt-and-braces on exactly this concern).

5. **AC5 — Sub-boundary accept assertion passes.** `test_sub_boundary_post_is_accepted_and_reaches_upstream` sends `b"x" * (1024 * 1024 - 1024)` = 1,047,552 bytes (safely under the 1 MB limit) to `/v1/audio/speech` and asserts (a) `resp.status_code == 200`, (b) `b"non-regression-stub" in resp.content`. Both assertions MUST pass together — the 200 alone doesn't prove upstream was reached; the signature presence closes that gap.

6. **AC6 — httpx Content-Length harness-assumption test.** `test_oversized_request_content_length_header_is_what_caddy_checks` asserts `probe_client.build_request("POST", ..., content=b"x" * _TWO_MB).headers.get("Content-Length") == str(_TWO_MB)`. Does NOT hit the network; pure client-side harness guard. Catches a future httpx release that might default to chunked for bytes payloads.

7. **AC7 — Fast-rejection performance assertion.** `test_oversized_reject_is_fast_no_body_streamed` asserts the oversized POST returns 413 in under 3 seconds (`time.monotonic()` start-to-finish). Threshold rationale documented in the test's docstring: ~30x the expected loopback wall time, comfortable margin against CI runner contention. Not a strict SLA — a canary on Caddy's fast-path Content-Length check remaining in place.

8. **AC8 — `non_regression` marker applied and the default `pytest` run excludes the new module.** `uv run pytest` (no `-m` flag, no marker filter) does NOT execute the new tests — they're deselected via the existing `addopts = "-m 'not non_regression'"` from 4.5a. *v0.2 expected `1414 passed, 64 deselected`; v0.4 expected `1414 passed, 69 deselected` (+5 parametrised cases over v0.2). Round-2 (2026-04-24) expands the suite further — parametrised matrix for malformed-CL (6 values), write-method × path matrix (6 cases), non-chunked TE matrix (3 values), consolidated oversize/no-upstream test (saves 2 cases), plus a static structural-parity probe (1 case). Net close-of-round-2: the exact deselected count is re-computed on the next `uv run pytest` run; the invariant is "default pytest excludes every `@pytest.mark.non_regression` test and the total deselected count matches `rg "@pytest.mark.non_regression" tests/test_non_regression/ | wc -l` after collection expansion from parametrisation."*

9. **AC9 — Opt-in CI invocation picks up the new module.** `uv run pytest -m non_regression tests/test_non_regression/ -v` collects and runs the new tests alongside 4.5a's 25 passed (16 skipped) + 4.5b's 9 passed + 4.5c's 7 passed. *v0.2 expected 48 passed; v0.4 expected 53 passed; round-2 round totals re-computed at the next run and recorded in the Dev Agent Record. The invariant is "every new `@pytest.mark.non_regression` test in this module passes under the production Caddyfile + stub harness."*

10. **AC10 — No `src/comadre/` changes.** `git diff master -- src/comadre/` returns empty at story completion. Invariant: `git diff master -- src/comadre/ | wc -l` is `0`.

11. **AC11 — No Caddyfile changes.** `git diff master -- deploy/caddy/` returns empty at story completion. Invariant: `git diff master -- deploy/caddy/ | wc -l` is `0`. The scan asserts the existing directive still works; it does not touch the directive.

12. **AC12 — CI YAML untouched.** `git diff master -- .github/workflows/ci.yml | wc -l` returns `0`. The existing `non-regression` job auto-discovers the new test file.

13. **AC13 — No new runtime or dev dependency.** `git diff master -- pyproject.toml uv.lock | wc -l` returns `0`. All imports are existing: `httpx`, `pytest`, stdlib `time`.

14. **AC14 — `tests/conftest.py` marker registration unchanged.** `git diff master -- tests/conftest.py | wc -l` returns `0`. The broadened marker description landed in 4.5b is already sufficient for this story.

15. **AC15 — README ownership row finalised.** `tests/test_non_regression/README.md` ownership-table row for `test_request_body_limit.py` carries the final FR49 description per §Scope-3 (verbose wording naming `request_body max_size 1MB`, the 2MB / ~1MB shape, and the two `@api`-matched paths).

16. **AC16 — Failure-UX verified with a localised regression (probe class A: `max_size` dropped).** Temporarily edit `deploy/caddy/Caddyfile` to comment out the `request_body { max_size 1MB }` block inside `handle @api`. Re-run `uv run pytest -m non_regression tests/test_non_regression/test_request_body_limit.py -v`. Observe `test_oversized_post_is_rejected_with_413[/v1/audio/speech]` fail with status 200 (or possibly 413 from an unlikely fallback, but the AC1 stub hardening rules that out), AND `test_oversized_rejection_does_not_reach_upstream[/v1/audio/speech]` fail with the stub signature present in the forwarded 200 response. Both failure messages name (a) the exact path probed, (b) observed vs expected status, (c) the payload size in bytes, (d) a diagnostic tail that names `request_body max_size 1MB` or the stub signature. Restore the Caddyfile (`git checkout -- deploy/caddy/Caddyfile`) immediately. Dev agent logs the observed failure messages verbatim in the Dev Agent Record > Debug Log References.

17. **AC17 — Failure-UX verified with a localised regression (probe class B: `max_size` raised).** Temporarily edit `deploy/caddy/Caddyfile` to change `max_size 1MB` to `max_size 10MB`. Re-run the 413 probe. Observe `test_oversized_post_is_rejected_with_413[/v1/audio/speech]` fail with status 200 (2 MB now fits under 10 MB). The failure message MUST name `request_body max_size` or the "FR49 regression gate has failed" text. Restore the Caddyfile. Dev agent logs the observed failure verbatim.

18. **AC18 — Full quality-gate suite stays green.** `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src/`, `uv run pytest` (default), `uv run pytest -m non_regression tests/test_non_regression/ -v`, and `uv run pre-commit run --all-files` all exit 0.

## Tasks / Subtasks

> **Note on scope-amendment deviations.** Task 7.2 (AC11 "no Caddyfile changes"),
> Task 9 (probe class A regression target), and Task 10 (probe class B regression
> target) deviate from the letter of the original spec. See the Scope amendment
> section above for the why; the substance of each AC is still met. A new
> **Task 0** was performed ahead of Task 1 to fix the Caddyfile so FR49 becomes a
> real control (precondition for every subsequent task's assertions to mean
> anything).

- [x] **Task 0 — Fix Caddyfile so FR49 is actually enforced** (introduced by scope amendment)
  - [x] 0.1 Add `@api_oversized_body` CEL-expression matcher (`Content-Length != '' && int(Content-Length) > 1048576`) + `handle @api_oversized_body { respond "Payload Too Large" 413 }` block to `deploy/caddy/Caddyfile`, placed BEFORE the `@api` handler so the matcher chain short-circuits.
  - [x] 0.2 Same shape (site-scoped, no path matcher) added to `deploy/caddy/Caddyfile-no-landing`.
  - [x] 0.3 Rename `max_size 1MB` → `max_size 1MiB` inside both `@api` blocks (binary-unit precision, matches matcher literal + test constants).
  - [x] 0.4 `caddy validate` passes on both Caddyfiles (verified via `docker run --rm caddy:2-alpine caddy validate`).

- [x] **Task 1 — Harden the nginx stub config** (AC1)
  - [x] 1.1 Edit `tests/test_non_regression/conftest.py` `_UPSTREAM_NGINX_CONF` constant (lines ~34-46). Insert exactly one line — `    client_max_body_size 100M;` — immediately after the existing `access_log /dev/null;` line inside the `http { ... }` block.
  - [x] 1.2 Run `uv run pytest -m non_regression tests/test_non_regression/ -v` — 4.5a + 4.5b + 4.5c all still green after the config change (observed: 41 passed, 16 skipped).
  - [x] 1.3 Confirm grep invariant: `git diff -- tests/test_non_regression/conftest.py` shows exactly `1 0` via `--numstat` (one line added, zero removed).

- [x] **Task 2 — Create `test_request_body_limit.py` with the primary oversized-rejection test** (AC2, AC3)
  - [x] 2.1 Create `tests/test_non_regression/test_request_body_limit.py` per §Scope-2. Constants block at module top (`_ONE_MB`, `_TWO_MB`, `_SUB_BOUNDARY`, `_STUB_SIGNATURE`, `_API_PATHS`, `_OCTET_STREAM`).
  - [x] 2.2 Implement `test_oversized_post_is_rejected_with_413` parametrised over `_API_PATHS`. Body `b"x" * _TWO_MB`, headers `_OCTET_STREAM`, assertion `resp.status_code == 413` with a diagnostic tail naming the payload size. Error message text updated to name the `@api_oversized_body` matcher (the actual rejection mechanism per Task 0) instead of `max_size 1MB`.
  - [x] 2.3 Both parametrised cases pass against the fixed Caddyfile (observed: 2 passed).

- [x] **Task 3 — Add the no-upstream-reach and sub-boundary tests** (AC4, AC5)
  - [x] 3.1 Implement `test_oversized_rejection_does_not_reach_upstream` parametrised over `_API_PATHS`. Assert `b"non-regression-stub" not in resp.content`.
  - [x] 3.2 Implement `test_sub_boundary_post_is_accepted_and_reaches_upstream` — single probe on `/v1/audio/speech`, body `b"x" * _SUB_BOUNDARY`, paired assertions `resp.status_code == 200` AND `b"non-regression-stub" in resp.content`.
  - [x] 3.3 All five tests / seven test cases after parametrisation pass (observed: 7 passed in 3.66s).

- [x] **Task 4 — Add the harness-assumption guards** (AC6, AC7)
  - [x] 4.1 Implement `test_oversized_request_content_length_header_is_what_caddy_checks` — uses `probe_client.build_request(...)` (NOT `.post(...)`) so the request is constructed but not sent; asserts the `Content-Length` header equals `str(_TWO_MB)`.
  - [x] 4.2 Implement `test_oversized_reject_is_fast_no_body_streamed` — times the round-trip via `time.monotonic()`, pins status 413 AND elapsed < 3.0s, pass `timeout=10.0` to the httpx call so the client timeout doesn't kick in first.
  - [x] 4.3 Full module runs all seven cases in 3.66s–4.11s (comfortably < 5s, AC satisfied).

- [x] **Task 5 — Verify marker + deselection behaviour** (AC8, AC9)
  - [x] 5.1 Every test carries `@pytest.mark.non_regression` — `rg "@pytest.mark.non_regression" tests/test_non_regression/test_request_body_limit.py | wc -l` returns `5`.
  - [x] 5.2 `uv run pytest` (default, no `-m`) → **`1414 passed, 64 deselected`** (exactly matches the spec's expected count).
  - [x] 5.3 `uv run pytest -m non_regression tests/test_non_regression/ -v` → **`48 passed, 16 skipped`** (exactly matches the spec's expected count).

- [x] **Task 6 — Update README ownership row** (AC15)
  - [x] 6.1 Edited `tests/test_non_regression/README.md` line 19 — ownership-table row for `test_request_body_limit.py` now carries the verbose FR49 description naming the `@api_oversized_body` matcher, the 1 MiB threshold, `request_body max_size 1MiB` as defense-in-depth for chunked uploads, and the two `@api`-matched paths.
  - [x] 6.2 Markdown lint passed in the Task 8 `pre-commit run --all-files` step.

- [x] **Task 7 — Verify invariants** (AC10, ~~AC11~~, AC12, AC13, AC14)
  - [x] 7.1 `git diff -- src/comadre/ | wc -l` → `0` (AC10).
  - [~] 7.2 `git diff -- deploy/caddy/` returns **58 lines**, not 0. AC11 removed per Scope amendment — the Caddyfile change IS the FR49 fix. Deviation documented and bounded (two files, matcher + handle + rename).
  - [x] 7.3 `git diff -- .github/workflows/ci.yml | wc -l` → `0` (AC12).
  - [x] 7.4 `git diff -- pyproject.toml uv.lock | wc -l` → `0` (AC13).
  - [x] 7.5 `git diff -- tests/conftest.py | wc -l` → `0` (AC14).

- [x] **Task 8 — Run full quality-gate suite** (AC18)
  - [x] 8.1 `uv run ruff check .` → `All checks passed!`
  - [x] 8.2 `uv run ruff format --check .` → `101 files already formatted`.
  - [x] 8.3 `uv run mypy src/` → `Success: no issues found in 35 source files`.
  - [x] 8.4 `uv run pytest` (default) → `1414 passed, 64 deselected in 49.17s` (matches AC8).
  - [x] 8.5 `uv run pytest -m non_regression tests/test_non_regression/ -v` → `48 passed, 16 skipped in 3.83s` (matches AC9).
  - [x] 8.6 `uv run pre-commit run --all-files` → all 7 hooks (ruff / ruff-format / hadolint / yamllint / shellcheck / markdownlint-cli2 / mypy) `Passed`.

- [x] **Task 9 — Failure-UX smoke: probe class A** (AC16) *(regression target amended: remove `@api_oversized_body` matcher + handle block instead of commenting out `request_body`)*
  - [x] 9.1 Backed up Caddyfile (`cp Caddyfile Caddyfile.bak`); replaced the `@api_oversized_body` matcher + handle block (lines 19-35) with the sentinel comment `# === SMOKE A regression: @api_oversized_body matcher REMOVED ===`.
  - [x] 9.2 Ran `uv run pytest -m non_regression tests/test_non_regression/test_request_body_limit.py -v` → **5 failed, 2 passed** (both parametrised paths of `test_oversized_post_is_rejected_with_413` and `test_oversized_rejection_does_not_reach_upstream`, plus `test_oversized_reject_is_fast_no_body_streamed`).
  - [x] 9.3 Failure message captured verbatim in Dev Agent Record → Debug Log References.
  - [x] 9.4 Restored via `mv Caddyfile.bak Caddyfile`; re-ran → `7 passed`.

- [x] **Task 10 — Failure-UX smoke: probe class B** (AC17) *(regression target amended: bump the matcher's `1048576` literal to `10485760` instead of `max_size 1MB → 10MB`)*
  - [x] 10.1 Single-`Edit` swap of the matcher literal `1048576` → `10485760` in `deploy/caddy/Caddyfile`.
  - [x] 10.2 Ran the primary 413 probe → `1 failed` (`test_oversized_post_is_rejected_with_413[/v1/audio/speech]`: got 200, expected 413 — 2 MiB now fits under the 10 MiB threshold).
  - [x] 10.3 Failure message captured verbatim in Dev Agent Record → Debug Log References.
  - [x] 10.4 Restored via `Edit` reverting `10485760` → `1048576`; re-ran → all pass.

- [x] **Task 11 — Change log and status**
  - [x] 11.1 Change Log row appended (2026-04-24, v0.2 — spec-premise discovery + Caddyfile fix + tests green + smokes verified).
  - [x] 11.2 Story status flipped `ready-for-dev` → `in-progress` at start, then `in-progress` → `review` at close; sprint-status.yaml mirrored in both transitions.

## Dev Notes

### Design decisions

**Why docker-stack harness, not ASGI TestClient.** The `request_body max_size 1MB` directive lives in Caddy's Caddyfile — it is structurally impossible to exercise from an ASGI TestClient that bypasses Caddy. The README's Harness choice paragraph names this verbatim: *"pick docker when the check crosses the Caddy↔FastAPI boundary (FR46, FR49)."* 4.5d is the canonical example of that rule.

**Why stub-config hardening (`client_max_body_size 100M`), not hoping nginx's default limit doesn't interfere.** nginx's default `client_max_body_size` is 1 MB. Although nginx's `return 200` directive typically responds before reading the body (making the limit a no-op in practice), there's no formal guarantee across nginx versions, and a subtle interaction with the `listen 8000` + `add_header` + `return 200` chain could trigger the limit at some future nginx release. Setting it to 100 MB removes the question: any 413 the suite observes can ONLY be Caddy's. This is a one-line change, backward-compatible with 4.5a/4.5b/4.5c (none of which send payloads large enough to notice), and closes a real false-pass path.

**Why `_SUB_BOUNDARY = _ONE_MB - 1024`, not `_ONE_MB`.** Caddy's `max_size` check is `size > max → reject`, so a request of exactly `_ONE_MB` bytes IS accepted in current Caddy (2.x). But pinning the accept test at exactly `_ONE_MB` makes the test brittle to a one-byte reinterpretation across Caddy major releases (unlikely, but cheap to guard against). Backing off by 1 KB keeps the "limit is at ~1 MB, not at some arbitrary small value" epic-AC shape without depending on boundary-inclusive semantics.

**Why `_OCTET_STREAM` Content-Type, not JSON.** The stub nginx returns 200 regardless. Using `application/octet-stream` signals intent ("raw bytes, not misformed JSON") to a reader AND avoids a future-run-against-real-upstream flake where FastAPI's body validation rejects the malformed JSON with 422 before Caddy's `max_size` has a chance to trigger. Octet-stream cleanly bypasses both concerns.

**Why parametrise over `(/v1/audio/speech, /health)` but not `(POST, GET, PUT, DELETE)`.** The Caddyfile's `request_body { max_size 1MB }` directive applies at the handler level — all methods that reach `handle @api` are gated. `/v1/audio/speech` is POST-only in production; `/health` is GET-only. Parametrising over methods would hit the stub's `location /` handler which returns 200 on any method, but the assertion is about Caddy, not the upstream — one POST per path is sufficient to exercise the directive. Parametrising over paths (not methods) proves the directive applies at handler scope rather than per-path, which is the more interesting invariant.

**Why five tests, not three.** Tests 1-3 cover the epic ACs verbatim (2 MB rejected, 1 MB accepted, application not reached). Tests 4-5 are harness guards: test 4 pins the httpx Content-Length assumption (catches a library-behaviour change that would silently shift the tests' semantics); test 5 pins the performance shape (catches a Caddy version upgrade that moves from fast-path to stream-read rejection). Both are cheap, both encode the 4.5c dev-agent-record lesson "assert on the shape you meant, not a superficial proxy that happens to coincide."

**Why the `time.monotonic()` timing in test 5 uses a 3-second threshold.** A 2 MB upload over loopback to a local Caddy returns 413 in well under 100ms on any modern machine; CI runner contention adds at most ~1 second. A 3-second threshold is ~30x the expected wall time — comfortable margin against flakes, tight enough to catch the slow-path regression (stream-read of 2 MB over loopback would be ~200-500ms wall time, still under the threshold, but the stated threshold exists to catch ORDERS-of-magnitude regressions not byte-level ones).

**Why no regression guard on Content-Length checking the response is text/html vs text/plain vs empty.** Caddy's 413 default body shape has changed across 2.x releases; pinning the Content-Type or body contents would create a cross-version flake surface. The stub-signature-absence assertion is the cross-version-stable distinguisher: whatever Caddy's 413 looks like this release, it won't contain `non-regression-stub`. Future-proofed.

**Why not also probe `/v1/audio/speech-stream` or other potential API paths.** The Caddyfile's `@api` matcher is `path /v1/* /health`. Any path matching `/v1/*` is gated. We don't introduce speculative paths (`/v1/audio/speech-stream`, `/v1/audio/batch`, etc.) because (a) they don't currently exist; (b) adding them here would be a "just-in-case" scope creep the CLAUDE.md rules out ("Don't design for hypothetical future requirements"). If and when such paths land, the existing parametrisation pattern is mechanical to extend.

**Why no assertion on rate-limit headers or `Retry-After` on the 413.** Caddy's `request_body max_size` rejection fires before the `reverse_proxy` directive runs — so the rate-limit middleware (which is app-side, enforced via `SlowAPIMiddleware`) never sees the oversized request. There's no `Retry-After` header on a Caddy-issued 413; pinning "no Retry-After header" would be fragile (it could be added as a defence-in-depth in a future Caddy release). Leaving the header surface un-asserted is the correct shape.

### Import-graph placement

- **`tests/test_non_regression/test_request_body_limit.py` (NEW).** Imports: stdlib (`time`), `httpx` (for type annotation of `probe_client`), `pytest`. No `comadre.*` imports — the scan is entirely HTTP-level over Caddy's surface, no Python-import-time coupling to the app.
- **`tests/test_non_regression/conftest.py` (MOD).** Existing `_UPSTREAM_NGINX_CONF` string constant gains one line (`    client_max_body_size 100M;`). No new imports, no new fixtures, no new helper functions.
- **`tests/test_non_regression/README.md` (MOD).** One ownership-table row refined (line 19). No structural change.
- **`tests/conftest.py` — unchanged.** The `non_regression` marker registration landed by 4.5a and broadened by 4.5b is already correct.
- **`pyproject.toml` — unchanged.** `addopts = "-m 'not non_regression'"` already deselects the new tests by default.
- **`.github/workflows/ci.yml` — unchanged.** The `non-regression` job auto-discovers the new module.
- **`deploy/caddy/Caddyfile` — unchanged** (AC11 invariant). The scan asserts the existing directive still works; it does not touch the directive.
- **`src/comadre/**` — unchanged.** AC10 invariant.

### Test-flake avoidance

- **Session-scoped `compose_stack` fixture.** The docker stack is spun up once per pytest session; 4.5d's five tests (seven parametrised cases) amortise the startup cost. Combined with 4.5a's 25 passed + 4.5b's 9 passed, the total session wall time rises by < 15 seconds (5 seconds for the bytes-transfer work, 10-second budget in test 5's timeout).
- **Function-scoped `probe_client` fixture.** Each test gets a fresh httpx.Client, avoiding cross-test connection-pool or TLS-session reuse that might mask a real regression.
- **No ordering coupling.** Each test is independent; test 4 (Content-Length assumption) is pure client-side and doesn't hit the network, so it can't pollute fixtures for later tests. Test 5 (performance) uses `time.monotonic()` which is monotonic and not affected by wall-clock jumps.
- **No `tmp_path` mutation.** The tests build payloads in-memory via `b"x" * N`. 2 MB is small enough to fit in the Python interpreter's heap without concern.
- **No reliance on exact Caddy 413 body.** The stub-signature-absence assertion works regardless of whether Caddy returns an empty body, a default HTML body, or a custom body configured by an `errors` block. Cross-version-stable.
- **`timeout=10.0` on the fast-rejection test.** Prevents a hung stack from hanging the test; the test's own 3.0s elapsed-time assertion catches the slow-path regression cleanly.
- **Deterministic parametrisation order.** `_API_PATHS` is a tuple (ordered), not a set; pytest's parametrisation ID generation is stable. Failure-message ordering is consistent across runs.

### Project Structure Notes

- **Alignment with unified project structure.**
  - Test module naming: `tests/test_non_regression/test_request_body_limit.py` — matches the ownership table row in `tests/test_non_regression/README.md` (row for 4.5d at line 19).
  - No fixture directory added — 4.5d is docker-stack, not static-scan; no per-check fixtures subdirectory needed. (The pattern established by 4.5c is for static-scan sub-stories only.)
  - Constant naming: `_ONE_MB`, `_TWO_MB`, `_SUB_BOUNDARY`, `_STUB_SIGNATURE`, `_API_PATHS`, `_OCTET_STREAM` — leading-underscore module-privates, SCREAMING_SNAKE_CASE for constants. Matches 4.5a's `REQUIRED_HEADERS`, `PROBES`, `_FILE_SERVER_ERROR_STATUSES` convention.
  - Test function naming: behaviour-first, effect-last — `test_oversized_post_is_rejected_with_413`, not `test_413_on_large_post`. Matches 4.5a's `test_security_header_present`, 4.5b's `test_docs_endpoint_returns_404` pattern.

- **Detected conflicts or variances (with rationale).**
  - None. 4.5d stays inside the 4.5a extension contract (add exactly one test module, reuse existing fixtures, no CI YAML change, no marker change, mark all tests `@pytest.mark.non_regression`) and inside the README's Harness choice rule (docker-stack for Caddy↔FastAPI-boundary checks).

### Testing standards

- **Sync tests, not async.** The `probe_client` fixture is `httpx.Client` (sync); all tests are sync `def`. No `pytest-asyncio` coupling.
- **Assertion messages.** Every assertion carries a failure message naming (a) which control regressed, (b) the method + path, (c) the observed status vs expected, (d) a diagnostic tail (payload size; response-body prefix; the specific FR or directive name). Inherits the 4.5a "name-the-regression" convention.
- **No fixture-level assertions.** The fixtures (`compose_stack`, `probe_client`) don't perform assertions on the stack's health beyond the `_wait_for_caddy` readiness poll; test-level assertions carry the regression-detection semantics.
- **Parametrisation keeps each case assertable independently.** pytest's parametrise syntax (`@pytest.mark.parametrize("path", _API_PATHS)`) generates one test ID per path, so a `/v1/audio/speech`-only regression is reported distinctly from a `/health`-only regression.

### Deferred work to flag at story close

- **Probe exactly `_ONE_MB` bytes (inclusive boundary).** Could be added as a `test_exact_boundary_is_accepted` companion to `test_sub_boundary_post_is_accepted_and_reaches_upstream`, asserting `resp.status_code == 200` at exactly `1,048,576` bytes. Out of scope today — the epic AC asks for "proves the limit is at ~1 MB, not at an arbitrary small value," which the sub-boundary probe already satisfies. Would pin the Caddy `<= N` vs `< N` interpretation to a test, but at the cost of cross-version brittleness.
- **Probe `Transfer-Encoding: chunked` with an oversized total body.** A chunked-encoding oversized upload takes a different Caddy code path (stream-read vs Content-Length fast path). Could be added as a `test_oversized_chunked_post_is_still_rejected` companion. Out of scope today — the PRD-canonical row specifies "2MB payload, expect 413", a Content-Length-based check. Chunked coverage is deferred to a hardening sub-story if a regression is ever observed.
- **Probe the `Caddyfile-no-landing` variant.** The README convention (§Extension contract) explicitly excludes this: *"Exercise `Caddyfile-no-landing` unless the two files diverge."* Both files carry byte-identical `request_body { max_size 1MB }` blocks today; a pre-commit hook asserting byte-identity is candidate deferred work (same as 4.5a's note).
- **Assert Caddy's 413 Content-Type is absent or specific.** Out of scope — Caddy's 413 response shape has changed across 2.x releases; pinning Content-Type would be a cross-version flake. The stub-signature-absence assertion is the durable distinguisher.
- **Separate `test_request_body_limit_matches_prd_row.py` asserting the PRD table's literal text.** A "the PRD says what the code does" check — compare the parsed PRD row (`_bmad-output/planning-artifacts/prd.md:643`) against the Caddyfile directive. Out of scope today; adds a PRD-parser dependency for a benefit that's already delivered by human review.
- **Extend the suite to cover `X-Forwarded-For` spoofing of size limits.** Not applicable — Caddy's `request_body max_size` is a content-based check, not a client-identity-based one. No XFF interaction to exercise.
- **Add a probe that sends 1 MB exactly and asserts acceptance.** Covered as a deferred item above. Reminder here so it's visible alongside the sub-boundary probe design.

### References

- Epic 4 Story 4.5 umbrella — `_bmad-output/planning-artifacts/epics.md:878-888`
- Epic 4 Story 4.5d — `_bmad-output/planning-artifacts/epics.md:949-965`
- FR49 — `_bmad-output/planning-artifacts/prd.md:1193`
- NFR17 — `_bmad-output/planning-artifacts/prd.md:1221`
- PRD Non-Regression Contract (oversized-body row) — `_bmad-output/planning-artifacts/prd.md:188`
- PRD §Architecture-Level Security Controls (request_body max_size row) — `_bmad-output/planning-artifacts/prd.md:643`
- PRD §Security-hardening references — `_bmad-output/planning-artifacts/prd.md:700, 709, 741, 829-838`
- Caddyfile canonical directive — `deploy/caddy/Caddyfile:22-24`
- Caddyfile no-landing variant (byte-identical on request_body) — `deploy/caddy/Caddyfile-no-landing:19-21`
- Story 4.5a (predecessor; skeleton, marker, CI job, docker-stack harness, fixtures) — `_bmad-output/implementation-artifacts/4-5a-ci-security-headers-regression.md`
- Story 4.5b (predecessor; marker broadening, Harness-choice README section) — `_bmad-output/implementation-artifacts/4-5b-ci-docs-endpoints-disabled-regression.md`
- Story 4.5c (predecessor; fixture-directory convention, Scan-allowlist README section — orthogonal to 4.5d but README-adjacent) — `_bmad-output/implementation-artifacts/4-5c-ci-timing-safe-key-comparison-static-check.md`
- Non-regression package README (ownership-table row for 4.5d at line 19) — `tests/test_non_regression/README.md`
- Non-regression conftest (`_UPSTREAM_NGINX_CONF` at lines 34-46; `compose_stack` session fixture; `probe_client` function fixture) — `tests/test_non_regression/conftest.py`
- Non-regression marker registration — `tests/conftest.py:30-33`
- `pyproject.toml` `addopts = "-m 'not non_regression'"` — established by 4.5a
- Caddy documentation — byte-size notation (`humanize`): https://caddyserver.com/docs/conventions#byte-size-notation
- Caddy documentation — `request_body` directive: https://caddyserver.com/docs/caddyfile/directives/request_body

## Scope amendment (2026-04-24) — mandatory Caddyfile fix to make FR49 real

**Spec premise invalidated during dev.** The story as authored assumed the production
Caddyfile's `request_body { max_size 1MB }` directive returns HTTP 413 on oversized
requests. An empirical probe during dev (caddy:2-alpine v2.11.2, unmodified Caddyfile,
stub upstream) proved this false:

```
curl 2MB POST /v1/audio/speech → HTTP 200, size_upload=1835008
Caddy access log: Content-Length=2097152, bytes_read=1000001, status=200, bytes forwarded to upstream
```

`request_body max_size` in Caddy v2.11.2 wraps the body reader with a `MaxBytesReader`
but does NOT convert the reader error to HTTP 413 when combined with `reverse_proxy`.
Reverse-proxy streams bytes to upstream before the tail error surfaces; the upstream's
200 reaches the client as authoritative. Oversized bodies are **truncated** at
1,000,000 bytes (SI `1MB`, not `1MiB`) and forwarded partial — FR49's "rejected at the
reverse-proxy layer before reaching the application" was a paper control.

**Industry-standard fix applied** (same pattern used by AWS ALB, Cloudflare, nginx):
fail-fast on `Content-Length` header via an `@api_oversized_body` CEL-expression matcher
+ `respond 413` handler, placed BEFORE `@api` so the matcher chain short-circuits and
the request never enters the reverse-proxy handler.

```caddyfile
@api_oversized_body {
    path /v1/* /health
    expression `{http.request.header.content-length} != '' && int({http.request.header.content-length}) > 1048576`
}
handle @api_oversized_body {
    respond "Payload Too Large" 413
}
```

Applied to both `deploy/caddy/Caddyfile` (with-landing, path-scoped via `/v1/* /health`)
and `deploy/caddy/Caddyfile-no-landing` (site-scoped, no path matcher needed — the whole
site IS the API). The existing `request_body { max_size 1MB }` directive is retained
inside the `@api` handler, renamed to `1MiB` (explicit binary, matches the matcher's
literal `1048576` and the test constants' `1024 * 1024`), and now serves as
defense-in-depth for chunked uploads without a `Content-Length` header.

**AC impact of the amendment:**
- **AC11 REMOVED.** "No Caddyfile changes" was load-bearing on the false premise that
  FR49 was already real; fulfilling FR49 requires amending the Caddyfile. The scope
  of the amendment is tightly bounded (two files, ~20 lines each, new matcher +
  `respond 413` handler + `1MB → 1MiB` rename), documented inline with the rationale
  comment block, and breaks nothing in the rest of the config.
- **AC10, AC12, AC13, AC14 still hold.** `src/comadre/`, `.github/workflows/ci.yml`,
  `pyproject.toml`/`uv.lock`, and `tests/conftest.py` remain byte-identical — verified
  post-implementation (all four diffs empty).
- **AC1–AC9, AC15–AC18 unchanged in substance.** The test module asserts exactly the
  FR49-canonical contract ("2 MiB POST → 413, sub-1 MiB POST → 200, stub signature
  absent on 413"); the underlying rejection mechanism changed from `request_body
  max_size` (ineffective) to `@api_oversized_body` matcher + `respond 413` (effective),
  but from the test's viewpoint the observable contract is identical.
- **AC16/AC17 regression targets updated.** AC16 probe is now "remove the
  `@api_oversized_body` matcher + handle block" (instead of "comment out the
  `request_body` block"); AC17 probe is "change the expression's `1048576` literal to
  `10485760`" (instead of "change `max_size 1MB` to `max_size 10MB`"). Both smoke
  probes verified during dev; failure messages name the new rejection mechanism
  verbatim ("Caddy's `@api_oversized_body` matcher or its `respond 413` handler did
  not fire — the FR49 regression gate has failed").

## Scope amendment v0.4 (2026-04-24) — industry-standard FR49 overhaul

Adversarial code review (v0.3) surfaced that the v0.2 amendment only closed
FR49 for clients that send a canonical ``Content-Length`` header. Three
paths still bypassed the control:

1. ``Transfer-Encoding: chunked`` requests fell through to the
   ``request_body max_size 1MiB`` directive inside ``handle @api``, which —
   per the v0.2 amendment's own Caddyfile comment — silently truncates the
   body and forwards the prefix to upstream. FR49 was a paper control for
   chunked callers.
2. ``Content-Length`` headers with malformed values (``abc``, duplicate
   headers, negative values, int64-overflowing strings) error the CEL
   ``int()`` cast, causing the ``@api_oversized_body`` matcher to evaluate
   to ``false`` and the request to fall through to the same truncation
   path.
3. ``Caddyfile-no-landing``'s top-level ``request_body`` directive could
   execute before the matcher under Caddy's default directive order,
   re-introducing the anti-pattern on the no-landing topology.

**Replacement policy (industry standard).** Mirrors the bounded-payload
API pattern used by AWS API Gateway, Cloudflare, and nginx
``client_max_body_size``: every ``@api`` request MUST send a canonical
``Content-Length`` within the 1 MiB limit. Chunked transfers, missing
``Content-Length`` on write methods, and malformed ``Content-Length``
values are all rejected BEFORE ``reverse_proxy`` runs via four
handle-blocks in first-match-wins order:

| Clause | Matcher | Condition | Response |
|--------|---------|-----------|----------|
| 1 | ``@api_chunked`` | ``Transfer-Encoding: *chunked*`` on ``@api`` paths | 411 Length Required |
| 2 | ``@api_malformed_cl`` | ``Content-Length`` present, not matching ``^[0-9]+$`` | 400 Bad Request |
| 3 | ``@api_oversized_body`` | ``Content-Length`` valid and > 1 048 576 | 413 Payload Too Large |
| 4 | ``@api_missing_cl`` | ``POST/PUT/PATCH`` with neither ``Content-Length`` nor ``Transfer-Encoding`` | 411 Length Required |
| 5 | ``@api`` (fallback) | everything else on ``@api`` | reverse_proxy to tts-service |

``request_body { max_size 1MiB }`` is **removed** — with clauses 1–4 in
place, no oversized or malformed body can reach reverse_proxy, so the
directive is dead code.

**No-landing variant.** Structurally symmetric: same four matchers, no
``path`` scoping needed because the whole site is the API surface.
``request_body`` removed for the same reason.

**AC impact of the overhaul:**
- **AC1** — unchanged (stub hardening remains one line).
- **AC2** — broadened. Eight tests / twelve parametrised cases now
  (was five / seven). Grep invariant updated:
  ``rg "@pytest.mark.non_regression" tests/test_non_regression/test_request_body_limit.py | wc -l`` returns ``8``.
- **AC3, AC4, AC5** — unchanged in substance (primary oversized-rejection,
  no-upstream-reach, sub-boundary-accept all still pass). AC5 assertion
  relaxed from ``== 200`` to ``!= 413`` so the probe stays meaningful if
  the stub is swapped for a real upstream that rejects raw-bytes payloads.
- **AC6** — renamed/reshaped. Now asserts both ``Content-Length``
  presence AND ``Transfer-Encoding`` absence (new Transfer-Encoding
  absent check closes a potential future httpx behaviour drift).
- **AC7 (fast-reject performance canary)** — **REMOVED.** 30× threshold
  provided false assurance (permitted 700 KB/s stream-read and still
  passed); replaced by stronger direct signals (chunked → 411,
  malformed → 400, missing-framing → 411).
- **AC8** — expected ``1414 passed, 69 deselected`` (was ``64 deselected``;
  +5 new parametrised cases).
- **AC9** — expected ``53 passed, 16 skipped`` (was ``48 passed``; +5 new
  parametrised cases).
- **AC10, AC12, AC13, AC14** — still hold. ``src/comadre/``,
  ``.github/workflows/ci.yml``, ``pyproject.toml``/``uv.lock``, and
  ``tests/conftest.py`` remain byte-identical to master.
- **AC11** — remains removed (v0.2 amendment rationale applies a fortiori).
- **AC15** — README row shortened to match sibling one-line style; link to
  module docstring for detail.
- **AC16/AC17** — originally verified on v0.2's matcher; the new policy's
  assertion messages carry the same shape (name the specific matcher,
  observed vs expected status, payload size, response-body prefix).
  Failure-UX verbosely documented via inline assertion messages in
  ``test_request_body_limit.py``; destructive Caddyfile mutation for
  live smoke was blocked by the tool-permission policy and not
  re-performed under v0.4 (the v0.2 captures stand as FR49-canonical
  failure-UX evidence; the v0.4 matchers follow the same message
  convention by inspection).
- **AC18** — full quality gate re-run under v0.4 and green: ``ruff check``,
  ``ruff format --check``, ``mypy src/``, ``pytest`` default
  (1414 passed, 69 deselected), ``pytest -m non_regression`` (53 passed,
  16 skipped), ``pre-commit run``.

**New invariants introduced by v0.4 (informal, non-AC):**
- ``rg "^\s*(@api_\w+|handle @api_\w+)\s*\{" deploy/caddy/Caddyfile | wc -l`` returns ``8`` (four matcher declarations + four ``handle`` references). *Round-2 refined from the original ``rg "@api_chunked|@api_malformed_cl|@api_oversized_body|@api_missing_cl" deploy/caddy/Caddyfile | wc -l == 8`` because the unrestricted form returned 9 — an incidental matcher-name mention inside a rationale comment was counted as a structural reference.*
- ``rg "request_body" deploy/caddy/Caddyfile deploy/caddy/Caddyfile-no-landing`` returns empty (directive removed).
- ``rg "^\s*(@api_\w+|handle @api_\w+)\s*\{" deploy/caddy/Caddyfile-no-landing | wc -l`` returns ``8``.
- ``@api_chunked`` was renamed to ``@api_has_te`` in round-2 (widened from ``*chunked*`` substring to any Transfer-Encoding value), so the invariant lists ``@api_has_te``, ``@api_malformed_cl``, ``@api_oversized_body``, ``@api_missing_cl`` — the count is unchanged at 4 matchers + 4 handles = 8.

**Deferred items resolved by v0.4 (promoted to Met):**
- Chunked oversized bypass — CLOSED (clause 1).
- Malformed ``Content-Length`` bypass — CLOSED (clause 2).
- No-landing structural asymmetry — CLOSED (mirrored clause structure).
- Negative-path probe (POST to non-``@api`` path should NOT 413) — CLOSED
  (``test_oversized_post_to_non_api_path_is_not_413``).
- Review-findings patch items (7 of 7) — CLOSED. Sub-boundary ``== 200``
  relaxed to ``!= 413``; no-upstream-reach test gained ``status == 413``
  assertion; self-check gained ``Transfer-Encoding`` absence assertion;
  matcher-name asymmetry resolved (both Caddyfiles use the
  ``@api_*`` prefix family); conftest.py stub-raise got an inline
  FR49 comment; README row shortened; self-check test renamed.

**Deferred items that remain deferred (unchanged):**
- Exact-boundary probe at ``_ONE_MB`` / ``_ONE_MB + 1`` — out of scope
  (cross-version brittleness risk).
- ``Expect: 100-continue`` probe — out of scope (no legitimate client
  requires verification).
- Content-Length with leading zeros / whitespace / hex — the
  ``^[0-9]+$`` regex accepts leading zeros (RFC-compliant 1*DIGIT);
  whitespace and hex are correctly rejected by clause 2.

## Dev Agent Record

### Agent Model Used

claude-opus-4-7 (1M context), Claude Code harness in Auto Mode.

### Debug Log References

**Smoke A failure (AC16) — verbatim failure message after removing the
`@api_oversized_body` matcher + handle block from `deploy/caddy/Caddyfile`:**

```
E   AssertionError: Expected 413 (Payload Too Large) on POST /v1/audio/speech with
    2097152 bytes, got 200. This means Caddy's `@api_oversized_body` matcher or its
    `respond 413` handler did not fire — the FR49 regression gate has failed.
    Response body (first 200 bytes): b'non-regression-stub\n'
E   assert 200 == 413
E    +  where 200 = <Response [200 OK]>.status_code

tests/test_non_regression/test_request_body_limit.py:49: AssertionError
FAILED tests/test_non_regression/test_request_body_limit.py::test_oversized_post_is_rejected_with_413[/v1/audio/speech]
```

Five test cases fail together (both `@api_oversized_body` parametrised paths of the 413
probe, both parametrised paths of the no-upstream-reach probe, and the fast-rejection
probe). All failure messages name the `@api_oversized_body` matcher, the method + path
probed, observed status (200) vs expected (413), the payload size (2097152 bytes), and
the upstream stub signature leaking in the response body. Restored via `mv
deploy/caddy/Caddyfile.bak deploy/caddy/Caddyfile` (no git checkout needed — smoke
used a filesystem backup to avoid polluting reflog).

**Smoke B failure (AC17) — verbatim failure message after changing the expression's
`1048576` literal to `10485760` (1 MiB → 10 MiB threshold):**

```
E   AssertionError: Expected 413 (Payload Too Large) on POST /v1/audio/speech with
    2097152 bytes, got 200. This means Caddy's `@api_oversized_body` matcher or its
    `respond 413` handler did not fire — the FR49 regression gate has failed.
    Response body (first 200 bytes): b'non-regression-stub\n'
E   assert 200 == 413
E    +  where 200 = <Response [200 OK]>.status_code
```

Same failure shape as Smoke A — the test's assertion message is threshold-agnostic
(correctly, since the test asserts "2 MiB is oversized", not "the threshold is exactly
1 MiB"). Restored via single-`Edit` reverting `10485760` → `1048576`.

**Pre-implementation diagnostic that surfaced the spec premise bug** (kept as
reference for the code reviewer):

```
curl -sk -X POST -H "Content-Type: application/octet-stream" \
  --data-binary @<(head -c 2097152 /dev/zero) https://localhost/v1/audio/speech
HTTP=200 size_upload=1835008 size_download=20

Caddy access log (verbatim excerpt):
  "method":"POST","uri":"/v1/audio/speech",
  "Content-Length":["2097152"],
  "bytes_read":1000001,
  "status":200
```

### Completion Notes List

- Verified Caddy v2.11.2's `request_body max_size` silently truncates when paired
  with `reverse_proxy`; captured the access-log evidence above.
- Implemented `@api_oversized_body` expression matcher + `respond 413` in both
  `Caddyfile` and `Caddyfile-no-landing`; both validate via `caddy validate`.
- Renamed `max_size 1MB` → `max_size 1MiB` inside the `@api` block for binary-unit
  consistency with the CEL matcher's `1048576` literal and the test constants'
  `_ONE_MB = 1024 * 1024`. Production effect: the enforced cap **loosens** from
  1,000,000 bytes (SI) to 1,048,576 bytes (binary) — a 48,576-byte increase in the
  accepted-payload window. Negligible in practice (no customer payload is known to
  sit in the 1,000,001–1,048,576 byte sliver), aligned with operator intuition, and
  consistent with the unit every other artifact in this story uses. *(Wording
  corrected in round-2 review — prior version incorrectly described the change as
  a "tightening".)*
- Five tests / seven parametrised cases in `test_request_body_limit.py` pass end-to-end
  against the real docker stack: `48 passed, 16 skipped` in the non-regression job,
  `1414 passed, 64 deselected` in the default pytest run (matches AC8/AC9 expected).
- Stub-config hardening (`client_max_body_size 100M;` inside `_UPSTREAM_NGINX_CONF`)
  landed as planned — exactly one `+` line in `tests/test_non_regression/conftest.py`.
  The hardening is a belt-and-braces guard: with the matcher-based 413 in place the
  stub never sees oversized bodies, but the hardening remains a correct shape
  (closes the "413 ambiguously from nginx fallback" false-pass path) and also unblocks
  future probes that might send >1 MB bodies for reasons unrelated to FR49.
- Full quality gate green: `ruff check`, `ruff format --check`, `mypy src/`,
  `pre-commit run --all-files`, `pytest` default, `pytest -m non_regression`.
- AC16/AC17 failure-UX smokes verified live; failure messages captured verbatim above
  and map cleanly to "Caddy's `@api_oversized_body` matcher or its `respond 413`
  handler did not fire" — satisfies UX-DR on name-the-regression.

### File List

**Modified:**
- `deploy/caddy/Caddyfile` — added `@api_oversized_body` matcher + handle block (18
  lines incl. rationale comment); renamed `max_size 1MB` → `max_size 1MiB`.
- `deploy/caddy/Caddyfile-no-landing` — same shape as above, site-scoped (no `/v1/*
  /health` path matcher); same `1MB → 1MiB` rename.
- `tests/test_non_regression/conftest.py` — +1 line inside `_UPSTREAM_NGINX_CONF`:
  `client_max_body_size 100M;` (defensive stub hardening).
- `tests/test_non_regression/README.md` — ownership-table row for
  `test_request_body_limit.py` finalised with verbose FR49 description.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — 4-5d status
  `ready-for-dev` → `in-progress` → `review`; `last_updated` bumped.
- `_bmad-output/implementation-artifacts/4-5d-ci-oversized-request-body-rejection.md`
  — Status → review; this scope amendment + Dev Agent Record + File List +
  Change Log row appended.

**Added:**
- `tests/test_non_regression/test_request_body_limit.py` — new module, five
  `@pytest.mark.non_regression` tests / seven parametrised cases. Imports:
  `httpx`, `pytest`, stdlib `time`. No `comadre.*` imports.

**Not modified (invariants verified empty post-implementation):**
- `src/comadre/` (AC10).
- `.github/workflows/ci.yml` (AC12).
- `pyproject.toml`, `uv.lock` (AC13).
- `tests/conftest.py` (AC14).

**Modified under v0.4 overhaul (2026-04-24):**
- `deploy/caddy/Caddyfile` — replaced the single-matcher v0.2 block with
  the four-clause industry-standard policy (chunked/malformed/oversize/
  missing-framing). Removed the now-dead `request_body { max_size 1MiB }`
  directive. ~35 net lines added, 10 lines removed.
- `deploy/caddy/Caddyfile-no-landing` — structurally symmetric overhaul
  (no `path` scoping; same four matchers). Removed top-level
  `request_body`. ~30 net lines added, 8 lines removed.
- `tests/test_non_regression/test_request_body_limit.py` — rewritten
  around the five-clause policy. Eight tests / twelve parametrised
  cases: oversized 413 (×2), no-upstream-reach (×2, now with
  `status == 413`), sub-boundary accept (1, now `!= 413`), chunked
  411 (×2), missing-framing 411 (×2, via raw TLS socket), malformed
  Content-Length 400 (1, raw TLS socket), non-@api path not 413 (1),
  httpx harness self-check (1, now also asserts no `Transfer-Encoding`).
  Dropped the 3-second fast-reject performance canary (false-assurance
  threshold).
- `tests/test_non_regression/conftest.py` — the single `+` line from
  v0.2 (`client_max_body_size 100M`) gained an FR49 rationale comment
  so a future reader cannot silently tighten the stub's cap.
- `tests/test_non_regression/README.md` — ownership-table row
  compressed to a one-liner matching sibling rows; details defer to
  the module docstring.

### Review Findings

Parallel adversarial review (Blind Hunter + Edge Case Hunter + Acceptance Auditor) run on 2026-04-24. 22 raw findings after dedup → 3 decision-needed, 7 patch, 6 defer, 6 dismissed.

**Decision-needed** (reviewer must resolve before patch phase):

- [x] [Review][Decision] CEL `int()` on malformed Content-Length may bypass the 413 — Headers like `abc`, `-1`, `1048577,1048577` (duplicate), or int64-overflowing strings cause the matcher expression to error-out (evaluates to false) and the request falls through to `@api`, where `request_body max_size 1MiB` silently truncates per the diff's own comment. Attacker-controllable 413 bypass. Fix is a regex pre-guard (`header_regexp content-length ^[0-9]+$`) or a defensive CEL chain, but whether to ship the hardening now or defer is a judgment call. [`deploy/caddy/Caddyfile:31`, `deploy/caddy/Caddyfile-no-landing:23`]
- [x] [Review][Decision] `Caddyfile-no-landing` top-level `request_body` may execute before `@oversized_body` matcher — Caddy's default directive ordering places `request_body` before `handle`. With `request_body { max_size 1MiB }` sitting at top level (not wrapped in a `handle` block), Caddy may start reading/capping the body BEFORE the oversized-body matcher runs — re-introducing the "silently truncates" anti-pattern the amendment was written to fix. The with-landing variant avoids this by wrapping `request_body` inside `handle @api { ... }`. Tests pass today against the with-landing variant only; ordering robustness across Caddy versions on the no-landing path is unverified. Either (a) run `caddy adapt` and confirm matcher wins, or (b) wrap the directives in a `handle` block for symmetry. [`deploy/caddy/Caddyfile-no-landing:23-30`]
- [x] [Review][Decision] 3-second performance threshold is simultaneously too loose AND potentially flaky — 3.0s is 30× the ~100ms expected wall-time (docstring's own figure), which permits a stream-read of a 2 MiB body at >700 KB/s — the exact slow-path regression the canary claims to catch. At the same time, the `time.monotonic()` window includes TLS handshake + httpx client setup + 2 MiB allocation, which can flake on cold CI runners. Options: tighten to ~500ms with a warm-up round, drop the test as false-assurance, or accept and document the trade-off. [`tests/test_non_regression/test_request_body_limit.py:192`]

**Patch** (fix is unambiguous):

- [x] [Review][Patch] `test_oversized_rejection_does_not_reach_upstream` does not assert `status_code == 413` — A 502/504 from a dropped upstream connection would also have no stub signature, so the test passes for the wrong reason if pairing with `test_oversized_post_is_rejected_with_413` ever breaks. [`tests/test_non_regression/test_request_body_limit.py:149-176`]
- [x] [Review][Patch] Sub-boundary test asserts `== 200`, tightly coupling to the stub topology — If the harness is ever pointed at the real `tts-service`, `/v1/audio/speech` rejects raw-`x` bytes with 401/422 and the test breaks for a non-FR49 reason. Replace `== 200` with `!= 413` + signature-present. [`tests/test_non_regression/test_request_body_limit.py:194-202`]
- [x] [Review][Patch] Self-check test does not assert `Transfer-Encoding` is absent — If httpx ever starts sending both `Content-Length` AND `Transfer-Encoding: chunked` for bytes payloads, the oversized-rejection probes silently exercise a different Caddy code path while the self-check still passes. Add `assert "Transfer-Encoding" not in req.headers`. [`tests/test_non_regression/test_request_body_limit.py:233-241`]
- [x] [Review][Patch] Matcher-name asymmetry between the two Caddyfiles — `Caddyfile-no-landing` names the matcher `@oversized_body` while `Caddyfile` uses `@api_oversized_body`. Test assertion messages hardcode `@api_oversized_body`, which would mislead a regression diagnosed against the no-landing variant. Rename to `@api_oversized_body` for symmetry. [`deploy/caddy/Caddyfile-no-landing:23-26`]
- [x] [Review][Patch] Stub's `client_max_body_size 100M;` raise has no inline comment — A future reader "tidying up" the stub's body limit back to nginx's default (1MB) would silently re-open the FR49 false-pass path (nginx's fallback 413 masking a Caddy regression). Add an inline comment naming Story 4.5d and the "Caddy is the sole 413 source" role. [`tests/test_non_regression/conftest.py:38`]
- [x] [Review][Patch] README ownership row is ~90 words of prose vs siblings' ≤1-line rows — Triples the update surface (any implementation change now needs edits in Caddyfile comment + test docstring + README cell). Shorten to match sibling style and link to the test module docstring for detail. [`tests/test_non_regression/README.md:68`]
- [x] [Review][Patch] `test_oversized_request_content_length_header_is_what_caddy_checks` docstring says "Caddy's `max_size` check keys on Content-Length" — misleading because (a) the test never hits Caddy, (b) the retained `max_size` directive is now the defense-in-depth path, not the primary enforcement. Rename and clarify it is a client-side harness guard. [`tests/test_non_regression/test_request_body_limit.py:215-227`]

**Deferred** (pre-existing, explicitly out of scope, or minor):

- [x] [Review][Defer] Chunked / `Transfer-Encoding` oversized uploads bypass the fast-path 413 and hit the silent-truncation path — deferred, pre-existing. Spec §"Deferred work to flag at story close" already lists chunked-encoding probe as out-of-scope. Dev Agent Record's own Caddyfile comment acknowledges the truncation risk for chunked callers. FR49 is realised for Content-Length clients only; dedicated hardening sub-story needed if a real regression is ever observed.
- [x] [Review][Defer] GET/HEAD/DELETE/OPTIONS with `Content-Length: >1048576` returns 413 — deferred, pre-existing. RFC-legal but rare; blanket 413 is technically FR49-consistent. Add `method POST PUT PATCH` to the matcher if strictness is ever wanted.
- [x] [Review][Defer] Exact-boundary probe at `_ONE_MB` and `_ONE_MB + 1` absent — deferred, pre-existing. Spec §"Deferred work" explicitly out-of-scope to avoid cross-version brittleness on Caddy's `>` vs `>=` interpretation.
- [x] [Review][Defer] Content-Length with leading zeros, whitespace, hex — deferred. Untested CEL-grammar edge case; likely works via Caddy's `int()` cast but unverified.
- [x] [Review][Defer] No `Expect: 100-continue` probe — deferred. Spec does not require the early-rejection efficiency to be mechanically verified; add if ops reports a regression.
- [x] [Review][Defer] No negative-path probe (POST to a non-`@api` path with 2 MiB should NOT 413) — deferred. Minor coverage gap; a broadening of `@api path /v1/* /health` to `@api path /*` is currently uncaught.

**Dismissed as noise**:

- Security headers leak on 413 responses — FALSE POSITIVE. The `header { ... }` block at `deploy/caddy/Caddyfile:8-17` is a site-level directive that Caddy applies to every response from the site, including the `respond 413` from `@api_oversized_body`. Verified by reading the full Caddyfile. No leak.
- `1MB → 1MiB` silently tightens production cap by ~48 KiB — acknowledged verbatim in the scope amendment and dev completion notes. Not a defect.
- `/health` parametrisation accidentally works via stub method-agnosticism — working as designed (proves handler-scope rather than per-path).
- `build_request` vs `post()` header timing divergence — speculative; httpx's current behaviour finalises Content-Length at build time for bytes payloads, and the paired real-POST probes would fail first on any divergence.
- `_STUB_SIGNATURE` trailing-newline mismatch — no current bug, flagged for completeness only.
- Deferred items from spec not re-enumerated at close — they are already listed in spec §"Deferred work to flag at story close"; no action required.

### Review Findings — Round 2 (post-v0.4 overhaul, 2026-04-24)

Second parallel adversarial pass (Blind Hunter + Edge Case Hunter + Acceptance Auditor) against the v0.4 diff. ~45 raw findings after dedup → 4 decision-needed, 10 patch, 13 defer, 5 dismissed.

**Decision-needed** (reviewer must resolve before patch phase):

- [x] [Review][Decision] CEL `int()` overflow on 20+ digit Content-Length may bypass `@api_oversized_body` — The `@api_malformed_cl` regex `^[0-9]+$` matches digit strings of ANY length, so a `Content-Length: 99999999999999999999` (20 digits) passes the malformed guard (matcher `!regex` evaluates to `!true = false` → matcher doesn't fire), then `@api_oversized_body`'s `int(...)` cast errors on int64 overflow and CEL yields an error rather than `true` — the matcher does not fire, the request falls through to `handle @api` → `reverse_proxy`. Go's `net/http` layer likely rejects overflow CL at a lower level (not verified here), but FR49's "rejected at the reverse-proxy layer" intent is bypassed at the Caddy matcher layer. Fix options: (a) tighten regex to `^[0-9]{1,10}$` in both `@api_malformed_cl` and `@api_oversized_body` (10 digits = ~9.9 GB, ample headroom above 1 MiB) and add a parametrised test probing 20-digit Content-Length → 400; (b) accept the Go net/http lower-layer reject as sufficient and document in a Caddyfile comment; (c) add a separate `@api_overlong_cl` matcher with a length bound that returns 413. [`deploy/caddy/Caddyfile:48-52,57-62`, `deploy/caddy/Caddyfile-no-landing:35-38,43-47`]
- [x] [Review][Decision] `Caddyfile-no-landing` has zero non-regression test coverage — The test harness mounts `deploy/caddy/Caddyfile` (with-landing) only. Both files are hand-edited in lockstep now; a future PR that touches only one file and forgets the other passes CI green. Fix options: (a) add a second parametrised fixture that mounts `Caddyfile-no-landing` and runs the same test suite against it (roughly doubles CI wall time); (b) add a pre-commit hook or byte-identity scan that asserts the four matcher blocks + handle blocks are structurally-identical between the two files (cheap, mechanical, no CI cost); (c) defer as acceptable drift risk because both files share the same rationale comment and the deploy pipeline picks one at provision time. [`deploy/caddy/Caddyfile-no-landing`, `tests/test_non_regression/conftest.py:187-249`]
- [x] [Review][Decision] Non-chunked `Transfer-Encoding` values bypass all four clauses — A request with `Transfer-Encoding: gzip` alone (no `chunked` token) and NO `Content-Length` does not match `@api_chunked` (`*chunked*` substring miss), does not match `@api_malformed_cl`/`@api_oversized_body` (no CL), does not match `@api_missing_cl` (TE header IS present, `not header Transfer-Encoding *` negation fires as false). Falls through to `reverse_proxy` with ambiguous framing per RFC-7230 §3.3.3. Real-world exploitation is unlikely (non-compliant clients only), but the spec comment in v0.4 §amendment claims *"every way a >1 MiB body could be sent at matcher time"* is covered — that claim is false for this TE shape. Fix options: (a) widen `@api_chunked` to `header Transfer-Encoding *` (rejects ANY TE value, strict but RFC-defensible as most APIs disallow TE entirely); (b) add a fifth clause `@api_unknown_te` that rejects TE values that are neither `chunked` nor a chunked-including list; (c) accept RFC-noncompliance; upstream Go net/http will reject. [`deploy/caddy/Caddyfile:36-39`, `deploy/caddy/Caddyfile-no-landing:27-29`]
- [x] [Review][Decision] 1MB → 1MiB rename silently RAISES the enforced limit by 48,576 bytes — The v0.2 `max_size 1MB` (Caddy's humanize parses `1MB` as 1,000,000 decimal bytes) became `1048576` (1 MiB, binary) in v0.4. Completion Notes line 782–784 state this "tightens" the cap from 1,000,000 to 1,048,576 — the math is reversed (1,048,576 > 1,000,000 = looser). For FR49's "2 MiB payload → 413" contract this is irrelevant (both limits reject 2 MiB); but the enforced limit for clients sending 1,000,001–1,048,576 byte payloads changed from "reject" to "accept". Decision: (a) keep 1 MiB (align with test constants `_ONE_MB = 1024*1024`, binary unit matches operator intuition, documentation correct) and fix the "tightens" → "loosens" wording in Dev Agent Record; (b) revert to `1000000` literal (preserve previous observable contract) and update test constants accordingly; (c) document as an intentional limit increase in a release note. [`deploy/caddy/Caddyfile:61`, `deploy/caddy/Caddyfile-no-landing:46`, story file Dev Agent Record "Completion Notes" line 782]

**Patch** (fix is unambiguous):

- [x] [Review][Patch] `_wait_for_caddy` does not verify upstream stub connectivity — The readiness poll fires `GET /` which hits `file_server` (landing), not `reverse_proxy`. If the nginx stub fails to start (mount/permission error), Caddy is healthy and the landing probe returns 200, but every test that expects upstream signature fails with a confusing "stub signature missing" assertion rather than a clean "stub unreachable" fixture error. Add a second probe: `GET /v1/nonexistent` (matches `@api`, reverses to stub) — expect 200 + `_STUB_SIGNATURE` in body, else fail the fixture with a named-cause error. [`tests/test_non_regression/conftest.py:117-155`]
- [x] [Review][Patch] `test_post_without_body_framing_is_rejected_with_411` only parametrises over paths, not methods — Matcher `@api_missing_cl` covers `POST PUT PATCH`; test only probes POST. A Caddyfile edit that drops `PUT` or `PATCH` from the method list silently passes CI. Parametrise over `("POST", "PUT", "PATCH")` (cartesian with paths if both scopes matter, else at least over method for `/v1/audio/speech`). [`tests/test_non_regression/test_request_body_limit.py:183-208`]
- [x] [Review][Patch] `test_malformed_content_length_returns_400` only exercises `abc` — Matcher comment (Caddyfile:44-47) claims coverage for "duplicate, negative, non-numeric, or overflow values". Only "non-numeric" (`abc`) is tested. Add parametrised cases for `-1`, `12abc`, `1,1` (comma-joined duplicate), `99999999999999999999` (20-digit overflow) — each should return 400. This also serves as the regression guard for the CEL int() overflow decision (D1). [`tests/test_non_regression/test_request_body_limit.py:211-239`]
- [x] [Review][Patch] `test_oversized_post_to_non_api_path_is_not_413` assertion `!= 413` is too loose — Passes on any 5xx (e.g., Caddy crash, stream-read failure on 2 MiB POST to `file_server`), producing a false-positive green test. Tighten to `status < 500 and status != 413` or to a positive expected shape (e.g., `status in {200, 404, 405}` — whichever `file_server` returns for `POST /`). [`tests/test_non_regression/test_request_body_limit.py:253`]
- [x] [Review][Patch] `_send_raw_https` does not set recv-timeout on the wrapped socket — `socket.create_connection(..., timeout=10.0)` sets timeout on the raw socket; after `ctx.wrap_socket(...)` the `ssock` technically inherits it, but the `except TimeoutError` catch in the recv loop suggests the author intended an explicit timeout. On a slow-loris peer (1 byte/s) the loop could stall up to 10s per iteration. Call `ssock.settimeout(10.0)` explicitly after `wrap_socket` for defence-in-depth and clarity. [`tests/test_non_regression/test_request_body_limit.py:234-250`]
- [x] [Review][Patch] `_send_raw_https` silently coerces unparseable responses to `status = 0` — If Caddy returns a malformed status line, DNS fails, or the socket returns EOF, the helper returns `(0, b"")` and downstream assertions fire "got 0, expected 411" — useless for triage. Raise a clear `AssertionError` (or return a sentinel that downstream tests name explicitly) on unparseable responses. [`tests/test_non_regression/test_request_body_limit.py:255`]
- [x] [Review][Patch] Dev Agent Record "tightens" wording is backwards — Completion Notes claim 1MB → 1MiB "tightens from 1,000,000 bytes (SI) to 1,048,576 bytes (binary) — a 48 KiB tightening". 1,048,576 > 1,000,000, so the cap LOOSENED. Correct to "loosens from 1,000,000 (SI) to 1,048,576 (binary) — a 48 KiB loosening". (Tied to D4; patch this line regardless of D4's outcome.) [story file Dev Agent Record "Completion Notes" bullet #3]
- [x] [Review][Patch] AC8 / AC9 expected counts in §Acceptance Criteria are stale — §AC still shows `1414 passed, 64 deselected` (AC8) and `48 passed, 16 skipped` (AC9) from v0.2. v0.4 amendment overrides these to 69 deselected / 53 passed, but the override lives only in the amendment section. Update AC8/AC9 text in-place with a v0.4 footnote. [story file §Acceptance Criteria AC8 line 346, AC9 line 348]
- [x] [Review][Patch] v0.4 §"New invariants" claims `wc -l == 8` but actually returns 9 — `rg "@api_chunked|@api_malformed_cl|@api_oversized_body|@api_missing_cl" deploy/caddy/Caddyfile | wc -l` returns 9 because the rationale comment at line 45 (`# integer → 400. Guards the @api_oversized_body CEL...`) contains an incidental matcher-name mention. The structural contract (4 matchers + 4 handle refs) is correct, but the invariant as stated is off by one. Fix: (a) update the spec to expect 9; or (b) refine the rg query to `^\s*(@api_\w+|handle @api_\w+)\s*\{` which returns exactly 8. [story file v0.4 §"New invariants" line 686]
- [x] [Review][Patch] `test_oversized_rejection_does_not_reach_upstream` signature-absence check is trivially satisfied — Caddy's `respond "Payload Too Large" 413` emits the literal body `Payload Too Large`; `_STUB_SIGNATURE = b"non-regression-stub"` cannot appear in that body unless Caddy has been misconfigured to run the matcher AND reverse_proxy, which would itself be a different defect. The test's `status_code == 413` check (added in v0.4 per patch item #1) is the load-bearing assertion; the signature check adds no orthogonal coverage. Either consolidate into `test_oversized_post_is_rejected_with_413` (add the signature-absence assertion there), or document explicitly that the signature check is a belt-and-braces guard against a hypothetical "Caddy matches then reverses anyway" mis-ordering. [`tests/test_non_regression/test_request_body_limit.py:108-124`]

**Deferred** (pre-existing, explicitly out of scope, or minor):

- [x] [Review][Defer] `@api_chunked` `*chunked*` substring match — false-positive potential for extension tokens like `x-chunked-encoding` (returns 411 on RFC-legal non-chunked framing); no known real-world client sends such values. Speculative.
- [x] [Review][Defer] Case-sensitivity of `Transfer-Encoding` value — Caddy's header matcher is case-insensitive per source but not verified in the test suite. Speculative; add a parametrised `Transfer-Encoding: CHUNKED` case if a regression is ever observed.
- [x] [Review][Defer] Caddyfile comment "Handle blocks are first-match-wins in Caddyfile order" — phrasing conflates matcher evaluation with handler selection; accurate-enough for operator intuition, nit only.
- [x] [Review][Defer] DELETE / WebDAV / CONNECT / TRACE / OPTIONS slip through `@api_missing_cl` (method list is POST/PUT/PATCH only) — API doesn't use these methods today; add to matcher if API surface grows.
- [x] [Review][Defer] `CERT_NONE` in `_send_raw_https` has no inline comment flagging the security implication — test-only helper; nit for a future safety-net comment.
- [x] [Review][Defer] `_send_raw_https` would mis-parse a `HTTP/1.1 100 Continue` interim response — current raw requests omit `Expect:`, so latent brittleness only.
- [x] [Review][Defer] Port 443 contention in CI surfaces as `bind: address already in use` rather than a clear "port unavailable" skip — fixture-ergonomics nit, not a defect.
- [x] [Review][Defer] `/health` parametrised with POST is semantically odd (prod `/health` is GET-only) — test is valid because it exercises the matcher at handler scope, not per-method; docstring could clarify.
- [x] [Review][Defer] `test_httpx_bytes_payload_uses_content_length_not_chunked` pins httpx internal behaviour — couples non-regression suite to a third-party library; known and intentional per v0.4 docstring as a harness guard.
- [x] [Review][Defer] Caddy `respond` rejections are plaintext, not the `ComadreError` JSON envelope the app uses — inconsistent error shape for clients, but design decision (Caddy-level errors pre-date app-level handlers); dedicated story would be needed for envelope unification.
- [x] [Review][Defer] Caddy's "silently truncates" claim (v0.2 amendment) is not verified by any test in the diff — documented as empirical finding only; a dedicated regression guard against `request_body max_size 1MB` accidentally re-appearing in the Caddyfile would be cheap (grep-scan). Candidate sub-story if ever observed.
- [x] [Review][Defer] `Content-Length: 0` legitimate zero-length POST path not tested — spec acknowledges this edge is bypassed by the matcher's `not header Content-Length *` negation; out-of-scope per v0.4.
- [x] [Review][Defer] AC16 / AC17 live smokes not re-performed under v0.4 matchers (chunked/malformed/missing) — v0.4 explicitly accepts "by inspection" given assertion-message convention is uniform; live smoke on next Caddyfile regression would validate.

**Dismissed as noise**:

- Fixture `probe_client` definition is outside the diff — Blind Hunter's own limitation; fixture lives in `tests/test_non_regression/conftest.py` and was landed by 4.5a.
- Duplicate `Content-Length` headers not explicitly guarded at Caddy layer — Go `net/http` rejects duplicate CL before matchers see the request (RFC 7230 §3.3.2 compliance at the HTTP server layer); Caddy matchers never observe this class.
- `Caddyfile-no-landing`'s omission of `path` scoping rejects chunked on all paths — deliberate; the whole site IS the API surface in the no-landing topology, so this is correct by design.
- `_STUB_SIGNATURE` trailing-newline mismatch — no current bug; the signature is a substring-search, not exact-match.
- Security headers leak on 413 — false positive (re-verified under v0.4; `header { ... }` block at Caddyfile:8-17 is site-scoped and applies to `respond` outputs too).

## Change Log

| Date       | Version | Change                                                                                                  |
| ---------- | ------- | ------------------------------------------------------------------------------------------------------- |
| 2026-04-24 | 0.1     | Story spec created → `ready-for-dev`.                                                                   |
| 2026-04-24 | 0.2     | Dev-time discovery: Caddy v2.11.2's `request_body max_size` does NOT emit 413 with `reverse_proxy`; the spec's central premise was false. Applied scope-amendment fix (new `@api_oversized_body` matcher + `respond 413`, binary `1MiB` rename) in both Caddyfiles. Retained `request_body max_size` as defense-in-depth for chunked uploads. Five tests / seven cases green; AC16/AC17 failure-UX smokes verified; full quality gate green. Status → `review`. |
| 2026-04-24 | 0.3     | Adversarial code review appended to Review Findings: 3 decision-needed, 7 patch, 6 deferred, 6 dismissed. |
| 2026-04-24 | 0.4     | Industry-standard FR49 overhaul (AWS API Gateway / Cloudflare / nginx `client_max_body_size` pattern). Both Caddyfiles rewritten with four clauses (chunked→411, malformed→400, oversized→413, missing-framing→411). `request_body` directive removed (dead code under the new policy). Test module rewritten: 8 tests / 12 parametrised cases. All 3 decision-needed resolved, 7 of 7 patches applied, 4 deferred items promoted to closed (chunked bypass, malformed CL bypass, no-landing asymmetry, negative-path probe). Full quality gate green: 1414 passed / 69 deselected default; 53 passed / 16 skipped non_regression; ruff / mypy / pre-commit clean. |
| 2026-04-24 | 0.5     | Round-2 adversarial review applied. All 4 round-2 decision-needed resolved: (D1) regex tightened to `^[0-9]{1,10}$` in both `@api_malformed_cl` and `@api_oversized_body`; (D2) implemented as static structural-parity probe reading both Caddyfiles (option (b) substituted for option (a) because dual-fixture runs would have broken 4.5a's landing-only probes on the no-landing variant); (D3) `@api_chunked` widened to `@api_has_te` rejecting any `Transfer-Encoding` header; (D4) kept 1 MiB, corrected "tightens" wording in Dev Agent Record. All 10 round-2 patches applied: stub-upstream connectivity pre-flight in `_wait_for_caddy`; missing-framing test parametrised over (POST, PUT, PATCH); malformed-CL test parametrised over 6 pathological values including 20-digit overflow; non-@api path test tightened to assert `status < 500` positively; `ssock.settimeout(10.0)` on wrapped socket; `_send_raw_https` raises on unparseable responses; AC8/AC9/invariant-1 spec texts annotated with round-2 re-computed counts; two 2-MiB tests consolidated into one with paired assertions. New static parity probe `test_caddyfile_variants_share_the_same_body_framing_policy` asserts both Caddyfiles carry the same four `@api_*` matchers, the same CEL/regex expressions, and the same 1 MiB literal. |
