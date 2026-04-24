# Story 4.5g: CI — SQL-Injection Static Analysis (Bandit)

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

> **Scope note — SQL-injection prevention (PRD §Technical Constraints line 192, §Continuity with Existing Hardening line 703; architecture §Code Review Pre-Flight line 486, §Project Structure line 509; NFR17).** Seventh and last of the seven CI non-regression sub-stories (4.5a–4.5g). Closes the 4.5 umbrella. Inherits the skeleton 4.5a landed (`tests/test_non_regression/` package, `non_regression` pytest marker, `addopts = "-m 'not non_regression'"` default-exclusion, `non-regression` job in `.github/workflows/ci.yml`), the marker broadening 4.5b applied ("Static-scan checks skip both harnesses."), the static-scan fixture-subdirectory convention 4.5c established (`tests/test_non_regression/fixtures/<check_name>/`), and the AST-scan precedent 4.5f reinforced. 4.5g is the **third** static-scan sub-story but the **first that delegates the scan to an external tool (`bandit`) rather than a stdlib AST walker**. Delivers five artefacts: (1) `bandit` added to `[dependency-groups.dev]` in `pyproject.toml` so `uv sync` installs it in CI and on developer laptops; (2) `# nosec B608: <reason>` comments on the four legitimate column-allowlist f-string SQL sites currently in `src/comadre/keys/db.py` (each reason is reviewer-enforced and names the controlled-input contract that makes the f-string safe); (3) `tests/test_non_regression/test_sql_static_bandit.py` — subprocess-invokes bandit, parses the JSON result, asserts zero B608 findings in `src/comadre/keys/`; (4) four fixture files under `tests/test_non_regression/fixtures/sql_static_bandit/` driving the scan's self-tests (bad f-string, bad `%`/concat, `# nosec`-suppressed, canonical parameterised); (5) README ownership-row refinement. **No CI YAML change. No `tests/conftest.py` change. No `tests/test_non_regression/conftest.py` change. No app runtime behaviour change — the four `# nosec` comments are pure annotations.**

> **Empirical premise (READ BEFORE IMPLEMENTING).** Dry-run on 2026-04-24 — `uv run --with bandit bandit -r src/comadre/keys/ --format json`:
> - 5× **B101 (`assert_used`, LOW severity / HIGH confidence)** in `src/comadre/keys/cli/commands/keys.py` (lines 220, 984, 1099, 1100, 1250). These are intentional internal-consistency asserts in CLI code; they are NOT SQL-injection risk and are OUT OF SCOPE for 4.5g.
> - 4× **B608 (`hardcoded_sql_expressions`, MEDIUM severity / LOW confidence)** in `src/comadre/keys/db.py` at lines 548, 814, 1064, 1268. All four are **legitimate** column-allowlist f-string splicing — the f-string fragments come from `set_parts`/`predicates`/`placeholders` lists whose elements are hardcoded column names or programmatically-derived `?` placeholders. User/operator input lands exclusively in positional `?` bindings via `conn.execute(sql, params)`. The docstring at `db.py:1048-1052` already articulates this invariant verbatim for the audit-log `IN (…)` case: *"placeholders are produced programmatically from the sequence length; operator input only lands in positional ``?`` bindings, never in the SQL text."*
>
> 4.5g therefore must (a) scope the scan to B608 specifically (via `-t B608`) so B101 noise does not leak into the gate — B101 is a deferred-work concern, not 4.5g's charter; (b) suppress the four current legitimate B608 sites via bandit's native `# nosec B608: <reason>` line comment so the current codebase scans clean on 4.5g merge; (c) lower the severity gate to include MEDIUM findings — the epic AC's wording *"fails the build if any HIGH-severity finding is reported"* is empirically wrong for bandit's SQL-injection rule (B608 maxes at MEDIUM; a HIGH-only gate would catch zero SQL-injection regressions). The story spec adopts the correct semantics explicitly and notes the epic-AC calibration. Grep invariants that must hold before 4.5g lands:
> - `rg "conn.execute" src/comadre/ -l` → lists ONLY files under `src/comadre/keys/` (zero SQL surface outside the keys module; verified 2026-04-24).
> - `rg "# nosec" src/comadre/` → 0 hits pre-4.5g (no pre-existing bandit allowlist comments; 4.5g introduces the convention).
> - `rg "bandit" pyproject.toml` → 0 hits pre-4.5g.
> - `uv run --with bandit bandit -r src/comadre/keys/ -t B608 --format json` reports 4 B608 findings pre-4.5g, 0 findings post-4.5g.

## Story

As a contributor,
I want every pull request against master to prove — via `bandit -r src/comadre/keys/ -t B608 -l -c … --format json` (scoped to the `hardcoded_sql_expressions` plugin only, severity gate at MEDIUM-or-higher, bandit run as a subprocess of a pytest test under the existing `non-regression` CI job) — that no module under `src/comadre/keys/` constructs SQL via f-string interpolation, `%`-formatting, or `+`-concatenation of untrusted input, so the sole permitted SQL-construction patterns are (a) bare `conn.execute("… WHERE id = ?", (value,))` parameterised queries and (b) column-allowlist f-string splicing where the interpolated fragments come from a hardcoded controlled list (`set_parts`, `predicates`, `placeholders`) and are explicitly annotated with a `# nosec B608: <reviewer-enforced-reason>` comment,
so that a well-meaning PR that "quick-fixes" a new filter by `conn.execute(f"SELECT * FROM t WHERE customer_id = {cid}")` — or that introduces `sql = "SELECT … WHERE x = '" + value + "'"` anywhere under `src/comadre/keys/` — cannot land on master without the PR build turning red and naming (a) the source path and line number, (b) the bandit test id (`B608`), (c) the severity + confidence of the finding, and (d) a one-line remediation hint pointing to the sqlite3 `?`-placeholder pattern.

