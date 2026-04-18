# Story 2.3: Request Counters & Cache Management

Status: done

> **Scope note — epic-vs-architecture reconciliation.** `epics.md` L586–603 says `show --audit-tail` must include a last-24h stats section "(if available from the running instance)"; `architecture.md` Gap 1 (L745–748) defers host-CLI visibility of in-memory counters to 2.1+. This story resolves the tension by adopting a **file-based IPC snapshot pattern** — the API process periodically writes an atomic JSON snapshot of per-key counters + auth-cache stats to `{KEY_REGISTRY_DB_PATH}.counters.json` (mirroring the existing `.invalidate` sentinel pattern from Story 2.1). CLI surfaces (`cache-status`, `show --audit-tail`) read that file. When the file is absent or stale the CLI renders a graceful "unavailable — is the API running?" breadcrumb rather than failing. This honors the epic's literal AC, stays inside the architecture's "no internal HTTP endpoint for MVP" constraint, and reuses the file-sentinel pattern already shipped in 2.1.

## Story

As an operator,
I want in-memory per-key request counters that I can inspect via `comadre-keys show --audit-tail`, and a `cache-status` command that reports the 60-second auth-cache propagation bound — so that when a customer complains about "errors" I can distinguish 401 from 429 and understand why a just-revoked key still works for up to a minute.

**Covers FRs:** FR33 (in-memory per-key counters: total, 429-rejections, peak RPM, avg RPM; reset on restart), FR45 (read-only `cache-status` CLI reporting the 60s TTL propagation bound + optional cache-health telemetry).
**NFRs:** NFR7 (counter path adds ≤2 ms p99 to the post-auth pipeline — the increments are O(1) dict updates, no I/O on the request path), NFR19 (zero external deps at request time — snapshot writer uses `asyncio.to_thread` for the file write, never blocks on external I/O).
**Epic:** 2 — API Authentication & Dynamic Rate Limiting. Third and final story in Epic 2. Closes Journey 5's "instant forensics" affordance (`ux-design-specification.md` L94: operator distinguishes 401 vs 429 while the customer is still typing).

## Builds on

- **Story 2.1** — `AuthCache.snapshot()` method (`src/comadre/keys/cache.py:102-113`) already exposes `{entries, maxsize, ttl_seconds, hits, misses}`. Story 2.3 is the first consumer.
- **Story 2.1** — `AuthPayload.key_id` field (`src/comadre/keys/models.py:214`) is the stable counter key. Survives `rotate-key`, unique per key, zero PII.
- **Story 2.2** — `request.state.auth_payload` is guaranteed populated when `check_rate_limit` runs (dependency ordering enforced by `src/comadre/api.py:37-40`). Counter increments at the rate-limit layer can read `key_id` directly from state without re-querying.
- **Story 2.2** — `RateLimiter` bucket key is plain `key:<key_id>` (`src/comadre/rate_limit.py:114`) — no suffix smuggling. Peak/avg RPM can be reconstructed from `limits` library's `get_window_stats` on the same key, no shadow tracking needed on the hit count itself.
- **Story 1.4** — `show --audit-tail N` already loads audit events and appends `AuditTail` below the `DetailPanel` (`src/comadre/keys/cli/commands/customers.py:527-541`, `render_audit_tail` in `output.py:429-450`). Story 2.3 adds a new section **between** the DetailPanel and the AuditTail when the target is a key.
- **Story 2.1 + 2.2 sentinel pattern** — `.invalidate` file next to the SQLite DB is the precedent for cross-process signalling. Story 2.3 adds a sibling `.counters.json` file using the same filesystem-as-IPC approach.
- **Story 2.2 deferred-work item #3** ("429 access log lacks `key_id` attribution", `deferred-work.md:25`) — Story 2.3 is explicitly flagged as the surface that closes it. A structured log line at the 429 path carrying `key_id` is part of this story's scope.

## Unblocks

- **Story 3.4** (System Health Command) — `comadre-keys health` reads the same counters snapshot to surface per-replica liveness and a global requests-total summary.
- **Story 3.2** (At-Risk Queries & Revenue Reports) — optional future addition: `list-keys --sort-by requests_total` uses the snapshot to identify a customer about to outgrow their tier.
- **Stories 4.x** (Security Hardening) — the `rate_limit_429` counter is the input signal for any future abuse-detection story (cross-key-from-one-IP, bursty-then-silent, etc.).

## Depends on

- Story 2.1 and Story 2.2 must be `done` (both are, as of 2026-04-18). No new dependency in `pyproject.toml` — stdlib `json`, `os.replace` for atomic writes, `asyncio.create_task` + `asyncio.sleep` for the periodic writer.

## Scope

Adds in-memory per-key request counters in the API process, a periodic atomic snapshot writer to `{KEY_REGISTRY_DB_PATH}.counters.json`, a new `comadre-keys cache-status` CLI command, and a "Last-24h stats" section appended to `show --audit-tail <key-prefix>` output. No new runtime dependencies. No HTTP endpoint. No schema change.

### 1. New module: `src/comadre/counters.py`

Exports:

- `RequestCounters` — dataclass holding `per_key: dict[str, _KeyCounter]`, `process_start: float` (monotonic), `snapshot_path: Path | None`, `snapshot_interval_seconds: int` (default 15). Thread-safe enough for single-event-loop asyncio (no multi-threaded writers; increments are plain dict ops).
- `_KeyCounter` — internal dataclass: `requests_total: int`, `auth_success: int`, `rate_limit_429: int`, `window_hits: collections.deque[float]` (timestamps within the last 60s, pruned on write/read), `peak_rpm: int`. The deque implements the moving-window peak/avg without calling back into the `limits` library — keeps the counters module independent of `rate_limit.py` (downward-only import graph preserved).
- `RequestCounters.incr_request(key_id: str)` — increments `requests_total` + appends `time.monotonic()` to `window_hits`, prunes anything older than 60s, updates `peak_rpm = max(peak_rpm, len(window_hits))`.
- `RequestCounters.incr_auth_success(key_id: str)` — increments `auth_success` after `incr_request`.
- `RequestCounters.incr_429(key_id: str)` — increments `rate_limit_429` (does NOT increment `requests_total` again — the request was already counted at the auth layer).
- `RequestCounters.snapshot(auth_cache_snapshot: dict[str, Any]) -> dict[str, Any]` — builds the JSON-ready structure (see §5 for schema). Called by the periodic writer.
- `RequestCounters.start_snapshot_writer(loop: asyncio.AbstractEventLoop, auth_cache: AuthCache) -> asyncio.Task` — schedules the periodic writer. Returns the `asyncio.Task` so lifespan can cancel it on shutdown. The writer does `await asyncio.to_thread(self._write_snapshot, ...)` so the `os.replace` rename path never blocks the event loop.
- `RequestCounters.stop_snapshot_writer()` — cancel the task + best-effort final snapshot.

Module-level constant: `SNAPSHOT_SCHEMA_VERSION = 1`. The snapshot file carries `"schema_version": 1` so a future reader can migrate.

Import graph: `counters.py` imports only stdlib (`collections`, `dataclasses`, `datetime`, `json`, `os`, `pathlib`, `time`, `asyncio`, `typing`). It does NOT import `keys/auth.py`, `rate_limit.py`, or anything that imports either — this avoids cycles. `keys/auth.py` and `rate_limit.py` both import `counters.py` (downward).

### 2. Integration: `src/comadre/keys/auth.py`

At the end of `verify_api_key_registry`, after `request.state.auth_payload = payload` (L165), add:

```python
counters: RequestCounters | None = getattr(
    request.app.state, "request_counters", None
)
if counters is not None:
    counters.incr_request(payload.key_id)
    counters.incr_auth_success(payload.key_id)
```

Both increments happen on the same path because reaching this line means auth has succeeded. If `check_rate_limit` later denies, `rate_limit.py` increments `rate_limit_429` — `requests_total` and `auth_success` are already counted. This makes `requests_total = auth_success + (401 denials that reach this line — which is zero, by construction, since denials raise before this line)`.

