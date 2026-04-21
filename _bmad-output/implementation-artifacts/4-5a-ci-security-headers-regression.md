# Story 4.5a: CI — Security Headers Regression

Status: ready-for-dev

> **Scope note — FR46, NFR17.** Ships the FIRST of seven CI non-regression sub-stories (4.5a–4.5g). Because it lands first, it owns the **shared skeleton** every subsequent sub-story appends to: the non-regression test module namespace, a CI job (new file or extension of `.github/workflows/ci.yml`) that spins up the Caddy reverse proxy with the production Caddyfile against a stubbed upstream, reusable HTTP-probe helpers, and the `non_regression` pytest marker. On top of that skeleton, 4.5a asserts the FR46 contract: every response code Caddy emits over HTTPS carries the full security-header block (`Strict-Transport-Security`, `Content-Security-Policy` incl. the `upgrade-insecure-requests` directive, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`), with clear per-header failure diagnostics — AND the companion banner-strip contract (no `Server:` / `Via:` headers leaked), with the documented 404/308 leak (`feedback_caddy_server_header.md`) explicitly excluded from banner-strip but NOT from security-header presence. **No change to `src/comadre/`. No new Python dependency.** The work is pure test infra + CI wiring + one ansible-free integration test module that talks to a locally-spawned `docker compose` stack over loopback.

## Story

As a contributor,
I want every pull request against master to prove that every security header Caddy is configured to emit is actually present on every representative HTTPS response — and that Server/Via banner stripping still works outside the known, documented 404/308 leak — all verified automatically in CI with per-header failure diagnostics,
so that a well-meaning Caddyfile edit, an accidental `-Server`/`-Via` directive removal, a CSP directive drop (e.g. losing `upgrade-insecure-requests`), or an HSTS downgrade cannot land on master without the PR build turning red, and the turn-red message names exactly which header regressed on which status code.

**Covers FRs:** FR46 (CI can verify that every security header required by the Caddy configuration — HSTS, CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, `upgrade-insecure-requests` — is present on every response code returned by the reverse proxy).
**Partially covers:** the **Server/Via banner-stripping** row of the PRD Non-Regression Contract (`_bmad-output/planning-artifacts/prd.md:642`) — same Caddy `header` block, naturally co-tested in this story; 4.5a claims it now so no later sub-story has to revisit Caddyfile header assertions.
**NFRs:** NFR17 (all Non-Regression Contract controls remain satisfied on every PR; CI regression coverage mandatory for each control row).
**UX-DRs:** Contributor-facing CI UX — when the check fails, the pytest failure message MUST name the specific header that went missing AND the endpoint/status-code where it went missing. No buried `AssertionError: True != False`; the first line of the failure reads like `Missing 'Strict-Transport-Security' on GET /health (200)`. This is the contract 4.5b–g inherit.
**Epic:** 4 — Security Hardening, LGPD & Operational Safety. Fifth story in Epic 4 (4.1 → 4.2 → 4.3 → 4.4 → **4.5a** → 4.5b–g → 4.6). First of the seven-sub-story CI non-regression cluster; establishes the module + workflow skeleton 4.5b–4.5g extend by appending files / test cases (no further skeleton work required from them).

## Builds on

- **Story 4.4 — `ansible-playbook health.yml` assertion playbook (FR52).** `deploy/ansible/playbooks/health.yml` now exits non-zero on any operational-state deviation. Story 4.4's §Unblocks explicitly called out 4.5a + 4.5e as the closest semantic neighbours. 4.5a does NOT run `health.yml` in CI (that's a reserved extension point for a future iteration — see §Deferred-work); 4.5a asserts the HTTP attack surface at the Caddy layer. The two verifications complement: `health.yml` covers deploy-state; 4.5a covers request-path headers.
- **`deploy/caddy/Caddyfile`** (full file, 48 lines). Line 8–17 is the `header { ... }` block enforcing the 6 named headers + the `upgrade-insecure-requests` directive inside `Content-Security-Policy` (line 14) + `-Server` / `-Via` strip (lines 15–16). Line 33–34 is the per-handler `header_down -server` / `-via` on the reverse-proxy path. Both surfaces are in scope for 4.5a's assertions — the global `header` block's directives apply site-wide; the per-handler strip is a belt-and-braces second pass for the `/v1/*` + `/health` upstream responses.
- **`deploy/caddy/Caddyfile-no-landing`** (full file, 40 lines). Identical security-header block (line 8–17) to the primary Caddyfile, just without the `file_server` branch. 4.5a exercises the **primary `Caddyfile` only** (`landing_enabled: true` default) — the Caddy `header` block being byte-identical means the no-landing variant is covered transitively; documenting this trade-off explicitly in `tests/test_non_regression/README.md` so 4.5b–g do not re-litigate.
- **`compose.yaml`** (full file, ~80 lines). The `caddy` service (line 3–24) maps the production Caddyfile into a Caddy 2-alpine container exposing 80/443. 4.5a uses the same compose file for its CI integration test — no CI-specific fork of compose — with a stubbed upstream substituted for `tts-service` so the test does not pay the Kokoro + Qwen3 model-download cost on every PR (≈1.5 GB, multiple minutes). See §Design-decisions for the stubbing approach.
- **`.github/workflows/ci.yml`** (current: lint + test jobs, ~44 lines). Story 4.5a chooses between (a) extending `ci.yml` with a third `non-regression` job, or (b) adding a standalone `.github/workflows/non-regression.yml`. The epic leaves the choice explicit ("`.github/workflows/non-regression.yml` or an extension of the existing CI"). §Scope recommends extending `ci.yml` — single-file CI is simpler for a small team and the new job parallelises with `test` naturally.
- **`tests/conftest.py`** (existing, 162 lines). Canonical place to register a new pytest marker (line 25–29 shows the pattern: `config.addinivalue_line("markers", "slow: ...")`). Story 4.5a adds `non_regression` alongside the existing `slow` marker — same shape.
- **`feedback_caddy_server_header.md`** (user-memory file). Establishes the documented, accepted-risk boundary: `Server: Caddy` leaks on Caddy-emitted 404 (file_server-driven) and on the automatic HTTP→HTTPS 308 redirect are known, Caddy-architectural, and not fixable via the Caddyfile. 4.5a's banner-strip sub-assertion MUST respect this boundary: 404 and 308 responses are probed but excluded from the banner-strip check. Security-header presence, however, IS asserted on every HTTPS response code that the site's `header` directive reaches (200, 401, 404, 405, 5xx) — the 308 HTTP→HTTPS redirect is issued from Caddy's global automatic-HTTPS block *before* the site block's `header` applies, so it is **also** excluded from security-header presence, but for a different reason (structural impossibility, not policy). See §Design-decisions.
- **`_bmad-output/planning-artifacts/prd.md:633-690`** (Continuity with Existing Hardening table). The canonical row-by-row non-regression contract. 4.5a takes ownership of rows: *Security headers (HSTS, CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, `upgrade-insecure-requests`)* **and** *Server/Via banner stripping*. Subsequent sub-stories own other rows — docs-endpoints-disabled (4.5b), timing-safe-compare (4.5c), request-body-size (4.5d), rate-limit-middleware (4.5e), no-raw-HTTPException (4.5f), SQL-injection static analysis (4.5g).
- **Story 4.4 Change-log pattern for CI integration.** 4.4 Deferred-work §980 flags `health.yml` as the natural "CI non-regression hook-in" — 4.5a does NOT wire that in (staying scoped to HTTP headers), but its CI job layout leaves room for 4.5b–g and a future `health.yml`-in-CI step to co-exist in the same job.

## Unblocks

- **Stories 4.5b through 4.5g.** All six sub-stories reuse the module skeleton 4.5a ships: the `tests/test_non_regression/` package, the docker-compose-stack pytest fixture, the HTTP-probe helper, the `non_regression` marker, the CI job. Each subsequent sub-story adds exactly ONE test file (or appends to an existing one) plus ZERO lines of workflow YAML. This is the reason 4.5a is front-loaded in Epic 4's sub-story ordering — amortising the skeleton across six downstream consumers.
- **Operator confidence on Caddyfile edits.** Any Caddy config evolution (e.g. tightening CSP to drop `'unsafe-inline'`, adding COOP/COEP headers, switching HSTS max-age) lands with a mechanical regression check that a header didn't silently disappear. Operator can review the Caddyfile diff without having to manually exercise the header surface with `curl -I`.
- **Future CSP hardening stories.** If a later story narrows the Content-Security-Policy (e.g. removes `unsafe-inline` for the landing page after refactoring inline scripts), the CSP-directive-presence assertion 4.5a ships is the safety net that catches accidental CSP-header removal during that refactor. (Directive-value tightening — e.g. asserting exact CSP string — is out of scope for 4.5a; see §Deferred-work.)

## Depends on

- **Story 4.4 is `done`** (sprint-status.yaml confirms, checked 2026-04-20). Not a direct code dependency, but 4.4 shipped the most-recent ansible+CI-adjacent work; its patterns (e.g. `docker compose exec -T` discipline, `changed_when: false`, failure messages with corrective hints) inform 4.5a's CI-job UX.
- **No new Python runtime dependency.** `httpx` is already a transitive/explicit dep (used in `tests/conftest.py`). The test uses `httpx.Client(verify=False)` to hit the locally-spawned Caddy over HTTPS with self-signed cert — no new lib required.
- **No new dev dependency.** `pytest`, `docker` CLI (always present on GitHub-hosted `ubuntu-latest` runners), and the existing `compose.yaml` are sufficient.
- **No new ansible collection.** The CI test does not invoke ansible; it invokes `docker compose` directly from the runner shell (the runner has the docker group pre-configured on `ubuntu-latest`).
- **No schema change. No auth-path change. No FastAPI runtime change. No new CLI verb.** Grep invariant (AC11): `git diff master -- src/comadre/` returns empty. The entire story lives under `tests/test_non_regression/` + `.github/workflows/` + `tests/conftest.py` (marker line only) + one docs file.

## Scope

Three workstreams, in order of implementation:

1. **Non-regression test module skeleton** — new `tests/test_non_regression/` package with shared fixtures + HTTP-probe helper + one reusable `docker compose`-lifecycle fixture + a short `README.md` documenting the extension contract for 4.5b–g. Also the `non_regression` pytest marker registration in `tests/conftest.py`.
2. **FR46 security-headers + banner-strip test module** — `tests/test_non_regression/test_security_headers.py` containing the actual assertions (7 security headers × 5 endpoint probes + banner-strip × 5 probes with documented exclusions).
3. **CI job wiring** — new `non-regression` job in `.github/workflows/ci.yml` (recommended extension) OR new `.github/workflows/non-regression.yml` (alternative). Boots the compose stack with a stub upstream, runs the non-regression pytest subset, tears down on any exit.

### 1. Non-regression test module skeleton

**New directory: `tests/test_non_regression/`**

```
tests/
├── conftest.py                       [MOD] register `non_regression` marker
└── test_non_regression/
    ├── __init__.py                   [NEW]
    ├── conftest.py                   [NEW] compose-stack + probe-helper fixtures
    ├── README.md                     [NEW] extension contract for 4.5b–g
    └── test_security_headers.py      [NEW] the 4.5a assertions
```

**`tests/conftest.py` (MOD):** add one line alongside the existing `slow` marker:
```python
config.addinivalue_line(
    "markers",
    "non_regression: integration tests that exercise the prod docker-compose stack",
)
```
Rationale: the marker lets the default `uv run pytest` invocation **exclude** the non-regression suite (those tests need `docker compose`), while the CI non-regression job opts in via `pytest -m non_regression`. See §Design-decisions for why marker-based opt-in beats a separate pytest config.

**`tests/test_non_regression/conftest.py` (NEW):** exposes two fixtures the per-check modules consume:

- **`compose_stack`** (session-scoped) — yields an HTTPS base URL (`https://localhost`) after orchestrating:
  1. Prereq: assert `docker compose version` exit 0; skip the whole module with a clear reason if docker isn't available (so `pytest` run locally without docker still passes the rest of the suite).
  2. Write a minimal `.env` override into a `tmp_path_factory`-provided temp dir (no leakage to repo root): `KEY_REGISTRY_ENCRYPTION_KEY=<Fernet.generate_key()>`, `DOMAIN=localhost`, `QWEN3_ENABLED=false`, `BACKUP_PASSPHRASE=` (empty — Story 4.3 allows empty at boot).
  3. Pick ONE of the two upstream-stubbing strategies (see §Design-decisions — recommendation: **strategy A — caddy-only stack via `docker run caddy:2-alpine` with a stubbed upstream sidecar**):
     - **Strategy A (recommended):** start `caddy:2-alpine` with the production `Caddyfile` bind-mounted + `deploy/landing` bind-mounted as `/srv/www:ro`, plus a sidecar `nginx:alpine` serving 200 on any path as the `tts-service` upstream target (via `docker network create` + container aliasing so Caddy's `dynamic a { name tts-service }` resolves to the nginx sidecar).
     - **Strategy B (alternative):** `docker compose up -d` with a CI-only override `compose.ci.yaml` that swaps `tts-service`'s `build:` for `image: nginx:alpine` and drops the `healthcheck` + `depends_on`.
  4. Wait up to 15 seconds for `https://localhost/health` (or `/`) to return ANY HTTP status code (including 502 — the upstream stub may take a moment to come up; all we need is Caddy being ready).
  5. `yield "https://localhost"`.
  6. Teardown — `docker rm -f` (strategy A) or `docker compose down -v` (strategy B), regardless of test outcome, including on Ctrl-C.

- **`probe_client`** (function-scoped) — yields an `httpx.Client(verify=False, base_url=compose_stack, follow_redirects=False)` with a 5-second timeout. Explicitly does NOT follow redirects — the HTTP→HTTPS 308 is a targeted probe, not an implementation detail to hide.

**`tests/test_non_regression/README.md` (NEW):** one-page contributor doc, explicitly naming:
- The `pytest -m non_regression` opt-in contract.
- The `compose_stack` + `probe_client` fixture API.
- How 4.5b–g add their own module: **append a new `test_<check_name>.py` file that imports from `conftest.py`; do NOT modify CI YAML**.
- The 404/308 known-leak exclusion (with a link back to `feedback_caddy_server_header.md`'s spirit, captured in the file via `CLAUDE.md`).
- The upstream-stub strategy choice and rationale (so a future contributor understands why `tts-service` is not fully built in CI).

### 2. FR46 security-headers + banner-strip test module

**New file: `tests/test_non_regression/test_security_headers.py`**

Structure (each test receives `probe_client` + `compose_stack` from the module `conftest.py`):

```python
REQUIRED_HEADERS: tuple[str, ...] = (
    "Strict-Transport-Security",
    "Content-Security-Policy",
    "X-Frame-Options",
    "X-Content-Type-Options",
    "Referrer-Policy",
    "Permissions-Policy",
)

# Endpoints probed — chosen for status-code diversity (200, 401, 404, 405, 5xx)
PROBES: tuple[tuple[str, str, int | None], ...] = (
    ("GET",  "/",                      200),  # file_server landing
    ("POST", "/v1/audio/speech",       None), # reverse-proxy (no auth → 401 from stub; shape-agnostic)
    ("GET",  "/health",                None), # reverse-proxy
    ("GET",  "/this-path-does-not-exist", 404),  # file_server 404
    ("POST", "/",                      405),  # file_server method-not-allowed
)
```

**AC-2 assertions (one test per header × probe matrix, parametrized):**

```python
@pytest.mark.non_regression
@pytest.mark.parametrize("method,path,expected_status", PROBES)
@pytest.mark.parametrize("header", REQUIRED_HEADERS)
def test_security_header_present(probe_client, method, path, expected_status, header):
    resp = probe_client.request(method, path)
    if expected_status is not None:
        assert resp.status_code == expected_status, (
            f"Probe setup regressed: {method} {path} returned {resp.status_code}, expected {expected_status}"
        )
    assert header in resp.headers, (
        f"Missing '{header}' on {method} {path} ({resp.status_code}). "
        f"Response headers: {dict(resp.headers)}"
    )
```

**AC-2 special case — `upgrade-insecure-requests` is a CSP directive, not a standalone header:**

```python
@pytest.mark.non_regression
@pytest.mark.parametrize("method,path,expected_status", PROBES)
def test_csp_upgrade_insecure_requests_directive(probe_client, method, path, expected_status):
    resp = probe_client.request(method, path)
    csp = resp.headers.get("Content-Security-Policy", "")
    assert "upgrade-insecure-requests" in csp, (
        f"CSP on {method} {path} ({resp.status_code}) missing 'upgrade-insecure-requests' directive. "
        f"CSP value: {csp!r}"
    )
```

**AC-4 banner-strip assertion (excludes 404/308):**

```python
@pytest.mark.non_regression
@pytest.mark.parametrize("method,path,expected_status", PROBES)
def test_server_and_via_headers_stripped(probe_client, method, path, expected_status):
    resp = probe_client.request(method, path)
    if resp.status_code == 404:
        pytest.skip("Known Caddy 404 leak — see feedback_caddy_server_header.md")
    assert "Server" not in resp.headers, (
        f"Server header leaked on {method} {path} ({resp.status_code}): {resp.headers.get('Server')!r}"
    )
    assert "Via" not in resp.headers, (
        f"Via header leaked on {method} {path} ({resp.status_code}): {resp.headers.get('Via')!r}"
    )


@pytest.mark.non_regression
def test_http_to_https_redirect_is_308_and_excluded_from_banner_strip(probe_client):
    # Explicit probe of the known-leak scenario — asserts the redirect IS issued,
    # acknowledges the Server-banner leak as documented, and documents the
    # security-header-structural-absence so a future contributor doesn't "fix"
    # the test by forcing headers that Caddy's global block cannot emit.
    resp = httpx.get("http://localhost/", follow_redirects=False, timeout=5)
    assert resp.status_code == 308, f"Expected HTTP→HTTPS 308, got {resp.status_code}"
    # Deliberately NO assertion on Server/Via or security headers here —
    # the 308 is issued from Caddy's automatic-HTTPS global block, not the site
    # block, and cannot carry the site's `header` directives.
```

**Failure UX (AC-3) contract:** every assertion message names (a) the missing header or control, (b) the HTTP method + path, (c) the observed status code, (d) a short diagnostic tail (observed header value or full header dict where useful). This is what 4.5b–g inherit — no `AssertionError` in the module without a `f"..."` message.

### 3. CI job wiring

**Recommended: extend `.github/workflows/ci.yml` with a third job.**

```yaml
  non-regression:
    name: Non-Regression (Security)
    needs: [lint]
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - uses: astral-sh/setup-uv@v4
        with:
          cache: true
      - run: uv sync
      # Docker is pre-installed on ubuntu-latest; verify and proceed.
      - run: docker --version && docker compose version
      - run: uv run pytest -m non_regression tests/test_non_regression/ -v
      - name: Teardown compose stack (always)
        if: always()
        run: |
          docker compose -f compose.yaml down -v --remove-orphans || true
          docker rm -f $(docker ps -aq --filter label=comadre-non-regression) 2>/dev/null || true
```

**Why parallel to `test`, not serial:** lint must pass first (cheap); `test` and `non-regression` are independent (unit-mock tests vs. real-compose tests) and parallelise naturally. CI total wall-time regresses by ≤2 min (compose-up + 5 assertions), not 4+ min.

**Why extend `ci.yml` rather than new `non-regression.yml`:** one workflow file is simpler to reason about when reviewing PR-status badges; the `needs: [lint]` edge is explicit; badge sprawl on the README is avoided. The epic's "`.github/workflows/non-regression.yml` or an extension of the existing CI" wording explicitly permits either; recommend extension.

### 4. Docs

- **`tests/test_non_regression/README.md`** (already covered in §1) — the primary developer doc.
- **No CLAUDE.md gotcha addition required.** The non-regression contract is already documented in `_bmad-output/planning-artifacts/prd.md:633-690`; adding a gotcha would duplicate. The gotchas-pattern is reserved for non-obvious runtime/operator surfaces, not CI conventions.
- **No `docs/` addition required.** 4.5a is test-infra; operator-facing docs are unchanged.

## Acceptance Criteria

1. **AC1 — Test module skeleton exists:** `tests/test_non_regression/` is a Python package (`__init__.py` present) with `conftest.py` exposing session-scoped `compose_stack` and function-scoped `probe_client` fixtures. A `README.md` at the same path documents the `pytest -m non_regression` opt-in and the extension pattern for 4.5b–g.

2. **AC2 — pytest marker registered:** `tests/conftest.py` has a `non_regression` marker registered via `config.addinivalue_line`. Default `uv run pytest` run (no `-m` flag) does **not** execute the non-regression tests (they opt in via the marker and require docker).

3. **AC3 — All six standalone security headers present on every in-scope probe:** for each of `(GET /, POST /v1/audio/speech, GET /health, GET /this-path-does-not-exist, POST /)`, the response from the locally-spawned Caddy stack carries all six headers: `Strict-Transport-Security`, `Content-Security-Policy`, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`. The per-probe + per-header matrix is asserted in parametrised pytest tests so ONE missing header fails ONE test with a precise message (not a chained failure).

4. **AC4 — CSP directive `upgrade-insecure-requests` present:** a separate pytest assertion verifies the `Content-Security-Policy` header value string-contains `upgrade-insecure-requests` on every in-scope probe. This covers FR46's "(or its CSP directive form)" wording.

5. **AC5 — Server / Via banner strip on non-404 responses:** for each probe whose response status is NOT 404, the response carries neither a `Server:` nor a `Via:` header. 404 responses are `pytest.skip`ped with a reason citing the known Caddy leak — they are **not** excluded silently (so a future contributor who "fixes" the leak can un-skip with confidence).

6. **AC6 — HTTP→HTTPS 308 probe exists and is documented:** a dedicated test asserts `http://localhost/` yields a 308 redirect to HTTPS. No banner-strip assertion fires on the 308 (accepted known leak); no security-header-presence assertion fires on the 308 either (structural — the redirect is issued from Caddy's global automatic-HTTPS block, not the site block). The test body carries a comment explaining both exclusions so a future "why is this test so bare?" reader finds the answer inline.

7. **AC7 — Failure diagnostics name the specific regression:** each assertion message on a failure includes (a) the missing header or control, (b) the HTTP method + path, (c) the observed status code, (d) a short diagnostic tail. Validated via a smoke test that deliberately patches the Caddyfile to drop ONE header, runs the suite, and observes the exact failure message.

8. **AC8 — CI job exists and is wired into the PR gate:** `.github/workflows/ci.yml` has a `non-regression` job that (a) depends on `lint`, (b) boots the compose stack, (c) runs `uv run pytest -m non_regression tests/test_non_regression/ -v`, (d) tears the stack down on EVERY exit (success, failure, cancel). Branch-protection implications are out of scope (operator-driven setting); the job shows up as a check on every PR by virtue of the existing `pull_request: branches: [master]` trigger.

9. **AC9 — Upstream stub does not fetch models:** the Caddy-facing upstream in CI is NOT the real `tts-service` image. The CI run completes in under 3 minutes end-to-end (docker pull + compose up + 5 assertions + teardown), and NEVER downloads Kokoro or Qwen3 models. The stubbing approach (A or B — see §Scope-1) is documented in `tests/test_non_regression/README.md`.

10. **AC10 — Both Caddyfile variants covered:** the test exercises `deploy/caddy/Caddyfile` (primary, `landing_enabled: true`). `Caddyfile-no-landing` is NOT exercised in CI because its `header` block is byte-identical to the primary (asserted in the README as a rationale note). A follow-up story or a CLAUDE.md gotcha can invert this decision if the two files ever diverge; for now the primary covers both transitively.

11. **AC11 — No `src/comadre/` changes:** `git diff master -- src/comadre/` returns empty at story completion. Invariant: `git diff master -- src/comadre/ | wc -l` is `0`.

12. **AC12 — Existing ci.yml jobs unchanged:** the `lint` and `test` job step lists are byte-identical before and after; only the new `non-regression` job is added. Asserted via `git diff master -- .github/workflows/ci.yml` inspection.

13. **AC13 — Local developer workflow unchanged:** running `uv run pytest` (no marker filter) on a developer laptop continues to pass without docker available. The non-regression suite is cleanly skipped (or not collected) when the `non_regression` marker is absent from the command line.

14. **AC14 — Teardown is exhaustive:** after the CI job exits (success OR failure OR cancel), no `docker ps` entry remains for the test's containers; no bind-mount leak persists into `$GITHUB_WORKSPACE/.env`; no named volume survives. Verified by a trailing `docker ps -a` + `docker volume ls` inspection step in the workflow (optional, but recommended for operator-auditability).

15. **AC15 — Grep invariant on the extension contract:** `rg 'pytest.mark.non_regression' tests/test_non_regression/` matches exactly the assertions this story lands; `rg 'pytest.mark.non_regression' tests/` outside `test_non_regression/` returns zero matches (future sub-stories must place their tests inside `test_non_regression/`, not scatter them).

## Tasks / Subtasks

- [ ] **Task 1 — Scaffold the non-regression test module** (AC1, AC2)
  - [ ] 1.1 Create `tests/test_non_regression/__init__.py` (empty).
  - [ ] 1.2 Create `tests/test_non_regression/conftest.py` with `compose_stack` (session-scoped) + `probe_client` (function-scoped) fixtures, per §Scope-1.
  - [ ] 1.3 Create `tests/test_non_regression/README.md` documenting the opt-in contract, the fixture API, the 404/308 exclusion, and the 4.5b–g extension pattern.
  - [ ] 1.4 Append `non_regression` marker registration to `tests/conftest.py` (line near the existing `slow` marker).
  - [ ] 1.5 Verify `uv run pytest` (default, no marker filter) does NOT collect or run the new module.
  - [ ] 1.6 Verify `uv run pytest -m non_regression --collect-only` lists the new module's tests.

- [ ] **Task 2 — Pick and implement the upstream-stub strategy** (AC9, §Design-decisions)
  - [ ] 2.1 Implement Strategy A (recommended): the `compose_stack` fixture orchestrates `docker network create comadre-ci` + `docker run -d --name tts-service --network comadre-ci --label comadre-non-regression nginx:alpine` + `docker run -d --name caddy --network comadre-ci --label comadre-non-regression -p 80:80 -p 443:443 -v $PWD/deploy/caddy/Caddyfile:/etc/caddy/Caddyfile:ro -v $PWD/deploy/landing:/srv/www:ro -e DOMAIN=localhost caddy:2-alpine`.
  - [ ] 2.2 If Strategy A proves fragile (e.g. `dynamic a` resolver doesn't find the aliased nginx), fall back to Strategy B: a `compose.ci.yaml` override swapping `tts-service`'s `build:` for `image: nginx:alpine` and removing the `healthcheck` + `depends_on: service_healthy` lines. Document whichever strategy ships in the README (AC9).
  - [ ] 2.3 Assert: the fixture's teardown step runs on success, on failure, and on Ctrl-C (test via a deliberate `KeyboardInterrupt` during fixture-yield — not automated, one-shot manual check).

- [ ] **Task 3 — Implement the FR46 + banner-strip assertions** (AC3, AC4, AC5, AC6, AC7)
  - [ ] 3.1 Create `tests/test_non_regression/test_security_headers.py` with the 6 standalone-header parametrised assertions + the 1 CSP-directive assertion + the 5 banner-strip assertions (with the 404 skip) + the HTTP→HTTPS 308 documentation test, per §Scope-2.
  - [ ] 3.2 Run `uv run pytest -m non_regression tests/test_non_regression/ -v` locally; confirm all assertions pass green on an unmodified Caddyfile.
  - [ ] 3.3 Smoke the failure UX (AC7): temporarily remove `Referrer-Policy` from a copy of the Caddyfile, re-run, confirm the failing test's message names `'Referrer-Policy'` and the exact probe. Revert the Caddyfile.
  - [ ] 3.4 Confirm the `test_http_to_https_redirect_is_308_and_excluded_from_banner_strip` test passes and its inline comment is intact (so the "why is this test bare?" reader finds the structural rationale).

- [ ] **Task 4 — Wire the CI job** (AC8, AC12, AC14)
  - [ ] 4.1 Extend `.github/workflows/ci.yml` with the new `non-regression` job per §Scope-3.
  - [ ] 4.2 Verify locally with `act` (optional — GitHub Actions local runner) or by pushing to a throwaway branch and observing the PR check fire.
  - [ ] 4.3 Confirm the teardown step runs on job failure — deliberately break one assertion in `test_security_headers.py`, push, observe red PR check AND clean `docker ps` on the runner (via a trailing step or by inspection).
  - [ ] 4.4 Revert the deliberate break; confirm green PR check on the restored code.
  - [ ] 4.5 Confirm `lint` and `test` job step lists are byte-identical (AC12) — compare pre/post diff.

- [ ] **Task 5 — Verify the grep invariants and local-dev workflow** (AC11, AC13, AC15)
  - [ ] 5.1 Confirm `git diff master -- src/comadre/` returns empty at story close.
  - [ ] 5.2 Confirm `uv run pytest` on the dev laptop passes WITHOUT docker running (non-regression suite is not collected by default).
  - [ ] 5.3 Confirm `rg 'pytest.mark.non_regression' tests/test_non_regression/` matches the new assertions; `rg 'pytest.mark.non_regression' tests/ | grep -v test_non_regression/` returns empty.

- [ ] **Task 6 — Quality gate (non-regression surface)**
  - [ ] 6.1 `uv run ruff check .` — no new warnings on the new files.
  - [ ] 6.2 `uv run ruff format --check .` — no formatting drift.
  - [ ] 6.3 `uv run mypy src/` — green (should be untouched since no `src/comadre/` changes).
  - [ ] 6.4 `uv run pytest` (default, no marker) — all non-non-regression tests pass.
  - [ ] 6.5 `uv run pre-commit run --all-files` — green (new YAML in `.github/workflows/ci.yml` passes yamllint).
  - [ ] 6.6 `docker compose version` works locally (sanity check before running the new pytest subset).
  - [ ] 6.7 `uv run pytest -m non_regression tests/test_non_regression/ -v` — green end-to-end with the stack up.

## Dev Notes

### Design decisions

**Why a pytest marker instead of a separate pytest config / separate `tox` env.** Markers are the native pytest opt-in mechanism — already in use for the `slow` marker (`tests/conftest.py:25-29`). Adding a second marker keeps the test-discovery surface unified: a contributor running `uv run pytest` doesn't need to remember a second config file, and a CI job running a specific subset uses standard `-m non_regression` syntax. A separate pytest config would duplicate `pyproject.toml`'s `[tool.pytest.ini_options]` with drift risk; a `tox` env would introduce a new tool with no other justification.

**Why Strategy A (caddy-only + nginx stub) over Strategy B (full compose with override).** Strategy A is ~20 lines of fixture Python + two standalone `docker run` invocations; no `compose.ci.yaml` to keep in sync with `compose.yaml`. The Caddy `dynamic a { name tts-service }` DNS resolver works against a named container on a user-defined docker network, and nginx-alpine is a ~8 MB image that boots in under a second. Strategy B would drag in a real compose override file that drifts as `compose.yaml` evolves (e.g. adding a new env var, a new volume), creating maintenance burden. If Strategy A turns out to have a Caddy-resolver quirk (DNS caching, TLS cert issues on HTTPS-to-nginx), falling back to Strategy B is trivial — just replace the fixture body.

**Why NOT hit the real tts-service in CI.** First-boot model download is ~1.5 GB (Kokoro 330 MB + Qwen3 Q8_0 ~650 MB + tokenizer 100 MB + ggml overhead) and takes multiple minutes on GitHub-hosted runner egress. 4.5a tests Caddy's header surface, not the TTS pipeline. The upstream's identity is irrelevant: Caddy applies its `header` block to whatever the upstream returns (200, 500, 502), and the 404 / 405 / 308 probes don't even reach the upstream. Fetching models on every PR is a pure tax with no assertion-coverage gain. The deferred `docs/deferred-work.md` can capture "full-stack CI smoke" if a future story wants it.

**Why exercise only the primary Caddyfile, not Caddyfile-no-landing.** The security-header block is byte-identical between the two files (lines 8–17 in both). Exercising both would double CI wall-time for zero new assertion coverage. The README captures the rationale so a future PR that diverges the two files knows to add a parametrised variant. If a CI contributor later tightens one Caddyfile without the other, the header-block-byte-identical invariant could be added as a pre-commit hook (`diff <(sed -n '/header {/,/^}/p' Caddyfile) <(sed -n '/header {/,/^}/p' Caddyfile-no-landing)`) — deferred.

**Why the 308 probe has no header assertions.** Caddy's automatic HTTP→HTTPS 308 is issued from the global server block BEFORE site-block `header` directives are applied. This is documented Caddy architecture (`feedback_caddy_server_header.md`), and the memory explicitly states "Do not attempt to fix — already tried, Caddyfile `servers` global does not support `header`". The test exists not to assert on the 308 but to **document** that the 308 exists and that its bareness is intentional — so a future contributor reading the file understands why the test is structured the way it is. Removing this test would invite a well-meaning "add header assertions to the 308 too" PR that cannot pass.

**Why NOT assert on specific header values (e.g. `max-age=63072000`).** FR46 requires presence, not value. Asserting specific values would false-fail on every deliberate tightening (e.g. bumping HSTS max-age, narrowing Permissions-Policy). Value-tightening stories can add their own value-pin assertions when the tightening lands. The exception is the CSP `upgrade-insecure-requests` substring check — that's a directive-presence check, not a value-equality check, and FR46 explicitly names the directive.

**Why `follow_redirects=False` on `probe_client`.** The 308 HTTP→HTTPS redirect is a first-class probe target (AC6), not a transparent redirect to hide. Explicit redirect-disable in the fixture guarantees every test sees the status code it expects — no hidden `httpx.follow_redirects=True` magic converting a 308 into a 200 downstream.

**Why `verify=False` on the httpx client.** Caddy generates a self-signed TLS cert for `localhost` automatically. GitHub runners don't pre-trust it. `verify=False` is the accepted pattern for integration tests against the locally-spawned stack; NFR/security impact is zero (the test is asserting on response headers, not on TLS posture — Caddy's TLS posture is covered by a different, future story if ever needed).

### Import-graph placement

- **`tests/test_non_regression/`** — new test package, NOT imported by any `src/comadre/` code, NOT imported by any other `tests/*.py` file. Downward-only imports: `conftest.py` imports stdlib (`subprocess`, `pytest`, `httpx`, `pathlib`); `test_security_headers.py` imports `pytest` + `httpx` + shared fixtures from the module `conftest.py`.
- **`tests/conftest.py`** — MOD only (one new marker registration line). No new imports. Does not import from the new module.
- **`.github/workflows/ci.yml`** — extended with a third job; the `lint` and `test` jobs are unchanged.
- **`src/comadre/` — untouched.** Grep-invariant per AC11. No new runtime code, no new module, no schema change.

### Test-flake avoidance

- **Docker daemon readiness:** the `compose_stack` fixture polls `https://localhost/health` (or `/`) for up to 15 seconds; short enough to surface a real failure quickly, long enough to absorb cold-start Caddy boot (~2 s typical on ubuntu-latest) + nginx-alpine cold-start (~1 s typical).
- **Port collisions:** the test uses ports 80 and 443 on the runner. GitHub-hosted ubuntu-latest runners do NOT run anything on those ports by default. If a local dev runs the test with `docker compose up -d` already active (e.g. they have a local Comadre dev stack), the `docker run -p` invocation will fail fast with a clear "port already allocated" error — the README documents this.
- **Container-label cleanup:** every `docker run` in Strategy A uses `--label comadre-non-regression`, and the workflow teardown does `docker rm -f $(docker ps -aq --filter label=comadre-non-regression)`. This survives a test-process SIGKILL where the Python teardown didn't run.
- **Self-signed cert:** Caddy regenerates the self-signed cert on every container cold-start, but the fixture uses `verify=False` so cert identity never matters. No cert-trust persistence layer to go stale.
- **Order-of-test-execution:** pytest-parametrized tests are independent; no shared mutable state between probes. The `probe_client` fixture is function-scoped, so each test gets a fresh `httpx.Client` (zero cookie/connection-pool bleed).
- **CI-runner flake:** if `docker compose` CLI is missing (shouldn't happen on ubuntu-latest, but defensive), the fixture `pytest.skip`s the whole module with a clear reason rather than erroring out. This keeps the check green for unusual runner configurations while preserving a loud operator signal.
- **Assertion ordering:** parametrised tests mean ONE missing header fails ONE test with a precise message, not a chained `assert all([...])` that reports only the first failure. Contributors get the full failure surface in one CI run, not one-regression-per-re-run.

### Project Structure Notes

- **Alignment with unified project structure (paths, modules, naming)**
  - Test package naming: `tests/test_non_regression/` (mirrors pytest's discovery convention for packages; matches the `tests/test_<module>.py` single-file convention by extension).
  - Pytest marker naming: `non_regression` (underscore, matches the existing `slow` marker's lowercase-word convention).
  - Fixture naming: `compose_stack`, `probe_client` (snake_case, descriptive, no abbreviations — matches existing `mock_router`, `registry_db_path` shapes in `tests/conftest.py`).
  - CI job naming: `non-regression` (kebab-case, matches the existing `lint` and `test` job-key conventions — single word/phrase, no prefix).

- **Detected conflicts or variances (with rationale)**
  - The non-regression tests bind ports 80 and 443 on the CI runner, which no other CI job does. Rationale: Caddy's automatic HTTPS binding is opinionated about 443; changing ports would require Caddyfile surgery and diverges from the production config — exactly what the test is meant to validate. GitHub-hosted runners allow privileged port binding (`-p 80:80`) by default.
  - The `compose_stack` fixture uses `subprocess` + `docker` CLI rather than the `docker` Python SDK. Rationale: the Python SDK adds a dependency for ~50 lines of fixture code; the CLI is always present on ubuntu-latest and on any contributor's laptop with docker installed; failure modes are shell-transparent. Matches the existing `ansible.builtin.command: docker compose ...` pattern in the ansible playbooks.

### Testing standards

- **Python tests (new module):** pytest + pytest-parametrize; one assertion per test (so failures are precisely attributable); each assertion message carries method + path + status + missing-control name. Fixtures are session-scoped where they're expensive (compose stack) and function-scoped where they need isolation (httpx client). No `unittest.TestCase` classes — the project convention is pytest-function-based (see every existing `tests/test_*.py`).
- **Marker discipline:** every test in the new module MUST carry `@pytest.mark.non_regression`. Verified via AC15's grep invariant. A future sub-story that forgets the marker would accidentally run its test under `uv run pytest` default, which would fail locally (no docker). Marker presence is the CI opt-in contract.
- **No `slow` marker on non-regression tests.** The two markers are orthogonal: `slow` means "model inference required, ~minutes per test"; `non_regression` means "docker-compose stack required, ~seconds per test". A test can carry one, both, or neither depending on its actual requirements. 4.5a's tests carry only `non_regression`.

### Deferred work to flag at story close

- **Full-stack CI smoke (real `tts-service` container).** A future story can add a `full-stack` CI job that boots the real image and exercises `POST /v1/audio/speech` end-to-end. Justification: would catch model-download / image-build regressions that Strategy A masks. Cost: ~5 min per PR + model-cache operator burden. Deferred until a real regression surfaces.
- **Caddyfile `header` block diff-assertion between `Caddyfile` and `Caddyfile-no-landing`.** A pre-commit hook (or a CI step) could assert the two files' `header` blocks are byte-identical so a future edit to one isn't silently absent from the other. Deferred — covered by code-review today; worth promoting if a real divergence incident occurs.
- **`health.yml` assertion playbook run in CI.** Story 4.4 Deferred-work §980 flags this explicitly. A future CI job (`ops-regression` or similar) can run `ansible-playbook health.yml` against the locally-spawned compose stack and assert exit 0. Orthogonal to 4.5a's HTTP-header surface; deferred to a dedicated story.
- **Value-tightening assertions on CSP / HSTS / Permissions-Policy.** 4.5a asserts presence only. A future hardening story could pin HSTS `max-age` to ≥ 63072000, CSP to not contain `'unsafe-inline'`, Permissions-Policy to contain an explicit `microphone=()` denial, etc. Scope-cut from 4.5a to keep the check mechanical — value assertions get re-evaluated every time a header value legitimately evolves.
- **Test the no-landing Caddyfile variant.** Transitively covered today (byte-identical header block), but if a story legitimately diverges the two files, a parametrised fixture over both Caddyfiles is a trivial extension. Hooks described in README.
- **Assert response has no additional headers that weren't expected.** 4.5a asserts presence only — a PR adding a new `X-Powered-By: Caddy` header wouldn't fail the check. A "no-unexpected-headers" assertion could add that coverage; deferred as over-strict for MVP (many proxies add metadata headers operators genuinely want).
- **Move the 404 Caddy-leak exclusion from `pytest.skip` to an explicit xfail+strict.** `pytest.skip` is semantically correct today ("we know this fails, we accept it, move on"), but `xfail(strict=True)` would fail LOUDLY if Caddy ever fixed the leak upstream (so we could un-pin the workaround). Deferred — low probability Caddy changes its 404 behaviour on a minor version, and the skip message already points at the memory file.
- **Exhaustive status-code matrix (501, 502, 503, 504, 429).** 4.5a probes 200, 401-ish, 404, 405, 308. A real stress case would cover upstream-503, rate-limit-429, and the full 5xx surface. Deferred — the `header` block applies to every status Caddy emits, so these are transitive; worth adding if a real regression slips through.

### References

- Epic 4 Story 4.5 umbrella — `_bmad-output/planning-artifacts/epics.md:878-888`
- Epic 4 Story 4.5a — `_bmad-output/planning-artifacts/epics.md:890-909`
- FR46 — `_bmad-output/planning-artifacts/prd.md:1190`
- NFR17 — `_bmad-output/planning-artifacts/prd.md:1221`
- PRD Non-Regression Contract (Security headers row) — `_bmad-output/planning-artifacts/prd.md:641`
- PRD Non-Regression Contract (Server/Via banner stripping row) — `_bmad-output/planning-artifacts/prd.md:642`
- Primary Caddyfile — `deploy/caddy/Caddyfile` (full file, 48 lines; header block at 8–17, per-handler strip at 33–34)
- No-landing Caddyfile — `deploy/caddy/Caddyfile-no-landing` (full file, 40 lines; header block byte-identical to primary at 8–17)
- Existing compose — `compose.yaml` (full file; caddy service 3–24, tts-service 24–74)
- Existing CI workflow — `.github/workflows/ci.yml` (full file, ~44 lines; `lint` + `test` jobs)
- Existing pytest marker example — `tests/conftest.py:25-29` (the `slow` marker registration pattern)
- Existing httpx-based test fixture — `tests/conftest.py:125-133` (`client` fixture; 4.5a's `probe_client` follows the same import + yield shape but targets a real HTTPS endpoint)
- CLAUDE.md Non-Obvious Gotcha — Caddy landing-page served by Caddy via file_server at root (informs §Scope-1 bind-mount of `deploy/landing` → `/srv/www:ro`)
- Memory file feedback_caddy_server_header.md (user-memory) — documents the 404 / 308 Server-banner leak as accepted-risk, Caddy-architectural
- Story 4.4 Deferred-work §980 — health.yml CI integration hook-in (cousin of 4.5a, same CI job row)
- PRD Continuity table row Security headers — exercise target
- PRD Continuity table row Server/Via banner stripping — exercise target (404/308 leak excluded)
- `_bmad-output/planning-artifacts/implementation-readiness-report-2026-04-16.md:524-531` — the readiness report's rationale for splitting 4.5 into 4.5a–g (single-check-per-sub-story, independent failure diagnosis)

## Questions for Operator (please confirm before dev-story)

> All questions have recommended answers. In auto-mode, apply the recommended answer; if any run hits a disagreement, reopen as a deferred-work entry.

1. **Extend `ci.yml` vs new `non-regression.yml`.** Recommended: **extend `ci.yml` with a `non-regression` job**. Rationale: one workflow file is simpler; the `needs: [lint]` edge is explicit in-place; badge sprawl on the README is avoided. Epic wording permits either.

2. **Strategy A (caddy-only + nginx stub) vs Strategy B (compose override).** Recommended: **Strategy A**. Rationale: ~20 lines of fixture vs. a drift-prone `compose.ci.yaml`; nginx-alpine boots in ~1 s; no maintenance tax as `compose.yaml` evolves.

3. **Exercise only the primary Caddyfile vs both variants.** Recommended: **primary only**. Rationale: `header` blocks are byte-identical between `Caddyfile` and `Caddyfile-no-landing`; exercising both doubles CI time for zero new coverage. Deferred work flagged if they ever diverge.

4. **`pytest.skip` vs `xfail(strict=True)` for the 404 Caddy leak.** Recommended: **`pytest.skip`**. Rationale: the leak is memory-accepted and not going to flip; `xfail-strict` adds a failure-on-fix surface that's noisy for minimal reward (Caddy upstream isn't going to change this in our cadence).

5. **Value-tightening assertions in 4.5a (e.g. HSTS `max-age=63072000` exact pin) vs presence-only.** Recommended: **presence only**. Rationale: FR46 requires presence; value-pinning would force-update the test on every legitimate header tightening. Value assertions are their own future story.

6. **Hit the real `tts-service` in CI vs stub.** Recommended: **stub**. Rationale: 4.5a tests Caddy's header surface, not the TTS pipeline; model download is ~1.5 GB / several minutes of pure tax. Full-stack CI smoke is deferred work.

7. **Register `non_regression` marker in `tests/conftest.py` vs new `pyproject.toml [tool.pytest.ini_options]` markers entry.** Recommended: **`tests/conftest.py`**. Rationale: matches the existing `slow` marker pattern (same file, same `config.addinivalue_line` call). `pyproject.toml` markers work but would fork the registration location.

8. **Test named `test_security_headers.py` in a package vs `test_non_regression_security_headers.py` at tests/ root.** Recommended: **package + short filename**. Rationale: 4.5b–g each add their own file to the package; a flat tests/ would be `test_non_regression_*.py` × 7 duplicating the prefix. The package structure amortises the prefix into the directory name.

9. **Teardown on `if: always()` vs explicit trap in fixture vs both.** Recommended: **both**. Rationale: fixture teardown is the first defence (runs even on `pytest` SIGTERM during the test); the `if: always()` workflow step is the catch-all (runs even if the fixture itself errors). `--label comadre-non-regression` label on every container makes the catch-all cheap and complete.

10. **Cover the automatic HTTP→HTTPS 308 as a probe at all.** Recommended: **yes, documentation-style**. Rationale: the bare-test-body form makes the structural rationale visible inline, preventing future "add asserts here too" well-meaning PRs. Deleting the test would trade zero assertion-coverage for future confusion.

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List
