# Story 3.4: System Health Command

Status: in-progress

> **Scope note — FR34 (+ FR42 / FR43 read-side).** Epic 3 closes its operator surface with the read-only `comadre-keys health` verb that turns four otherwise-buried signals into a single panel: *(1)* DB integrity (path, size, `0600` permissions, schema-version parity with the binary); *(2)* registry shape (active customer count, active/suspended/revoked key counts); *(3)* cron + sweep liveness (was bootstrap's `comadre-daily-suspension` entry installed? did `cron_suspend` fire recently?); *(4)* auth-cache state (the existing per-replica counter snapshots Story 2.3 already aggregates for `cache-status`). The command **never mutates state** — no `INSERT`, no `UPDATE`, no sentinel touch — and is safe to run from cron itself, from a monitoring script, or from the operator's terminal. **Two output modes**: `--format table` (default, single-border Rich panel, always exits 0 — yellow warnings are operator-readable hints, not script signals) and `--format json` (machine-readable, exits **7** when any check is `warn` / `fail` so a `nagios`-class monitor key off `$?`). The exit-7 bifurcation is the one architectural addition this story makes to the system-module exit-code contract; everything else reuses the helpers Stories 2.3 and 3.3 already shipped (`load_settings_and_tz`, `get_connection`, `_apply_migrations`, `read_all_snapshots` + `aggregate_cache_status`, `get_last_sweep_timestamp`, `count_tombstones`). **No DB write. No new auth path. No new dependency. No schema change.** Backup-recency is plumbed forward (Story 4.3 will populate it) but reports as `INFO` today — never `WARN` until 4.3 lands the backup writer.

## Story

As an operator,
I want to query overall system health with a single command,
so that I can verify in one glance — without grepping logs, parsing crontab, or stat-ing the DB file by hand — that the registry is the right size on disk, locked down to `0600`, schema-current, that yesterday's `comadre-daily-suspension` cron actually fired (and roughly when), and that the API replicas' auth caches are reporting fresh telemetry; and so that a monitoring script piping `comadre-keys health --format json` into Nagios / Prometheus textfile / a generic `$?` watcher gets a clean non-zero on any deviation worth my attention.

**Covers FRs:** FR34 (single-command health surface — primary). Consumes FR42 (file-permission policy — health *reports* drift; bootstrap *enforces* `0600`) and FR43 (last-sweep timestamp queryability — Story 3.3 persisted the timestamp; 3.4 surfaces it).
**NFRs:** NFR5 (CLI detail-class commands < 500 ms p99 for a 1 000-customer DB — `health` is detail-class). NFR15 (PII-austere INFO logs — the health log line carries counts and severity flags, never key prefixes / customer names / hashes / CPF digits). NFR16 (error hint never echoes invalid operator input — `--format` rejection mirrors `cache-status`'s exit-2 rendering).
**UX-DRs:** UX-DR3 (DetailPanel — single-border Rich panel with right-padded labels, the same shape `render_customer_detail` / `render_key_detail` use). UX-DR6 (ErrorDisplay — exit-2/5/6 panels via `render_error`). UX-DR8 (status colour discipline — green = ok, yellow = warn, red = fail; colour is the *accelerator*, the label word carries the meaning so `NO_COLOR` users still parse it). UX-DR10 (exit-code contract — extends to **0 / 2 / 5 / 6 / 7**; 7 is new, scoped to `--format json` mode only).
**Epic:** 3 — Billing & Revenue Operations. Final story in Epic 3 (3.1 → 3.2 → 3.3 → **3.4**); Epic 3's retrospective unblocks once this lands. The marker-file convention this story introduces (next §3) is the breadcrumb Epic 4's backup story (4.3) and encryption-rotation story (4.2) will reuse to surface their own liveness in `health` later.

## Builds on

- **Story 2.3 — `cache-status` CLI shape + counter-snapshot reader.** `src/comadre/keys/cli/commands/system.py:74-172` is the canonical template for a non-mutating system verb that supports both `--format table` and `--format json` while reusing `load_settings_and_tz` for exit-6 mapping. `health_cmd` follows the same skeleton: literal flag check → settings/TZ ladder → DB open → data collection → branch on format → render. The `read_all_snapshots(settings.key_registry_db_path)` + `aggregate_cache_status(snapshots)` pair from `src/comadre/counters.py:402-494` is reused **byte-for-byte** — `health` does not glob the snapshot files itself, it inherits whatever `cache-status` does. This is load-bearing: any future fix to snapshot parsing flows into both surfaces simultaneously.
- **Story 3.3 — `get_last_sweep_timestamp(conn)`.** `src/comadre/keys/db.py:1479` returns the canonical ISO-UTC timestamp (`YYYY-MM-DDTHH:MM:SSZ`) of the most-recent `cron_suspend` summary row, or `None` on a fresh DB. Story 3.4's "Last suspension sweep" field is a one-liner call to this helper + age-formatting via `_format_seconds_ago` (already in `output.py:672`). The story spec for 3.3 (§Integration with Story 3.4) explicitly committed this helper as the read surface — 3.4 takes the dependency unmodified.
- **Story 3.3 — `comadre-daily-suspension` cron entry + `BILLING_TIMEZONE` ↔ `CRON_TZ` parity invariant.** `deploy/ansible/playbooks/bootstrap.yml` installs the cron and the `CRON_TZ` envvar; `cleanup.yml` removes both. Story 3.4 piggybacks one new ansible task on each side: write a marker file (`{key_registry_db_path}.cron-installed`) when the cron entry is installed, remove it when the cron entry is uninstalled. Marker rationale spelled out below in §3.
- **Story 1.1 — `_apply_migrations` + `_SCHEMA_VERSION` constant.** `src/comadre/keys/db.py:188` (`_SCHEMA_VERSION = 1`) is the single source of truth for "what schema this binary supports". `_apply_migrations` (db.py:279) raises `RuntimeError` when the on-disk schema is **newer** than the binary (the operator deployed an older binary against a future-schema DB — refuse rather than corrupt). `health` reads `MAX(version) FROM schema_version` directly to compare against `_SCHEMA_VERSION`: `current == binary` → ok, `current < binary` → warn ("migration pending — run any other command to bootstrap"; in practice `_apply_migrations` ran during DB-open so this is unreachable on a `health` invocation that opened the DB successfully — the warn branch fires only when the DB exists but `schema_version` is empty or stale, which would itself be a bug worth surfacing).
- **Story 1.1 — `_chmod_0600` + `get_connection` permission discipline.** `src/comadre/keys/db.py:206-211` defines the canonical chmod helper; `get_connection` calls it on the DB file + WAL/SHM sidecars (db.py:270-272). `health` does not chmod — it stats. The drift check uses `os.stat(db_path).st_mode & 0o777` and compares to `0o600`. The renderer surfaces the actual mode in octal so the operator sees `0644` (drift) vs `0600` (ok) verbatim rather than a derived "DRIFT" sentinel string.
- **Story 1.1 — `count_tombstones(conn)`.** `src/comadre/keys/db.py:618` is the existing precedent for a small `int`-returning aggregate helper directly on the DB connection. Story 3.4 follows this idiom for **two new aggregate helpers** (§1 below), siting them adjacent to `count_tombstones` so all aggregate readers cluster.
- **Story 3.2 / 3.3 — `paid_until` / sort / output-formatting precedents.** `_iso_date` (output.py:223), `_format_seconds_ago` (output.py:672), `_format_uptime` (output.py:656) are the existing humanizers. `health` reuses all three — the renderer is largely a composition layer over existing primitives.
- **Story 1.6 / 3.1 — `load_settings_and_tz` shared helper.** `src/comadre/keys/cli/commands/keys.py:738` is the canonical exit-6 ladder; every CLI command in `system.py` and `billing.py` consumes it. `health_cmd` consumes it identically (with the now-standard `# type: ignore[attr-defined]` cast pattern that the deferred-work entry tracks for a future tightening pass).

## Unblocks

- **Story 4.2 — `rotate-encryption-key`.** Once landed, `health` will gain a new check: "Last encryption rotation: 2026-04-19T..." sourced from a new `audit_log` summary action (`encryption_rotated` / `target_type='system'` per the existing summary-row convention). 3.4's renderer is built so adding a new section is a one-line `render_health_section(...)` call — see §5 design.
- **Story 4.3 — `backup-keys.yml` / `restore-keys.yml`.** 3.4 already plumbs the "last backup" field as `INFO`-only (no WARN until 4.3 ships). When 4.3 lands, the operator just flips the `_BACKUP_NOT_IMPLEMENTED_INFO` constant in `keys/health.py` to enable the WARN branch when a backup is older than 48 h or absent. No new code — just a constant + a stale-threshold flip. The marker-file convention 3.4 introduces (next §3) is the same pattern 4.3 will use to signal "backup playbook installed yes/no" without parsing `crontab -l`.
- **Story 4.5x — CI Non-Regression Suite.** `health --format json` is the canonical machine-readable health-state oracle. CI smoke tests in 4.5e (rate-limit middleware registration) and 4.5f (no-raw-`HTTPException`) can additionally `comadre-keys health --format json | jq '.is_healthy'` against a freshly-bootstrapped registry to assert "default deploy is healthy" — a smoke that catches regressions in `_apply_migrations` / `bootstrap.yml` / DB perm policy in a single check.
- **Operator-side Nagios / Prometheus textfile / cron-watcher integrations.** The exit-7-on-unhealthy contract makes `health --format json` directly drop-in for `check_nagios`-style monitors. Document in `README.md` + `docs/configuration-reference.md`.

## Depends on

- Stories 1.1–1.6, 2.1–2.3, 3.1, 3.2, 3.3 must all be `done` (verified against `_bmad-output/implementation-artifacts/sprint-status.yaml` 2026-04-19; only 3.4 remains in Epic 3).
- No schema change. No new SQL beyond two `SELECT COUNT(*) ... GROUP BY status` reads + the existing `MAX(occurred_at)` from `get_last_sweep_timestamp`.
- No new dependency in `pyproject.toml` / `uv.lock`. The new module uses only stdlib (`os.stat`, `pathlib.Path`, `glob`, `sqlite3`, `datetime`) plus the existing `comadre.*` surfaces and `rich.*` (already a transitive dependency via the existing renderers).
- No FastAPI runtime change. `health` is CLI-only — `src/comadre/main.py`, `src/comadre/api.py`, `src/comadre/health.py` (the *HTTP* `/health` endpoint, distinct from this CLI verb), `src/comadre/rate_limit.py`, `src/comadre/keys/auth.py`, `src/comadre/keys/cache.py` all stay byte-identical (asserted by AC15).
- No change to `src/comadre/counters.py`. The CLI uses `read_all_snapshots` + `aggregate_cache_status` exactly as `cache_status_cmd` already does.

## Scope

Adds one new module (`src/comadre/keys/health.py` — collection + severity logic, no I/O beyond `os.stat` / `pathlib.Path.glob` / DB reads), one new CLI command (`health` in `src/comadre/keys/cli/commands/system.py`), one new renderer (`render_health_report` in `src/comadre/keys/cli/output.py`), two new small DB aggregate helpers (`count_active_customers`, `count_keys_by_status` in `src/comadre/keys/db.py`), one new "cron-installed" marker-file write/remove pair in `bootstrap.yml` / `cleanup.yml`, and the matching tests + docs. **No new dependency. No schema change. No auth-path change. No FastAPI route. No new env var.**

### 1. Two new DB aggregate helpers

`src/comadre/keys/db.py` — append directly after `count_tombstones` (L618-623). Both signatures mirror `count_tombstones`'s shape: take a `sqlite3.Connection`, return an `int` (or a small `dict[str, int]` for the by-status reader). No transaction wrapper — these are pure reads.

```python
def count_active_customers(conn: sqlite3.Connection) -> int:
    """Return the count of non-tombstoned customers (``deleted_at IS NULL``).

    Companion to ``count_tombstones`` — together they partition the
    ``customer`` table for ``health`` summary rendering. Used by
    ``collect_health_report`` (``keys.health``) and exposed here so test
    fixtures can assert against the same SELECT shape the production
    path uses.
    """
    row = conn.execute(
        "SELECT COUNT(*) FROM customer WHERE deleted_at IS NULL"
    ).fetchone()
    return int(row[0])


def count_keys_by_status(conn: sqlite3.Connection) -> dict[str, int]:
    """Return ``{status: count}`` for every status enumerated by ``CustomerStatus``.

    Always returns the full key set ``{"active": N, "suspended": N,
    "revoked": N}`` — statuses that GROUP BY did not see render as ``0``.
    The fixed-shape return contract lets the renderer iterate without
    branching on missing keys, and lets tests assert structure as well
    as values. Status strings are the literal ``api_key.status`` enum
    members from ``v001_initial.sql``.
    """
    base = {"active": 0, "suspended": 0, "revoked": 0}
    rows = conn.execute(
        "SELECT status, COUNT(*) FROM api_key GROUP BY status"
    ).fetchall()
    for row in rows:
        status = str(row[0])
        if status in base:
            base[status] = int(row[1])
    return base
```

**Why two helpers, not one combined `RegistryCounts` dataclass.** The dataclass shape is built one layer up (in `keys/health.py` — see §2). Keeping `db.py` at the "thin SQL helper" altitude matches Story 1.1's `count_tombstones` precedent — every other count-class helper in `db.py` returns a primitive. The dataclass aggregation is a `keys/health.py` concern.

**Why the `GROUP BY` form returns a fixed-shape dict rather than `dict[str, int]` directly from the cursor.** A registry that has zero suspended keys today does not produce a `'suspended': 0` row from the GROUP BY. The renderer needs all three statuses on every panel for column-stable output. Resolving the missing-status case at the helper boundary (rather than in the renderer) keeps the renderer concerned with formatting, not data normalisation.

**Why no `count_revoked_customers` separate helper.** `count_tombstones` already covers the LGPD-purged path; `revoked` is a key-only state. A single combined `count_customers_by_status` doesn't apply because customers don't have a `status` column — only `deleted_at`.

### 2. New module: `src/comadre/keys/health.py`

A module-sized boundary keeps DB reads + filesystem reads + severity arithmetic in one file, away from `db.py` (pure SQL) and `system.py` (CLI wiring).

```python
"""``comadre-keys health`` data-collection module.

Computes a HealthReport from: the SQLite registry, the cron-installed
marker file, the optional backup glob, and the per-replica counter
snapshots. No mutation. Safe to run from cron / monitoring scripts.

Severity model:
  ok    — nominal; renders green; never affects ``is_healthy``.
  info  — informational; no marker; never affects ``is_healthy``.
  warn  — operational drift; renders yellow; flips ``is_healthy=False``
          in JSON mode → exit 7.
  fail  — failed check; renders red; flips ``is_healthy=False`` in JSON
          mode → exit 7. Distinguished from ``warn`` purely by visual
          severity in table mode; equivalent in JSON.
"""
```

**Public surface:**

```python
from dataclasses import dataclass
from typing import Literal

Severity = Literal["ok", "info", "warn", "fail"]


@dataclass(frozen=True, slots=True)
class HealthCheck:
    """A single health field — what was measured + how to interpret it.

    ``label`` is the operator-facing field title ("Permissions", "Last
    sweep", "Cron", ...). ``value`` is the raw renderable string the
    panel displays ("0600", "2026-04-19T03:30:01Z (16h 12m ago)", ...).
    ``severity`` drives colour (table) and ``is_healthy`` aggregation
    (JSON). ``detail`` is the human hint ("expected 0600", "run
    bootstrap.yml") — rendered after the value on the same line in
    table mode, exposed as the ``detail`` JSON field. ``json_value``
    is an optional structured representation for the JSON output —
    when ``None`` the renderer falls back to ``value``.
    """

    label: str
    value: str
    severity: Severity
    detail: str | None = None
    json_value: object | None = None


@dataclass(frozen=True, slots=True)
class HealthReport:
    """Result payload returned by ``collect_health_report``.

    ``checks`` are ordered for table rendering. ``is_healthy`` is True
    iff zero check has severity ``warn`` or ``fail``. ``generated_at``
    is the canonical ISO-UTC timestamp at collection time — surfaces
    in JSON for downstream timestamp correlation.
    """

    checks: tuple[HealthCheck, ...]
    is_healthy: bool
    generated_at: str  # ISO-UTC %Y-%m-%dT%H:%M:%SZ


def collect_health_report(
    *,
    db_path: str,
    billing_timezone: str,
    schema_version_expected: int,
    cron_marker_path: str,
    backup_glob_pattern: str,
    sweep_staleness_warn_seconds: int = 48 * 3600,
) -> HealthReport:
    """Build the complete report. Single function; opens its own DB conn.

    All paths are resolved to ``Path`` internally. Failure modes that
    are *expected* (DB doesn't exist yet, snapshot directory empty,
    backup glob empty) become ``info`` / ``warn`` checks rather than
    raised exceptions. Failure modes that are *unexpected*
    (sqlite3.Error mid-query, OSError on a stat, marker file is a
    directory) propagate to the CLI for exit-5 mapping.
    """
```

**Internal helpers (private):**

- `_check_db_path(db_path: Path) -> HealthCheck` — `os.stat` for size + mode; severity `fail` if missing, `warn` if mode != `0o600`, else `ok`. Value renders as e.g. `"/keys/registry.db (2.4 MB, mode 0600)"`. JSON: `{"path": "...", "size_bytes": 2473984, "mode_octal": "0600", "exists": true}`.
- `_check_schema_version(conn, expected: int) -> HealthCheck` — `SELECT MAX(version) FROM schema_version`. Severity `ok` on parity, `warn` on `current < expected` (migration didn't run — almost unreachable since `_apply_migrations` ran on DB open), `fail` on `current > expected` (also unreachable — `_apply_migrations` would have raised). Value: `"1 (current)"` / `"0 (migration pending)"` / `"2 (binary too old, expected 1)"`.
- `_check_customer_count(conn) -> HealthCheck` — `count_active_customers(conn)` + `count_tombstones(conn)`. Severity always `ok` (counts are informational; no threshold). Value: `"47 active, 3 tombstoned"` (or `"47 active"` when tombstones == 0). JSON: `{"active": 47, "tombstoned": 3}`.
- `_check_key_counts(conn) -> HealthCheck` — `count_keys_by_status(conn)`. Severity always `ok`. Value: `"52 active, 8 suspended, 4 revoked"`. JSON: `{"active": 52, "suspended": 8, "revoked": 4}`.
- `_check_last_sweep(conn, *, staleness_warn_seconds) -> HealthCheck` — `get_last_sweep_timestamp(conn)`. Severity `ok` if age <= staleness_warn_seconds, `warn` if older or `None` AND the cron marker exists (proven below), `info` if `None` AND the cron marker is missing (no cron installed → no expectation that sweep ran). Value: `"2026-04-19T03:30:01Z (16h 12m ago)"` / `"never (cron not installed)"` / `"never (cron installed but not yet fired — wait until 00:30 operator-TZ)"`. JSON: `{"last_at": "2026-04-19T03:30:01Z" or null, "age_seconds": int or null, "staleness_warn_seconds": 172800}`.
- `_check_cron_marker(marker_path: Path) -> HealthCheck` — `marker_path.is_file()`. Severity `ok` if present, `warn` if absent. Value reads from the marker contents (the marker file contains the human-readable schedule string `"30 0 * * * (CRON_TZ=UTC)"` written by bootstrap; `health` echoes it verbatim). Value: `"comadre-daily-suspension at 30 0 * * * (CRON_TZ=UTC) ✓"` / `"Not installed (run ansible-playbook bootstrap.yml)"`. JSON: `{"installed": true, "schedule": "30 0 * * *", "tz": "UTC"}` or `{"installed": false}`.
- `_check_last_backup(backup_glob_pattern, *, allow_warn: bool = False) -> HealthCheck` — `Path(parent).glob(pattern)` → `max(p.stat().st_mtime for p in matches)`. **Severity always `info` until Story 4.3 lands** (`allow_warn=False` is the current default; 4.3 will flip the constant). When 4.3 ships and `allow_warn=True`, age > 48 h → `warn`, missing → `warn`. Value today: `"never (Story 4.3 not yet shipped — backup playbook is Epic 4 work)"`. JSON: `{"available_after_story_4_3": false}` (so a script can detect the not-yet-shipped state and degrade gracefully).
- `_check_auth_cache(snapshots, aggregated) -> HealthCheck` — wrapper over `aggregate_cache_status` from `comadre.counters`. Severity `info` when `aggregated is None` ("no API replicas reporting" — common for standalone CLI invocations), `ok` when one or more replicas reporting. **Never `warn`/`fail`** — auth-cache absence is not an error condition for `health`'s contract; it just means no API container is running, which is fine for a CLI-only invocation. Value: `"3 replicas, 1234 entries, 99.2% hit rate, 17m 04s ago"` / `"no API replicas reporting (snapshot directory empty)"`. JSON: embeds the existing `AggregatedCacheStatus` payload as `auth_cache: {...}` + `auth_cache_available: bool`.

**`is_healthy` aggregation:** `is_healthy = all(check.severity in {"ok", "info"} for check in checks)`. Boolean is computed once at the end of `collect_health_report` and stored on the `HealthReport`; the renderer never recomputes.

### 3. Cron-installed marker file convention

**The wrinkle.** `comadre-keys` runs inside the `tts-service` container (the cron entry is `cd ~/comadre && docker compose exec -T tts-service comadre-keys suspend-sweep ...`). The host's crontab is **not visible from inside the container** — there's no shared mount of `/var/spool/cron/crontabs/` and adding one would be a security regression for what is otherwise an isolated service. Naïvely shelling out to `crontab -l` from `health_cmd` would always print "Not installed" because the container has no crontab and no `cron` daemon.

**The fix.** `bootstrap.yml` writes a small marker file at the same volume the DB lives on:

```
{settings.key_registry_db_path}.cron-installed
```

**Marker file contents** — exactly two lines, ASCII, no trailing newline:

```
schedule=30 0 * * *
cron_tz=UTC
```

(`cron_tz` reflects the `billing_timezone` ansible var; defaults to `UTC` per Story 3.3's code-review patch.) `health` reads the marker via `Path.read_text(encoding="utf-8")`, parses it as `dict[str, str]` via a one-line list-comprehension over `splitlines()`, and renders the schedule + TZ verbatim. **Permissions on the marker file: `0600`** (matches the DB file — the marker lives in the same protected directory).

**`bootstrap.yml`** — append to the cron-installation block (after the existing `comadre-daily-suspension` task, before the "Next steps" summary):

```yaml
- name: "[Cron] Write health-marker for comadre-daily-suspension"
  ansible.builtin.copy:
    dest: "{{ key_registry_db_path }}.cron-installed"
    content: |-
      schedule=30 0 * * *
      cron_tz={{ billing_timezone | default('UTC') }}
    owner: "{{ ansible_user }}"
    group: "{{ ansible_user }}"
    mode: "0600"
```

**`cleanup.yml`** — symmetric removal in the same `block:` as the cron-entry / `CRON_TZ` removal pair (same partial-failure ordering rule per Story 3.3 deferred entry: remove the marker first, then the cron, then `CRON_TZ`):

```yaml
- name: "[Cron] Remove health-marker for comadre-daily-suspension"
  ansible.builtin.file:
    path: "{{ key_registry_db_path }}.cron-installed"
    state: absent
```

**Why the marker file lives on the same volume as the DB.** The volume is bind-mounted into the container (`./data/keys:/keys:rw` per architecture §752) so the marker is visible to the in-container CLI. It is NOT visible to the host's other processes by design — the marker is a CLI-internal signaling primitive, not a system-wide cron registry. An operator who manually edited the host crontab to disable the cron would leave the marker in place; `health`'s "Last sweep" check would then start to flag stale (>48 h) and the operator gets a downstream signal even though the upstream marker still says "installed". The two checks are designed to **complement** rather than duplicate.

**Why not `os.path.exists("/etc/cron.d/comadre-daily-suspension")` from inside the container.** That path doesn't exist in the container filesystem (no `cron` package installed — `tts-service` is FastAPI + uvicorn, not a multi-service image). And bind-mounting `/etc/cron.d/` would expose unrelated host cron entries, a clean security regression. Marker file is the minimum-surface-area answer.

**Why the marker file is named `.cron-installed` and not `.suspension-cron-installed`.** Future-extensibility. When Story 4.3 lands the backup cron (`comadre-keys-backup`), it can write `{db_path}.backup-cron-installed` following the same convention. Keeping each marker scoped to one cron entry means `health` doesn't have to parse a multi-entry marker file (forward-compatibility risk), and the file naming reads as "this cron is installed" rather than "all cron jobs are installed".

### 4. New CLI verb: `health`

`src/comadre/keys/cli/commands/system.py` — appended after `_suspend_sweep_dry_run` (currently L310). Same module as `cache-status` / `suspend-sweep` per architecture §357 / §551 (`system.py = health, rotate-encryption-key, cache-status, suspend-sweep`).

```python
@app.command("health")
def health_cmd(
    format: str = typer.Option(
        "table",
        "--format",
        help=(
            "Output format: table (default, human-readable single-border "
            "panel — always exits 0; warnings render as yellow text but "
            "do not flip the exit code) or json (machine-readable; exits 7 "
            "when any check has severity warn or fail). Example: "
            "--format json."
        ),
    ),
) -> None:
    """Report registry / cron / cache health (FR34).

    Read-only. Safe to run from cron, monitoring scripts, or the
    operator's terminal. Pipe ``--format json`` into a Nagios-class
    monitor; ``$?`` is 0 for healthy, 7 for any unhealthy condition.

    Example: comadre-keys health
             comadre-keys health --format json
    """
```

**Validation ladder (mirrors `cache_status_cmd` and `suspend_sweep_cmd` exactly — copy the pattern, do not invent a new one):**

1. **Literal flag check (exit 2).** `if format not in LIST_FORMAT_CHOICES: render_error("Usage error: --format must be table or json", "Valid values: table, json."); raise typer.Exit(code=2)`. Reuse `LIST_FORMAT_CHOICES` from `output.py:46` — the same tuple `cache-status` validates against. Single source of truth.
2. **Settings + TZ (exit 6).** `loaded = load_settings_and_tz()`. `None` → `raise typer.Exit(code=6)`. Same shared helper Stories 1.6 / 3.1 / 3.3 use; same exit-6 panel; same `# type: ignore[attr-defined]` cast pattern (the deferred-work entry tracks the future tightening of `load_settings_and_tz`'s return type).
3. **Open DB + migrations (exit 5).** Pattern verbatim from `suspend_sweep_cmd:212-224`. Wrap `get_connection(settings.key_registry_db_path)` in `try/except sqlite3.Error` → `render_error("Database error", str(exc)); raise typer.Exit(code=5) from exc`. (Note: `from exc`, not `from None` — Story 3.3's code-review patch established this contract for forensic preservation; `health` adopts it from day one.) Wrap `_apply_migrations(conn)` in `try/except (sqlite3.Error, RuntimeError)` → exit 5. **`health` opens the DB even though some checks (cron marker, backup glob, snapshot read) are filesystem-only.** Rationale: the registry DB IS the canonical health surface; failing-fast with a clean exit-5 panel when the DB is unreachable is more useful than a partial report that hides the most operationally important signal.
4. **Resolve marker / backup paths.** `cron_marker_path = Path(f"{settings.key_registry_db_path}.cron-installed")`. `backup_glob_pattern` is the architecture-reserved pattern `*.backup-*.tar.gz.enc` rooted at the DB's parent directory. Both are absolute paths inside the container; both are derived from `settings.key_registry_db_path`.
5. **Collect.** `report = collect_health_report(db_path=settings.key_registry_db_path, billing_timezone=settings.billing_timezone, schema_version_expected=_SCHEMA_VERSION, cron_marker_path=str(cron_marker_path), backup_glob_pattern=str(...))`. Wrap in `try/except (sqlite3.Error, OSError)` → exit 5 (an `OSError` from `os.stat` on the DB during health collection is operationally a DB-read failure even if the connection itself is open; mapping to exit 5 keeps the surface coherent).
6. **Close DB** in the `finally` of the outer `try` (matches every other CLI command in the repo).
7. **Render branch.**
   - `format == "table"`: `render_health_report(report)`. **Exit 0 always.** Read-tier semantics — yellow warnings are operator-readable, do not flip `$?`. Per UX-DR10's read-tier convention surfaced by the UX-spec extraction.
   - `format == "json"`: `stdout_console().print_json(data=_health_report_to_json(report))`. **Exit 7** when `report.is_healthy is False`. **Exit 0** when `report.is_healthy is True`.
8. **Structured INFO log.** PII-austere aggregate — counts only, never key prefixes / customer names / hashes:
   ```python
   with contextlib.suppress(Exception):
       _logger.info(
           "Health report generated | format=%s | is_healthy=%s | "
           "warn_count=%d | fail_count=%d",
           format,
           report.is_healthy,
           sum(1 for c in report.checks if c.severity == "warn"),
           sum(1 for c in report.checks if c.severity == "fail"),
       )
   ```

**Why exit 7 (not 1, not 5).** Exit 1 collides with shell convention "general error" — too generic; an operator scripting `if comadre-keys health --format json; then ...` has no way to distinguish "DB unreachable" (exit 5) from "DB reachable but cron stale" (the exit-1 case under generic semantics). Exit 5 is reserved for `sqlite3.Error` / `RuntimeError` — re-using it for "all checks ran but some are warn/fail" overloads the meaning. Exit 7 picks the next-available unused code in the system-module contract (0 / 2 / 5 / 6 / **7**). Architecture §357 only specifies the `system.py` module's verb list; the exit-code table is composed per-verb, so 3.4 owns the addition. Document in the module docstring (§7 below).

**Why `--format table` does not exit non-zero on warnings.** UX-spec read-tier semantics (`health` is classified as Read-only at ux-design-specification.md:892) say exit 0 is the default. The epic AC also pins exit-non-zero specifically to `--format json`. Interactive operators piping `comadre-keys health` into `less` or running it in a terminal expect `$?` to be 0; flipping it on a yellow warning would noise up shells that style their prompt by exit code. Scripts that need a strict signal use `--format json`.

**Why no `--include-cache` / `--exclude-backup` / verbosity flags.** Added scope. The single panel is the operator's full-vehicle dashboard; selective sections would fragment the contract that "health is one panel, one verdict". JSON consumers parse what they want from the full payload.

### 5. New renderer: `render_health_report`

`src/comadre/keys/cli/output.py` — append after `render_show_json` (currently L852-877). Same Console singleton + box style as `render_customer_detail` / `render_key_detail` (single rounded border, label-padded rows).

```python
def render_health_report(report: HealthReport) -> None:
    """UX-DR3 DetailPanel for ``comadre-keys health``.

    Single-border rounded Panel. Title: ``System Health``. One row per
    ``HealthCheck`` in the report's ``checks`` order; label is right-
    padded to the longest label in the report so values column-align.

    Severity drives colour:
      ok    — value rendered plain (no markup).
      info  — value rendered plain; not styled.
      warn  — value wrapped in ``[yellow]…[/yellow]`` markup.
      fail  — value wrapped in ``[red]…[/red]`` markup.

    ``detail`` (when present) renders after the value on the same line,
    wrapped in dim style ``[dim](… detail …)[/dim]`` so it visually
    backgrounds. The footer line below the panel is the canonical
    ``ConfirmationLine`` rendering of the verdict — green ``Healthy.``
    when ``is_healthy``, yellow ``Unhealthy: N warning(s), M failure(s).``
    otherwise.

    No ``markup=True`` injection risk: ``HealthCheck.value`` is
    composed entirely from typed primitives by the collector
    (timestamps, counts, paths, octal modes) — not from operator-
    supplied strings. The two operator-influenced strings (db_path,
    billing_timezone) are quoted within the value but pass through
    ``rich.markup.escape`` defensively before interpolation.
    """
```

**Implementation notes:**

- **Title:** literal `"System Health"`. No timestamp in the title — the timestamp lives in the JSON payload (`generated_at`) and is implicit in the table mode (the panel was generated when the operator typed the command).
- **Label width:** `max(len(c.label) for c in report.checks)` + 1, computed inside the renderer so adding a new check elsewhere doesn't require touching the renderer.
- **Row template:** `f"{label.ljust(width)} {value_with_severity}{detail_segment}"` where `value_with_severity` is the markup-wrapped value and `detail_segment` is `f" [dim]({c.detail})[/dim]"` or `""`.
- **Empty / single-check edge case:** `report.checks` is always non-empty by construction (collector always returns 7 fixed checks); renderer asserts `len(report.checks) > 0` defensively (real `if`, not `assert` — same `python -O` survival rule the Story 3.3 code-review patch established for `render_at_risk_table` / `render_suspend_sweep_preview`).
- **Footer:** `render_confirmation(...)`. Verdict text:
  - `report.is_healthy is True`: `Healthy.`
  - `report.is_healthy is False`: `Unhealthy: N warning(s), M failure(s).` where `N = sum(c.severity == "warn" ...)`, `M = sum(c.severity == "fail" ...)`. Never `0 warning(s)` / `0 failure(s)` (`is_healthy` is False iff one of N or M is > 0).

**JSON shape** (a sibling private helper `_health_report_to_json(report) -> dict[str, object]`):

```json
{
  "is_healthy": false,
  "generated_at": "2026-04-19T18:42:07Z",
  "warn_count": 2,
  "fail_count": 0,
  "checks": [
    {
      "label": "Database",
      "severity": "ok",
      "value": "/keys/registry.db (2.4 MB, mode 0600)",
      "detail": null,
      "data": {"path": "/keys/registry.db", "size_bytes": 2473984, "mode_octal": "0600", "exists": true}
    },
    {
      "label": "Schema version",
      "severity": "ok",
      "value": "1 (current)",
      "detail": null,
      "data": {"current": 1, "expected": 1}
    },
    {
      "label": "Customers",
      "severity": "ok",
      "value": "47 active, 3 tombstoned",
      "detail": null,
      "data": {"active": 47, "tombstoned": 3}
    },
    {
      "label": "Keys",
      "severity": "ok",
      "value": "52 active, 8 suspended, 4 revoked",
      "detail": null,
      "data": {"active": 52, "suspended": 8, "revoked": 4}
    },
    {
      "label": "Last suspension sweep",
      "severity": "warn",
      "value": "never (cron installed but not yet fired)",
      "detail": "wait until 00:30 operator-TZ for the first sweep",
      "data": {"last_at": null, "age_seconds": null, "staleness_warn_seconds": 172800}
    },
    {
      "label": "Cron",
      "severity": "warn",
      "value": "Not installed",
      "detail": "run ansible-playbook bootstrap.yml",
      "data": {"installed": false}
    },
    {
      "label": "Last backup",
      "severity": "info",
      "value": "never (Story 4.3 not yet shipped)",
      "detail": null,
      "data": {"available_after_story_4_3": false}
    },
    {
      "label": "Auth cache",
      "severity": "ok",
      "value": "3 replicas, 1234 entries, 99.2% hit rate, 17m 04s ago",
      "detail": null,
      "data": {
        "auth_cache_available": true,
        "auth_cache": {
          "replicas": 3,
          "entries": 1234,
          "maxsize_per_replica": 4096,
          "hits": 56781,
          "misses": 412,
          "hit_rate": 0.992,
          "snapshot_age_seconds": 1024,
          "process_uptime_seconds": 73482
        }
      }
    }
  ]
}
```

**Why the JSON shape is `checks: [{label, severity, value, detail, data}, ...]` and not a flat dict.** A flat dict (`{"db_path": ..., "schema_version": ..., ...}`) has a stable key set, but downstream consumers can't iterate severities without knowing every key in advance. The `checks: [...]` array keeps the rendering and aggregation contract symmetrical between table and JSON modes — both iterate `report.checks` in order. The trade-off: `jq '.checks[] | select(.severity != "ok")'` is the canonical "show me what's wrong" query, marginally more verbose than `jq '.unhealthy_checks'` but gives a richer surface for operator scripting (severity, label, detail all in one record).

**Why `data` is nested under each check.** Per-check structured payload avoids global namespace pollution and keeps each check self-contained. A future check addition (e.g., Story 4.2's "encryption rotation age") drops in as a new entry in `checks[]` without colliding with siblings.

### 6. CLI module-docstring extension

`src/comadre/keys/cli/commands/system.py:1-19` — extend the existing exit-code contract enumeration to include exit 7 for `health`:

```python
"""`comadre-keys cache-status` + `suspend-sweep` + `health` — system/operational verbs.

Story 2.3 landed ``cache-status``; Story 3.3 added ``suspend-sweep``;
Story 3.4 adds ``health``. Story 4.2 (``rotate-encryption-key``) will
add the final subcommand here — grouping the operational verbs in one
module keeps the CLI map legible (customers → keys → billing → system).

Exit-code contract (UX-DR10, matches sibling command modules):
  0 — success; for ``health`` includes ``--format table`` regardless of
      severity (read-tier semantics) and ``--format json`` when every
      check is ``ok`` / ``info``.
  2 — usage error (bad ``--format`` on ``cache-status`` / ``health``;
      ``suspend-sweep`` never emits 2 — the only operator-parseable
      flag is ``--dry-run``).
  5 — database error from ``get_connection`` / ``_apply_migrations`` /
      ``run_suspension_sweep`` (``suspend-sweep``) / health-collection
      query (``health``).
  6 — permission / configuration error (missing encryption key or
      invalid ``BILLING_TIMEZONE``).
  7 — unhealthy state in ``health --format json`` (any check has
      severity ``warn`` or ``fail``). Never emitted by ``cache-status``
      or ``suspend-sweep``; never emitted by ``health --format table``.
"""
```

### 7. Docs

- **`CLAUDE.md`** — extend the `keys/cli/` bullet to append `health` at the end of the system cluster: `... cache-status, suspend-sweep, health`. Append a new gotcha under "Non-Obvious Gotchas":
  > **`comadre-keys health` cannot read the host's crontab from inside the `tts-service` container.** Cron-installed detection uses a marker file at `{KEY_REGISTRY_DB_PATH}.cron-installed` written by `bootstrap.yml`, not a `crontab -l` shell-out. The marker says "ansible installed the cron entry" — for "is the cron actually firing?" check the "Last suspension sweep" age field, which reads `audit_log` directly. The two checks are designed to complement: marker present + recent sweep = healthy; marker present + stale sweep = cron installed but failing; marker absent = bootstrap not run.
- **`README.md`** — append a "System health" feature bullet under "Registry-backed API keys" with the canonical invocations (`comadre-keys health`, `comadre-keys health --format json`).
- **`docs/configuration-reference.md`** — note that the marker file `{KEY_REGISTRY_DB_PATH}.cron-installed` is managed by `bootstrap.yml` / `cleanup.yml` and should not be edited by hand; manual edits will mislead `health`'s cron check.
- **`docs/deployment-guide.md`** — append a brief "monitoring integration" subsection showing the canonical Nagios / Prometheus textfile invocation: `comadre-keys health --format json`, exit 0 healthy, exit 7 unhealthy. Quote one example `jq` query for piping the warn list into an alert.
- **No new `docs/monetization.md`** — still deferred to Story 4.6 per Story 3.1 §6.

### 8. Tests

**`tests/test_keys_health.py`** (NEW) — unit tests for `keys/health.py`. Single-file, ~25 cases. No CliRunner; constructs `HealthReport`s directly via the module's public API.

- **`test_collect_full_healthy_report`** — seed a tmp DB with 5 customers + 10 keys (8 active, 2 suspended), one `cron_suspend` summary row aged 1 hour, the cron marker file present with canonical contents, no backup file, one fresh counter snapshot. Assert: 8 checks, all `ok`/`info` (no warn, no fail), `is_healthy is True`. The DB / schema / customers / keys / sweep / cron / cache checks all `ok`; the backup check is `info` (Story 4.3 deferred).
- **`test_warn_when_db_permissions_drift`** — seed a DB, then `os.chmod(db_path, 0o644)`. Collect. Assert the Database check is `severity='warn'`, value contains `"mode 0644"`, detail mentions `"expected 0600"`, `is_healthy is False`.
- **`test_warn_when_cron_marker_missing`** — seed everything else, no marker file. Cron check is `warn`, value contains `"Not installed"`, detail mentions bootstrap.
- **`test_warn_when_last_sweep_stale`** — marker present, but the most-recent `cron_suspend` row is 72 hours old. Sweep check is `warn`, value contains `"72h"`, detail mentions "expected within 48h".
- **`test_info_when_last_sweep_null_and_no_cron`** — fresh DB, no marker. Sweep check is `info` ("never (cron not installed)"), not `warn` — there's no expectation a sweep ran when no cron is installed.
- **`test_warn_when_last_sweep_null_and_cron_installed`** — marker present, no `cron_suspend` row yet. Sweep check is `warn` (the operator deployed but the cron hasn't fired), detail says "wait until 00:30 operator-TZ".
- **`test_info_when_no_replicas_reporting`** — empty snapshot dir. Auth-cache check is `info`, not `warn`/`fail` — absence is fine for CLI-only invocations.
- **`test_ok_when_one_replica_reports`** — one snapshot file present, parseable, age 5 s. Auth-cache check is `ok`, value contains `"1 replicas"` (the renderer's wording — kept consistent with `cache-status`).
- **`test_schema_version_warn_when_below_expected`** — manually `INSERT INTO schema_version (version, applied_at) VALUES (0, '...')`. Schema check is `warn`. (In practice `_apply_migrations` would fix this on DB open, so the warn branch is mostly defensive — exercise it anyway.)
- **`test_schema_version_fail_when_above_expected`** — `INSERT (version=999)`. Schema check is `fail` (binary too old).
- **`test_customer_count_combines_active_and_tombstoned`** — seed 3 active + 2 tombstoned. Value contains `"3 active, 2 tombstoned"`. JSON `data` has both fields.
- **`test_customer_count_omits_tombstoned_when_zero`** — seed 3 active, 0 tombstoned. Value reads `"3 active"` (no `, 0 tombstoned` tail).
- **`test_key_counts_render_all_three_statuses_even_when_zero`** — seed 1 active key only. Value reads `"1 active, 0 suspended, 0 revoked"` — the fixed-shape dict from `count_keys_by_status` renders all three statuses.
- **`test_db_size_uses_real_st_size`** — seed a small DB, collect, assert the value's `(N MB)` segment matches `os.stat(db_path).st_size` formatted via the renderer's size humanizer.
- **`test_collect_propagates_sqlite_errors`** — point `db_path` at a non-existent directory the user can't write to; collector raises `OSError` (caught by CLI's exit-5 mapping) — assert by `pytest.raises(OSError)`.
- **`test_marker_with_garbage_contents_renders_warn`** — write a marker file with unparseable contents (e.g., `"\x00binary"`). Cron check is `warn` (defense-in-depth — we don't trust marker contents to be well-formed when it could indicate corruption), value contains `"Marker present but unparseable"`, detail says "re-run bootstrap.yml".
- **`test_marker_permissions_check_no_op_today`** (advisory) — assert the collector does NOT chmod the marker file (read-only contract). Documented but not strictly tested — comment-only.
- **`test_is_healthy_aggregates_via_severity`** — manually construct a `HealthReport` with one `warn` and confirm `is_healthy is False`; with one `info` and confirm `is_healthy is True`.
- **`test_generated_at_is_canonical_iso_utc`** — `report.generated_at` matches the regex `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$`.
- **`test_backup_check_is_info_only_today`** — even with a backup file present (forward-leaning test fixture: `touch '<db>.backup-2026-04-19.tar.gz.enc'`), the check renders `info` not `ok` until the `_BACKUP_NOT_IMPLEMENTED_INFO` constant is flipped. This test pins the deferred 4.3 contract — when 4.3 lands and flips the constant, this test will need updating, which is a desired forcing-function.
- **`test_collect_completes_under_500ms_for_1k_customer_db`** — NFR5 budget. Seed 1 000 customers + 2 000 keys + 5 000 audit rows (matches Story 1.6 perf seed). Wrap `collect_health_report` in `time.perf_counter()`; assert `elapsed_ms < 500`. Smoke-class assertion (CI jitter tolerated by the slack); actual figure on bare metal should be <50 ms.

**`tests/test_keys_cli_health.py`** (NEW) — end-to-end CLI via `CliRunner`. ~15 cases. Mirrors `tests/test_keys_cli_cache_status.py` scaffolding (`_clear_settings_cache`, `_reset_consoles_to_buffers`, `_buffers`, `env`, `_write_snapshot` — copy verbatim).

- **`test_table_mode_healthy_exits_0`** — fully-seeded healthy registry, `health`, exit 0, stdout contains `"System Health"` panel + `"Healthy."` footer.
- **`test_table_mode_unhealthy_still_exits_0`** — DB perms drifted, `health` (no `--format`), exit **0** (read-tier rule), stdout contains the yellow warning + `"Unhealthy: 1 warning(s), 0 failure(s)."` footer.
- **`test_json_mode_healthy_exits_0`** — fully-seeded, `health --format json`, exit 0, stdout parses as JSON, `payload["is_healthy"] is True`, `payload["warn_count"] == 0`, `payload["fail_count"] == 0`, `payload["generated_at"]` matches ISO-UTC regex.
- **`test_json_mode_unhealthy_exits_7`** — DB perms drifted, `health --format json`, **exit 7**, `payload["is_healthy"] is False`, `payload["warn_count"] == 1`.
- **`test_json_payload_includes_all_eight_checks`** — `len(payload["checks"]) == 8`, label set is exactly `{"Database", "Schema version", "Customers", "Keys", "Last suspension sweep", "Cron", "Last backup", "Auth cache"}`.
- **`test_invalid_format_exits_2`** — `health --format xml`, exit 2, stderr contains `"--format must be table or json"`.
- **`test_missing_encryption_key_exits_6`** — unset env var, exit 6, stderr contains `"KEY_REGISTRY_ENCRYPTION_KEY"`.
- **`test_invalid_billing_tz_exits_6`** — `BILLING_TIMEZONE=Mars/Olympus_Mons`, exit 6, stderr contains `"BILLING_TIMEZONE"`.
- **`test_db_unreachable_exits_5`** — monkeypatch `system_cmd.get_connection` to raise `sqlite3.OperationalError`; exit 5; stderr contains `"Database error"`. **Asserts `result.exit_code == 5`** (not `!= 0`) — Story 3.3 code-review patch precedent.
- **`test_pii_austere_log`** — run `health` against a registry with 3 real-looking customers (names, emails, CPF). `caplog` captures INFO. Reuse Story 3.3's `_PII_FORBIDDEN_RE` (extended to formatted CPF/CNPJ). Assert zero matches in any INFO record. The single INFO line carries `format=`, `is_healthy=`, `warn_count=`, `fail_count=` — counts only.
- **`test_health_appears_in_top_level_help`** — `runner.invoke(app, ["--help"])`, stdout contains `"health"`. One-line description matches the docstring's first sentence.
- **`test_table_renders_yellow_for_warn`** — DB perm drift; capture stdout via the no-color buffer (Console with `no_color=True`); assert the rendered value contains the literal `mode 0644` (severity colour can't be asserted via `no_color=True`, but the value is the canonical signal — colour is the accelerator, label/value carry the meaning).
- **`test_marker_present_renders_schedule_verbatim`** — write the marker with `"schedule=30 0 * * *\ncron_tz=America/Sao_Paulo"`. Run `health`. Stdout's Cron row contains `"30 0 * * *"` AND `"America/Sao_Paulo"` — verbatim from the marker.
- **`test_json_payload_round_trips_through_jq_query`** (advisory): `payload = json.loads(stdout)`; `[c for c in payload["checks"] if c["severity"] in {"warn", "fail"}]` matches the `warn_count + fail_count`. Closes the loop on the canonical operator query.
- **`test_health_is_idempotent_no_writes`** — capture `os.stat(db_path).st_mtime` before and after `health`; assert the mtime is unchanged (the DB was not written during the call). Same assertion for the marker file's mtime.

**`tests/test_keys_db.py`** (MOD) — append unit tests for the two new aggregate helpers:

- **`test_count_active_customers_excludes_tombstones`** — seed 3 active + 2 tombstoned; assert `count_active_customers(conn) == 3`.
- **`test_count_keys_by_status_returns_full_shape`** — seed 1 active + 2 suspended + 0 revoked; assert `count_keys_by_status(conn) == {"active": 1, "suspended": 2, "revoked": 0}`. Empty DB returns `{"active": 0, "suspended": 0, "revoked": 0}`.

**`tests/test_keys_output.py`** (MOD) — renderer tests for `render_health_report`:

- **`test_render_health_report_panel_shape`** — feed a 3-check `HealthReport`; capture stdout; assert title `"System Health"`, all three labels right-padded to the longest, footer reads `"Healthy."`.
- **`test_render_health_report_unhealthy_footer`** — 1 warn + 1 fail; footer reads `"Unhealthy: 1 warning(s), 1 failure(s)."`.
- **`test_render_health_report_severity_colours`** — feed a check with `severity='warn'` and `value="0644"`; render to a Console with `force_terminal=True` (so ANSI is emitted); assert the captured output contains a yellow ANSI escape (`\x1b[33m` or equivalent — match against `_format_seconds_ago`'s test pattern).
- **`test_render_health_report_markup_injection_guarded`** — feed a check with `value="[red]evil[/]"`; assert the rendered output contains the literal escaped form, not interpreted markup. Defense-in-depth parallel to Story 3.2 / 3.3's renderers.

**No new ansible integration tests.** `bootstrap.yml` / `cleanup.yml` are exercised by the existing `ansible-playbook --check` smoke (manual verification). Add a brief note to the story close about the manual verification step on 10.10.10.207 (Task 8.5 deferred to deploy-time).

### 9. Grep checks (Task-N style, for the implementer's pre-commit pass)

- `rg -n "@app.command\\(\"health\"\\)" src/comadre/keys/cli/commands/system.py` — exactly 1 hit (the new verb).
- `rg -n "exit.*code=7" src/comadre/keys/cli/commands/system.py` — exactly 1 hit (the unhealthy-JSON branch). No exit-7 anywhere else in the repo.
- `rg "HTTPException" src/comadre/keys/cli/commands/system.py src/comadre/keys/health.py` → zero hits.
- `rg "\\bprint\\(" src/comadre/keys/cli/commands/system.py src/comadre/keys/health.py` → zero hits (stdout goes through `render_*` / `stdout_console`).
- `rg "os\\.environ" src/comadre/keys/cli/commands/system.py src/comadre/keys/health.py` → zero hits (pydantic-settings only).
- `rg -n "count_active_customers|count_keys_by_status" src/comadre/keys/db.py` — exactly 2 hits (the two new helpers' definitions).
- `rg -n ".cron-installed" deploy/ansible/playbooks/` — exactly 2 hits (one in `bootstrap.yml`, one in `cleanup.yml`).
- `git diff src/comadre/api.py src/comadre/main.py src/comadre/rate_limit.py src/comadre/keys/auth.py src/comadre/keys/cache.py src/comadre/health.py src/comadre/counters.py` — empty (AC15 invariant).
- `git diff pyproject.toml uv.lock src/comadre/keys/migrations/` — empty (no new dep, no schema change).

## Acceptance Criteria

> BDD-style. Each AC maps to at least one test. AC numbers are stable — do not renumber if a mid-story pivot adds/removes an AC (append a new number instead).

### AC1 — `comadre-keys health` renders the canonical eight-check panel

**Given** a fully-seeded healthy registry (DB at `0600`, schema-current, 5 customers, 10 keys [8 active / 2 suspended / 0 revoked], cron marker present with canonical contents, fresh counter snapshot, no backup file)

**When** the operator runs `comadre-keys health`

**Then** exit code is 0
**And** stdout renders a single-border rounded `Panel` titled `"System Health"`
**And** the panel contains exactly 8 rows, in this order: `Database`, `Schema version`, `Customers`, `Keys`, `Last suspension sweep`, `Cron`, `Last backup`, `Auth cache`
**And** each row's label is right-padded to the longest label width
**And** the footer reads `"Healthy."`

### AC2 — Database row shows path, size, and `0600` permissions when nominal

**Given** a registry DB at `/keys/registry.db` with permissions `0o600`

**When** `health` runs

**Then** the `Database` row's value contains the DB path AND a humanized size (e.g., `"2.4 MB"`) AND `"mode 0600"`
**And** the row's severity is `ok` (no yellow / red markup in the rendered cell)
**And** the JSON `data` payload for this check is `{"path": "<path>", "size_bytes": <int>, "mode_octal": "0600", "exists": true}`

### AC3 — Database row warns on permission drift

**Given** the registry DB has permissions `0o644` (drift from `0o600`)

**When** `health --format json` runs

**Then** the `Database` check has `severity == "warn"`
**And** the rendered value contains `"mode 0644"`
**And** the rendered detail contains `"expected 0600"`
**And** the JSON payload has `is_healthy == False` and exit code is **7**

### AC4 — Schema-version row reports parity with the binary

**Given** the registry DB has `schema_version` row with `version=1` and the binary's `_SCHEMA_VERSION` constant is `1`

**When** `health` runs

**Then** the `Schema version` row's value reads `"1 (current)"`
**And** the row's severity is `ok`
**And** the JSON `data` payload is `{"current": 1, "expected": 1}`

### AC5 — Customer / key count rows render the partition

**Given** a registry with 47 active customers + 3 tombstoned, and 52 active + 8 suspended + 4 revoked keys

**When** `health` runs

**Then** the `Customers` row's value contains `"47 active, 3 tombstoned"`
**And** the `Keys` row's value contains `"52 active, 8 suspended, 4 revoked"`
**And** both rows have severity `ok`
**And** when tombstoned count is 0, the `Customers` row's value reads `"47 active"` (no `, 0 tombstoned` tail)
**And** the `Keys` row always renders all three statuses even when zero (e.g., `"1 active, 0 suspended, 0 revoked"`)

### AC6 — Last-sweep row consumes `get_last_sweep_timestamp` and humanizes the age

**Given** the most-recent `cron_suspend` summary audit row's `occurred_at` is `2026-04-19T03:30:01Z`
**And** the time of the `health` invocation is `2026-04-19T19:42:01Z` (16h 12m 0s later)

**When** `health` runs

**Then** the `Last suspension sweep` row's value contains both the canonical timestamp AND the humanized age (e.g., `"2026-04-19T03:30:01Z (16h 12m ago)"`)
**And** the severity is `ok` (age <= 48 h staleness threshold)
**And** the JSON `data.age_seconds` matches the wall-clock delta within ±2 s tolerance

### AC7 — Last-sweep row warns when stale beyond the staleness threshold

**Given** the cron marker is present
**And** the most-recent `cron_suspend` summary row's `occurred_at` is 72 hours ago

**When** `health --format json` runs

**Then** the `Last suspension sweep` check has `severity == "warn"`
**And** the rendered detail contains the staleness threshold ("expected within 48h" or equivalent)
**And** `is_healthy == False`, exit code 7

### AC8 — Last-sweep row distinguishes "never ran (no cron)" from "never ran (cron installed but waiting)"

**Given** a fresh DB with no `cron_suspend` rows

**When** `health` runs WITHOUT the cron marker present

**Then** the `Last suspension sweep` check has `severity == "info"` (no expectation; no cron installed)
**And** the value reads `"never (cron not installed)"`

**Given** the same fresh DB

**When** `health` runs WITH the cron marker present

**Then** the `Last suspension sweep` check has `severity == "warn"`
**And** the value reads `"never (cron installed but not yet fired)"`
**And** the detail mentions waiting for 00:30 operator-TZ

### AC9 — Cron row reads the marker file verbatim

**Given** the marker file exists at `{key_registry_db_path}.cron-installed` with contents:
```
schedule=30 0 * * *
cron_tz=America/Sao_Paulo
```

**When** `health` runs

**Then** the `Cron` row's value contains `"30 0 * * *"` AND `"America/Sao_Paulo"` — verbatim substrings
**And** the severity is `ok`
**And** the JSON `data` is `{"installed": true, "schedule": "30 0 * * *", "tz": "America/Sao_Paulo"}`

### AC10 — Cron row warns when the marker is absent

**Given** no marker file at `{key_registry_db_path}.cron-installed`

**When** `health --format json` runs

**Then** the `Cron` check has `severity == "warn"`
**And** the value reads `"Not installed"`
**And** the detail mentions `"run ansible-playbook bootstrap.yml"`
**And** `is_healthy == False`, exit code 7

### AC11 — Backup row is `info`-only today (Story 4.3 forward-lean)

**Given** any registry state (with or without a `*.backup-*.tar.gz.enc` file present)

**When** `health` runs

**Then** the `Last backup` check has `severity == "info"` (NOT `warn`, NOT `fail`)
**And** the value reads `"never (Story 4.3 not yet shipped)"` when no backup file exists
**And** the JSON `data` is `{"available_after_story_4_3": false}`
**And** `is_healthy` is unaffected by the backup field
**And** when the `_BACKUP_NOT_IMPLEMENTED_INFO` constant in `keys/health.py` is later flipped (Story 4.3 work), the WARN branch activates without touching `system.py` or `output.py`

### AC12 — Auth-cache row reuses `aggregate_cache_status` payload

**Given** at least one per-replica counter snapshot file at `{key_registry_db_path}.counters.*.json`

**When** `health` runs

**Then** the `Auth cache` row's value contains the replica count, total entries, hit-rate, and the snapshot age (using the same `_format_seconds_ago` helper `cache-status` uses)
**And** the JSON `data.auth_cache` payload has the same shape `cache-status --format json` emits (replicas, entries, maxsize_per_replica, hits, misses, hit_rate, snapshot_age_seconds, process_uptime_seconds)
**And** `health` and `cache-status` produce byte-identical numeric values when invoked back-to-back with no concurrent traffic (covered indirectly: both call the same `aggregate_cache_status`)

### AC13 — Auth-cache absence is `info`, not `warn`

**Given** the snapshot directory is empty (no API replicas running)

**When** `health` runs

**Then** the `Auth cache` check has `severity == "info"`
**And** the value reads `"no API replicas reporting (snapshot directory empty)"`
**And** `is_healthy` is unaffected (CLI-only invocations are valid)

### AC14 — `--format json` exits 7 on any unhealthy condition; `--format table` always exits 0

**Given** any registry state where `report.is_healthy is False`

**When** the operator runs `comadre-keys health --format json`

**Then** exit code is **7**
**And** `payload["is_healthy"] is False`
**And** `payload["warn_count"] + payload["fail_count"] >= 1`

**Given** the same unhealthy state

**When** the operator runs `comadre-keys health` (default `--format table`)

**Then** exit code is **0**
**And** the panel renders the warnings in yellow / red as appropriate
**And** the footer reads `"Unhealthy: N warning(s), M failure(s)."`

### AC15 — Read-only invariant: no DB write, no auth-path / runtime-code touch

**Given** the diff at story completion

**When** `git diff` is inspected over `src/comadre/api.py src/comadre/main.py src/comadre/rate_limit.py src/comadre/keys/auth.py src/comadre/keys/cache.py src/comadre/health.py src/comadre/counters.py` AND `git diff pyproject.toml uv.lock src/comadre/keys/migrations/`

**Then** the diff is empty
**And** `health_cmd` does not write to the DB (asserted by `os.stat(db_path).st_mtime` byte-equality before/after a real-DB invocation)
**And** `health_cmd` does not touch the auth-cache sentinel (`{db_path}.invalidate` mtime is unchanged)

### AC16 — Configuration / DB error mapping matches sibling `system.py` verbs

**Given** `KEY_REGISTRY_ENCRYPTION_KEY` is unset

**When** `health` runs (any `--format`)

**Then** exit code is 6
**And** stderr renders the canonical "Configuration error: KEY_REGISTRY_ENCRYPTION_KEY is not set" panel

**Given** `BILLING_TIMEZONE=Mars/Olympus_Mons`

**When** `health` runs

**Then** exit code is 6
**And** stderr panel mentions `BILLING_TIMEZONE`

**Given** `get_connection` raises `sqlite3.OperationalError` (e.g., DB path is a directory, EACCES on the file)

**When** `health` runs

**Then** exit code is **5** (assert `result.exit_code == 5`, not `!= 0` — Story 3.3 code-review patch contract)
**And** stderr renders `"Database error"` panel with the underlying exception preserved as `__cause__`

### AC17 — `--format` literal validation exits 2

**Given** the operator runs `comadre-keys health --format xml`

**When** the command starts

**Then** exit code is 2
**And** stderr contains `"Usage error: --format must be table or json"`
**And** stderr's hint contains the valid values (`table, json`)
**And** no DB connection is opened (assertable via `monkeypatch` on `get_connection` to raise — exit-2 must short-circuit before)

### AC18 — Bootstrap installs the marker; cleanup removes it

**Given** `ansible-playbook bootstrap.yml` runs on a fresh VPS

**When** the playbook completes

**Then** the file `{key_registry_db_path}.cron-installed` exists with mode `0600`
**And** its contents are exactly two lines: `schedule=30 0 * * *` and `cron_tz=<billing_timezone>` (no trailing newline)

**Given** `ansible-playbook bootstrap.yml` runs a second time

**When** the marker task evaluates

**Then** the task reports `ok` (idempotent — no rewrite, no permissions drift)

**Given** `ansible-playbook cleanup.yml` runs after a successful bootstrap

**When** the playbook completes

**Then** the marker file no longer exists
**And** the `comadre-daily-suspension` cron entry no longer exists
**And** the `CRON_TZ` envvar entry no longer exists
**And** the removal order is marker → cron → CRON_TZ (per Story 3.3 deferred-work entry on partial-failure resilience)

### AC19 — PII-austere INFO log (NFR15)

**Given** any successful `health` invocation against a registry with real customer data (names, emails, encrypted CPF, hashed keys)

**When** the INFO log line is emitted

**Then** the line contains `format=`, `is_healthy=`, `warn_count=`, `fail_count=`
**And** the line does NOT contain any customer name, email, plaintext or formatted CPF / CNPJ (any 11–14-digit run, OR any `\d{3}\.\d{3}\.\d{3}-\d{2}` shape, OR any `\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}` shape), plaintext bearer (`cmdr_live_`), SHA-256 hash (64 hex), or `Authorization` header substring
**And** Story 3.3's `_PII_FORBIDDEN_RE` (with the formatted-CPF/CNPJ extension from the code-review patch) finds zero matches in the captured INFO records for the run

### AC20 — `health` surfaces at top-level `comadre-keys --help`

**Given** the operator runs `comadre-keys --help`

**When** the help text is rendered

**Then** `health` appears as a top-level command (flat, not nested under `system`)
**And** its one-line description matches the first sentence of `health_cmd`'s docstring (`"Report registry / cron / cache health (FR34)."`)

### AC21 — Performance: `collect_health_report` completes under 500 ms for a 1 000-customer DB (NFR5)

**Given** a registry seeded with 1 000 active customers + 2 000 keys (mixed status) + 5 000 audit rows (mirrors Story 1.6's perf seed)

**When** `collect_health_report(...)` is timed via `time.perf_counter()`

**Then** elapsed wall-clock time is under 500 ms
**And** the report contains the canonical 8 checks with non-error severities

### AC22 — Marker-file robustness against malformed contents

**Given** the marker file exists but its contents are unparseable (binary, truncated, missing keys, extra unknown keys)

**When** `health --format json` runs

**Then** the `Cron` check has `severity == "warn"` (defense-in-depth — we don't trust the marker to be well-formed when it could indicate corruption)
**And** the value contains `"Marker present but unparseable"`
**And** the detail mentions `"re-run ansible-playbook bootstrap.yml"`
**And** unknown keys in the marker are tolerated silently (forward-compatibility — Story 4.x may extend the marker schema)

### AC23 — JSON payload structure is stable and self-documenting

**Given** any successful `health --format json` invocation

**When** the JSON output is parsed

**Then** the top-level keys are exactly `{is_healthy, generated_at, warn_count, fail_count, checks}`
**And** `checks` is a list of objects, each having exactly `{label, severity, value, detail, data}` keys
**And** `severity` is always one of `{"ok", "info", "warn", "fail"}` (literal check via type check or membership assertion)
**And** `generated_at` matches the canonical regex `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$`
**And** the `data` field for each check is either `null` or a dict (never a primitive at the top level — this preserves forward-compatibility for adding fields)

## Tasks / Subtasks

- [ ] **Task 1 — Add `count_active_customers` + `count_keys_by_status` helpers in `src/comadre/keys/db.py`** (AC5)
  - [ ] 1.1 Append both helpers immediately after `count_tombstones` (db.py:618-623), preserving the alphabetical-by-purpose ordering of count helpers.
  - [ ] 1.2 `count_active_customers` SELECTs `COUNT(*) FROM customer WHERE deleted_at IS NULL`.
  - [ ] 1.3 `count_keys_by_status` returns the fixed-shape `{"active": N, "suspended": N, "revoked": N}` dict — initialise from the base dict; overlay GROUP BY rows.
  - [ ] 1.4 Add unit tests in `tests/test_keys_db.py`: `test_count_active_customers_excludes_tombstones`, `test_count_keys_by_status_returns_full_shape`, `test_count_keys_by_status_returns_zeros_on_empty_db`.
  - [ ] 1.5 Mypy clean — both helpers have explicit return types; the dict literal in `count_keys_by_status` uses `dict[str, int]` annotation.

- [ ] **Task 2 — Create `src/comadre/keys/health.py` module** (AC1–AC13, AC21, AC22)
  - [ ] 2.1 Module-level docstring per §2 spec (severity-model enumeration).
  - [ ] 2.2 `Severity` Literal type, `HealthCheck` and `HealthReport` dataclasses (`frozen=True, slots=True`).
  - [ ] 2.3 Public `collect_health_report(...)` function with the keyword-only signature from §2.
  - [ ] 2.4 Eight private `_check_*` builders, each returning a `HealthCheck` per the §2 specs.
  - [ ] 2.5 `_BACKUP_NOT_IMPLEMENTED_INFO` module constant (currently `True`); `_check_last_backup` honours it. Story 4.3 will flip to `False`.
  - [ ] 2.6 `_marker_parse(text: str) -> dict[str, str] | None` returns `None` on any malformed input (used by AC22). Tolerates unknown keys (drops them).
  - [ ] 2.7 `is_healthy` aggregation runs once at the end of `collect_health_report` and is stored on the `HealthReport` (no recomputation in renderer or CLI).
  - [ ] 2.8 `generated_at` uses `_utcnow_iso` from `comadre.keys.db` (canonical ISO-UTC second-precision form).

- [ ] **Task 3 — Add `health_cmd` in `src/comadre/keys/cli/commands/system.py`** (AC1, AC14, AC16, AC17, AC19, AC20)
  - [ ] 3.1 Decorator `@app.command("health")` with `--format` option.
  - [ ] 3.2 Validation ladder per §4 (literal flag check → settings/TZ → DB+migrations → collect → render).
  - [ ] 3.3 `from exc` on the exit-5 mapping (Story 3.3 patch contract).
  - [ ] 3.4 Render branch: table mode always exits 0; JSON mode exits 7 iff `report.is_healthy is False`.
  - [ ] 3.5 Structured INFO log (PII-austere — counts only, wrapped in `contextlib.suppress(Exception)`).
  - [ ] 3.6 Module-docstring extended per §6 (exit-7 added to the contract enumeration; `health` added to the verb list).
  - [ ] 3.7 Imports: `from comadre.keys.health import HealthCheck, HealthReport, collect_health_report` + `_health_report_to_json` (private helper inside `system.py`).

- [ ] **Task 4 — Add `render_health_report` in `src/comadre/keys/cli/output.py`** (AC1, AC2, AC3, AC9, AC22)
  - [ ] 4.1 Signature `def render_health_report(report: HealthReport) -> None`.
  - [ ] 4.2 Single-border rounded `Panel`, title `"System Health"`.
  - [ ] 4.3 Right-pad labels to the longest label width.
  - [ ] 4.4 Severity → markup mapping (`ok`/`info` → plain; `warn` → `[yellow]…[/yellow]`; `fail` → `[red]…[/red]`).
  - [ ] 4.5 `detail` rendered as `[dim](…)[/dim]` after the value when present.
  - [ ] 4.6 Footer via `render_confirmation`: `"Healthy."` or `"Unhealthy: N warning(s), M failure(s)."`.
  - [ ] 4.7 Defense against markup injection in operator-influenced strings (rare but defensive `rich.markup.escape` on `db_path` / `billing_timezone` substrings).
  - [ ] 4.8 Import `from comadre.keys.health import HealthCheck, HealthReport` at the top of `output.py` (sibling import — matches the existing `from comadre.counters import AggregatedCacheStatus` pattern at output.py:24).

- [ ] **Task 5 — Ansible marker-file write/remove** (AC9, AC18)
  - [ ] 5.1 Append the marker-write task to `bootstrap.yml` per §3 (immediately after the `comadre-daily-suspension` cron entry, before the "Next steps" summary).
  - [ ] 5.2 Append the marker-remove task to `cleanup.yml` per §3 — order: marker → cron → `CRON_TZ` (per Story 3.3 deferred entry on partial-failure resilience). Wrap the three in a `block:` if convenient.
  - [ ] 5.3 Update bootstrap's "Next steps" summary (L328-358) to mention `comadre-keys health` as the first-run sanity check ("After bootstrap, verify with: `docker compose exec tts-service comadre-keys health`").
  - [ ] 5.4 `ansible-playbook --check` smoke pass (manual — deferred to 10.10.10.207 acceptance gate; see Completion Notes).

- [ ] **Task 6 — Health-module unit tests** (AC1, AC2, AC3, AC4, AC5, AC6, AC7, AC8, AC11, AC12, AC13, AC21, AC22)
  - [ ] 6.1 Create `tests/test_keys_health.py` per §8 spec (~25 cases).
  - [ ] 6.2 Reuse the `tmp_path` + `get_connection` + `_apply_migrations` + raw-SQL seed pattern from `test_keys_db_suspend_sweep.py`.
  - [ ] 6.3 NFR5 perf test — 1 K customers + 2 K keys + 5 K audit rows; assert `collect_health_report` < 500 ms.
  - [ ] 6.4 Time-freeze for sweep-age tests via `monkeypatch.setattr("comadre.keys.health._utcnow", lambda: <fixed>)` (the module's clock seam) — patch the **source** module per Story 3.3 deferred guidance.

- [ ] **Task 7 — CLI tests** (AC1, AC2, AC3, AC10, AC14, AC15, AC16, AC17, AC18, AC19, AC20, AC23)
  - [ ] 7.1 Create `tests/test_keys_cli_health.py` per §8 spec (~15 cases).
  - [ ] 7.2 Scaffolding copied verbatim from `tests/test_keys_cli_cache_status.py` (buffers fixture, env fixture, snapshot writer, `_buffers()` helper).
  - [ ] 7.3 AC15 read-only assertion: capture `os.stat(db_path).st_mtime` and `os.stat(sentinel).st_mtime` before/after the CLI invocation; assert byte-equality.
  - [ ] 7.4 AC18 marker-write/remove coverage uses Python-level fixtures (writes the marker file directly via `Path.write_text`) — full ansible run is the deploy-time gate.

- [ ] **Task 8 — Renderer tests** (AC1, AC22)
  - [ ] 8.1 Add `TestRenderHealthReport` class to `tests/test_keys_output.py` per §8 (4 cases).
  - [ ] 8.2 Markup-injection guard test parallels Story 3.2 / 3.3 precedent.
  - [ ] 8.3 Severity-colour test uses `force_terminal=True` Console + ANSI-escape regex (existing pattern in test_keys_output.py for `_format_seconds_ago`).

- [ ] **Task 9 — Docs sweep** (CLAUDE.md / README.md / docs/configuration-reference.md / docs/deployment-guide.md)
  - [ ] 9.1 `CLAUDE.md` CLI bullet — append `health` to the system cluster after `suspend-sweep`.
  - [ ] 9.2 `CLAUDE.md` "Non-Obvious Gotchas" — add the cron-marker-vs-crontab note per §7 wording.
  - [ ] 9.3 `README.md` — append "System health" feature bullet under the registry-backed-API-keys section, with both invocations.
  - [ ] 9.4 `docs/configuration-reference.md` — note the marker file path + don't-edit-by-hand caveat.
  - [ ] 9.5 `docs/deployment-guide.md` — add a brief "Monitoring integration" subsection with the canonical `--format json` invocation, exit 0/7 contract, and a short `jq` example.

- [ ] **Task 10 — Sanity gates**
  - [ ] 10.1 `uv run ruff check .` clean.
  - [ ] 10.2 `uv run mypy src/` clean.
  - [ ] 10.3 `uv run pytest` green (baseline 1250 + ~46 new = ~1296 passing).
  - [ ] 10.4 `uv run pre-commit run --all-files` clean.
  - [ ] 10.5 Grep-check suite per §9.
  - [ ] 10.6 Manual smoke on 10.10.10.207 — `health`, `health --format json`, observed exit codes 0 and 7 against synthetic warn fixtures (deferred to deploy-time acceptance gate; document in Completion Notes).

## Dev Notes

### Import-graph placement

```
keys/cli/commands/system.py → {
    keys/cli/commands/keys.py         (load_settings_and_tz)
    keys/cli/output.py                (render_error, render_health_report [NEW],
                                       LIST_FORMAT_CHOICES, stdout_console)
    keys/db.py                        (get_connection, _apply_migrations,
                                       _SCHEMA_VERSION)
    keys/health.py [NEW]              (HealthReport, HealthCheck,
                                       collect_health_report)
    comadre.config                    (Settings — via load_settings_and_tz)
    comadre.logging                   (get_logger)
}

keys/health.py [NEW] → {
    keys/db.py                        (get_connection, _apply_migrations,
                                       _SCHEMA_VERSION, _utcnow_iso,
                                       count_active_customers [NEW],
                                       count_keys_by_status [NEW],
                                       count_tombstones,
                                       get_last_sweep_timestamp)
    comadre.counters                  (read_all_snapshots, aggregate_cache_status,
                                       AggregatedCacheStatus)
    comadre.logging                   (get_logger)
    stdlib                            (os, pathlib, datetime, sqlite3)
}

keys/cli/output.py → {
    keys/health.py [NEW]              (HealthCheck, HealthReport)
    keys/models.py                    (existing imports)
    comadre.counters                  (existing AggregatedCacheStatus import)
    rich                              (existing)
}
```

No reverse edges. `keys/auth.py`, `rate_limit.py`, `main.py`, `api.py`, `keys/cache.py`, `keys/counters.py` (the runtime counters writer — not to be confused with the `comadre.counters` module read surface) do NOT import from `health.py` or any `health`-related symbols. The CLI is downstream of all runtime modules.

### Why `health.py` is a new module, not a function in `db.py` or `system.py`

`db.py` is the SQL-helper module. Putting filesystem reads (`os.stat`, marker-file parse, backup glob) and counter-snapshot aggregation in `db.py` would muddy its altitude. `system.py` is the CLI-wiring module — its job is settings → DB → render branch. Neither is the right home for the severity arithmetic + 8-check assembly.

A dedicated `keys/health.py` keeps each layer at its native altitude:
- `db.py` — SQL helpers (counts, lookups).
- `health.py` — multi-source collector + severity arithmetic.
- `system.py` — CLI wiring (validation, format branch).
- `output.py` — rendering primitives.

This matches the architecture's intentional layering and makes Story 4.2 / 4.3's future additions (each will add a check or two to `collect_health_report`) a localised diff against `health.py` only.

### Why exit code 7 (and not extending `system.py`'s 0/2/5/6 contract differently)

The system-module exit-code table is composed per-verb, not per-module — `cache-status` emits 0/2/6, `suspend-sweep` emits 0/5/6, `health` emits 0/2/5/6/**7**. The shared module-docstring enumerates the union; each verb's docstring tells the operator which subset applies.

Alternative considered: collapse `warn` and `fail` into one severity and just use the existing exit-5 ("error") contract for "unhealthy". Rejected because exit-5 is reserved for *infrastructure* errors (DB unreachable, `_apply_migrations` failure) — semantically distinct from "DB reachable but registry state has drift". Operators monitoring exit-5 expect to call SRE; operators monitoring exit-7 expect to investigate config drift. The split is operationally meaningful.

Alternative considered: emit exit-1 for unhealthy. Rejected per §4 rationale — exit-1 is shell-conventional "general error", too generic.

Alternative considered: never emit non-zero from `health` even in JSON mode; let the caller `jq '.is_healthy' | grep -q true`. Rejected because the epic AC explicitly prescribes "exits non-zero on any unhealthy condition" for `--format json`. The exit-code IS the script-level signal; having to pipe through `jq` defeats the point of integrating with `check_nagios` / Prometheus textfile collectors that key off `$?`.

### Why the marker-file convention has the contents it has

Two key=value lines, ASCII, no JSON. Rationale:
- **No JSON**: the file is read once during `health` and parsed with a four-line list-comprehension. Pulling in `json` for two key-value pairs would over-engineer it. The `_marker_parse` helper is naturally `dict(line.split("=", 1) for line in text.splitlines() if "=" in line)` — five lines with the ValueError guard, fully type-safe.
- **Two specific keys**: `schedule` (the cron schedule string verbatim from the ansible task) and `cron_tz` (the IANA zone). These are the two pieces of information the operator wants the `health` panel to surface. Adding `installed_at`, `installed_by`, `playbook_version` would be useful telemetry but not actionable health signals — defer to a future "deployment audit" surface if the need emerges.
- **No trailing newline**: `Path.write_text` and `ansible.builtin.copy` with `content: |-` (block-strip) match. This is a brittle invariant — the test in `tests/test_keys_health.py` should NOT assert on trailing-newline presence (the parser tolerates both).
- **Permissions 0600**: matches the DB file. Same volume, same protection level. The marker contains no secrets but lives next to data that does — uniform permission policy is easier to audit than per-file exceptions.

### Why eight checks specifically (and what's omitted)

The eight checks correspond exactly to the FR34 / Epic-AC enumeration: DB integrity (path / size / permissions / schema), registry shape (customers / keys), operational liveness (sweep / cron / backup), runtime telemetry (auth cache). Adding more (CPU, memory, disk-free, network) would drift `health` from "registry health" into "system health" — the latter is `health.yml`'s ansible job, not the CLI's contract.

**Explicitly omitted:**
- **Disk-free.** Architecture's `health.yml` ansible playbook already warns at >80% root usage (`health.yml:109-122`). The CLI doesn't replicate; the two surfaces complement.
- **API HTTP `/health` endpoint reachability.** This is `health.yml`'s job (it `uri:` the endpoint over HTTPS). The CLI runs inside the container and would shell out to `curl localhost:8000/health` — possible but adds a network dependency to a CLI that should be DB-only. Defer.
- **Encryption-key freshness / age.** Story 4.2 will add this. Reserved as the 9th check.
- **Audit-log retention age.** No retention story exists yet. When one lands, add it as a 10th check.
- **Counter-snapshot per-replica details.** The aggregate suffices for `health`; per-replica drill-down is `cache-status`'s job.

### NFR5 performance budget

`collect_health_report` performs:
- 5 SQLite reads (`SELECT MAX(version) FROM schema_version`, `count_active_customers`, `count_tombstones`, `count_keys_by_status` GROUP BY, `get_last_sweep_timestamp`'s ORDER-BY-LIMIT-1).
- 3 filesystem stats (DB file, marker file, possibly the auth-cache sentinel — though the sentinel isn't in scope).
- 1 directory glob for backup files (always misses today; cheap directory scan).
- 1 directory glob for counter snapshots (cached at the OS level after the first call).

Total budget on a 1 K-customer / 2 K-key / 5 K-audit DB: < 50 ms on bare metal (SQLite reads are <2 ms each, filesystem stats are sub-millisecond, globs are a single readdir). The 500 ms NFR5 budget has 10× headroom. Test assertion uses `< 500 ms` to tolerate CI jitter (same slack pattern Story 3.3 used for NFR3).

### Why no `--quiet` / `--verbose` flags

The panel is the contract. A `--quiet` mode that emits only the verdict would duplicate `--format json` (parse `is_healthy`); a `--verbose` mode that adds per-replica drill-down would duplicate `cache-status`. Two output modes is the right cardinality.

### Why no `comadre-keys system health` subcommand grouping

The architecture decision (§357 / §551) keeps the `comadre-keys` namespace flat: every verb is at the top level. `health` joins `cache-status`, `suspend-sweep`, `rotate-encryption-key` as a flat sibling. Operators don't memorise a tree; they tab-complete a single namespace.

### Test-flake avoidance

- **Patch the source module's clock**, not the importer's. `monkeypatch.setattr("comadre.keys.health._utcnow", lambda: ...)` — same idiom Story 3.3 deferred-work flagged.
- **Seed marker files with `Path.write_text(..., encoding="utf-8")`** + `os.chmod(..., 0o600)`. No ansible in unit tests.
- **AC15 mtime assertion**: capture mtime via `os.stat(db_path).st_mtime_ns` (nanosecond precision) before the CLI call; assert exact equality after. Filesystems with second-resolution mtime would noise this — `test_keys_health.py` skips on FAT32-style mtime systems via the same `os.utime(p, (0, 0))` baseline pattern Story 3.3 deferred recommended.
- **JSON payload assertions via `json.loads(...) == expected_dict`**, not byte strings. Same hygiene rule Story 3.1 / 3.3 followed.
- **Severity-colour assertion via ANSI escape regex** on a `force_terminal=True` Console — same pattern `test_keys_output.py` uses for `_format_seconds_ago`. Do NOT assert on the no-color buffer's content for colour-dependent fields; assert only on the rendered text content there.
- **PII regex**: reuse Story 3.3's `_PII_FORBIDDEN_RE` post-code-review-patch (covers formatted CPF/CNPJ).
- **Counter-snapshot test fixtures**: copy `_write_snapshot` from `test_keys_cli_cache_status.py:61-94` verbatim. Do NOT re-derive the snapshot schema.

### Integration with monitoring tooling

`health --format json` is designed as a drop-in for `check_nagios`-style monitors:

```bash
# Nagios plugin
comadre-keys health --format json > /dev/null
case $? in
  0) echo "OK"; exit 0 ;;
  7) echo "WARNING: $(comadre-keys health --format json | jq -r '.checks[] | select(.severity != "ok" and .severity != "info") | "\(.label): \(.value)"' | tr '\n' ', ')"; exit 1 ;;
  *) echo "CRITICAL: comadre-keys health failed (exit $?)"; exit 2 ;;
esac
```

Document this snippet (or its Prometheus-textfile equivalent) in `docs/deployment-guide.md`. The snippet is illustrative — the canonical contract is "exit 0 healthy, exit 7 unhealthy, anything else is broken".

### Backup-check forward compatibility

`_BACKUP_NOT_IMPLEMENTED_INFO = True` in `keys/health.py` is the Story 3.4 ↔ Story 4.3 handshake. When 4.3 lands:
1. Flip `_BACKUP_NOT_IMPLEMENTED_INFO = False`.
2. Update `_check_last_backup` to use `staleness_warn_seconds=48*3600` for the warn threshold (same pattern as the sweep check).
3. Update the corresponding test (`test_backup_check_is_info_only_today`) — expected to need an updated test fixture (forcing function — the test will fail, signalling the constant flip is the right next step).

No other code in 3.4's diff needs to change. The renderer + JSON shape + CLI wiring all remain stable. This is the architectural payoff of the per-check severity model.

### Deferred work to flag at story close

Add to `_bmad-output/implementation-artifacts/deferred-work.md`:

- **`crontab -l` shell-out is not available from inside the `tts-service` container**, so the marker file is the cron-installed signal. Future enhancement: surface the running cron daemon's actual schedule (parse `/var/spool/cron/crontabs/$USER` mounted read-only into the container, or have ansible write the schedule into a more structured marker file) — the current marker is "ansible installed it" which is a strong-but-not-perfect signal. Pair with a deeper observability story.
- **Backup-check is `info`-only until Story 4.3 lands** — not an oversight, a conscious deferral. Flip the `_BACKUP_NOT_IMPLEMENTED_INFO` constant when 4.3 ships.
- **`AggregatedCacheStatus` snapshot age threshold is not surfaced as a warn condition** today. A snapshot older than 5 minutes might indicate the snapshot writer thread is stuck; `health` could `warn` on this. Out of scope for 3.4 (would require choosing a threshold in coordination with Story 2.3's writer cadence).
- **`health` does not check the `.invalidate` sentinel mtime**. The sentinel is the auth-cache propagation primitive (Story 2.1); a stale sentinel mtime is operationally meaningful (no recent mutations vs propagation may be lagging). Deferring because the sentinel can be legitimately stale on a quiet read-only registry.
- **No integration test for "exit 7 from a real subprocess"**. The CLI tests use `CliRunner.invoke` which surfaces the exit code via `result.exit_code` — same as `os.system` would but in-process. A real `subprocess.run` test would exercise the actual `os.exit`/`SystemExit` plumbing. Out of scope; covered indirectly by the deploy-time smoke (Task 10.6).
- **`is_healthy` semantic mixes `warn` and `fail`** in the JSON output — both flip `is_healthy` to false, both contribute to exit-7. A monitoring system that distinguishes "warning" from "critical" tier alerts must parse `warn_count` vs `fail_count` separately. Documented in the deployment guide; revisit if operators ask for a finer-grained exit-code split.

### Project Structure Notes

**New files:**

```
src/comadre/keys/
  health.py                                     [NEW]

tests/
  test_keys_health.py                           [NEW]
  test_keys_cli_health.py                       [NEW]
```

**Modified files:**

```
src/comadre/keys/
  db.py                                         [MOD — count_active_customers + count_keys_by_status helpers]
  cli/commands/system.py                        [MOD — health_cmd + module-docstring exit-7 extension]
  cli/output.py                                 [MOD — render_health_report]

tests/
  test_keys_db.py                               [MOD — 3 tests for the two new aggregate helpers]
  test_keys_output.py                           [MOD — TestRenderHealthReport class, 4 cases]

deploy/ansible/
  playbooks/bootstrap.yml                       [MOD — marker-file write task; "Next steps" summary update]
  playbooks/cleanup.yml                         [MOD — marker-file remove task; ordering before cron / CRON_TZ]

docs/
  configuration-reference.md                    [MOD — marker file note]
  deployment-guide.md                           [MOD — Monitoring integration subsection]

CLAUDE.md                                       [MOD — CLI command list + cron-marker gotcha]
README.md                                       [MOD — System health feature bullet]
```

**Unchanged (asserted by AC15):**

```
src/comadre/api.py                              — no new route, no middleware change
src/comadre/main.py                             — health is CLI-only, never loaded by FastAPI runtime
src/comadre/rate_limit.py                       — rate-limit path untouched
src/comadre/keys/auth.py                        — auth path untouched
src/comadre/keys/cache.py                       — cache untouched (sentinel not modified by health)
src/comadre/health.py                           — HTTP /health endpoint untouched (distinct from CLI verb)
src/comadre/counters.py                         — read_all_snapshots / aggregate_cache_status reused as-is
src/comadre/keys/migrations/v001_initial.sql    — no schema change
src/comadre/keys/billing.py                     — billing-provider untouched
src/comadre/keys/cli/commands/billing.py        — no new verb here
src/comadre/keys/cli/commands/customers.py      — no new verb here
src/comadre/keys/cli/commands/keys.py           — no new verb here
src/comadre/keys/cli/app.py                     — system_app already registered; no new extend call
pyproject.toml, uv.lock                         — no new dependency
```

### Testing standards

- CLI tests use `CliRunner` from `typer.testing` + the `_reset_consoles_to_buffers` auto-fixture pattern (copy verbatim from `test_keys_cli_cache_status.py` — canonical template; same scaffolding Story 3.3 followed).
- DB / health tests use `tmp_path` for the SQLite file + `get_connection` + `_apply_migrations`. Seed customers/keys via `insert_customer` / `insert_api_key` (never hand-roll SQL beyond the audit-log seed for sweep-age tests).
- Time-freeze via `monkeypatch.setattr("comadre.keys.health._utcnow", lambda: <fixed datetime>)` — patch the **source** module per Story 3.3 deferred-work guidance.
- `caplog` captures INFO log lines for AC19 PII assertions.
- Rich output capture via `result.stdout` / `result.stderr` from `CliRunner().invoke(...)` — `_reset_consoles_to_buffers` plumbs both into `StringIO` buffers.
- JSON assertions on payload structure: `payload = json.loads(stdout)` then dict comparison; never byte-string comparison.
- PII-regex guard: reuse `_PII_FORBIDDEN_RE` from Story 3.1 / 3.3's test files (post-code-review extension covering formatted CPF/CNPJ).
- For severity-colour assertions, use a `force_terminal=True` Console (separate from the no-color test buffers) and grep for ANSI escape sequences. Do NOT try to assert colour against a `no_color=True` buffer.

### References

- Epic 3 Story 3.4 scope — `_bmad-output/planning-artifacts/epics.md:719-744`
- FR34 wording — `_bmad-output/planning-artifacts/prd.md:1169`
- FR42 (file permissions; health *reports* drift) — `_bmad-output/planning-artifacts/prd.md:1183`
- FR43 (last-sweep timestamp queryable) — `_bmad-output/planning-artifacts/prd.md:1184`
- NFR5 (CLI detail-class < 500 ms p99) — `_bmad-output/planning-artifacts/prd.md:1206`
- NFR15 (PII-austere logs) — `_bmad-output/planning-artifacts/prd.md:1219`
- Architecture system-module verb list — `_bmad-output/planning-artifacts/architecture.md:357, 551`
- Architecture file-permission policy — `_bmad-output/planning-artifacts/architecture.md:752-754`
- Backup file path convention (Story 4.3 forward-lean) — `_bmad-output/planning-artifacts/architecture.md:242, 249, 256`
- UX-spec: read-tier exit-0 default, DetailPanel pattern — `_bmad-output/planning-artifacts/ux-design-specification.md:244, 768-785, 892, 1043-1056`
- `cache-status` CLI shape (template for `health_cmd`) — `src/comadre/keys/cli/commands/system.py:74-172`
- `suspend-sweep` CLI shape (template for exit-5 mapping with `from exc`) — `src/comadre/keys/cli/commands/system.py:175-256`
- `_apply_migrations` + `_SCHEMA_VERSION` — `src/comadre/keys/db.py:188, 279-312`
- `count_tombstones` (template for the two new aggregate helpers) — `src/comadre/keys/db.py:618-623`
- `get_last_sweep_timestamp` (Story 3.3 read surface for FR43) — `src/comadre/keys/db.py:1479`
- `read_all_snapshots` + `aggregate_cache_status` — `src/comadre/counters.py:402-494`
- `render_customer_detail` / `render_key_detail` (DetailPanel templates) — `src/comadre/keys/cli/output.py:562-616`
- `_iso_date` / `_format_seconds_ago` / `_format_uptime` (humanizers) — `src/comadre/keys/cli/output.py:223, 656, 672`
- `LIST_FORMAT_CHOICES` (shared `--format` choices) — `src/comadre/keys/cli/output.py:46`
- `load_settings_and_tz` (shared exit-6 ladder) — `src/comadre/keys/cli/commands/keys.py:738-781`
- Story 3.3 cron entry + `BILLING_TIMEZONE` ↔ `CRON_TZ` parity — `deploy/ansible/playbooks/bootstrap.yml` (post-3.3 state)
- PII-forbidden regex (NFR15 guard, post-3.3 patch) — `tests/test_keys_cli_suspend_sweep.py::_PII_FORBIDDEN_RE`
- HTTP `/health` endpoint (distinct surface — do NOT touch) — `src/comadre/health.py`
- Ansible `health.yml` (complementary infra-health surface — do NOT replicate) — `deploy/ansible/playbooks/health.yml`

## Questions for Operator (please confirm before dev-story)

> All seven have recommended answers. In auto-mode, apply the recommended answer; if any run hits a disagreement, reopen as a deferred-work entry.

1. **Exit code 7 for `--format json` unhealthy.** Adds a new code to the `system.py` module contract (was 0/2/5/6, becomes 0/2/5/6/7). Alternative: collapse `warn`+`fail` and use exit 5. Recommend **7** — operationally distinguishes "registry-state drift" from "infrastructure error" and matches the epic AC's "non-zero" requirement without overloading exit 5.

2. **Table mode always exits 0; JSON mode exits 7 on unhealthy.** Read-tier UX-spec convention plus the epic AC pinning the non-zero contract specifically to JSON mode. Alternative: also exit 7 in table mode. Recommend **table=0 always** — interactive operators don't want their shell-prompt exit-code styling to flip on a yellow warning.

3. **Cron-installed marker file at `{key_registry_db_path}.cron-installed`.** Two-line key=value, mode 0600, written by bootstrap, removed by cleanup. Alternative: shell out to `crontab -l` from inside the container. Rejected — the host crontab isn't visible from inside the `tts-service` container; mounting it would be a security regression. Recommend the marker file.

4. **Backup check is `info`-only until Story 4.3 lands.** A `_BACKUP_NOT_IMPLEMENTED_INFO = True` constant in `keys/health.py` gates the WARN branch. When 4.3 ships, flip the constant. Alternative: skip the backup row entirely until 4.3. Recommend the `info` row — surfaces the forward-lean to the operator and makes the eventual addition a one-line change.

5. **Auth-cache absence is `info`, not `warn`.** A CLI-only invocation with no API container running has no replicas reporting; `info` reflects "no signal", not "drift". Alternative: `warn` to flag "no API replicas running". Recommend **info** — operators legitimately run `health` from a host shell without an API container running (e.g., during initial setup, after a deploy, or for offline DB inspection).

6. **Eight specific checks; no disk-free / no HTTP `/health` reachability.** Architecture's `health.yml` ansible playbook already covers infra-level concerns; CLI `health` is the registry-level surface. Recommend **stay scoped** — adding infra checks would muddy the contract.

7. **JSON shape `checks: [{label, severity, value, detail, data}, ...]`** instead of a flat dict. Trade-off: marginally more verbose `jq` queries vs richer per-check structure. Recommend the **array shape** — matches the table-rendering iteration order and gives `jq '.checks[] | select(.severity != "ok")'` as the canonical operator query.

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List

### Change Log