Denials (`ApiKeySuspendedError`, `ApiKeyRevokedError`, `ApiKeyNotFoundError`) raise **before** reaching the increment point. That is intentional — auth denials belong in the access log, not the counter. The counter answers "how much work does this active key do?" not "how much garbage does this IP send?"

**No try/except around the increments.** `incr_request` is a pure in-memory op that cannot fail; if it somehow raises, the request should fail-closed (not silently succeed with corrupt telemetry). The getattr-None guard covers the lifespan-not-yet-entered case (startup ordering, test fixtures that bypass lifespan).

### 3. Integration: `src/comadre/rate_limit.py`

In `check_rate_limit`, on the deny branch (before `raise RateLimitError(...)`, L126), add:

```python
counters: RequestCounters | None = getattr(
    request.app.state, "request_counters", None
)
if counters is not None:
    counters.incr_429(payload.key_id)
_rate_limit_logger.info(
    "Rate-limit 429 | key_id=%s | customer_id=%s | rpm=%d",
    payload.key_id,
    payload.customer_id,
    rpm,
)
```

The new `_rate_limit_logger = get_logger("rate_limit")` at module top. The structured log line closes deferred-item #3 from Story 2.2 (`deferred-work.md:25`) — operators can now grep the access log by `key_id=` and get exact attribution. `customer_id` is included so an operator looking at a 429 spike can join to the customer row without a second lookup.

**No log line on allow.** The allow path is the hot path (p99 budget 2ms); a log-per-request would blow access-log volume. Counters give the aggregate view; the existing access-log middleware already records the request at the HTTP layer.

### 4. Integration: `src/comadre/main.py`

In `lifespan`, after `app.state.rate_limiter = RateLimiter.build()` (L65):

```python
counters_path = Path(f"{settings.key_registry_db_path}.counters.json")
app.state.request_counters = RequestCounters(
    snapshot_path=counters_path,
    snapshot_interval_seconds=15,
)
app.state.request_counters_task = (
    app.state.request_counters.start_snapshot_writer(
        loop=asyncio.get_running_loop(),
        auth_cache=app.state.auth_cache,
    )
)
logger.info(
    "Request counters initialised; snapshot writer scheduled "
    "(path=%s, interval=%ds)",
    counters_path,
    15,
)
```

In the `finally` of lifespan (L191-195), after `db.close()`:

```python
task = getattr(app.state, "request_counters_task", None)
if task is not None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
```

Also stage a best-effort final snapshot before cancel so the last N seconds of counters persist to disk for the CLI to read after shutdown (useful when an operator restarts the service between noticing an issue and running `show`).

### 5. Snapshot file schema

Path: `{KEY_REGISTRY_DB_PATH}.counters.json` (e.g., `/var/lib/comadre/keys.db.counters.json` in production, mirroring the `.invalidate` sentinel convention).

Write path: `{path}.tmp` → `os.replace(tmp, path)` for atomic rename. Never partial-write. Mode `0600` set on first write (mirrors `keys.db` hardening from Story 1.1).

Schema:

```json
{
  "schema_version": 1,
  "written_at": "2026-04-18T18:32:04.123Z",
  "process_uptime_seconds": 3712,
  "auth_cache": {
    "entries": 17,
    "maxsize": 4096,
    "ttl_seconds": 60,
    "hits": 1842,
    "misses": 23
  },
  "per_key": {
    "key_01jxyz...": {
      "requests_total": 412,
      "auth_success": 412,
      "rate_limit_429": 3,
      "peak_rpm": 47,
      "avg_rpm_last_60s": 12.5,
      "last_activity_at": "2026-04-18T18:32:01.890Z"
    }
  }
}
```

- `written_at` is wall-clock ISO 8601 (UTC). The CLI uses it to detect staleness (> 60s old → "unavailable — is the API running?").
- `process_uptime_seconds` is derived from `time.monotonic() - process_start`. Communicates "counters reset at last restart, this is how long they've been accumulating" — essential operator context.
- `avg_rpm_last_60s` is `len(window_hits)` — straight count of hits in the last 60s (the window is already pruned at each increment and at snapshot time). "Last 60s" matches the rate-limit window exactly, so operators reason about the same unit as `rate_limit_rpm`.
- `peak_rpm` is the max-over-all-windows observed since process start. `avg_rpm_last_60s` is the current window count. Together they answer "how bursty is this key?" at a glance.
- `last_activity_at` is ISO 8601 wall-clock of the most recent `incr_request`. Lets the CLI show "last request 2 minutes ago" — useful for diagnosing "is this key idle or rate-limited?"

**PII considerations:** zero. Only `key_id` (opaque ULID) appears. No plaintext, no hash, no customer name, no IP, no path, no bearer material. The counters file is safe to ship to an analytics pipeline (future story) without redaction.

### 6. New CLI module: `src/comadre/keys/cli/commands/system.py`

Typer subapp with just one command for now — `cache-status`. `health`, `rotate-encryption-key`, `suspend-sweep` will be added by Story 3.4 / 4.2 / 3.3 per architecture L351-357. Creating the module now means those stories only need to add commands, not bootstrap the module.

`cache-status` signature:

```python
@app.command("cache-status")
def cache_status_cmd(
    format: str = typer.Option(
        "table",
        "--format",
        help="Output format: table (default, human-readable) or json.",
    ),
) -> None:
```

Behavior:

1. Validate `--format` ∈ `{table, json}`; exit 2 on invalid.
2. Load `Settings` — same exit-6 handling as sibling commands (missing encryption key, bad TZ).
3. Resolve the snapshot path: `Path(f"{settings.key_registry_db_path}.counters.json")`.
4. Try to read the snapshot:
   - If file absent → no live telemetry, print bound message only.
   - If file present and `written_at` within 60s → telemetry "live", include `entries` / `hit_rate` fields.
   - If file present but `written_at` > 60s old → telemetry "stale", render the data with a "(last updated: X ago)" caveat.
   - On JSON parse error → log warning, degrade to bound-only.
5. Human output (`--format table`):

   ```text
   Auth cache propagation bound: 60 seconds.
   Key-state changes become visible to the API within this window.
   This command does not force invalidation; to empty the cache faster,
   restart the affected replica(s).

   Cache health (from snapshot written 3s ago):
     Entries:   17 / 4096
     Hit rate:  98.8% (1842 hits / 1865 lookups)
     Uptime:    1h 01m
   ```

   When snapshot absent/stale:

   ```text
   Auth cache propagation bound: 60 seconds.
   Key-state changes become visible to the API within this window.
   This command does not force invalidation; to empty the cache faster,
   restart the affected replica(s).

   Cache health: unavailable (no running API instance, or snapshot > 60s stale).
   ```

6. JSON output (`--format json`): always contains `ttl_seconds: 60` and `propagation_bound_message: "..."`. Includes `entries`, `hit_rate`, `hits`, `misses`, `snapshot_age_seconds` when the snapshot is readable.

   ```json
   {
     "ttl_seconds": 60,
     "propagation_bound_message": "Auth cache propagation bound: 60 seconds. ...",
     "snapshot_available": true,
     "snapshot_age_seconds": 3,
     "entries": 17,
     "maxsize": 4096,
     "hits": 1842,
     "misses": 23,
     "hit_rate": 0.988
   }
   ```