**Covers FRs:** Cross-cutting SQL-injection prevention control from PRD §Technical Constraints line 192 ("parameterized queries exclusively, `bandit` or equivalent static-analysis check in pre-commit, code-review checklist item") and PRD §Continuity with Existing Hardening line 703 ("all queries use parameterized statements (`?` placeholders, never string interpolation). Any CLI arg that becomes a SQL value passes through sqlite3's bound-parameter layer, never a format string"). Epic 4 §Story 4.5g AC. Also satisfies the architecture §Code Review Pre-Flight item 4 at `architecture.md:486` ("Verify all SQL uses parameterized queries — grep for string interpolation in `.py` files touching `conn.execute`"). Also the architecture §Project Structure line 509 prediction (`.github/workflows/ci.yml [MOD] add bandit step, keys test coverage gate`) — implemented via the existing `non-regression` job rather than a separate step (see Design decisions below; both shapes satisfy the architecture's wording).
**NFRs:** NFR17 (all Non-Regression Contract controls remain satisfied on every PR; CI regression coverage mandatory for each control row).
**UX-DRs:** Contributor-facing CI UX — when the scan fires, the pytest failure message MUST name (a) the absolute source path, (b) the line number, (c) the bandit test id (`B608`), (d) the severity (MEDIUM) and confidence (LOW/MEDIUM/HIGH — bandit assigns per-case), (e) a one-line snippet of the offending source, (f) a remediation hint naming sqlite3's `?`-placeholder contract AND the `# nosec B608: <reason>` escape hatch. Inherits the 4.5a "name-the-regression" assertion convention and the 4.5c/4.5f fixture-per-scan-property discipline (here: four fixture files, one per distinct property).
**Epic:** 4 — Security Hardening, LGPD & Operational Safety. Eleventh and penultimate story in Epic 4 (4.1 → 4.2 → 4.3 → 4.4 → 4.5a → 4.5b → 4.5c → 4.5d → 4.5e → 4.5f → **4.5g** → 4.6). Seventh and final sub-story in the 4.5 non-regression cluster; third static-scan sub-story (after 4.5c for timing-safe compare and 4.5f for raw HTTPException). Third occupant of `tests/test_non_regression/fixtures/` (siblings: 4.5c's `timing_safe_compare/`, 4.5f's `no_raw_httpexception/`). Appends ONE test module + ONE fixtures subdirectory with four source fixtures. Modifies `src/comadre/keys/db.py` (four annotation-only `# nosec B608: <reason>` comments — zero runtime behaviour change) AND `pyproject.toml` + `uv.lock` (add `bandit` to `[dependency-groups.dev]`). Zero CI YAML change, zero marker change, zero `tests/conftest.py` change.

## Builds on

- **Story 4.5a — CI non-regression skeleton (`done`).** Established the `tests/test_non_regression/` package, the `non_regression` pytest marker (`tests/conftest.py:30-33`), the `addopts = "-m 'not non_regression'"` default-exclusion in `pyproject.toml`, the `non-regression` job in `.github/workflows/ci.yml` that runs `uv run pytest -m non_regression tests/test_non_regression/ -v`, and the "Extension contract" README section. 4.5g adds exactly one `test_<check_name>.py` plus one fixtures subdirectory, following the blueprint 4.5a promised.
- **Story 4.5b — README harness-choice section (`done`).** Broadened the `non_regression` marker to cover both docker and in-process tests; the README's `Harness choice` section (`tests/test_non_regression/README.md:177-191`) already names 4.5g verbatim: *"Static-scan checks skip both harnesses."* 4.5g is a pure subprocess invocation of bandit — no docker, no ASGI TestClient, no HTTP traffic.
- **Story 4.5c — First static-scan sub-story (`done`).** Established the fixture-subdirectory convention (`tests/test_non_regression/fixtures/<check_name>/`), the one-self-test-per-scan-property discipline, and the reviewer-enforced allowlist-comment pattern. 4.5g reuses the fixture-subdirectory convention verbatim (sibling to `fixtures/timing_safe_compare/`). 4.5g does NOT reuse the `# scan-allow:` token — bandit has its own escape hatch (`# nosec`) which is both more widely recognised and natively honoured by the tool; reimplementing a `# scan-allow:` bridge for bandit would be strictly worse than using bandit's native mechanism.
- **Story 4.5c + 4.5f "Scan allowlist convention" README section.** `tests/test_non_regression/README.md:193-206` already names 4.5g as a participant in the shared escape-hatch vocabulary ("Static-scan sub-stories (4.5c, 4.5f, 4.5g) share one escape hatch…"). 4.5g deliberately does NOT participate in the `# scan-allow:` token — the README needs a short addendum clarifying that 4.5g uses bandit's native `# nosec` mechanism (the two tokens are complementary, not competing; a line under `src/comadre/keys/` could in principle carry both if it triggered multiple scans simultaneously, though no current line does). Addendum text in Task 7.
- **Story 4.5f — Second static-scan sub-story (`done`).** Reinforced 4.5c's fixture-per-property discipline (four fixtures → four self-tests), the `_Violation` dataclass pattern, and the fixture-collection-isolation invariant (`pytest … --collect-only` ignores the fixture directories). 4.5g mirrors the four-self-test shape but abandons the in-file `_Violation` dataclass — bandit already produces structured JSON findings (`{test_id, filename, line_number, issue_severity, issue_confidence, issue_text, code}`) which the test module parses directly. Reusing bandit's native schema is strictly simpler than wrapping it in a project-local dataclass.
- **Existing SQL construction patterns in `src/comadre/keys/db.py`.** Four legitimate column-allowlist f-string splicing sites exist today (lines 548, 814, 1064, 1268 at story-draft time). The self-documented invariant at `db.py:1048-1052`: *"placeholders are produced programmatically from the sequence length; operator input only lands in positional ``?`` bindings, never in the SQL text."* All four sites share this invariant — only column-name fragments from a controlled `set_parts`/`predicates`/`placeholders` list are spliced; all VALUE bindings remain positional `?` + `params`. 4.5g pins the distinction mechanically: f-string SQL that passes reviewer-enforced justification carries `# nosec B608: <reason>`; f-string SQL that doesn't fails the build.
- **CLAUDE.md invariant.** *"All errors via `ComadreError` subclasses with `status_code`, `error_type`, `hint` — never raw HTTPException."* — adjacent invariant enforced by 4.5f. 4.5g closes the last remaining security-hardening gap from the 2.0.0 pentest response: SQL-injection prevention. After 4.5g lands, the six mechanical gates (4.5a through 4.5f) plus 4.5g's SQL-injection gate cover every row in the PRD's Non-Regression Contract.
- **Architecture §Code Review Pre-Flight — `architecture.md:484-486`.** *"Verify no `HTTPException` in new code — grep for it as a sanity check"* (mechanised by 4.5f) and *"Verify all SQL uses parameterized queries — grep for string interpolation in `.py` files touching `conn.execute`"* (mechanised by 4.5g). 4.5g promotes the manual grep to a PR-level bandit gate.
- **Architecture §Project Structure line 509.** *`.github/workflows/ci.yml [MOD] add bandit step, keys test coverage gate`*. The architecture authoritatively predicts a CI workflow modification. 4.5g honours this prediction at the **logical** level (bandit runs in CI on every PR) while implementing it via the existing `non-regression` job rather than a new separate step — see Design decisions for rationale. The "keys test coverage gate" half of the architecture line is explicitly OUT OF SCOPE for 4.5g (covered by a separate deferred-work story).
- **PRD §Technical Constraints line 192.** *"SQL-injection prevention story: parameterized queries exclusively, `bandit` or equivalent static-analysis check in pre-commit, code-review checklist item."* 4.5g is the story this line names. The "pre-commit" wording is historical — 4.5g implements the check at the CI-PR level rather than pre-commit because (a) bandit adds ~200 ms to every `git commit` invocation (acceptable but perceptible on a developer laptop), (b) the existing `non-regression` CI job already offers the desired gate at the right lifecycle point (PR-merge), (c) pre-commit would add a dependency that developers might `--no-verify` around whereas CI cannot be bypassed. A future refinement could also wire bandit into `.pre-commit-config.yaml` for local-loop feedback; out of scope today.
- **PRD §Continuity with Existing Hardening line 703.** *"all queries use parameterized statements (`?` placeholders, never string interpolation). Any CLI arg that becomes a SQL value passes through sqlite3's bound-parameter layer, never a format string."* 4.5g converts this prose contract to a mechanically-enforced PR gate for the VALUE side. The identifier/column-name side remains covered by reviewer judgement on `# nosec B608: <reason>` comments.
- **Story 1.1 through 1.6 + Epic 2 Security slice — the `src/comadre/keys/` module.** All SQL code that 4.5g scans was authored by Epic 1 stories. The module's authors (per commit history + CLAUDE.md header) already disciplined value bindings to `?` placeholders. 4.5g does not discover a regression — it proves the baseline is clean and prevents future regressions.

## Unblocks

- **Epic 4 retrospective.** 4.5g closing marks the end of the 4.5a–4.5g cluster and the penultimate story in Epic 4 (4.6 remains). All seven PRD Non-Regression Contract rows — security headers (4.5a), docs-disabled (4.5b), timing-safe compare (4.5c), oversized body (4.5d), rate-limit wiring (4.5e), no-raw-HTTPException (4.5f), SQL-injection (4.5g) — are mechanically enforced on every PR. The PRD Non-Regression Contract converts fully from a prose document to a CI gate.
- **Story 4.6 — LGPD Documentation & Breach Runbook (`backlog`).** 4.6 is prose-only; depends on no code landing after 4.5g. 4.5g closing confirms the full 2.0.0 security-hardening surface is under mechanical enforcement — 4.6 can cite this in the operator-facing documentation without caveat.
- **Future "broaden bandit scope" story (deferred).** 4.5g intentionally scopes the scan to `src/comadre/keys/` and only the B608 test-id. A follow-up story could widen either axis: (a) scan the full `src/comadre/` tree (currently zero non-keys `conn.execute` sites; low risk but low cost); (b) enable additional bandit plugins beyond B608 (B101 assert-used, B404 subprocess-module-use, etc. — each requires a triage pass over existing findings). Both are out of scope for 4.5g; listed in Deferred work.
- **Codebase-wide "parameterised queries only" invariant.** Once 4.5g lands, a PR cannot land ANY new `conn.execute(f"…")`, `conn.execute("…" % x)`, or `conn.execute("…" + x)` anywhere under `src/comadre/keys/` without an explicit `# nosec B608: <reason>` annotation — regardless of whether the module is in db.py, audit.py, health.py, or a future module. The mechanical gate covers the whole SQL risk surface.

## Depends on

- **Stories 4.5a, 4.5b, 4.5c, 4.5f are `done`** (sprint-status.yaml confirms; checked 2026-04-24). Hard dependency on 4.5a's non-regression package skeleton + marker + CI job + default-exclusion. Hard dependency on 4.5c's fixture-subdirectory convention and self-test-per-property discipline. Soft dependency on 4.5f's four-self-test shape (identical discipline, different tool). Soft dependency on 4.5b's broadened marker description (no change needed for 4.5g; the description as-landed already admits subprocess-based static scans under the same marker).
- **Story 4.5d, 4.5e are `done`** — not structurally required but 4.5g lands in a post-4.5e codebase so any quality-gate numbers cited downstream already include their contributions.
- **`src/comadre/keys/db.py` SQL patterns are stable.** The four current B608 sites (lines 548, 814, 1064, 1268 at story-draft time) use the column-allowlist f-string-splicing pattern that 4.5g's `# nosec` reasons will cite verbatim. If db.py is reshuffled mid-story (unlikely — no in-flight work touches these lines per git log 2026-04-24), the `# nosec` reasons may need minor rewording but the mechanical contract (four sites, each with a reviewer-enforced reason) does not change.
- **bandit 1.8+ is available on PyPI** (confirmed 2026-04-24 — dry-run used `uv run --with bandit bandit --version` reporting 1.9.4). The project pins `bandit>=1.8` to allow for the 1.8 `--severity-level` / `--confidence-level` flag polish; 1.9+ preferred because it ships with Python 3.12 source support. No feature depends on a specific 1.x minor.
- **No schema change. No auth-path change. No CI YAML change. No `tests/conftest.py` change. No `tests/test_non_regression/conftest.py` change. No new CLI verb. No ansible change. No `deploy/caddy/` change.**
- **Scoped `src/comadre/keys/db.py` change.** 4.5g adds exactly four `# nosec B608: <reason>` trailing comments. Zero runtime behaviour change — `# nosec` is a bandit-only annotation invisible to Python, ruff, mypy, and the sqlite3 layer. Grep invariant: `git diff master -- src/comadre/keys/db.py | rg "^\\+" | rg -v "# nosec B608"` MUST return empty (the diff contains ONLY the four nosec comments, no other line change).
- **Scoped `pyproject.toml` + `uv.lock` change.** 4.5g adds `"bandit>=1.8"` to `[dependency-groups.dev]` (alongside the existing `lint`, `test`, `type-check` subgroups — either as a new `security` subgroup included by `dev`, or inline in `dev` itself; dev-story picks the simpler shape at implementation time and records the choice in Completion Notes). `uv.lock` regenerates via `uv lock`. The diff is small and reviewer-readable.

## Scope

Five workstreams, in order:

1. **Add bandit as a dev dependency** — `pyproject.toml` gains a `security` dependency group containing `"bandit>=1.8"`; `dev` includes `security`; `uv lock` regenerates the lockfile. Idiomatic uv pattern (mirrors the existing `lint`/`test`/`type-check` subgroups).
2. **Annotate the four legitimate B608 sites in `src/comadre/keys/db.py`** — append `# nosec B608: <reason>` to the f-string SQL lines at 548, 814, 1064, 1268. Each reason names the controlled-input contract (column-allowlist / programmatic `?` placeholders). Zero runtime behaviour change.
3. **Ship the bandit wrapper test and the `src/comadre/keys/` regression assertion** — `tests/test_non_regression/test_sql_static_bandit.py`. A `_run_bandit(paths: Iterable[Path]) -> list[_Finding]` helper that subprocess-invokes bandit with `-t B608 -l -f json -q`, parses `result.stdout` into `_Finding` records, skips-rather-than-fails the test if bandit is unavailable in the environment (per the 4.5c/4.5f "fail loudly on genuine regression, skip on infra absence" discipline). One primary test asserts `_run_bandit([src/comadre/keys/])` returns an empty list.
4. **Ship the fixture files and the self-tests** — four files under `tests/test_non_regression/fixtures/sql_static_bandit/` (`bad_fstring_sql.py`, `bad_concat_sql.py`, `nosec_allowed_sql.py`, `parameterised_sql.py`). Four self-tests assert: (a) the f-string fixture produces exactly one B608 finding; (b) the concat fixture produces exactly one B608 finding; (c) the `# nosec`-annotated fixture produces zero findings; (d) the parameterised-only fixture produces zero findings.
5. **README housekeeping** — refine the ownership-table row at `tests/test_non_regression/README.md:22` from the placeholder *"Bandit SQL-injection static analysis"* to the verbose description naming the scope (keys/ tree), the scoped test id (`B608`), the severity gate (MEDIUM-or-higher), and the `# nosec B608: <reason>` contract. Append a short addendum to the `Scan allowlist convention` section clarifying 4.5g's use of bandit's native `# nosec` mechanism (orthogonal to 4.5c/4.5f's `# scan-allow:` token).

### 1. Add bandit to the dev dependencies

**Edit `pyproject.toml`** — append a new `security` subgroup and include it from `dev`:

```toml
[dependency-groups]
dev = [
    { include-group = "lint" },
    { include-group = "test" },
    { include-group = "type-check" },
    { include-group = "security" },
]
lint = ["ruff>=0.9", "pre-commit>=4.0"]
test = ["pytest>=8.3", "pytest-asyncio>=0.25", "httpx>=0.28", "coverage>=7.6"]
type-check = [
    "mypy>=1.14",
    "types-pyyaml>=6.0.12.20260408",
]
security = ["bandit>=1.8"]
```

Pin rationale:
- `bandit>=1.8` — the 1.8 line is the first to stabilise the `--severity-level` / `--confidence-level` pair under their current long-form names (older versions still work but emit a deprecation notice; avoiding those notices keeps CI log noise low).
- `bandit` (not `bandit[toml]`) — the `[toml]` extra pulls `toml` for pre-3.11 support; on Python 3.12 the stdlib `tomllib` covers bandit's config needs, so the extra is unnecessary. Bandit does its own TOML parsing for `pyproject.toml`-based configs, which we do not use here.

Regenerate `uv.lock`:

```bash
uv lock
```

The lockfile gains bandit + its transitive deps (`pyyaml` — already present; `rich` — already present via typer/pydantic transitively; `stevedore` — new, small). Reviewer should skim the `uv.lock` diff to confirm no surprises.

### 2. Annotate the four legitimate B608 sites in `src/comadre/keys/db.py`

**Four inline annotations, each carrying a reviewer-enforced reason:**

Line 548 (inside `update_customer`, UPDATE customer SET with column-allowlist):

```python
sql = (
    f"UPDATE customer SET {', '.join(set_parts)} "  # nosec B608: set_parts is a hardcoded column-allowlist ("email = ?", "name = ?", ...); only ? placeholders bind values
    "WHERE id = ? AND deleted_at IS NULL"
)
conn.execute(sql, params)
```

Line 814 (inside `list_api_keys`, SELECT with predicate-allowlist):

```python
sql = (
    "SELECT k.id, k.customer_id, c.name AS customer_name, "
    "k.key_prefix, k.status, k.billing_mode, k.rate_limit_rpm, "
    "k.price_monthly, k.paid_until, k.created_at, k.last_used_at, k.notes "
    "FROM api_key AS k JOIN customer AS c ON c.id = k.customer_id "
    f"{where_clause} "  # nosec B608: where_clause is assembled from a hardcoded predicate-allowlist ("k.status = ?", "k.billing_mode = ?", ...); every value binds via ?
    "ORDER BY k.created_at ASC"
)
cursor = conn.execute(sql, params)
```

Line 1064 (inside `get_audit_events_for_targets`, IN (…) with programmatic placeholders):

```python
placeholders = ",".join("?" * len(target_ids))
sql = (
    "SELECT id, occurred_at, actor, action, target_type, target_id, "
    "details_json FROM audit_log "
    f"WHERE target_id IN ({placeholders}) "  # nosec B608: placeholders is ",".join("?" * n) — only ? tokens; operator input binds via positional ? params
    "ORDER BY occurred_at DESC, id DESC LIMIT ?"
)
cursor = conn.execute(sql, (*target_ids, limit))
```

Line 1268 (inside `update_api_key`, UPDATE api_key SET with column-allowlist):

```python
sql = (
    f"UPDATE api_key SET {', '.join(set_parts)} "  # nosec B608: set_parts is a hardcoded column-allowlist ("rate_limit_rpm = ?", "notes = ?", ...); only ? placeholders bind values
    "WHERE id = ? AND status != 'revoked'"
)
conn.execute(sql, params)
```

**Reason-vocabulary rules (reviewer-enforced at PR time):**
- Must name WHICH collection is spliced (`set_parts`, `where_clause`, `placeholders`).
- Must name the nature of that collection (*hardcoded column-allowlist*, *programmatic ? tokens*).
- Must assert that VALUES bind via `?` placeholders.
- An empty, one-word, or vague reason (`# nosec B608: safe`) is a review-blocker — functionally equivalent to the 4.5c/4.5f `# scan-allow:` reason contract.

**Why line-range or `# nosec` without test-id is rejected:** `# nosec` without an explicit test-id suppresses ALL bandit findings on that line, not just B608. Suppressing only B608 (`# nosec B608`) narrows the escape hatch to the specific risk class the reviewer has vouched for; a future B201 or B301 finding on the same line would still fire. Mirrors ruff's `# noqa: F401` vs bare `# noqa` discipline.

**Why `# nosec` comments go on the f-string line specifically (not the final `conn.execute(sql, …)`):** bandit attaches the B608 finding to the f-string construction site (`line_number` points at the `f"…"` line), not at the execute call. A `# nosec` on the execute line is invisible to bandit for B608. Empirically verified at story-draft time via the dry-run above — all four finding `line_number` values match the `sql = (` continuation line where the f-string fragment lives.

### 3. `_run_bandit` + the primary regression assertion

**New module: `tests/test_non_regression/test_sql_static_bandit.py`**

**The scan's contract:**

- Scope: `src/comadre/keys/` (explicitly, NOT `src/comadre/` — the epic AC scopes this way, AND `rg "conn.execute" src/comadre/ -l` confirms zero `execute` calls outside `keys/` at story-draft time).
- Tests: `-t B608` (scoped to `hardcoded_sql_expressions`; all other bandit plugins explicitly deferred — see §Deferred work).
- Severity gate: MEDIUM-or-higher via `-l` (`-l` alone maps to MEDIUM). The epic AC's *"HIGH-severity finding"* wording is empirically wrong for B608 (max is MEDIUM); 4.5g adopts the MEDIUM gate with explicit rationale in the module docstring.
- Confidence gate: LOW-or-higher (bandit default; no `-i`/`--confidence-level` override). Justification: the controlled-input false positives are annotated via `# nosec B608`, so the gate need not rely on confidence filtering. Lowering the confidence gate would be a silent "tolerate uncertain findings" posture — the wrong default for a security gate.
- Output: `-f json -q` (machine-readable, quiet suppresses bandit's stdout banner; `-q` keeps the JSON on stdout clean for json.loads).
- Exit-code semantics: bandit exits 0 on zero findings, 1 on findings, 2 on usage error. The test does not rely on exit code; it parses `stdout` directly and asserts the `results` list is empty. This makes the failure diagnostic immediately actionable (the test names the finding's file/line/source/confidence) without having to shell out a second time to re-render the findings.

**Graceful-skip contract:** if bandit is not installed, the test module calls `pytest.skip(...)` rather than failing. Justification: a developer running `uv run pytest -m non_regression` without having `uv sync`'d the `security` dep group would see a confusing failure otherwise. CI always has bandit (because `uv sync` installs all dependency groups by default), so this skip is invisible to the gate in practice. Mirrors 4.5d's "skip if docker unavailable" and 4.5e's "skip if slowapi unavailable" discipline.

**Skeleton:**

```python
"""SQL-injection non-regression — bandit B608 static check (Story 4.5g).

Subprocess-invokes ``bandit -r src/comadre/keys/ -t B608 -l -f json -q``
and asserts the ``results`` list is empty. Scoped to the bandit
``hardcoded_sql_expressions`` (B608) plugin specifically — other bandit
plugins (B101 assert_used, B404 subprocess-module-use, etc.) are
explicitly deferred to future stories; 4.5g's charter is SQL-injection
prevention, not full bandit coverage.

Severity gate: MEDIUM-or-higher via ``-l``. This calibrates the epic AC's
"HIGH-severity finding" wording to bandit's actual behaviour — B608's max
severity is MEDIUM; a HIGH-only gate would catch zero SQL-injection
regressions. See the story spec's "Empirical premise" section for the
dry-run receipts.

The four currently-legitimate B608 sites under ``src/comadre/keys/db.py``
(column-allowlist f-string splicing in UPDATE/SELECT/IN-clause construction)
carry inline ``# nosec B608: <reason>`` comments — bandit's native escape
hatch. Each reason is reviewer-enforced per the story spec's reason
vocabulary rules (names the controlled collection + its allowlist
contract + the ? binding of values).

The scan's complement is positive: every new SQL query must use
``conn.execute("… WHERE x = ?", (value,))`` parameterised bindings for
VALUES; column/identifier splicing remains permitted only when annotated
with a ``# nosec B608: <reason>`` that passes reviewer judgement at PR
time.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

_PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
_SRC_KEYS_ROOT: Path = _PROJECT_ROOT / "src" / "comadre" / "keys"
_FIXTURES_ROOT: Path = (
    Path(__file__).resolve().parent / "fixtures" / "sql_static_bandit"
)

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
        except ValueError:  # fixture files live outside _PROJECT_ROOT? no, safety net.
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


def _run_bandit(paths: list[Path]) -> list[_Finding]:
    """Subprocess-invoke bandit on ``paths`` and return B608 findings.

    Raises ``pytest.skip.Exception`` if bandit is not on ``$PATH`` — keeps
    developer laptops honest when they run ``pytest -m non_regression``
    without having ``uv sync``'d the ``security`` dependency group.
    """
    if shutil.which("bandit") is None:
        pytest.skip(
            "bandit not available on $PATH; run `uv sync` to install the "
            "security dependency group."
        )

    cmd = [
        "bandit",
        "-r",
        *[str(p) for p in paths],
        "-t",
        _BANDIT_TEST_ID,
        "-l",
        "-f",
        "json",
        "-q",
    ]
    completed = subprocess.run(
        cmd,
        cwd=_PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
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

    findings: list[_Finding] = []
    for result in payload.get("results", []):
        if result.get("test_id") != _BANDIT_TEST_ID:
            continue  # defensive — -t B608 should already filter, but belt-and-braces
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
    return findings


@pytest.mark.non_regression
def test_src_comadre_keys_has_no_b608_findings() -> None:
    """Non-regression: bandit B608 (hardcoded_sql_expressions) reports zero
    findings against ``src/comadre/keys/``.

    Controlled-input column/identifier f-string splicing sites are
    annotated ``# nosec B608: <reason>`` (reviewer-enforced). A new raw
    f-string / %% / + SQL construction lands this assertion red with the
    file, line, snippet, severity, and confidence named in the failure
    message.
    """
    findings = _run_bandit([_SRC_KEYS_ROOT])
    assert not findings, (
        "bandit B608 (hardcoded_sql_expressions) reported findings in "
        "src/comadre/keys/.\n"
        "This regression breaks the PRD Non-Regression Contract row "
        "'parameterized queries exclusively' (PRD §Technical Constraints "
        "line 192, §Continuity with Existing Hardening line 703). Use a "
        "parameterised query with ? placeholders instead:\n"
        "  - conn.execute(\"SELECT … WHERE x = ?\", (value,))\n"
        "  - conn.execute(\"UPDATE t SET col = ? WHERE id = ?\", (val, id))\n"
        "If the f-string SPLICES ONLY controlled column names or "
        "programmatically-derived ? tokens (not operator input), and "
        "every VALUE binds via a ? placeholder, annotate with a trailing "
        "comment naming the controlled-input contract:\n"
        "    # nosec B608: <which collection, why it's safe>\n"
        "Example: `# nosec B608: set_parts is a hardcoded column-allowlist "
        "(\"email = ?\", \"name = ?\", …); only ? placeholders bind values`.\n\n"
        "Findings:\n  " + "\n  ".join(f.render() for f in findings)
    )
```

### 4. Fixture files and self-tests

**New subdirectory: `tests/test_non_regression/fixtures/sql_static_bandit/`** (sibling to `timing_safe_compare/` from 4.5c and `no_raw_httpexception/` from 4.5f).

#### `bad_fstring_sql.py` — the scan MUST flag

```python
"""Fixture — intentional SQL-injection regression (f-string interpolation).

Consumed by ``test_scan_flags_bad_fstring``. A raw f-string
``conn.execute(f"… WHERE id = {x}")`` is the canonical B608 pattern the
scan must catch — operator input inside the SQL text instead of behind a
? placeholder. Not imported at runtime; not part of the production
codebase.
"""

from __future__ import annotations

import sqlite3


def fetch(conn: sqlite3.Connection, x: int) -> list[tuple[object, ...]]:
    # Intentional regression — the scan MUST flag this line.
    return list(conn.execute(f"SELECT * FROM t WHERE id = {x}"))
```

**Expected:** exactly one B608 finding on the `conn.execute(f"…")` line.

#### `bad_concat_sql.py` — the scan MUST flag

```python
"""Fixture — intentional SQL-injection regression (%-formatting / concat).

Consumed by ``test_scan_flags_bad_concat``. ``"… '" + str(x) + "'"`` and
``"… %s" % x`` both belong to the same risk class as the f-string form —
operator input substituted into the SQL TEXT. Bandit's B608 flags all
three shapes uniformly. This fixture uses the %-formatting variant to
pin that the scan doesn't only catch f-strings.
"""

from __future__ import annotations

import sqlite3


def fetch(conn: sqlite3.Connection, x: int) -> list[tuple[object, ...]]:
    # Intentional regression — the scan MUST flag this line.
    return list(conn.execute("SELECT * FROM t WHERE id = %s" % x))  # noqa: UP031
```

**Expected:** exactly one B608 finding on the `conn.execute("…" % x)` line. The `# noqa: UP031` silences ruff's `pyupgrade` rule (`printf-style-format`) — ruff would otherwise block the fixture at pre-commit by suggesting the f-string rewrite that defeats the fixture's purpose.

#### `nosec_allowed_sql.py` — the scan MUST NOT flag

```python
"""Fixture — an intentional B608 site SUPPRESSED via ``# nosec B608``.

Consumed by ``test_scan_respects_nosec``. Demonstrates bandit's native
escape hatch for reviewer-approved exceptions: the f-string SPLICES ONLY
a hardcoded column-allowlist fragment (``set_parts`` — mimics the real
pattern at ``src/comadre/keys/db.py:548``), and VALUES bind via the
positional ? params. A ``# nosec B608: <reason>`` trailing comment
suppresses the finding. Scan returns zero findings for this file.
"""

from __future__ import annotations

import sqlite3


def update(conn: sqlite3.Connection, email: str, customer_id: str) -> None:
    # ``set_parts`` is a hardcoded column-allowlist — identical to the
    # production pattern in src/comadre/keys/db.py. VALUES bind via ?.
    set_parts = ["email = ?"]
    params: list[object] = [email, customer_id]
    sql = (
        f"UPDATE customer SET {', '.join(set_parts)} "  # nosec B608: fixture mirrors the production column-allowlist pattern; only ? placeholders bind values
        "WHERE id = ?"
    )
    conn.execute(sql, params)
```

**Expected:** zero findings.

#### `parameterised_sql.py` — the scan MUST NOT flag

```python
"""Fixture — the canonical safe pattern (pure parameterised queries).

Consumed by ``test_scan_ignores_parameterised_sql``. Positional ? bindings
for every value; no f-string, no %-formatting, no concat. Bandit B608
does not fire on this shape. Pins the scan's negative contract.
"""

from __future__ import annotations

import sqlite3


def fetch(conn: sqlite3.Connection, x: int) -> list[tuple[object, ...]]:
    return list(conn.execute("SELECT * FROM t WHERE id = ?", (x,)))


def update(conn: sqlite3.Connection, new_email: str, customer_id: str) -> None:
    conn.execute(
        "UPDATE customer SET email = ? WHERE id = ?",
        (new_email, customer_id),
    )
```

**Expected:** zero findings.

**Self-test block inside `test_sql_static_bandit.py`:**

```python
@pytest.mark.non_regression
def test_scan_flags_bad_fstring() -> None:
    """Self-test: f-string SQL interpolation is flagged by B608."""
    findings = _run_bandit([_FIXTURES_ROOT / "bad_fstring_sql.py"])
    assert len(findings) == 1, (
        f"Expected exactly one B608 finding in bad_fstring_sql.py; got "
        f"{len(findings)}: {[f.render() for f in findings]}"
    )
    assert findings[0].test_id == "B608"
    assert "f\"SELECT" in findings[0].code or 'f"SELECT' in findings[0].code, (
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
    """Self-test: ``# nosec B608: <reason>`` suppresses the finding."""
    findings = _run_bandit([_FIXTURES_ROOT / "nosec_allowed_sql.py"])
    assert findings == [], (
        f"Expected zero B608 findings in nosec_allowed_sql.py (the one "
        f"f-string site carries an inline # nosec B608: comment); got "
        f"{[f.render() for f in findings]}"
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
```

**Why four self-tests instead of parametrising:** each pins a distinct property — (a) f-string shape is flagged; (b) `%`/concat shape is flagged (same B608 rule covers both, but future bandit tuning could split them); (c) `# nosec` suppresses; (d) parameterised baseline returns clean. Splitting keeps failure messages property-specific. Mirrors the 4.5c/4.5f precedent.

**Why run bandit separately on each fixture instead of one multi-path subprocess:** clarity. Each self-test's `_run_bandit([single_file])` returns ONLY that fixture's findings — no cross-contamination. The subprocess overhead is ~300 ms per invocation; four fixture-level tests + one primary = ~5 invocations = ~1.5 s added to the `non-regression` job. Acceptable cost for crisp per-property failure diagnostics.

**Why `bad_concat_sql.py` carries `# noqa: UP031`:** ruff's `UP031` (`printf-string-formatting`) would otherwise demand the fixture be rewritten as an f-string — which would defeat the fixture's point (testing the non-f-string shape). `# noqa: UP031` is ruff-scoped and inert to bandit, analogous to 4.5f's `# noqa: F401` on `bad_import.py`.

**Why line-number pinning is NOT asserted:** same as 4.5c/4.5f — ruff-format reflow can shift fixture line numbers by ±1. The `test_id`, `code`-substring, and count assertions are stable properties of fixture intent.

### 5. README housekeeping

**Edit `tests/test_non_regression/README.md:22`** — the ownership-table row for `test_sql_static_bandit.py`. Replace:

```
| `test_sql_static_bandit.py`  | 4.5g      | Bandit SQL-injection static analysis                        |
```

with:

```
| `test_sql_static_bandit.py`  | 4.5g      | SQL-injection prevention — subprocess-runs ``bandit -r src/comadre/keys/ -t B608 -l -f json -q``, asserts zero B608 (``hardcoded_sql_expressions``) findings at MEDIUM-or-higher severity. Controlled-input column/identifier splicing sites use bandit's native ``# nosec B608: <reviewer-enforced reason>`` escape hatch (orthogonal to 4.5c/4.5f's ``# scan-allow:`` token — see "Scan allowlist convention"). |
```

**Append to the `Scan allowlist convention` section** (after the existing paragraph at line 193-206), one short paragraph clarifying the dual escape-hatch vocabulary:

```markdown
### Bandit allowlist convention (4.5g)

Sub-story 4.5g delegates its scan to `bandit`, which ships its own native
escape hatch: a trailing `# nosec <test-ids>: <reason>` comment on the
offending source line. 4.5g's gate calls `# nosec B608: <reason>`
specifically — the explicit test-id narrows the suppression to the SQL
plugin only (a bare `# nosec` would silence all bandit findings on that
line, which is too broad). The `# nosec` vocabulary is complementary to
the `# scan-allow:` vocabulary 4.5c/4.5f share; the two tokens are
orthogonal and a line could in principle carry both if it tripped
multiple scans simultaneously. Same reviewer-enforced reason-vocabulary
rules apply: the reason must name the controlled-input contract (which
collection is spliced, why it's safe, how values bind).
```

No other README edit. The `Harness choice` section already names 4.5g as a static-scan sub-story ("Static-scan checks skip both harnesses.") — no update needed.

### 6. Housekeeping: no CI YAML change

The existing `non-regression` job in `.github/workflows/ci.yml` runs `uv run pytest -m non_regression tests/test_non_regression/ -v` — it auto-discovers `test_sql_static_bandit.py`. `uv sync` (already the first step of the lint/test/non-regression jobs) installs bandit via the new `security` dependency group. The new fixture files under `tests/test_non_regression/fixtures/sql_static_bandit/` are NOT test modules (no `test_` prefix); pytest's collection rules naturally skip them. Grep invariants (all enforced as ACs):

- `git diff master -- .github/workflows/ci.yml | wc -l` is `0`.
- `git diff master -- tests/conftest.py | wc -l` is `0`.
- `git diff master -- tests/test_non_regression/conftest.py | wc -l` is `0`.
- `git diff master -- deploy/caddy/ | wc -l` is `0`.

Non-zero-diff files (expected):
- `pyproject.toml` — new `security` subgroup + `dev` includes it.
- `uv.lock` — regenerated via `uv lock`.
- `src/comadre/keys/db.py` — four `# nosec B608: <reason>` trailing comments, zero behavioural change.
- `tests/test_non_regression/README.md` — ownership row + new `Bandit allowlist convention` subsection.
- `tests/test_non_regression/test_sql_static_bandit.py` — NEW.
- `tests/test_non_regression/fixtures/sql_static_bandit/*.py` — NEW (4 files).

## Acceptance Criteria

1. **AC1 — `_run_bandit` helper exists and subprocess-invokes bandit.** `tests/test_non_regression/test_sql_static_bandit.py` defines `_run_bandit(paths: list[Path]) -> list[_Finding]` that (a) skips the test via `pytest.skip` when `shutil.which("bandit")` is `None`, (b) runs `bandit -r <paths> -t B608 -l -f json -q` via `subprocess.run(cwd=_PROJECT_ROOT, capture_output=True, text=True, check=False, timeout=60)`, (c) fails the test via `pytest.fail` on a returncode outside `{0, 1}` or on invalid JSON, (d) parses `payload["results"]` into `_Finding(test_id, filename, line_number, severity, confidence, code)` records, (e) defensively filters to `test_id == "B608"` (the `-t` flag should already restrict, but belt-and-braces).

2. **AC2 — Primary assertion: zero B608 findings in `src/comadre/keys/`.** `test_src_comadre_keys_has_no_b608_findings` invokes `_run_bandit([_SRC_KEYS_ROOT])` and asserts the findings list is empty. Failure message enumerates findings as `<relpath>:<lineno>: [B608] severity=<S> confidence=<C> — <snippet>` and names (a) the PRD Non-Regression Contract row being violated, (b) the parameterised-query template to use instead, (c) the `# nosec B608: <reason>` escape hatch with a verbatim example reason.

3. **AC3 — Self-test: f-string fixture produces exactly one B608 finding.** `test_scan_flags_bad_fstring` asserts `_run_bandit([fixtures/sql_static_bandit/bad_fstring_sql.py])` returns exactly one `_Finding` with `test_id == "B608"`. The finding's `code` excerpt contains an `f"SELECT` substring (f-string form evidence).

4. **AC4 — Self-test: `%`/concat fixture produces exactly one B608 finding.** `test_scan_flags_bad_concat` asserts `_run_bandit([fixtures/sql_static_bandit/bad_concat_sql.py])` returns exactly one `_Finding` with `test_id == "B608"`. The fixture carries `# noqa: UP031` to silence ruff's printf-format upgrade rule without affecting bandit.

5. **AC5 — Self-test: `# nosec B608` suppresses the finding.** `test_scan_respects_nosec` asserts `_run_bandit([fixtures/sql_static_bandit/nosec_allowed_sql.py])` returns an empty list. The fixture carries a `# nosec B608: <reason>` comment on the f-string line; the reason text names the `set_parts` column-allowlist contract, mirroring the production pattern at `src/comadre/keys/db.py`.

6. **AC6 — Self-test: parameterised baseline produces zero findings.** `test_scan_ignores_parameterised_sql` asserts `_run_bandit([fixtures/sql_static_bandit/parameterised_sql.py])` returns an empty list. The fixture's two SQL calls (SELECT + UPDATE) use positional `?` bindings exclusively.

7. **AC7 — Bandit scope is `-t B608` specifically.** `_run_bandit` invokes `bandit` with `-t B608` (scoped to `hardcoded_sql_expressions` plugin only). The module docstring explains the scoping rationale (B101 assert-used and other plugins are out of scope for 4.5g's SQL-injection charter; future-story widening tracked in deferred work).

8. **AC8 — Bandit severity gate is `-ll` (MEDIUM-or-higher).** `_run_bandit` invokes `bandit` with `-ll`. Per `bandit --help`: `-l` reports LOW-or-higher, `-ll` MEDIUM-or-higher, `-lll` HIGH-only. The module docstring explicitly calibrates the epic AC's "HIGH-severity" wording to bandit's actual behaviour (B608 maxes at MEDIUM; a HIGH-only gate would catch zero SQL-injection regressions). **Calibration history**: story v0.2 landed with `-l` while documenting the gate as MEDIUM-or-higher — a code/doc drift caught in code review and corrected to `-ll` in v0.3.

9. **AC9 — Bandit output format is `-f json -q`.** `_run_bandit` invokes `bandit` with `-f json -q`. The `-q` suppresses bandit's stdout banner so `json.loads(stdout)` succeeds without leading-text stripping.

10. **AC10 — `non_regression` marker applied to every test.** All five tests in `test_sql_static_bandit.py` (one primary + four self-tests) carry `@pytest.mark.non_regression`. Grep invariant: `rg "@pytest.mark.non_regression" tests/test_non_regression/test_sql_static_bandit.py | wc -l` returns `5`. 4.5a's AC15 (no `@pytest.mark.non_regression` outside `tests/test_non_regression/`) continues to hold.

11. **AC11 — `pyproject.toml` adds `security` dep group; `dev` includes it.** `[dependency-groups.security] = ["bandit>=1.8"]` and `[dependency-groups.dev]` includes `{ include-group = "security" }`. Grep invariant: `rg "bandit" pyproject.toml | wc -l` ≥ 1.

12. **AC12 — `uv.lock` regenerated via `uv lock`.** `git diff master -- uv.lock | wc -l` > 0 after implementation. The lockfile gains bandit and its transitive deps (`pyyaml` + `rich` are already present; `stevedore` is new). Running `uv sync` on a fresh checkout installs bandit without errors.

13. **AC13 — Four `# nosec B608: <reason>` comments in `src/comadre/keys/db.py`.** Lines 548, 814, 1064, 1268 (or their post-format equivalents if ruff-format reflows) each carry `# nosec B608: <reason>`. Each reason (a) names which collection is spliced (`set_parts`, `where_clause`, `placeholders`), (b) names the collection's allowlist nature, (c) asserts values bind via `?`. Grep invariants:
    - `rg "# nosec" src/comadre/keys/db.py | wc -l` → `4`.
    - `rg "# nosec B608" src/comadre/keys/db.py | wc -l` → `4`.
    - `rg "# nosec" src/comadre/ -l` → ONLY `src/comadre/keys/db.py` (no drift to other modules).

14. **AC14 — Annotation-only change to `src/comadre/keys/db.py`.** `git diff master -- src/comadre/keys/db.py` shows ONLY added/modified lines carrying `# nosec B608`. No other line-semantics change (no imports, no function signatures, no SQL text, no control flow). Grep invariant: every `^\+` line in the diff either carries `# nosec B608` OR is context a ruff-format reflow introduced incidentally (document any such reflow in Completion Notes).

15. **AC15 — CI YAML untouched.** `git diff master -- .github/workflows/ci.yml | wc -l` is `0`. The existing `non-regression` job auto-discovers `test_sql_static_bandit.py`; `uv sync` installs bandit via the new `security` dep group.

16. **AC16 — `tests/conftest.py` and `tests/test_non_regression/conftest.py` untouched.** `git diff master -- tests/conftest.py tests/test_non_regression/conftest.py | wc -l` is `0`.

17. **AC17 — Default `pytest` run excludes the new module.** `uv run pytest` (no `-m` flag) does NOT execute the new tests — they are deselected via the existing `addopts = "-m 'not non_regression'"`. The default run's `deselected` count grows by exactly 5 vs the pre-4.5g baseline.

18. **AC18 — Opt-in CI invocation picks up the new module.** `uv run pytest -m non_regression tests/test_non_regression/ -v` collects and runs the five new tests alongside the existing 4.5a/b/c/d/e/f surface; the new module contributes +5 passed (or +5 skipped in the narrow case where bandit is unavailable — the CI environment always has it via `uv sync`). Exact post-4.5g totals captured in the Dev Agent Record.

19. **AC19 — Fixture-directory convention honoured.** Fixtures live under `tests/test_non_regression/fixtures/sql_static_bandit/`, sibling to `fixtures/timing_safe_compare/` (4.5c) and `fixtures/no_raw_httpexception/` (4.5f). No files under `tests/test_non_regression/fixtures/` are at the flat level. The fixture files have no `test_` prefix and no `Test*` class, so pytest's default collection rules skip them (verified: `uv run pytest -m non_regression tests/test_non_regression/ --collect-only 2>&1 | rg "fixtures/sql_static_bandit"` returns empty).

20. **AC20 — README ownership row refined.** `tests/test_non_regression/README.md:22` carries the verbose description per §Scope-5 (names the bandit invocation, the B608 scope, the MEDIUM severity gate, and the `# nosec B608: <reason>` contract). The `Scan allowlist convention` section gains a new `### Bandit allowlist convention (4.5g)` subsection per §Scope-5. Neither the `Harness choice` subsection nor the primary `Scan allowlist convention` paragraph for `# scan-allow:` is modified.

21. **AC21 — Failure-UX verified with probe A (bad f-string SQL).** Temporarily insert a minimal B608-flaggable statement at the bottom of a sacrificial file under `src/comadre/keys/`. Recommended: append to `src/comadre/keys/health.py` (smallest SQL surface) an `if False:` no-op block:
    ```python
    if False:  # scratch for 4.5g failure-UX probe
        import sqlite3 as _sqlite3
        _conn = _sqlite3.connect(":memory:")
        _x = 1
        list(_conn.execute(f"SELECT * FROM t WHERE id = {_x}"))
    ```
    Run `uv run pytest -m non_regression tests/test_non_regression/test_sql_static_bandit.py::test_src_comadre_keys_has_no_b608_findings -v`. Observe ONE finding named in the failure message: `src/comadre/keys/health.py:<N>: [B608] severity=MEDIUM confidence=<C> — …`. Observe the remediation hint names the `?`-placeholder template AND the `# nosec B608: <reason>` escape hatch (with an example reason). Restore via `git checkout -- src/comadre/keys/health.py`. Dev agent logs the observed failure message verbatim in the Dev Agent Record > Debug Log References.

22. **AC22 — Failure-UX verified with probe B (`# nosec` on the probe).** Re-apply the AC21 probe but append `  # nosec B608: probe-for-4.5g-AC22` to the offending line. Re-run the same test. Observe zero findings (scan runs clean). Restore via `git checkout`. Logs the observed success verbatim in the Dev Agent Record. This probe pins the end-to-end `# nosec` contract on real source (not just on fixture files).

23. **AC23 — Full quality-gate suite stays green.** `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src/`, `uv run pytest` (default), `uv run pytest -m non_regression tests/test_non_regression/ -v`, and `uv run pre-commit run --all-files` all exit 0. Pre-commit suite includes bandit-inert hooks (ruff, mypy, yamllint, markdownlint-cli2, shellcheck, hadolint) that ignore the fixture files' intentional-regression content; any hook that DOES fail on the fixtures must be per-file-excluded via pre-commit config — ONLY as a last resort, with a comment explaining why, and logged in Completion Notes.

## Tasks / Subtasks

- [x] **Task 1 — Add bandit to dev dependencies** (AC11, AC12)
  - [x] 1.1 Edit `pyproject.toml`: append `security = ["bandit>=1.8"]` as a new entry under `[dependency-groups]`, and add `{ include-group = "security" }` to the `dev` subgroup's list. Order consistently with the existing `lint`, `test`, `type-check` subgroups.
  - [x] 1.2 Run `uv lock` to regenerate `uv.lock`. Review the lock diff — expect bandit + transitive deps (`pyyaml` already present, `rich` already present; `stevedore` is new, small). If any unexpected large transitive dep appears, pause and record the observation in Completion Notes before proceeding.
  - [x] 1.3 Run `uv sync` to install bandit locally. Verify via `uv run bandit --version` — expect 1.9.x or later.
  - [x] 1.4 Verify `shutil.which("bandit")` resolves inside a `uv run python -c ...` — the bandit script must be reachable via the venv's `bin/` PATH so the subprocess invocation in `_run_bandit` succeeds without an absolute-path workaround.

- [x] **Task 2 — Annotate the four legitimate B608 sites in `src/comadre/keys/db.py`** (AC13, AC14)
  - [x] 2.1 Append `# nosec B608: set_parts is a hardcoded column-allowlist ("email = ?", "name = ?", ...); only ? placeholders bind values` to the f-string line in `update_customer` (current line 548 of db.py — verify the f-string's exact line number before editing; ruff-format may have reflowed since story draft).
  - [x] 2.2 Append `# nosec B608: where_clause is assembled from a hardcoded predicate-allowlist ("k.status = ?", "k.billing_mode = ?", ...); every value binds via ?` to the `f"{where_clause} "` line in `list_api_keys` (current line 818 of db.py).
  - [x] 2.3 Append `# nosec B608: placeholders is ",".join("?" * n) — only ? tokens; operator input binds via positional ? params` to the `f"WHERE target_id IN ({placeholders}) "` line in `get_audit_events_for_targets` (current line 1066 of db.py).
  - [x] 2.4 Append `# nosec B608: set_parts is a hardcoded column-allowlist ("rate_limit_rpm = ?", "notes = ?", ...); only ? placeholders bind values` to the f-string line in `update_api_key` (current line 1268 of db.py).
  - [x] 2.5 Verify the annotations survive ruff-format: `uv run ruff format src/comadre/keys/db.py` must leave the `# nosec` comments on the f-string lines (ruff preserves comments by default). If ruff-format reflows the f-string parenthesised continuation onto a different line, re-attach the `# nosec` to the new f-string physical line and re-run bandit to confirm suppression still fires.
  - [x] 2.6 Dry-run the scan: `uv run bandit -r src/comadre/keys/ -t B608 -l -f json -q | python -c "import json,sys; data=json.load(sys.stdin); print('findings:', len(data['results']))"` → expect `findings: 0`. If the output reports any findings, the `# nosec` line attachment is wrong — re-verify line alignment before proceeding.

- [x] **Task 3 — Scaffold fixtures directory and four fixture files** (AC3, AC4, AC5, AC6, AC19)
  - [x] 3.1 Create `tests/test_non_regression/fixtures/sql_static_bandit/` (no `__init__.py` — fixtures are source samples, not a Python package; mirrors the 4.5c/4.5f convention).
  - [x] 3.2 Create `bad_fstring_sql.py` per §Scope-4. Docstring names the fixture's intent; `conn.execute(f"SELECT * FROM t WHERE id = {x}")` inside a `def fetch(conn, x)`. Verify with `uv run bandit tests/test_non_regression/fixtures/sql_static_bandit/bad_fstring_sql.py -t B608 -l -f json -q` — expect one finding.
  - [x] 3.3 Create `bad_concat_sql.py` per §Scope-4. Uses `"…" % x` (NOT f-string). Trailing `# noqa: UP031` to silence ruff's printf-format upgrade. Verify bandit flags it.
  - [x] 3.4 Create `nosec_allowed_sql.py` per §Scope-4. f-string on `set_parts`-style pattern + trailing `# nosec B608: <reason>` with the verbatim reason text from §Scope-4. Verify bandit returns zero findings on this file.
  - [x] 3.5 Create `parameterised_sql.py` per §Scope-4. Two helpers using `?` placeholder binding exclusively. Verify bandit returns zero findings.
  - [x] 3.6 Run `uv run ruff check tests/test_non_regression/fixtures/sql_static_bandit/` — exits 0. Investigate any ruff warning before moving on (the `# noqa: UP031` on `bad_concat_sql.py` covers printf-format; the other three fixtures should be ruff-clean out of the box).

- [x] **Task 4 — Implement `_run_bandit` + primary regression assertion** (AC1, AC2, AC7, AC8, AC9)
  - [x] 4.1 Create `tests/test_non_regression/test_sql_static_bandit.py` per §Scope-3. Module docstring names the scan scope, severity gate, and epic-AC calibration explicitly.
  - [x] 4.2 Define constants: `_PROJECT_ROOT`, `_SRC_KEYS_ROOT`, `_FIXTURES_ROOT`, `_BANDIT_TEST_ID = "B608"`. Mirror 4.5f's constant-definition style.
  - [x] 4.3 Define `_Finding` dataclass per §Scope-3 (`test_id`, `filename`, `line_number`, `severity`, `confidence`, `code` + `render()` method).
  - [x] 4.4 Define `_run_bandit(paths: list[Path]) -> list[_Finding]` per §Scope-3 (skip-on-missing-bandit, subprocess.run with 60s timeout, JSON parse + defensive test-id filter, pytest.fail on unexpected exit / malformed JSON).
  - [x] 4.5 Define `test_src_comadre_keys_has_no_b608_findings` per §Scope-3. Failure message contains all three AC2 elements: (a) PRD Non-Regression Contract row reference, (b) ?-placeholder template example, (c) `# nosec B608: <reason>` escape hatch with an example reason text.
  - [x] 4.6 Run `uv run pytest tests/test_non_regression/test_sql_static_bandit.py::test_src_comadre_keys_has_no_b608_findings -m non_regression -v` — expect PASSED. If it fails, revisit Task 2.5 — the `# nosec` comments' line attachment is the most likely cause.

- [x] **Task 5 — Add the four self-tests** (AC3, AC4, AC5, AC6, AC10)
  - [x] 5.1 Append `test_scan_flags_bad_fstring` per §Scope-4. Asserts one B608 finding; code excerpt contains f-string SELECT evidence.
  - [x] 5.2 Append `test_scan_flags_bad_concat` per §Scope-4. Asserts one B608 finding.
  - [x] 5.3 Append `test_scan_respects_nosec` per §Scope-4. Asserts `findings == []`.
  - [x] 5.4 Append `test_scan_ignores_parameterised_sql` per §Scope-4. Asserts `findings == []`.
  - [x] 5.5 Verify every test carries `@pytest.mark.non_regression`: `grep -c "@pytest.mark.non_regression" tests/test_non_regression/test_sql_static_bandit.py` returns `5`.

- [x] **Task 6 — Verify marker + deselection + fixture-collection behaviour** (AC17, AC18, AC19)
  - [x] 6.1 `uv run pytest` (default) — capture pre-4.5g `passed` + `deselected` baseline from master BEFORE Tasks 1-5 land. Post-4.5g: `+5 deselected`.
  - [x] 6.2 `uv run pytest -m non_regression tests/test_non_regression/ -v` — capture pre-4.5g `passed` + `skipped` baseline. Post-4.5g: `+5 passed` when bandit is installed (the normal CI and uv-sync'd-dev case).
  - [x] 6.3 `uv run pytest -m non_regression tests/test_non_regression/ --collect-only 2>&1 | rg "fixtures/sql_static_bandit"` — returns empty (fixture files not collected as tests).
  - [x] 6.4 `uv run pytest -m non_regression tests/test_non_regression/fixtures/sql_static_bandit/ -v` — reports "collected 0 items" / "no tests ran."
  - [x] 6.5 Record the exact pre- and post-4.5g counts in Dev Agent Record > Completion Notes.

- [x] **Task 7 — Update README** (AC20)
  - [x] 7.1 Edit `tests/test_non_regression/README.md:22` — replace the placeholder ownership-row description with the verbose 4.5g description per §Scope-5.
  - [x] 7.2 Append a new `### Bandit allowlist convention (4.5g)` subsection inside `## Scan allowlist convention` per §Scope-5. Place it directly after the existing `### Scan allowlist convention` paragraph.
  - [x] 7.3 Verify neither the `Harness choice` section nor the primary `Scan allowlist convention` paragraph (the `# scan-allow:` token description) is modified — 4.5g's new subsection is purely additive.
  - [x] 7.4 Markdown lint covered by Task 9's `pre-commit run --all-files` hook (markdownlint-cli2).

- [x] **Task 8 — Verify invariants** (AC13, AC14, AC15, AC16)
  - [x] 8.1 `rg "# nosec" src/comadre/keys/db.py | wc -l` → `4` (AC13).
  - [x] 8.2 `rg "# nosec B608" src/comadre/keys/db.py | wc -l` → `4` (AC13).
  - [x] 8.3 `rg "# nosec" src/comadre/ -l` — prints exactly `src/comadre/keys/db.py` (no drift — AC13).
  - [x] 8.4 `git diff master -- src/comadre/keys/db.py | rg "^\+" | rg -v "# nosec B608|^\+\+\+"` — returns empty OR contains only incidental ruff-format reflow context (log any such context in Completion Notes — AC14).
  - [x] 8.5 `git diff master -- .github/workflows/ci.yml | wc -l` → `0` (AC15).
  - [x] 8.6 `git diff master -- tests/conftest.py tests/test_non_regression/conftest.py | wc -l` → `0` (AC16).
  - [x] 8.7 `git diff master -- deploy/caddy/ | wc -l` → `0`.
  - [x] 8.8 `git diff master -- src/comadre/` is CONFINED to `src/comadre/keys/db.py` (no collateral damage elsewhere under src/comadre/).

- [x] **Task 9 — Run full quality-gate suite** (AC23)
  - [x] 9.1 `uv run ruff check .` — exits 0.
  - [x] 9.2 `uv run ruff format --check .` — exits 0.
  - [x] 9.3 `uv run mypy src/` — exits 0 (adding `# nosec` comments is a no-op for mypy; they are comments, not annotations).
  - [x] 9.4 `uv run pytest` (default) — exits 0; `deselected` count up by `+5` vs pre-4.5g baseline.
  - [x] 9.5 `uv run pytest -m non_regression tests/test_non_regression/ -v` — exits 0; `passed` count up by `+5` vs pre-4.5g baseline.
  - [x] 9.6 `uv run pre-commit run --all-files` — all hooks `Passed`. If any hook fails on the fixtures' intentional-regression content (most likely candidate: ruff's `B904`, `PLC1901`, or `E501` — low-probability but possible), add the fixture directory or specific file to the hook's exclude list IN `.pre-commit-config.yaml` with an explicit comment, and log the exclusion in Completion Notes.

- [x] **Task 10 — Failure-UX probe A: bad f-string SQL** (AC21)
  - [x] 10.1 Backup `src/comadre/keys/health.py` (`cp src/comadre/keys/health.py src/comadre/keys/health.py.bak`).
  - [x] 10.2 Append an `if False:` no-op block to the bottom of the file per §AC21. Use `if False:` so the block is dead-code-eliminable and leaves no runtime surface (bandit walks the AST regardless of reachability).
  - [x] 10.3 Run `uv run pytest -m non_regression tests/test_non_regression/test_sql_static_bandit.py::test_src_comadre_keys_has_no_b608_findings -v`. Observe ONE finding named in the failure message (`src/comadre/keys/health.py:<N>: [B608] severity=MEDIUM confidence=<C> — …`). Capture the failure message verbatim in Dev Agent Record > Debug Log References.
  - [x] 10.4 Verify the failure message contains all three required remediation-hint elements: (a) PRD Non-Regression Contract row reference, (b) `?`-placeholder template, (c) `# nosec B608: <reason>` example.
  - [x] 10.5 Restore `src/comadre/keys/health.py` via `mv src/comadre/keys/health.py.bak src/comadre/keys/health.py`. Re-run the scan; confirm it passes. `git diff master -- src/comadre/keys/health.py | wc -l` → `0`.

- [x] **Task 11 — Failure-UX probe B: `# nosec` suppresses a real-source violation** (AC22)
  - [x] 11.1 Re-apply the Task 10 probe but append `  # nosec B608: probe-for-4.5g-AC22` to the offending line.
  - [x] 11.2 Re-run the same test. Observe the scan passes with zero findings reported. Capture the success verbatim (`PASSED` line + elapsed time).
  - [x] 11.3 Restore `src/comadre/keys/health.py`. Re-run; confirm it still passes. `git diff master -- src/comadre/keys/health.py | wc -l` → `0`.

- [x] **Task 12 — Change log and status**
  - [x] 12.1 Append a Change Log row to this story file (version `0.2 — dev-story execution`) with date, summary of what landed, and the pre/post-4.5g quality-gate numbers from Task 6.
  - [x] 12.2 Flip story Status `ready-for-dev → in-progress` (on starting implementation) → `review` (on completing Tasks 1-11); update `_bmad-output/implementation-artifacts/sprint-status.yaml` entry `4-5g-ci-sql-injection-static-analysis-bandit` to mirror both transitions and bump `last_updated`.

### Review Findings

_Three-layer adversarial review (Blind Hunter / Edge Case Hunter / Acceptance Auditor) on 2026-04-24. Acceptance audit: 17 MET, 6 MET-with-receipts, 0 NOT MET. All actionable findings below resolved in story v0.3._

- [x] [Review][Decision] **`# nosec B608: <reason>` format produces ~58 stderr WARNINGs/scan against `db.py`.** Verified live with bandit 1.9.4. **Resolved**: switched to two-comment form `# nosec B608  # <reason>` (operator chose option 2). Bandit reads test-ids only until the next `#` boundary, so reason text never reaches the tolerant nosec lexer. Stderr noise dropped 58 → 7 lines per scan. All four `db.py` sites + the `nosec_allowed_sql.py` fixture migrated. README "Bandit allowlist convention (4.5g)" subsection updated to document the two-comment contract.
- [x] [Review][Patch] **`-l` flag means LOW-or-higher, not MEDIUM.** Confirmed via `bandit --help`. **Resolved**: `_run_bandit` cmd switched to `-ll` (MEDIUM-or-higher), module docstring + AC8 + README updated. Production scan still reports 0 findings; functional gate identical for B608 (always MEDIUM) but contract now matches docs. [`tests/test_non_regression/test_sql_static_bandit.py:163`]
- [x] [Review][Patch] **`pytest.skip` on missing bandit fails open in CI.** **Resolved**: invocation switched to `[sys.executable, "-m", "bandit", ...]` (callable whenever the `security` dep group is installed, even when the script shim is missing from `$PATH`); `_bandit_importable()` probes via `python -m bandit --version`; on failure the helper calls `pytest.fail` if `os.getenv("CI")` else `pytest.skip`. [`tests/test_non_regression/test_sql_static_bandit.py:118-141`]
- [x] [Review][Patch] **No isolation from project-level `[tool.bandit]` config.** **Resolved**: new sentinel fixture `tests/test_non_regression/fixtures/sql_static_bandit/bandit_isolation.yaml` (minimal `profiles: {}` map — bandit's empty-config crash on null payloads worked around) passed via `-c <sentinel>` on every invocation. A future `[tool.bandit]` section in `pyproject.toml` cannot silently neuter the gate. [`tests/test_non_regression/fixtures/sql_static_bandit/bandit_isolation.yaml`, `test_sql_static_bandit.py:152-153`]
- [x] [Review][Patch] **Unhandled `subprocess.TimeoutExpired`.** **Resolved**: `subprocess.run(...)` wrapped in `try/except subprocess.TimeoutExpired as exc: pytest.fail(f"bandit exceeded 60s timeout: {exc}")`. [`tests/test_non_regression/test_sql_static_bandit.py:171-180`]
- [x] [Review][Patch] **`text=True` decode crashes on non-UTF8 source bytes under C/POSIX locale.** **Resolved**: replaced `text=True` with explicit `encoding="utf-8", errors="replace"` — UTF-8 force-decode + replacement char fallback for any pathological source bytes in bandit's `code` excerpt. [`tests/test_non_regression/test_sql_static_bandit.py:172-179`]
- [x] [Review][Patch] **JSON schema parse mixes defensive `.get()` with raising `[]` — silent fail-open on top-level rename, raw KeyError on field rename.** **Resolved**: `if "results" not in payload: pytest.fail(...)` guard; `_Finding(...)` constructor wrapped in `try/except (KeyError, TypeError, ValueError) as exc: pytest.fail(...)` with offending result echoed. Future bandit schema drift fails loudly with diagnostic context. [`tests/test_non_regression/test_sql_static_bandit.py:200-225`]
- [x] [Review][Patch] **`_PROJECT_ROOT = parents[2]` silently scans wrong tree if test file is relocated.** **Resolved**: replaced with `_find_project_root()` walk that ascends parents until `pyproject.toml` is found, raising `RuntimeError` if none exists. Test file can move anywhere under the repo without scope drift. [`tests/test_non_regression/test_sql_static_bandit.py:60-72`]
- [x] [Review][Patch] **Self-tests don't pre-check fixture file existence.** **Resolved**: `_run_bandit` early-returns with `pytest.fail("bandit input path(s) missing — fixture renamed or deleted? ...")` when any input path is absent. Renamed/deleted fixtures surface immediately. [`tests/test_non_regression/test_sql_static_bandit.py:143-147`]
- [x] [Review][Defer] **Bandit scope is `src/comadre/keys/` only — future SQL surface elsewhere under `src/comadre/` would go unscanned.** Already in spec's Deferred work ("Widen bandit scope from `src/comadre/keys/` to all of `src/comadre/`"). Zero coverage cost today (no `conn.execute` outside keys/). [`tests/test_non_regression/test_sql_static_bandit.py:79, 230`] — deferred, pre-existing. Logged in `deferred-work.md`.
- [x] [Review][Defer] **`'f"SELECT' in findings[0].code'` self-test is brittle to bandit's context-line formatting.** Loosened to `"SELECT" in code AND "{" in code` (less coupled to bandit's exact quoting/window). Full f-string-literal pinning deferred until a major bandit bump forces re-validation. [`tests/test_non_regression/test_sql_static_bandit.py:251`] — deferred, low-probability infrastructure-bump risk. Logged in `deferred-work.md`.

## Dev Notes

### Design decisions

**Why bandit over a hand-rolled AST scan.** 4.5c and 4.5f already implemented hand-rolled AST scans for their respective checks. For SQL injection, using bandit delivers three wins: (a) bandit's B608 is battle-tested across the Python security community — rewriting it would be strictly worse, with unknown false-positive/negative characteristics; (b) bandit's `# nosec` convention is widely recognised — contributors who encounter a `# nosec B608` comment can research the semantics via bandit's docs without project-specific priming; (c) bandit's JSON output format is stable and machine-readable, sparing us from parsing human-readable scan output. The cost is one external dev-group dependency and a subprocess-per-invocation overhead (~300 ms) — acceptable for CI, invisible to developers who only run the default `pytest` suite.

**Why scope to `-t B608` specifically.** Bandit ships ~60 plugins. Most of them (B101 assert_used, B311 random, B403 import_pickle, etc.) are either unrelated to this story's charter (SQL-injection prevention) or would produce false-positive noise that drowns the signal. The existing `src/comadre/keys/` tree dry-runs with 5× B101 findings (intentional CLI asserts) and 0× of any other plugin. Scoping to `-t B608` makes the gate focused: it fails iff an SQL-injection regression lands. A follow-up story can widen to `-t B608,B101,…` with per-plugin triage.

**Why `-l` (MEDIUM-or-higher) instead of the epic AC's "HIGH-severity".** The epic AC's wording is empirically wrong for bandit's B608 plugin — B608 never emits HIGH severity. Running `bandit … -ll` (HIGH-only gate) against a fixture like `conn.execute(f"SELECT * FROM t WHERE id = {x}")` reports ZERO findings in the HIGH bucket, defeating the gate. The correct calibration is `-l` (MEDIUM-or-higher). We document this calibration in the module docstring and AC8's rationale so a future reader doesn't "fix" the gate back to `-ll` and silently break it.

**Why `-c` config file not used.** Bandit supports a `.bandit` YAML config, an entry in `pyproject.toml` `[tool.bandit]`, or a `bandit.yaml` file. None of them add value for 4.5g's needs — the CLI flags `-t B608 -l -f json -q` express the configuration fully, and externalising them into a config file adds one more file to keep in sync for zero gain. If future stories add bandit complexity (multi-plugin scoping, per-file-tree severity tiers), a `[tool.bandit]` pyproject section becomes worth it.

**Why `# nosec B608: <reason>` rather than a config-file skip list.** Three options for suppressing the four legitimate B608 sites in `db.py`:
1. **`# nosec B608: <reason>` inline comments** — bandit's native, per-line escape hatch. Reviewer-enforceable at PR time. Keeps the annotation at the risk site rather than in a separate file. **Chosen.**
2. **`[tool.bandit]` skip list in `pyproject.toml`** — would require `pyproject.toml` to carry four `src/comadre/keys/db.py:548` / `…:814` / `…:1064` / `…:1268` entries. Line numbers drift under ruff-format reflow; the skip list becomes stale silently. Rejected.
3. **`# noqa`-style project-specific token** — reinventing `# scan-allow:` for bandit. Would require a wrapper that post-filters bandit's JSON by cross-referencing an allowlist-token scan over source lines. Strictly more complex than (1) for zero gain. Rejected.

**Why four fixtures, not three or five.** The four-property partition (f-string flagged, `%`/concat flagged, `# nosec` suppresses, parameterised baseline clean) mirrors 4.5f's four-property partition. A three-fixture shape would collapse two positive cases (f-string + concat) into one; a five-fixture shape would add a "multi-pattern-in-one-file" case that doesn't pin a distinct property (bandit handles per-file independently, so cross-pattern behaviour is already pinned by running each fixture separately).

**Why `conn.execute(...)` (not `cursor.execute(...)`) in the fixtures.** The production code in `src/comadre/keys/db.py` uses `conn.execute(...)` throughout — direct connection method, sqlite3's shorthand for `conn.cursor().execute(...)`. The fixtures mirror the production shape so the scan's false-positive tolerance (or lack thereof) is tested against the actual idiom the codebase uses.

**Why use `subprocess.run` instead of `bandit.core.manager.BanditManager`.** Bandit exposes a Python API but it's semi-private (`bandit.core.*`), its signature has shifted between 1.7 and 1.9, and calling it in-process forces the test to pin specific bandit internals. Subprocess is stable, versionable, observable, and produces the same JSON output the CI-facing mental model expects. Subprocess overhead (~300 ms per invocation) is acceptable for an opt-in CI gate.

**Why `-q` (quiet).** Without `-q`, bandit prepends a `[main] INFO profile include tests: B608` banner + `Run started: <timestamp>` lines to stdout BEFORE the JSON. `json.loads(stdout)` would then raise `JSONDecodeError` because the prefix isn't valid JSON. `-q` suppresses the banner, leaving clean JSON on stdout.

**Why `-r` (recursive) even when the scope is a single directory.** `src/comadre/keys/` has subdirectories (`cli/`, `cli/commands/`, `migrations/`). Without `-r`, bandit scans only files at the top level and misses `cli/commands/*.py`. The `-r` flag is free insurance against scope drift.

**Why `timeout=60` on the subprocess call.** Bandit completes in <5 s on the current keys/ tree. 60 s is 12× headroom — enough for worst-case CI runner contention without being so large a genuine hang goes undetected. If bandit ever times out, the test fails loudly with a clear error message rather than hanging the CI job until the job-level timeout fires.

**Why the architecture line 509 predicted `.github/workflows/ci.yml [MOD]` but 4.5g leaves ci.yml untouched.** The architecture line was written before the 4.5a-4.5g decomposition crystallised. 4.5a's extension contract (READ by this story) explicitly instructs sub-stories NOT to modify ci.yml — the `non-regression` job already auto-discovers every test in `tests/test_non_regression/`. 4.5g honours the architecture's **intent** (bandit runs in CI on every PR) while implementing it via the extension contract (pytest wrapper, no ci.yml touch). Both shapes satisfy the architecture's wording; the extension-contract shape is mechanically simpler and consistent with 4.5a-4.5f. Log this decision in Completion Notes.

**Why NOT add bandit to `.pre-commit-config.yaml`.** Two options: (a) bandit only in CI (current proposal), (b) bandit in both CI and pre-commit. Option (b) gives developer-laptop feedback at `git commit` time but adds ~200 ms to every commit invocation (acceptable) and a route to `--no-verify` bypass (unacceptable for a security gate — the gate must be unskippable at PR-merge time, which only the CI approach guarantees). If future UX research shows developers want local-loop feedback, a pre-commit hook can be added additively without rewriting 4.5g.

**Why scope to `src/comadre/keys/` rather than `src/comadre/`.** Two reasons: (a) `rg "conn.execute" src/comadre/ -l` returns only files under `src/comadre/keys/` at story-draft time — no SQL surface exists elsewhere in the codebase; (b) the epic AC explicitly scopes to `src/comadre/keys/`. Widening to `src/comadre/` would add zero coverage today (no files to scan would produce findings) and create an ambiguity on story completion if a future non-keys module adds SQL surface. If that future day comes, a follow-up story can widen the scope deliberately.

**Why no pre-commit stale-allowlist sweep.** A housekeeping scan could count `# nosec` annotations per file and flag files that grow unexpectedly (early warning for scan-policy drift). Zero entries exist pre-4.5g; four enter via Task 2; no growth beyond four is expected for the foreseeable future. Listed in Deferred work.

### Import-graph placement

- **`tests/test_non_regression/test_sql_static_bandit.py` (NEW).** Imports: stdlib (`json`, `shutil`, `subprocess`, `dataclasses.dataclass`, `pathlib.Path`), `pytest`. No `comadre.*` imports — bandit runs as a subprocess against source paths.
- **`tests/test_non_regression/fixtures/sql_static_bandit/*.py` (NEW).** Imports: `sqlite3` (stdlib). No `comadre.*`, no `fastapi`, no non-stdlib deps. Fixtures are standalone source samples.
- **`tests/test_non_regression/README.md` (MOD).** Prose-only edits.
- **`src/comadre/keys/db.py` (MOD).** Four `# nosec B608:` comments. Zero Python-semantics change.
- **`pyproject.toml` (MOD).** One new `[dependency-groups.security]` entry + `dev` includes it.
- **`uv.lock` (MOD).** Regenerated by `uv lock`.
- **`tests/conftest.py` — unchanged.** `non_regression` marker registration already correct.
- **`tests/test_non_regression/conftest.py` — unchanged.** No docker/ASGI fixtures consumed.
- **`.github/workflows/ci.yml` — unchanged.** The `non-regression` job already discovers any test under `tests/test_non_regression/`.
- **`src/comadre/` outside `src/comadre/keys/db.py` — unchanged.** AC13 invariant.
- **`deploy/caddy/` — unchanged.** N/A for a static scan.

### Test-flake avoidance

- **Deterministic bandit output.** `-f json -q` produces stable machine-readable output. The `test_id`, `filename`, `line_number`, `issue_severity`, `issue_confidence`, `code` fields are stable bandit public API since 1.0.
- **Deterministic subprocess invocation.** `cwd=_PROJECT_ROOT` fixes the working directory — bandit's file paths then resolve relative to the project root, making `render()` output stable across developer machines and CI runners.
- **No `tmp_path` or `tmp_path_factory`.** Fixture files live under the test module's `fixtures/sql_static_bandit/` directory at a stable absolute path derived from `Path(__file__).resolve().parent`.
- **No shared mutable state across tests.** Each `_run_bandit` call spawns a fresh subprocess; no persistent state carries between tests.
- **Graceful skip on bandit-absent environment.** `shutil.which("bandit")` is the canonical Python test-skip predicate; works uniformly on Linux/macOS/Windows. A developer running `pytest -m non_regression` without `uv sync` gets a clean skip rather than a subprocess NameError.
- **Subprocess timeout.** `timeout=60` catches a hung bandit before the CI job's global timeout triggers, producing a clean test-level error.
- **JSON parse guard.** `json.JSONDecodeError` → `pytest.fail` with verbatim stdout/stderr dump — if bandit's output format ever changes (extremely unlikely), the test fails loudly with maximum diagnostic.
- **Defensive test-id filter.** The `-t B608` CLI flag should already restrict bandit's `results` list to B608-only — BUT the helper still filters by `test_id == "B608"` as belt-and-braces. If a future bandit version changes `-t` semantics subtly, the test continues to gate on the intended rule.
- **Subprocess isolation from `PYTHONPATH`.** The subprocess inherits the test's environment, including `PYTHONPATH` and `VIRTUAL_ENV`. bandit treats source files as text, not Python imports; there's no module-resolution dependency. The fixture files include `from __future__ import annotations` as a stylistic consistency — bandit parses annotation-only code without evaluation.
- **ruff-format stability.** The `# nosec B608` comments land on physical lines matching the f-string location. ruff-format preserves trailing comments on f-string lines (verified via dry-run at story-draft time). If a future ruff-format major version changes that contract, dev-story Task 2.5 catches the drift immediately.

### Project Structure Notes

- **Alignment with unified project structure.**
  - Test module naming: `tests/test_non_regression/test_sql_static_bandit.py` — matches the ownership table row in `tests/test_non_regression/README.md` (row 22).
  - Fixture directory: `tests/test_non_regression/fixtures/sql_static_bandit/` — sibling to `fixtures/timing_safe_compare/` (4.5c) and `fixtures/no_raw_httpexception/` (4.5f). Convention per 4.5c: each static-scan sub-story owns one subdirectory named after its scan identifier.
  - Helper naming: `_run_bandit`, `_Finding` (snake_case for functions, PascalCase for the dataclass, leading-underscore for module-privates). Matches 4.5c/4.5f conventions.
  - Escape-hatch vocabulary: `# nosec B608: <reason>` — bandit's native token. Deliberately orthogonal to 4.5c/4.5f's `# scan-allow:`; the two systems are complementary, not competing. README addendum documents the distinction.

- **Detected conflicts or variances (with rationale).**
  - **First sub-story that modifies `src/comadre/` for scan-annotation purposes.** 4.5c and 4.5f delivered pure test-side changes (no src/comadre/ diff). 4.5g adds four `# nosec B608` comments to `src/comadre/keys/db.py`. Justification: the comments are annotation-only (zero runtime behaviour change); bandit's native escape hatch is in-source by design; suppressing via a separate config file would externalise annotation from risk site — strictly worse. Reviewer inspects the four nosec reasons for vocabulary compliance.
  - **First sub-story that modifies `pyproject.toml` + `uv.lock`.** 4.5c and 4.5f were pure-stdlib. 4.5g needs bandit as a dev dependency. Justification: delegating to a community-maintained tool beats hand-rolling. The `security` dependency subgroup keeps bandit out of runtime install surface.
  - **First sub-story whose gate depends on a subprocess tool.** 4.5c and 4.5f ran in-process AST/tokenize. 4.5g subprocess-invokes bandit. Justification: bandit is CLI-native; its Python API is unstable; subprocess isolation prevents bandit import-time side effects from polluting test state.
  - **No line-number pinning on any self-test.** Same as 4.5c/4.5f — ruff-format may shift fixture line numbers.
  - **The epic AC's "HIGH-severity" wording is calibrated to "MEDIUM-or-higher" in this story.** Rationale: bandit's B608 max is MEDIUM; a HIGH-only gate would catch zero regressions. Calibration documented in AC8, the module docstring, and Design decisions.

### Testing standards

- **Sync tests, not async.** All five tests are sync `def` — no `async def`, no event loop, no `pytest-asyncio` opt-in.
- **Assertion messages.** Every assertion carries a failure message naming (a) which property broke, (b) expected vs observed state, (c) a diagnostic tail. The primary assertion additionally carries remediation text naming the PRD Non-Regression Contract, the `?`-placeholder pattern, and the `# nosec B608: <reason>` escape hatch.
- **No fixture-level assertions.** `_run_bandit` does NOT raise on findings — it returns a list (possibly empty). Callers assert on the list content.
- **One assertion per failure mode.** Four self-tests, four distinct properties. Parametrising would collapse failure messages.
- **Subprocess timeout + JSON parse guard + exit-code guard.** Three layers of defensive coding for the external-tool boundary. Each fails with a distinct, actionable error message.

### Deferred work to flag at story close

- **Widen bandit scope from `src/comadre/keys/` to all of `src/comadre/`.** Zero-cost today (no `conn.execute` sites outside keys/), but a pre-emptive widening prevents future drift. Trade-off: widening today adds zero coverage (no new findings to triage); leaves the scope flag as a three-character diff for a future story. Candidate for 4.5h or a housekeeping PR.
- **Enable additional bandit plugins (B101 assert_used, B311 random, B403 import_pickle, etc.).** Each plugin needs a triage pass over existing findings. Dry-run at story-draft time shows 5× B101 in `cli/commands/keys.py` (intentional internal-consistency asserts) — widening `-t` to `B608,B101` would immediately red the build until those are triaged. Deliberate deferred work; 4.5g's charter is specifically SQL-injection.
- **Wire bandit into `.pre-commit-config.yaml` for local-loop feedback.** Gives developers pre-`git commit` feedback on SQL-injection regressions rather than waiting for PR CI. Trade-offs: ~200 ms added to every `git commit` (acceptable); `--no-verify` bypass path (unacceptable as the SOLE gate, but acceptable as a *convenience layer* over the CI gate). Deferred as a UX enhancement, not a contract change.
- **Housekeeping scan over `# nosec` comment counts.** Early warning for scan-policy drift — if a file grows from 4 to 40 nosec comments, that's a signal. Candidate for a meta-story alongside 4.5c/4.5f's analogous `# scan-allow:` counter.
- **Consolidate the 4.5g scan helper with future bandit-based scans.** If 4.5h or later adds a second bandit-based gate (e.g., B311 random or B403 import_pickle), consider extracting `_run_bandit` into `tests/test_non_regression/_bandit.py`. Today the single occupant doesn't justify it.
- **Enforce the `# nosec B608: <reason>` reason-vocabulary mechanically.** Today the reason text is reviewer-enforced. A future scan could post-filter bandit's nosec-suppressed lines, count words in each reason, and fail if `< 3` words or lacking a collection name. Tricky to implement robustly; reviewer judgement remains authoritative.
- **Scan broader query-construction shapes.** Bandit B608 catches f-string / %-format / concat inside `execute` and friends, but misses (a) SQL built into a module-level constant then passed to `execute`, (b) SQL built via a helper function returning a dynamic string. Out of scope for bandit's semantics; catching these would need project-specific static analysis (similar shape to 4.5c/4.5f's AST scans). Candidate for a follow-up.

### References

- Epic 4 Story 4.5 umbrella — `_bmad-output/planning-artifacts/epics.md:878-888`
- Epic 4 Story 4.5g — `_bmad-output/planning-artifacts/epics.md:1006-1022`
- PRD §Technical Constraints — `_bmad-output/planning-artifacts/prd.md:192` ("SQL-injection prevention story: parameterized queries exclusively, `bandit` or equivalent static-analysis check")
- PRD §Continuity with Existing Hardening — `_bmad-output/planning-artifacts/prd.md:703` ("all queries use parameterized statements (`?` placeholders, never string interpolation)")
- PRD §Risk Mitigations "SQL injection via CLI input" row — `_bmad-output/planning-artifacts/prd.md:753`
- NFR17 — `_bmad-output/planning-artifacts/prd.md:1221`
- Architecture §Code Review Pre-Flight item 4 — `_bmad-output/planning-artifacts/architecture.md:486` ("Verify all SQL uses parameterized queries — grep for string interpolation in `.py` files touching `conn.execute`")
- Architecture §Project Structure line 509 — `_bmad-output/planning-artifacts/architecture.md:509` (`.github/workflows/ci.yml [MOD] add bandit step, keys test coverage gate`)
- Story 4.5a (predecessor; skeleton + marker + CI job; extension contract) — `_bmad-output/implementation-artifacts/4-5a-ci-security-headers-regression.md`
- Story 4.5b (predecessor; marker broadening; Harness-choice README) — `_bmad-output/implementation-artifacts/4-5b-ci-docs-endpoints-disabled-regression.md`
- Story 4.5c (predecessor; first static-scan; fixture convention) — `_bmad-output/implementation-artifacts/4-5c-ci-timing-safe-key-comparison-static-check.md`
- Story 4.5f (predecessor; second static-scan; four-self-test discipline) — `_bmad-output/implementation-artifacts/4-5f-ci-no-raw-httpexception.md`
- SQL construction sites covered by this story — `src/comadre/keys/db.py:548, 814, 1064, 1268`
- Self-documented SQL invariant — `src/comadre/keys/db.py:1048-1052` ("placeholders are produced programmatically from the sequence length; operator input only lands in positional ``?`` bindings, never in the SQL text")
- Non-regression package README (ownership-table row at line 22; `Scan allowlist convention` at lines 193-206) — `tests/test_non_regression/README.md`
- Non-regression marker registration — `tests/conftest.py:30-33`
- `pyproject.toml` existing dependency-groups structure — `pyproject.toml:[dependency-groups]`
- Bandit B608 plugin documentation — https://bandit.readthedocs.io/en/latest/plugins/b608_hardcoded_sql_expressions.html
- Bandit `# nosec` documentation — https://bandit.readthedocs.io/en/latest/config.html#suppressing-individual-lines
- Empirical dry-run at story-draft time — `uv run --with bandit bandit -r src/comadre/keys/ --format json` reports 4× B608 / 5× B101 on 2026-04-24 (see Scope note)
- Bandit version compatible with Python 3.12 — 1.8+ (1.9.4 verified via `uv run --with bandit bandit --version` on 2026-04-24)

## Dev Agent Record

### Agent Model Used

claude-opus-4-7 (1M context) via Claude Code

### Debug Log References

**Pre-4.5g baselines (captured 2026-04-24 before any code change):**
- `uv run pytest --co -q` → `1414/1502 tests collected (88 deselected)`
- `uv run pytest -m non_regression tests/test_non_regression/` → `72 passed, 16 skipped`
- `uv run --with bandit bandit -r src/comadre/keys/ -t B608 -l -f json -q` → 4 findings at `db.py:548, 814, 1064, 1268` (all MEDIUM/LOW — matches the story-draft Empirical premise exactly).

**Post-4.5g counts:**
- `uv run pytest --co -q` → `1414/1507 tests collected (93 deselected)` — +5 deselected, as AC17 requires.
- `uv run pytest -m non_regression tests/test_non_regression/` → `77 passed, 16 skipped` — +5 passed, as AC18 requires.
- `uv run bandit -r src/comadre/keys/ -t B608 -l -f json -q` → 0 findings (all four legitimate sites now carry `# nosec B608: <reason>`).

**Self-test-per-fixture bandit dry-runs (2026-04-24 after fixture creation):**
- `bad_fstring_sql.py` → 1 finding ✓ (AC3)
- `bad_concat_sql.py` → 1 finding ✓ (AC4)
- `nosec_allowed_sql.py` → 0 findings ✓ (AC5)
- `parameterised_sql.py` → 0 findings ✓ (AC6)

**AC21 — Probe A (bad f-string in `src/comadre/keys/health.py`).** Appended an `if False:` scratch block with `list(_conn.execute(f"SELECT * FROM t WHERE id = {_x}"))`. Ran `uv run pytest tests/test_non_regression/test_sql_static_bandit.py::test_src_comadre_keys_has_no_b608_findings -m non_regression -v`. Observed failure. Verbatim relevant lines:

```
Findings:
  src/comadre/keys/health.py:750: [B608] severity=MEDIUM confidence=MEDIUM — 750     list(_conn.execute(f"SELECT * FROM t WHERE id = {_x}"))
```

The failure message named (a) absolute path `src/comadre/keys/health.py`, (b) line `750`, (c) test id `B608`, (d) severity `MEDIUM` + confidence `MEDIUM`, (e) the offending source snippet, (f) remediation hint naming the PRD Non-Regression Contract row + the `?`-placeholder templates (`SELECT … WHERE x = ?` + `UPDATE … SET col = ?`) + the `# nosec B608: <reason>` escape hatch with a verbatim example reason. All six required UX elements present.

**AC22 — Probe B (`# nosec B608: probe-for-4.5g-AC22` suppresses).** Re-applied the Probe A block plus the trailing `# nosec B608: probe-for-4.5g-AC22` comment on the offending line. Re-ran the same test. Observed:

```
tests/test_non_regression/test_sql_static_bandit.py::test_src_comadre_keys_has_no_b608_findings PASSED [100%]
============================== 1 passed in 0.35s ===============================
```

The `# nosec B608:` escape hatch works end-to-end on real source (not just on fixture files).

**Probe restoration.** `git checkout -- src/comadre/keys/health.py` after each probe. Final `git diff master -- src/comadre/keys/health.py | wc -l` → `0`. Primary test re-run after restore → PASSED.

**Grep invariants verified (Task 8):**
- `rg "# nosec" src/comadre/keys/db.py | wc -l` → `4`
- `rg "# nosec B608" src/comadre/keys/db.py | wc -l` → `4`
- `rg "# nosec" src/comadre/ -l` → only `src/comadre/keys/db.py`
- `git diff master -- src/comadre/keys/db.py | rg "^\+" | rg -v "# nosec B608|^\+\+\+"` → empty (only nosec lines changed; zero semantics delta; ruff-format introduced no reflow)
- `git diff master -- .github/workflows/ci.yml | wc -l` → `0`
- `git diff master -- tests/conftest.py tests/test_non_regression/conftest.py | wc -l` → `0`
- `git diff master -- deploy/caddy/ | wc -l` → `0`
- `git diff master --name-only -- src/comadre/` → only `src/comadre/keys/db.py`

**Full quality-gate suite (Task 9):**
- `uv run ruff check .` → All checks passed
- `uv run ruff format --check .` → 112 files already formatted
- `uv run mypy src/` → Success: no issues found in 35 source files
- `uv run pytest` → 1414 passed, 93 deselected in 55.46s
- `uv run pytest -m non_regression tests/test_non_regression/` → 77 passed, 16 skipped in 6.67s
- `uv run pre-commit run --all-files` → ruff check / ruff format / Lint Dockerfiles / yamllint / shellcheck / markdownlint-cli2 / mypy all Passed. No exclude-list changes required.

### Completion Notes List

- **Dev dependency shape chosen:** `security = ["bandit>=1.8"]` as a new subgroup under `[dependency-groups]`, included from `dev` via `{ include-group = "security" }` — the symmetric option relative to the existing `lint`/`test`/`type-check` subgroups. This is the "idiomatic uv" shape the story spec suggested. `uv lock` resolved 99 packages and added `bandit==1.9.4` + `stevedore==5.7.0` (small; used by bandit's plugin-discovery). No unexpected transitives.
- **Four `# nosec B608:` annotations** landed at the f-string physical lines of each SQL site: `db.py:548` (update_customer), `db.py:818` (list_api_keys — story had cited line 814 as the statement-start, but bandit's B608 line_number came back at the f-string continuation, which is 818 post-format; suppression only takes effect when the nosec is on the f-string line itself), `db.py:1066` (get_audit_events_for_targets — story cited 1064 likewise), `db.py:1268` (update_api_key). Dry-run after annotation → 0 B608 findings. `ruff format` preserved the comments in place. bandit's stderr does emit "Test in comment: <word> is not a test name or id, ignoring" warnings for each word after the `: ` reason separator — cosmetic only, bandit's legacy tolerant parser trying to match each word as an additional test-id; JSON on stdout is clean and `findings == 0` on the production tree. Not worth reshaping the reason format (the story spec mandates `# nosec B608: <reason>` verbatim).
- **Architecture §Project Structure line 509 observation.** The architecture predicted `.github/workflows/ci.yml [MOD] add bandit step, keys test coverage gate`. 4.5g honours the spec's intent (bandit runs in CI on every PR) while implementing it via the existing `non-regression` job per the 4.5a extension contract. `git diff master -- .github/workflows/ci.yml | wc -l` is `0`. The "keys test coverage gate" half of line 509 is explicitly out of scope (deferred).
- **Severity-gate calibration preserved.** The story spec explicitly calibrated the epic AC's "HIGH-severity" wording to "MEDIUM-or-higher via `-l`", and the implementation follows that literally. Probe A confirmed bandit emits `severity=MEDIUM confidence=MEDIUM` for a raw f-string SQL construction — a HIGH-only gate would have silently missed the regression. Module docstring and AC8 both state the calibration rationale so a future reader doesn't "fix" the gate back to `-ll`.
- **`# noqa: S603` on the subprocess call was removed.** Initial draft carried a `# noqa: S603` hint on the `subprocess.run(...)` line (defensive against a future ruff rule-enable), but ruff's `RUF100` flagged it as unused (the `S` category is not in the project's `select`). Removed to keep the linter quiet. If the project ever enables `S` and wants to suppress here, the `# noqa: S603` can be re-added.
- **No pre-commit exclude-list change required.** The three suspicious candidates (`bad_fstring_sql.py`, `bad_concat_sql.py`, `nosec_allowed_sql.py`) pass ruff/mypy/markdownlint-cli2/yamllint/shellcheck on the first try. The `# noqa: UP031` on `bad_concat_sql.py` is the only in-source suppression, covering ruff's `printf-style-format` upgrade rule which would otherwise rewrite the fixture into an f-string and defeat its purpose.
- **Scan determinism.** `_run_bandit` runs with `cwd=_PROJECT_ROOT`, `timeout=60`, `check=False`. Exit codes outside `{0, 1}` → `pytest.fail`. JSON parse failures → `pytest.fail`. A missing bandit binary → `pytest.skip`. All five tests run in ~0.85 s total on a developer laptop (five subprocess invocations of bandit against small input sets).

### File List

- `pyproject.toml` (MOD) — added `security = ["bandit>=1.8"]` subgroup; `dev` now includes `{ include-group = "security" }`.
- `uv.lock` (MOD) — regenerated via `uv lock`; added `bandit==1.9.4` + `stevedore==5.7.0`.
- `src/comadre/keys/db.py` (MOD) — four trailing `# nosec B608: <reason>` annotations at the f-string SQL sites (lines 548, 818, 1066, 1268). Zero behavioural change.
- `tests/test_non_regression/test_sql_static_bandit.py` (NEW) — `_Finding` dataclass + `_run_bandit` subprocess wrapper + one primary regression test (`test_src_comadre_keys_has_no_b608_findings`) + four self-tests (`test_scan_flags_bad_fstring`, `test_scan_flags_bad_concat`, `test_scan_respects_nosec`, `test_scan_ignores_parameterised_sql`). All five carry `@pytest.mark.non_regression`.
- `tests/test_non_regression/fixtures/sql_static_bandit/bad_fstring_sql.py` (NEW)
- `tests/test_non_regression/fixtures/sql_static_bandit/bad_concat_sql.py` (NEW)
- `tests/test_non_regression/fixtures/sql_static_bandit/nosec_allowed_sql.py` (NEW)
- `tests/test_non_regression/fixtures/sql_static_bandit/parameterised_sql.py` (NEW)
- `tests/test_non_regression/README.md` (MOD) — refined ownership-table row for `test_sql_static_bandit.py` per §Scope-5; appended `### Bandit allowlist convention (4.5g)` subsection under `## Scan allowlist convention`.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (MOD) — `4-5g-ci-sql-injection-static-analysis-bandit` flipped `ready-for-dev → in-progress → review`; `last_updated` bumped.
- `_bmad-output/implementation-artifacts/4-5g-ci-sql-injection-static-analysis-bandit.md` (MOD) — Task/Subtask boxes checked; Dev Agent Record populated; Change Log v0.2 row appended; Status flipped to `review`.

## Change Log

| Date       | Version | Change                                                                                                  |
| ---------- | ------- | ------------------------------------------------------------------------------------------------------- |
| 2026-04-24 | 0.3     | Code-review fixes → `done`. Three-layer adversarial review (Blind Hunter / Edge Case Hunter / Acceptance Auditor). Acceptance audit: 17 MET, 6 MET-with-receipts, 0 NOT MET. **Eight code patches + one operator-decided format change applied:** (1) `-l` → `-ll` — bandit's `-l` is LOW-or-higher, not MEDIUM; module docstring/AC8/README all promised MEDIUM via `-l`; gate now matches docs (production scan still 0 findings; B608 always emits MEDIUM so functional gate identical). (2) `[sys.executable, "-m", "bandit", ...]` invocation — callable whenever the `security` dep group is installed, even when the script shim is missing from `$PATH`; `_bandit_importable()` probes via `python -m bandit --version`. (3) `pytest.fail` instead of `pytest.skip` on missing bandit when `os.getenv("CI")` — dropped `security` dep group can no longer fail the gate open in CI; developer-laptop UX preserved via skip-when-not-in-CI. (4) New `bandit_isolation.yaml` sentinel fixture (minimal `profiles: {}` map) passed via `-c` on every invocation — short-circuits bandit's auto-discovery of any future `[tool.bandit]` section in `pyproject.toml`. (5) `subprocess.TimeoutExpired` caught + converted to curated `pytest.fail`. (6) `text=True` → `encoding="utf-8", errors="replace"` — locale-independent UTF-8 decode with replacement-char fallback for pathological source bytes in bandit's `code` excerpt. (7) Defensive JSON schema parse: `if "results" not in payload: pytest.fail(...)` guard + `_Finding(...)` constructor wrapped in `try/except (KeyError, TypeError, ValueError)` with offending result echoed. (8) `_PROJECT_ROOT` discovery via `_find_project_root()` parent walk for `pyproject.toml` (replaces fragile `Path(__file__).parents[2]`). (9) Pre-check fixture file existence in `_run_bandit` — renamed/deleted fixtures surface as actionable `pytest.fail` instead of "expected 1, got 0". **Operator-decided D1 (two-comment nosec form):** all four `db.py` `# nosec B608:` annotations migrated from `# nosec B608: <reason>` to `# nosec B608  # <reason>` (and same for `nosec_allowed_sql.py` fixture). Bandit's tolerant nosec lexer reads test-ids only until the next `#` boundary, so reason text never trips the `[manager] WARNING Test in comment: <word> is not a test name or id, ignoring` stderr noise — measured: 58 → 7 lines per scan against `src/comadre/keys/`. README's `### Bandit allowlist convention (4.5g)` subsection rewritten to document the two-comment contract. AC8 spec text + module docstring updated; v0.2 `-l` history footnoted as the calibration record. **Two findings deferred** (logged in `_bmad-output/implementation-artifacts/deferred-work.md`): (a) widen bandit scope from `src/comadre/keys/` to all of `src/comadre/` — zero coverage cost today (no `conn.execute` outside keys/), already in story Deferred work; (b) `f"SELECT' in code` self-test brittleness — loosened to `"SELECT" in code AND "{" in code` (looser match), full pinning deferred until bandit major bump. **Quality gates re-verified:** ruff check, ruff format --check, mypy, default pytest (1414 passed, 93 deselected — counts unchanged from v0.2), non_regression pytest (77 passed, 16 skipped — unchanged), pre-commit run --all-files all green. |
| 2026-04-24 | 0.2     | Dev-story execution → `review`. All 12 tasks + 72 subtasks complete. `bandit==1.9.4` + `stevedore==5.7.0` added via a new `[dependency-groups.security]` subgroup (included from `dev`); `uv.lock` regenerated. Four `# nosec B608: <reason>` annotations landed at `src/comadre/keys/db.py` lines 548, 818, 1066, 1268 (story cited 814/1064 as statement-start lines but suppression must attach to the f-string physical line itself — 818/1066 post-format; annotation-only diff, zero runtime delta). New `tests/test_non_regression/test_sql_static_bandit.py` with `_Finding` dataclass + `_run_bandit` subprocess wrapper + one primary assertion + four self-tests. Four fixture files under `tests/test_non_regression/fixtures/sql_static_bandit/`. README ownership row refined and new `### Bandit allowlist convention (4.5g)` subsection appended. CI YAML untouched (non-regression job auto-discovers the module). Baselines: default pytest 88→93 deselected (+5); non_regression 72→77 passed (+5). B608 against `src/comadre/keys/`: pre 4, post 0. Full quality-gate suite green (ruff check/format, mypy, default pytest 1414 passed, non_regression 77 passed/16 skipped, pre-commit all hooks Passed). Failure-UX probes A (bad f-string in health.py) and B (`# nosec B608: probe-for-4.5g-AC22` suppresses) verified end-to-end; health.py restored clean. |
| 2026-04-24 | 0.1     | Story spec created → `ready-for-dev`. Seventh and last sub-story in the 4.5 CI non-regression cluster (closes the 4.5a–4.5g umbrella). Scan delegates to `bandit -r src/comadre/keys/ -t B608 -l -f json -q`, parsed via a subprocess wrapper in `tests/test_non_regression/test_sql_static_bandit.py`. Four fixture files under `tests/test_non_regression/fixtures/sql_static_bandit/` pin one scan property each (f-string flagged, `%`/concat flagged, `# nosec B608: <reason>` suppresses, parameterised baseline clean). Four pre-existing legitimate B608 sites in `src/comadre/keys/db.py` (lines 548, 814, 1064, 1268) receive inline `# nosec B608: <reason>` comments with reviewer-enforced reason vocabulary naming the controlled-input collection (`set_parts` / `where_clause` / `placeholders`). `pyproject.toml` gains a `security` dependency subgroup (`bandit>=1.8`) included by `dev`; `uv.lock` regenerates via `uv lock`. CI YAML untouched — the existing `non-regression` job auto-discovers the new test and installs bandit via `uv sync`. Epic AC's "HIGH-severity finding" wording calibrated to "MEDIUM-or-higher via `-l`" (B608 maxes at MEDIUM; HIGH-only gate catches zero regressions — dry-run receipts in Scope note). Empirical baseline verified 2026-04-24: `uv run --with bandit bandit -r src/comadre/keys/ -t B608 --format json` reports 4 findings pre-4.5g (the four legitimate sites), 0 findings post-4.5g. |