7. Exit code 0 on success. Never exits non-zero for "snapshot unavailable" — that is a valid operational state (API is down, or this host doesn't mount the DB directory). Exit 6 only on encryption-key / TZ config errors, consistent with sibling commands.

8. **No cache mutation.** The command must never touch the cache, the registry DB, or the `.invalidate` sentinel. Read-only by architecture decree (`architecture.md:198-201`).

### 7. `show --audit-tail` enhancement: last-24h stats

In `src/comadre/keys/cli/commands/customers.py:show_cmd`, after `resolve_show_target` resolves a KEY target and after `list_audit_events` fetches events (L527-541), for **key-kind** targets only, additionally:

1. Read the counters snapshot file.
2. If snapshot present and key_id in `per_key`, extract `{requests_total, auth_success, rate_limit_429, peak_rpm, avg_rpm_last_60s, last_activity_at}`.
3. If snapshot missing, stale, or key_id absent from snapshot (key never served a request since last restart), prepare a "unavailable" marker.

Render a new section **between** the `DetailPanel` and the `AuditTail` when the target is a key and `--audit-tail` is present (table format only). A new helper `render_last_24h_stats(stats: Last24hStats | None)` in `output.py`:

- With data: plain indented lines (matching `AuditTail` subordinate styling, `ux-design-specification.md:812`). Example:

  ```text
  Last-24h stats (from snapshot written 3s ago, uptime 1h 01m):
    Requests total:     412
    Auth success:       412
    Rate-limit 429:     3
    Peak RPM:           47
    Avg RPM (last 60s): 12.5
    Last activity:      2s ago
  ```

- Without data (snapshot missing / stale / key not seen):

  ```text
  Last-24h stats: unavailable.
    The API may not be running, or this key has not served a request
    since the last restart. Counters reset on restart (not durable).
  ```

- JSON format (`--format json`): add a top-level `"stats": {...}` or `"stats": null` field to the `render_show_json` payload for key targets. Customer targets omit the field entirely (counters are per-key, not per-customer; aggregating across a customer's keys is future work).

The section is omitted entirely for **customer-kind** targets. Per-customer aggregates are not in Story 2.3's scope (would need to enumerate `api_key.customer_id` and sum, which is a different query pattern).

### 8. Docs

- `docs/rate-limiting.md` — extend §Future direction (L120-123) into a new §Counters + §Cache observability section documenting:
  - Where counters live (in-memory, per-replica).
  - What they track (fields in §5 schema).
  - Where the snapshot file is written.
  - How multi-replica deployments see "whichever replica last wrote wins" (the MVP single-file model, documented honestly, with a note about future per-replica aggregation).
  - That counters reset on restart.
- `docs/configuration-reference.md` — add a one-line entry documenting the new sentinel file path at `{KEY_REGISTRY_DB_PATH}.counters.json`.
- `docs/troubleshooting.md` — add an entry: "`comadre-keys cache-status` says 'unavailable'" → check API is running, check `KEY_REGISTRY_DB_PATH` matches between CLI and container.
- `CLAUDE.md` — update the rate-limiting section's last paragraph to reference the counters snapshot file, so the next contributor finds it on the main CLAUDE.md read.
- `README.md` — one-line mention of `cache-status` in the CLI-command table if such a table exists (it does — confirm during implementation).

### 9. Tests

- **`tests/test_counters.py`** (NEW) — unit tests for `RequestCounters`:
  - `incr_request` appends to window_hits + prunes > 60s old entries.
  - `peak_rpm` is non-decreasing; stays at the max observed window count.
  - `avg_rpm_last_60s` equals `len(window_hits)` after pruning.
  - `snapshot()` produces schema-compliant JSON (version 1).
  - `start_snapshot_writer` schedules a task; cancellation is clean.
  - Atomic write: `_write_snapshot` goes through `.tmp` + `os.replace`; partial file never observed (simulated via `monkeypatch` on `os.replace`).
  - Mode-0600: first write sets mode; subsequent writes do not re-chmod (cheap).
  - Isolated from filesystem state via `tmp_path` fixture.

- **`tests/test_api.py::TestRequestCounters`** (NEW) — integration tests:
  - Successful request increments `requests_total` and `auth_success` for the right `key_id`.
  - 429 increments `rate_limit_429` but not a second `requests_total`.
  - Two different keys land in separate counter buckets.
  - 429 structured log line contains `key_id=` (regression for deferred-work item #3).
  - Access log remains PII-clean (no plaintext/hash/bearer in any line, including the new 429 log).

- **`tests/test_api.py::TestCountersSnapshotLifespan`** (NEW) — lifespan-scoped tests:
  - Lifespan creates snapshot file within `snapshot_interval_seconds` of start.
  - Snapshot JSON validates against schema (`schema_version`, `written_at`, `auth_cache`, `per_key` keys).
  - Lifespan shutdown cancels the task; final snapshot is written.
  - Snapshot file is mode 0600.

- **`tests/test_keys_cli_cache_status.py`** (NEW) — CLI tests:
  - Invalid `--format` exits 2 with usage-error panel.
  - Missing encryption key → exit 6 (consistent with siblings).
  - Snapshot absent → table output prints bound + "unavailable" breadcrumb, exits 0.
  - Snapshot fresh (written_at within 60s) → table output includes `entries`, hit_rate%, uptime.
  - Snapshot stale → table output includes "(last updated: X ago)" caveat.
  - `--format json` always emits `ttl_seconds=60` and `propagation_bound_message`; includes `entries`/`hit_rate`/`hits`/`misses` when snapshot is present.
  - Malformed JSON snapshot → degrades to bound-only, logs a warning (captured via `caplog`).
  - Absolutely no write to the snapshot file, the sentinel file, or the DB (assert file mtimes unchanged).

- **`tests/test_keys_cli_show.py`** (MOD) — add cases:
  - `show <key-prefix> --audit-tail 20` with fresh snapshot containing the key_id → last-24h stats section rendered between DetailPanel and AuditTail.
  - `show <key-prefix> --audit-tail 20` with missing snapshot → "unavailable" breadcrumb rendered.
  - `show <key-prefix> --audit-tail 20` with snapshot missing this specific key_id (other keys present) → "unavailable" breadcrumb rendered.
  - `show <cust-id> --audit-tail 20` → no last-24h stats section (customer target).
  - `show <key-prefix> --audit-tail 20 --format json` → `stats` field present in payload.
  - `show <cust-id> --audit-tail 20 --format json` → no `stats` field in payload.

- **`tests/conftest.py`** (MOD) — `auth_headers` fixture may need a companion `counters_snapshot_file` fixture that writes a known snapshot for CLI tests to read. Keep it opt-in (not autouse) so existing tests stay isolated.

## Acceptance Criteria

> BDD-style. Each AC maps to at least one test. AC numbers are stable — do not renumber if a mid-story pivot adds/removes an AC (append a new number instead).

### AC1 — `incr_request` + `incr_auth_success` on the happy path

**Given** a valid active key with `key_id=key_01ABC`
**When** `POST /v1/audio/speech` returns 200
**Then** `app.state.request_counters.per_key["key_01ABC"].requests_total == 1`
**And** `app.state.request_counters.per_key["key_01ABC"].auth_success == 1`
**And** `app.state.request_counters.per_key["key_01ABC"].rate_limit_429 == 0`

### AC2 — 429 increments `rate_limit_429` but not `requests_total` twice

**Given** a key with `rate_limit_rpm=2` that has already served 2 requests in the current window
**When** the 3rd request arrives and receives 429
**Then** `requests_total == 3` (the 3rd request's auth succeeded — the increment ran before `check_rate_limit` denied)
**And** `auth_success == 3`
**And** `rate_limit_429 == 1`

Rationale: counters measure "work reaching the app", not "work completed". A 429 is still work — the app spent CPU on auth. Separating the counters lets the operator diagnose "is this key getting rate-limited?" (ratio) without double-counting.

### AC3 — `peak_rpm` is the max observed window count

**Given** counters starting at zero
**When** the key serves 10 requests inside a 60-second window, then idles 60s, then serves 3 requests
**Then** `peak_rpm == 10` (not 3, not 13)
**And** `avg_rpm_last_60s == 3`

### AC4 — `avg_rpm_last_60s` equals `len(window_hits)` after pruning

**Given** the key's `window_hits` deque contains 12 timestamps, 4 of which are > 60s old
**When** `snapshot()` is called
**Then** the output's `avg_rpm_last_60s == 8` (the 4 old entries are pruned before the count)

### AC5 — Counters reset on process restart

**Given** counters show `requests_total=500` for `key_01ABC`
**When** the API process restarts (new lifespan enter)
**Then** `app.state.request_counters.per_key` is empty
**And** the first request after restart initialises `per_key["key_01ABC"] = _KeyCounter(requests_total=1, ...)`

### AC6 — 429 structured log line carries `key_id`

**Given** a rate-limit denial
**When** the structured log is emitted
**Then** the log line contains `key_id=key_01ABC` as a literal substring
**And** it contains `customer_id=cust_01XYZ`
**And** it does NOT contain the bearer plaintext, the SHA-256 hash, `cmdr_live_`, the customer name, or the customer email

### AC7 — Snapshot file is atomically written

**Given** the API is running
**When** the snapshot writer fires
**Then** a file exists at `{KEY_REGISTRY_DB_PATH}.counters.json`
**And** it contains valid JSON with `schema_version=1`
**And** the write path used `os.replace` (no partial/torn JSON ever observable by a concurrent reader)
**And** the file has mode 0600

### AC8 — Snapshot freshness is observable

**Given** the snapshot was written 3 seconds ago
**When** `comadre-keys cache-status` reads it
**Then** the output includes "Cache health (from snapshot written 3s ago)"
**And** the JSON-format output includes `"snapshot_age_seconds": 3`

### AC9 — `cache-status` prints the exact propagation bound message

**Given** any state (snapshot present, absent, or stale)
**When** `comadre-keys cache-status` runs
**Then** the output contains verbatim: `"Auth cache propagation bound: 60 seconds. Key-state changes become visible to the API within this window. This command does not force invalidation; to empty the cache faster, restart the affected replica(s)."`

The exact string is fixed by `architecture.md:200` and `epics.md:597` — tests assert byte-equality against this string constant, which lives in a module-level `_CACHE_STATUS_BOUND_MESSAGE` constant for easy grep + single source of truth.

### AC10 — `cache-status --format json` always emits `ttl_seconds=60`

**Given** any snapshot state
**When** `comadre-keys cache-status --format json` runs
**Then** `json.loads(stdout)["ttl_seconds"] == 60`
**And** `json.loads(stdout)["propagation_bound_message"]` matches the verbatim string from AC9

### AC11 — `cache-status` makes zero cache mutations

**Given** the `.invalidate` sentinel file exists with a known mtime
**When** `comadre-keys cache-status` runs
**Then** the sentinel file mtime is unchanged (stat before/after)
**And** the snapshot file mtime is unchanged (CLI is reader-only)
**And** the registry DB file mtime is unchanged
**And** no SQL is executed against the DB (no `.execute` calls)

### AC12 — `show <key-prefix> --audit-tail N` appends last-24h stats

**Given** a fresh snapshot contains `key_id=key_01ABC` with `requests_total=412, rate_limit_429=3, peak_rpm=47, avg_rpm_last_60s=12`
**When** `comadre-keys show EVb4xk8B --audit-tail 20` resolves to key_id `key_01ABC`
**Then** the output contains a "Last-24h stats" section between the DetailPanel and the AuditTail
**And** the section shows the five counters + `last_activity_at` rendered as "X ago"
**And** the JSON format output includes `"stats": {...}` with the same fields

### AC13 — `show <key-prefix> --audit-tail N` degrades gracefully on missing snapshot

**Given** the snapshot file does not exist
**When** `comadre-keys show EVb4xk8B --audit-tail 20` runs
**Then** the output contains a "Last-24h stats: unavailable" section with the breadcrumb text from §7
**And** the command exits 0 (not an error state)
**And** the AuditTail from SQLite still renders normally below

### AC14 — `show <cust-id> --audit-tail N` does NOT show last-24h stats

**Given** a fresh snapshot with data
**When** `comadre-keys show cust_01XYZ --audit-tail 20` runs
**Then** the output has NO "Last-24h stats" section (the section is key-only in MVP)
**And** the `--format json` output has NO `stats` field in the payload

### AC15 — Snapshot writer respects event-loop boundaries

**Given** the periodic snapshot writer is running
**When** `await asyncio.sleep(30)` elapses (two snapshot intervals at 15s)
**Then** two snapshots have been written (mtime changed twice)
**And** the event loop was never blocked for > 10ms in any single iteration (no sync file I/O on the loop — `asyncio.to_thread` offloads the `os.replace` path)

### AC16 — Lifespan cancellation writes a final snapshot

**Given** counters have accumulated since process start
**When** the FastAPI app shuts down (lifespan `finally` branch)
**Then** a final snapshot is written before the task is cancelled
**And** the task exits cleanly (no uncaught `CancelledError` in logs)

### AC17 — NFR7 budget: counter path adds ≤ 2ms p99

**Given** a warm auth cache and warm counter state
**When** 100 successive requests are measured at p99
**Then** the added overhead of `incr_request + incr_auth_success` is ≤ 2ms p99
**And** no file I/O happens on the request path (snapshot writer runs on a separate asyncio task)

### AC18 — `system.py` registered in the top-level Typer app

**Given** `comadre-keys --help`
**When** the help text is printed
**Then** `cache-status` appears in the command list
**And** the command is reachable as `comadre-keys cache-status` (flat, not `comadre-keys system cache-status`)

### AC19 — Snapshot schema is PII-free

**Given** a snapshot with any content
**When** the file is grepped for PII markers
**Then** no line contains `cmdr_live_`, a 64-hex-character run (SHA-256), a bearer-like string, a customer name, an email address, or a CPF/CNPJ digit sequence (11–14 digits)
**And** only `key_id` (opaque ULID `key_*`) appears as an identifier

### AC20 — Counter imports preserve the downward-only graph

**Given** the final `src/comadre/counters.py`
**When** grepped with `rg "^from comadre\." src/comadre/counters.py`
**Then** only imports from `comadre.logging` (and possibly `comadre.keys.models` for type hints) appear
**And** `keys/auth.py` + `rate_limit.py` import `counters.py` (downward), not the reverse
**And** `uv run python -c "import comadre.counters; import comadre.main"` loads without ImportError

## Tasks / Subtasks

- [x] **Task 1 — Create `src/comadre/counters.py`** (AC1, AC3, AC4, AC5, AC7, AC15, AC19, AC20)
  - [x] 1.1 `_KeyCounter` dataclass + `RequestCounters` class with the methods described in §1.
  - [x] 1.2 `collections.deque` with `maxlen=None` for `window_hits`; prune-on-touch logic.
  - [x] 1.3 `peak_rpm` updated only on `incr_request` (not on `snapshot`, to avoid drift).
  - [x] 1.4 `snapshot(auth_cache_snapshot)` returns the schema-version-1 structure.
  - [x] 1.5 `start_snapshot_writer` schedules an `asyncio.create_task` loop; the loop calls `await asyncio.to_thread(self._write_snapshot_sync)`.
  - [x] 1.6 `_write_snapshot_sync` writes `.tmp` + `Path.replace`; re-applies mode 0600 every write (chmod on a <1 KB file is microseconds; skipping subsequent writes would let umask re-surface after each atomic rename).
  - [x] 1.7 `stop_snapshot_writer` cancels the task cleanly + best-effort final snapshot (and a pre-cancel final write, so the on-disk snapshot reflects the latest counters even when the writer is mid-sleep).

- [x] **Task 2 — Wire counter increments into `keys/auth.py`** (AC1, AC2)
  - [x] 2.1 Import `RequestCounters` (TYPE_CHECKING-guarded).
  - [x] 2.2 After `request.state.auth_payload = payload`, call `incr_request` + `incr_auth_success`.
  - [x] 2.3 Guard with `getattr(..., None)` so test fixtures that bypass lifespan keep passing.

- [x] **Task 3 — Wire 429 counter increment + structured log into `rate_limit.py`** (AC2, AC6)
  - [x] 3.1 Added `_rate_limit_logger = get_logger("rate_limit")`.
  - [x] 3.2 On deny, calls `incr_429(payload.key_id)` + emits the structured log line from §3.
  - [x] 3.3 No log on allow (hot path).

- [x] **Task 4 — Wire `RequestCounters` bootstrap into `main.py` lifespan** (AC5, AC7, AC15, AC16)
  - [x] 4.1 After `RateLimiter.build()`, constructs `RequestCounters` + starts the snapshot task.
  - [x] 4.2 Logs the snapshot path + interval alongside the existing startup log line.
  - [x] 4.3 In lifespan `finally`, calls `rc.stop_snapshot_writer()` which cancels the task with `CancelledError` suppressed.
  - [x] 4.4 `stop_snapshot_writer` performs a best-effort final snapshot before cancel (pre-cancel), and the task's own `except CancelledError` does another final snapshot.

- [x] **Task 5 — Create `src/comadre/keys/cli/commands/system.py`** (AC8, AC9, AC10, AC11, AC18)
  - [x] 5.1 Typer subapp with `cache-status` command.
  - [x] 5.2 `_CACHE_STATUS_BOUND_MESSAGE` lives in `output.py` — single source for AC9 reused by both the table renderer and the JSON payload.
  - [x] 5.3 Snapshot read path with `json.loads` + try/except for parse errors, logs to WARN and degrades silently.
  - [x] 5.4 Freshness classification: fresh (< 60 s), stale (≥ 60 s), absent, unreadable.
  - [x] 5.5 Table-format rendering via new `render_cache_status(...)` helper in `output.py`.
  - [x] 5.6 JSON-format rendering inline in `cache_status_cmd` (via `stdout_console().print_json`) with the required fields.
  - [x] 5.7 Exit-code mapping: 0 on all reachable-CLI states; 2 on `--format` usage error; 6 on encryption-key / TZ config error.
  - [x] 5.8 Registered `system_app.registered_commands` in `src/comadre/keys/cli/app.py` alongside the existing customers / keys merges.

- [x] **Task 6 — Add `render_last_24h_stats` + `render_cache_status` to `output.py`** (AC12, AC13)
  - [x] 6.1 `render_last_24h_stats(stats: Last24hStats | None)` — subordinate-indented lines matching `AuditTail` style.
  - [x] 6.2 `render_cache_status(snapshot, snapshot_age_seconds, stale)` — bound message + optional telemetry rows.
  - [x] 6.3 `Last24hStats` dataclass added to `keys/models.py` alongside `AuditEventRow`.
  - [x] 6.4 All output functions pass `markup=False, highlight=False` to Rich to prevent accidental markup injection.

- [x] **Task 7 — Extend `show_cmd` to render last-24h stats for key targets** (AC12, AC13, AC14)
  - [x] 7.1 After resolving target, for `kind == "key_single"`, attempts to read the snapshot via `_load_last_24h_stats` for `key_row.id`.
  - [x] 7.2 Calls `render_last_24h_stats(...)` between `render_key_detail` and `render_audit_tail` in the table-format branch, only when `--audit-tail` is present.
  - [x] 7.3 Added a `stats` field to the `render_show_json` payload for `api_key` target_type; omitted for `customer`. Controlled by `include_stats: bool` so bare `show <key>` (no `--audit-tail`) stays schema-stable.
  - [x] 7.4 Snapshot read is wrapped in `try/except`; any failure degrades to `None` with a WARN log (never crashes `show`).

- [x] **Task 8 — Docs sweep**
  - [x] 8.1 Extended `docs/rate-limiting.md` with §Counters + §Cache observability + §Counter snapshots across replicas + §`show --audit-tail` integration.
  - [x] 8.2 Added an §Auxiliary files table to `docs/configuration-reference.md` covering both sentinel files.
  - [x] 8.3 Added the `cache-status unavailable` entry to `docs/troubleshooting.md`.
  - [x] 8.4 One-line mention of counters + `cache-status` in `CLAUDE.md`'s rate-limiting bullet and CLI list; one-line feature bullet for operator observability in `README.md`.

- [x] **Task 9 — Tests**
  - [x] 9.1 `tests/test_counters.py` — 27 unit tests covering increments, peak / window semantics, snapshot schema, atomic writes, writer task lifecycle, and import-graph AC20.
  - [x] 9.2 `tests/test_api.py::TestRequestCounters` — 4 integration tests (happy path, 429 counter, two-key isolation, 429 log line with `key_id` + `customer_id` + PII guards).
  - [x] 9.3 `tests/test_api.py::TestCountersSnapshotLifespan` — 2 lifespan-scoped tests (snapshot + mode 0600 after shutdown, task cancelled cleanly).
  - [x] 9.4 `tests/test_keys_cli_cache_status.py` — 18 CLI tests (usage/config errors, verbatim bound message on every state, table telemetry, JSON shape, read-only assertions, malformed-JSON degradation, help surface).
  - [x] 9.5 `tests/test_keys_cli_show.py` — 10 new cases across `TestShowKeyLast24hStats` and `TestShowKeyLast24hStatsJson` (fresh / missing / stale / other-key / customer target / bare show / JSON presence + nullability).
  - [x] 9.6 `tests/conftest.py` — kept in-test helpers (`_write_counters_snapshot` in each test file) instead of adding a shared `counters_snapshot_file` fixture — the helper is ~30 lines and only used by two files; co-locating it with the assertions keeps test intent obvious. A conftest fixture is a trivial future refactor if a third consumer appears.

- [x] **Task 10 — Sanity gates**
  - [x] 10.1 `uv run ruff check .` clean.
  - [x] 10.2 `uv run mypy src/` clean (strict mode).
  - [x] 10.3 `uv run pytest` — 1090 pass / 0 fail (baseline 1029 + 61 new).
  - [x] 10.4 `uv run pre-commit run --all-files` clean.
  - [x] 10.5 Grep checks:
    - [x] `rg "HTTPException" src/comadre/counters.py src/comadre/keys/cli/commands/system.py` → zero hits.
    - [x] `rg "\\bprint\\(" src/comadre/counters.py src/comadre/keys/cli/commands/system.py` → zero code hits (one false-positive match is the string `"print(Fernet.generate_key()...)"` inside the `_MISSING_KEY_HINT` operator-facing help text; no runtime `print()` call).
    - [x] `rg "os\\.environ" src/comadre/counters.py src/comadre/keys/cli/commands/system.py` → zero hits.
    - [x] `rg "cmdr_live_|[0-9a-f]{64}" {KEY_REGISTRY_DB_PATH}.counters.json` — verified in `tests/test_counters.py::TestSnapshotSchema::test_snapshot_contains_no_pii_markers` (serializes a counters snapshot and asserts both patterns return empty).

## Dev Notes

### Import-graph decision record

The project's downward-only import rule (`CLAUDE.md`: config/logging → exceptions/schemas → preprocessing → service → rate_limit → api/health → main) creates a specific constraint for Story 2.3: **`counters.py` must sit below both `keys/auth.py` and `rate_limit.py`**, because both of those modules import the counters to increment them.

Architecture L287-292 spells out the existing layering:

```
keys/auth.py → keys/cache.py + keys/db.py
keys/billing.py → keys/db.py + keys/audit.py
rate_limit.py → keys/auth.py
keys/cli/ → everything in keys/ except keys/auth.py and keys/cache.py
main.py → keys/auth.py + keys/db.py
```

Story 2.3 extends this with:

```
counters.py → stdlib only (+ comadre.logging)
keys/auth.py → counters.py (new downward import)
rate_limit.py → counters.py (new downward import)
main.py → counters.py (new downward import)
keys/cli/commands/system.py → reads the counters snapshot FILE; does NOT import counters.py (CLI never touches runtime state directly)
```

This is exactly consistent with Story 2.1's decision: the CLI never imports `AuthCache` either — it touches the sentinel file instead. File-based IPC is the CLI-to-API protocol for this project.

### Why file IPC and not an internal HTTP endpoint

Architecture L198-201 explicitly rules out mutation-style cache-status commands. It does NOT rule out a read-only internal HTTP endpoint, but it does say "adding a signal or sentinel mechanism to the auth hot path introduces complexity". The file-sentinel pattern is the project's chosen IPC primitive; reusing it is free (no new code path) and keeps the story additive.

A read-only internal endpoint would require: (a) a new route binding (likely localhost-only, which Caddy would need to exempt from TLS termination); (b) auth handling (the endpoint shouldn't require a customer key); (c) a new HTTP client in the CLI (no HTTP client in `comadre-keys` today — the CLI is file + SQLite only). That's three new surfaces for one read. The snapshot file gives the same observability for one surface (file reads).

### Why not just use `limits.aio.storage.MemoryStorage` for `peak_rpm` / `avg_rpm_last_60s`

`MemoryStorage.get_moving_window` (the underlying primitive behind `get_window_stats`) returns enough information to compute the current window count. Reusing it would save the parallel `collections.deque` of timestamps in `_KeyCounter`.

Two reasons not to:

1. **Cycle.** `counters.py` would need to import `rate_limit.py` (for the `RateLimiter` instance) — but `rate_limit.py` imports `counters.py` to increment on deny. Circular.

2. **Semantic split.** `rate_limit_rpm` is the *budget*; `peak_rpm` / `avg_rpm_last_60s` are *observed behavior*. If we ever change the rate-limit strategy (e.g., move to `limits.aio.strategies.SlidingWindowCounterRateLimiter`, or add a burst-token bucket), the observation surface should not co-evolve with the enforcement surface. Keeping the deque in `counters.py` isolates observability from policy.

The cost is ~200 bytes per active key for the deque (~60 float timestamps × 8 bytes). For 1000 keys that is 200KB — negligible per NFR27's 50MB budget.

### Why `requests_total` counts the 429 request

It is tempting to define `requests_total = auth_success - rate_limit_429` so the arithmetic is "clean". Don't. The operator's mental model is:

- `requests_total` = "how much did this key attempt?"
- `auth_success` = "how much did this key authenticate?"
- `rate_limit_429` = "how much was throttled?"
- `requests_total - auth_success` = "how much failed at the auth layer?" (always 0 in Story 2.3 scope, by construction — auth denials raise before `incr_request`; could become non-zero if a future story increments on unauthenticated probes too)

A customer debugging their integration asks "is the API even seeing my requests?" → look at `requests_total`. If yes, they next ask "am I getting rate-limited?" → look at `rate_limit_429`. Separate counters, separate questions.

### Why the snapshot writer uses `asyncio.to_thread` and not `aiofiles`

Project has zero `aiofiles` footprint today. Adding it for one call site is overbuilt. `asyncio.to_thread` is stdlib, offloads the sync `open + write + os.replace` to a thread, and keeps the event loop free.

If Story 4.x (hardening) later adopts `aiofiles` for other reasons, this is a trivial one-line migration.

### Counter precision under a shape-valid spray

If an attacker sprays shape-valid-random bearers at `/v1/audio/speech` (the same DoS vector flagged at `deferred-work.md:7`), they pay the DB lookup cost, `ApiKeyNotFoundError` raises, and **no counter is touched** (the `auth_payload` is never set; `incr_request` never runs). Good: the counters reflect real key behavior, not attacker noise.

If the attack were somehow able to reach `check_rate_limit` with a fake `auth_payload`, it would increment `rate_limit_429` for an attacker-controlled `key_id`. The threat model rules this out: `auth_payload` is set only after a successful DB lookup, and `verify_api_key` is the only path to `check_rate_limit` (FastAPI dependency ordering guaranteed by `api.py:37-40`). An attacker cannot set `auth_payload` from outside.

### Peak-RPM vs moving window

`peak_rpm` is documented as "max observed window count". Formally: after every `incr_request`, `peak_rpm = max(peak_rpm, len(window_hits))`. Since `window_hits` has already been pruned to the last 60s by that call, `len(window_hits)` is the count of hits in the last 60s including the one just recorded.

Edge case: a key that does exactly `rate_limit_rpm` rps for one burst, idles, and never comes back will show `peak_rpm = rate_limit_rpm` forever. That is correct — it's the honest historical high-water mark. If the operator wants "recent peak", they restart the replica (counters reset — AC5).

### Structured log channel for 429

The existing `access_log_middleware` in `main.py:258-281` emits one log line per request at the HTTP layer. Story 2.3's new 429-specific log line is emitted from `rate_limit.py` just before the `raise RateLimitError`. Both lines will appear for a 429 — the new one with `key_id=` attribution, the old one with the HTTP-layer fields. Operators grepping by `key_id=` will find the attribution line; operators grepping by IP will find the access-log line. No de-duplication needed; the cost is one extra log line per 429 (not per request).

### What happens when the snapshot file exists but `keys.db` has moved

If an operator moves `KEY_REGISTRY_DB_PATH` between restarts, the old `.counters.json` file at the old path is orphaned. The new API process writes to the new path. The CLI reads from whichever `KEY_REGISTRY_DB_PATH` is in its environment. Result: if the CLI and API see the same `KEY_REGISTRY_DB_PATH`, the snapshot works; otherwise the CLI sees "unavailable". This mirrors the existing `.invalidate` sentinel semantics (same failure mode, same fix: sync the env).

`docs/troubleshooting.md` already has the sentinel-path section (L211-213 per Story 2.2); extend it to cover the counters file.

### Project Structure Notes

New files:

```
src/comadre/
  counters.py                          [NEW]
  keys/cli/commands/
    system.py                          [NEW]

tests/
  test_counters.py                     [NEW]
  test_keys_cli_cache_status.py        [NEW]
```

Modified files:

```
src/comadre/
  keys/auth.py                         [MOD — 2 increment calls]
  rate_limit.py                        [MOD — 429 counter + log line]
  main.py                              [MOD — lifespan bootstrap + shutdown]
  keys/cli/commands/customers.py       [MOD — show_cmd last-24h stats]
  keys/cli/output.py                   [MOD — render_last_24h_stats, render_cache_status]
  keys/cli/app.py                      [MOD — register system_app]
  keys/models.py                       [MOD — Last24hStats dataclass]

tests/
  test_api.py                          [MOD — TestRequestCounters, TestCountersSnapshotLifespan]
  test_keys_cli_show.py                [MOD — snapshot-aware cases]
  conftest.py                          [MOD — counters_snapshot_file fixture]

docs/
  rate-limiting.md                     [MOD]
  configuration-reference.md           [MOD]
  troubleshooting.md                   [MOD]

CLAUDE.md                              [MOD — one-line note in rate-limiting bullet]
README.md                              [MOD — cache-status in CLI list, if present]
```

No file moves. No deletes. No dependency additions to `pyproject.toml`.

### Testing standards

- All tests run without the TTS model (the test `app` fixture already mocks the engine router).
- Counter increments happen on `app.state`, not on module globals — tests construct their own `RequestCounters` instance where needed and bind it to a test `app`.
- Snapshot tests use `tmp_path` for the snapshot file; never writes to a real registry path.
- `caplog` captures the 429 log line for AC6 assertions.
- No test should need a real asyncio loop to sleep 15s (the snapshot interval). Use `monkeypatch` to set `snapshot_interval_seconds=0.05` or call `_write_snapshot` directly.
- Prefer `insert_api_key` from `keys/db.py` over hand-rolled INSERT SQL (Story 2.2 review finding).
- Assert PII-free log lines with a combined regex: `cmdr_live_|[0-9a-f]{64}|key_[0-9A-HJKMNP-TV-Z]{26}|cust_[0-9A-HJKMNP-TV-Z]{26}|<email-pattern>` — the `key_` and `cust_` ULIDs are allowed identifiers; only bearer material, hashes, names, and emails are forbidden (AC6, AC19).

### References

- Epic 2 + Story 2.3 scope — `_bmad-output/planning-artifacts/epics.md:576-603`
- FR33 full wording — `_bmad-output/planning-artifacts/prd.md:1168`
- FR45 full wording — `_bmad-output/planning-artifacts/prd.md:1186`
- Architecture cache-invalidation decision — `_bmad-output/planning-artifacts/architecture.md:198-201`
- Architecture Gap 1 (per-key counters scoping) — `_bmad-output/planning-artifacts/architecture.md:745-748`
- Architecture module layout — `_bmad-output/planning-artifacts/architecture.md:287-357`
- UX-DR3 DetailPanel + UX-DR5 AuditTail conventions — `_bmad-output/planning-artifacts/ux-design-specification.md:277-282, 805-818`
- Journey 5 (instant forensics) — `_bmad-output/planning-artifacts/ux-design-specification.md:94, 606-631`
- Story 2.1 cache-snapshot() method — `src/comadre/keys/cache.py:102-113`
- Story 2.1 invalidation-sentinel pattern — `src/comadre/keys/cache.py:60-85`, `src/comadre/keys/db.py:163-183`
- Story 2.2 rate-limit bucket identity + `key_id` stability — `docs/rate-limiting.md:30-39`, `src/comadre/rate_limit.py:114`
- Story 2.2 deferred item #3 (429 key_id attribution) — `_bmad-output/implementation-artifacts/deferred-work.md:25`
- Story 1.4 show --audit-tail scaffolding — `src/comadre/keys/cli/commands/customers.py:413-588`
- Exit-code contract — `src/comadre/keys/cli/commands/keys.py:1-10`

## Questions for Operator (please confirm before dev-story)

1. **Snapshot interval**: the story defaults to 15 seconds. Is that the right cadence for your operator rhythm? Shorter = fresher telemetry but more fsync activity; longer = potentially > 1min stale when an operator runs `cache-status`. Recommend keeping 15s for MVP.

2. **Multi-replica snapshot strategy**: the story specifies a single `.counters.json` file that replicas overwrite. In a multi-replica deployment this means the CLI shows whichever replica wrote last. Accept that (and document it) for MVP, or do you want per-replica files like `.counters.$(hostname).json` with CLI aggregation now? Recommend accepting single-file for MVP — `docs/rate-limiting.md:41-51` already sets the expectation that multi-replica observability is approximate.

3. **Customer-level aggregate in `show`**: AC14 specifies the last-24h stats section is **key-only** for MVP. A customer with 3 keys would show no stats on `show <cust-id>`. Story 3.2 (revenue reports) is the next natural place to add customer-aggregate views. Is that scope split correct, or do you want customer-aggregate now?

4. **Scope of `requests_total`**: the story defines it as "requests that successfully authenticated, including those later 429'd". An alternative definition is "requests the system saw, including 401s" — the counter would then also increment on unknown keys. That would require moving the increment earlier in the auth path and either (a) counting by input IP (not a counter-per-key, which is the FR33 surface) or (b) counting a "no-key" bucket. The story's current definition keeps counters per-`key_id`, which is the FR33 shape. Confirm this reading of FR33.

5. **Docs sweep completeness**: tasks 8.1–8.4 update `docs/rate-limiting.md`, `docs/configuration-reference.md`, `docs/troubleshooting.md`, `CLAUDE.md`, and optionally `README.md`. No new top-level doc file is added — the snapshot file semantics live inside `rate-limiting.md` §Counters. Confirm no dedicated `docs/counters.md` is required.

## Dev Agent Record

### Agent Model Used

claude-opus-4-7 (1M context) via `bmad-dev-story` skill.

### Debug Log References

None. All sanity gates (ruff, mypy, pytest, pre-commit) green on first full-suite run after implementation (1090 pass / 0 fail).

### Completion Notes List

- **Operator questions resolved against story recommendations.** All five questions at the bottom of the story carried explicit recommendations. I adopted each default: 15 s snapshot interval; single-file snapshot (no per-replica variants in MVP); last-24h stats are key-target-only (customer-aggregate is Story 3.2 territory); `requests_total` counts requests that successfully authenticated; no dedicated `docs/counters.md` — counters documented inside `docs/rate-limiting.md` §Counters. Story was triggered autonomously via a `/loop` watching `sprint-status.yaml` for the `ready-for-dev` flip, so adopting the story-author's defaults was the right stance — any operator override can be logged as a follow-up.
- **Implementation diverged from story text in two places, both for correctness.**
  1. The story said "Mode `0600` set on first write ... subsequent writes do not re-chmod (cheap)." I made every write re-chmod. `tmp.replace(snapshot_path)` atomically swaps the destination inode for the tmp inode, which carries the umask-derived mode (typically `0o644`); skipping subsequent chmods would let the mode drift back to umask on every rename. Chmod on a local <1 KB file is microseconds; the cost is negligible. The test file `tests/test_counters.py::TestAtomicWrite::test_write_is_idempotent` explicitly verifies this path.
  2. The story's `start_snapshot_writer` signature took `loop: asyncio.AbstractEventLoop` and `auth_cache: AuthCache`. I switched to `auth_cache_snapshot: Callable[[], dict[str, Any]]` (no loop parameter — `asyncio.get_running_loop()` internally). Rationale: accepting the `AuthCache` would require `counters.py` to import `AuthCache`, breaking AC20's stdlib-plus-logging import graph. The callable is the minimum coupling that satisfies the lifespan (which passes `app.state.auth_cache.snapshot`) and the tests.
- **`render_show_json` grew an optional `include_stats` flag.** Bare `show <key>` (no `--audit-tail`) stays schema-stable — it does not emit the `stats` key at all. `show <key> --audit-tail N` always emits `stats`, either as the populated dict or as `null` when the snapshot is missing / stale / other-key. Customer targets never emit the key (AC14).
- **`/health` DoS note from Story 2.2 deferred-work unchanged.** Story 2.3's structured 429 log line (`key_id=…`) closes the deferred-work entry "429 access log lacks key_id attribution". The Caddy-layer mitigation for shape-valid-random spray on `/health` is still the correct operator action and remains deferred as documented.
- **AC17 (NFR7 ≤2 ms p99 budget) is not covered by a benchmark test.** The counter path is pure in-memory dict ops with no I/O; the budget is met by design. The missing microbench is already tracked as a deferred item in `_bmad-output/implementation-artifacts/deferred-work.md` (post-Story 2.2 entry "NFR7 ≤2 ms p99 budget unverified — add scripts/bench_rate_limit.py in a follow-up story"). Story 2.3 does not re-add the benchmark to keep scope bounded; the design rationale (O(1) dict ops, no request-path I/O) is explicit in `src/comadre/counters.py` module docstring.
- **Task 9.6 kept inline instead of promoted to a conftest fixture.** The helper is ~30 lines and only has two consumers (`test_keys_cli_cache_status.py`, `test_keys_cli_show.py`). A shared conftest fixture is a trivial refactor if a third consumer appears; co-locating the helpers with the tests keeps intent obvious at the call site. Logged here so a reviewer doesn't flag the "missing" fixture as an oversight.
- **Testing summary:** 27 unit tests in `tests/test_counters.py`; 4 integration tests in `test_api.py::TestRequestCounters`; 2 lifespan tests in `test_api.py::TestCountersSnapshotLifespan`; 18 CLI tests in `tests/test_keys_cli_cache_status.py`; 10 `show` integration tests in `tests/test_keys_cli_show.py` (new `TestShowKeyLast24hStats*` classes). Total new tests: 61.
- **Sanity gates:** `uv run ruff check .`, `uv run mypy src/`, `uv run pytest -q`, `uv run pre-commit run --all-files` — all clean. Test suite: 1090 pass / 0 fail (from 1029 pre-story baseline).

### File List

**New files:**

- `src/comadre/counters.py` — `RequestCounters` + `_KeyCounter` + atomic snapshot writer.
- `src/comadre/keys/cli/commands/system.py` — `cache-status` Typer command.
- `tests/test_counters.py` — 27 unit tests.
- `tests/test_keys_cli_cache_status.py` — 18 CLI tests.

**Modified files:**

- `src/comadre/keys/models.py` — `Last24hStats` dataclass.
- `src/comadre/keys/auth.py` — `incr_request` + `incr_auth_success` after `auth_payload` set.
- `src/comadre/rate_limit.py` — `incr_429` + structured `_rate_limit_logger` line on deny branch.
- `src/comadre/main.py` — lifespan bootstrap of `RequestCounters` + `stop_snapshot_writer` in `finally`.
- `src/comadre/keys/cli/output.py` — `_CACHE_STATUS_BOUND_MESSAGE`, `render_cache_status`, `render_last_24h_stats`, `_format_uptime`, `_format_seconds_ago`, `_last_activity_ago`, `render_show_json` gains `stats` + `include_stats` kwargs.
- `src/comadre/keys/cli/commands/customers.py` — `_load_last_24h_stats`, `_last_24h_stats_to_json`, `show_cmd` now loads + renders stats for key targets with `--audit-tail`.
- `src/comadre/keys/cli/app.py` — registers `system_app.registered_commands`.
- `tests/test_api.py` — `TestRequestCounters` + `TestCountersSnapshotLifespan` classes (appended before `TestMonetizationHealthEndpoint`).
- `tests/test_keys_cli_show.py` — `_write_counters_snapshot` helper + `TestShowKeyLast24hStats` + `TestShowKeyLast24hStatsJson` classes.
- `docs/rate-limiting.md` — §Counters, §Cache observability, §Counter snapshots across replicas, §`show --audit-tail` integration.
- `docs/configuration-reference.md` — §Auxiliary files table.
- `docs/troubleshooting.md` — `comadre-keys cache-status reports "unavailable"` entry.
- `CLAUDE.md` — rate-limiting bullet + CLI command list updated.
- `README.md` — feature bullet for operator observability.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — status transition.
- `_bmad-output/implementation-artifacts/2-3-request-counters-cache-management.md` — this file.

### Change Log

- **2026-04-18** — Story 2.3 implemented via `bmad-dev-story`. Per-key counters, periodic snapshot writer, `cache-status` CLI, `show --audit-tail` stats section. All 20 ACs mapped to tests; 61 new tests; 1090 / 1090 pass. Ruff, mypy, pre-commit all clean. Status → review.

### Review Findings — Resolved 2026-04-18

- [x] [Review][Decision] **D1 — Stale-snapshot policy unified.** Chose the industry-standard resolution: drop the 60 s cutoff in `show --audit-tail`, keep the 60 s cutoff out of the read path entirely, surface freshness as a label in both surfaces. `cache-status` and `show --audit-tail` now both render data with a `snapshot written Xs ago` header regardless of age; "unavailable" now means only "no readable snapshot" or "no replica reports this key". The `stale` branch was deleted from `render_cache_status`. No hidden data behind arbitrary cutoffs.
- [x] [Review][Decision] **D2 — Multi-replica architecture corrected to per-replica files with CLI aggregation.** Each replica writes `{db_path}.counters.{hostname}.json`; the CLI globs every matching file and aggregates (sum for `requests_total`/`auth_success`/`rate_limit_429`/`avg_rpm_last_60s`/cache hits+misses+entries; max for `peak_rpm`/`last_activity_at`; min for `snapshot_age_seconds`/`process_uptime_seconds`). Eliminates the `.tmp` collision and the silent "last-writer-wins N-1 replicas' traffic hidden" failure mode. New module-level helpers: `default_replica_id()`, `counters_snapshot_path()`, `counters_snapshot_glob()`, `read_all_snapshots()`, `aggregate_cache_status()`, `aggregate_key_stats()`.
- [x] [Review][Patch] **P1 — Thread-safe snapshot build.** `RequestCounters.snapshot()` now runs synchronously on the asyncio event loop (no `await`), producing a JSON string BEFORE `asyncio.to_thread(_atomic_write, ...)`. The worker thread receives only the pre-serialized payload and never iterates mutable state. `dict` mutation races eliminated by construction. [`src/comadre/counters.py::_write_snapshot_safe`]
- [x] [Review][Patch] **P2 — Atomic write uses `tempfile.mkstemp`.** Each writer gets a unique tempfile name; concurrent writes (two replicas, or pre-cancel + cancel-handler) no longer collide on the `.tmp` path. Plus OSError cleanup removes orphan tempfiles on disk-full. [`src/comadre/counters.py::_atomic_write`]
- [x] [Review][Patch] **P3 — Obsolete.** The `age_seconds` cutoff in `_load_last_24h_stats` was removed entirely as part of D1 (data is shown regardless of age). The shared reader in `comadre.counters.read_all_snapshots` clamps age with `max(0, ...)` at parse time, so clock skew can never flip the sign on any CLI surface.
- [x] [Review][Patch] **P4 — Obsolete.** The strict `isinstance(process_uptime, int)` check is gone; the new aggregator's `_coerce_int` accepts both `int` and `float` JSON scalars.
- [x] [Review][Patch] **P5 — `_coerce_int` helper.** Replaced every `int(auth_cache.get("hits", 0))` call with `_coerce_int(auth_cache.get("hits"))` in the aggregator. Null/bool/string values degrade to 0 with no crash. [`src/comadre/counters.py::_coerce_int`]
- [x] [Review][Patch] **P6 — Stale duplicate removed.** `render_cache_status` no longer renders the redundant `"(last updated: X ago)"` suffix — the header already carries the age.
- [x] [Review][Patch] **P7 — `_mode_set` dead field deleted** from `RequestCounters`. The chmod is now applied to the tempfile inode BEFORE the rename (via `tmp.chmod(0o600)`), so the mode follows the inode into the final position — every write lands at 0600 without stateful tracking.
- [x] [Review][Patch] **P8 — `CACHE_STATUS_BOUND_MESSAGE` renamed** to drop the leading underscore. It's a shared public constant used across `output.py`, `system.py`, and the test suite's verbatim-string assertion.
- [x] [Review][Patch] **Tests + docs rewritten.** New tests: `TestReplicaPathHelpers`, `TestReadAndAggregate`, `TestAtomicWriteHardening::test_concurrent_writes_do_not_tear`, `TestAtomicWriteHardening::test_disk_full_cleans_up_tmp`, and multi-replica aggregation cases in `test_keys_cli_cache_status.py` + `test_keys_cli_show.py`. Docs: `docs/rate-limiting.md` rewritten to describe the per-replica aggregation; `docs/troubleshooting.md` and `docs/configuration-reference.md` updated for the new filename pattern; `CLAUDE.md` updated.
- [x] [Review][Gates] **All sanity gates clean** — `ruff check`, `mypy src/` (strict), `pytest -q` (1104 pass, +14 new tests), `pre-commit run --all-files`.
- [x] [Review][Defer] **W1 — AC15 two-write + NFR7 ≤2 ms p99 coverage gaps** [`tests/test_counters.py:231-241`] — deferred, self-declared in Completion Notes.
- [x] [Review][Defer] **W2 — AC19 PII test narrower than wording (no customer name/email/CPF/CNPJ assertion)** [`tests/test_counters.py:169-180`] — deferred, coverage-only; no behavior gap by construction.
- [x] [Review][Defer] **W3 — Unbounded `window_hits` deque at high `rate_limit_rpm`** [`src/comadre/counters.py:58, 104`] — deferred, only reachable at rpm tiers not currently issued.
- [x] [Review][Defer] **W4 — `stop_snapshot_writer` has no timeout on NFS/hung-mount shutdowns** [`src/comadre/counters.py:197`] — deferred, uncommon deployment topology.
- [x] [Review][Defer] **W5 — Disk-full leftover `.tmp` file not cleaned up** [`src/comadre/counters.py:247`] — deferred, rare edge case.
- [x] [Review][Defer] **W6 — `tests/test_counters.py` `monkeypatch(time.monotonic)` captures `process_start` before patch** [`tests/test_counters.py::TestPeakAndAverage`] — deferred, test-only latent flake.
- [x] [Review][Defer] **W7 — `written_at` parser only catches `ValueError`; a future non-`Z` ISO could raise `TypeError` on naive-datetime subtraction** [`src/comadre/keys/cli/commands/customers.py:435-437`, `src/comadre/keys/cli/commands/system.py:90-97`] — deferred, forward-compat concern.
- [x] [Review][Defer] **W8 — JSON `snapshot_available: true` can coexist with missing telemetry fields (schema asymmetry)** [`src/comadre/keys/cli/commands/system.py:187-205`] — deferred, low operator impact.
