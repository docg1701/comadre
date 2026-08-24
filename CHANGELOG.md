# Changelog

All notable changes to Comadre are tracked here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.1.1] — 2026-08-23

### Changed

- **Siglas read intact by default** — `POCKET_SIGLA_SPACING` now defaults to
  `false`. The 2026-08-23 A/B (same voice, same seed) showed pocket-tts's
  sentencepiece reads intact siglas (`ABS`, `CNPJ`) more naturally than
  letter-spaced ones — spacing was Kokoro-era tuning. Operators with an
  explicit `POCKET_SIGLA_SPACING=true` in `.env` keep the old behavior;
  remove the line or set it to `false` to adopt the new default.

## [3.1.0] — 2026-08-23

### Added

- **MP3 output format** — `response_format: "mp3"` (64 kbps, 24 kHz mono)
  across the API and the landing page; WhatsApp-compatible fallback.
- **Per-request sampling controls** — `temperature` (0.1–2.0; lower = more
  consistent, higher = more expressive) and `seed` (reproducible prosody:
  same text + voice + seed → identical audio) on `/v1/audio/speech`, with
  matching controls in the landing demo's advanced options.

### Fixed

- **WhatsApp silent OGG** — OpusHead input sample rate is now the canonical
  48000 Hz (16 kHz streams attached to WhatsApp played mute).
- **Clipped first phoneme** — 500 ms of lead silence prepended to every
  generated audio (`adelay` in both final encode paths).
- **Download names** — landing saves as `comadre_<voice>_<timestamp>.<ext>`
  and the API Content-Disposition echoes `comadre-<voice>.<fmt>` instead of
  a fixed name.
- **Decimal commas / dot-grouped thousands stalled generation** — `10,50`
  used to expand to glued `dez,cinquenta` and `1.234` to `um.duzentos…`
  (out-of-distribution punctuation for pocket-tts); both now read naturally.
- **pt-BR preprocessing gaps** — `9h30`/`9h` times, short dates `12/05`,
  percent `50%`, the `24/7` idiom, masked phone numbers read digit-by-digit,
  emoji/URL/residual-slash sanitization. Full audit in
  [docs/preprocessing-fix-plan.md](docs/preprocessing-fix-plan.md).

### Removed

- Obsolete v2-era docs: migration feasibility/plan, pentest reports,
  deploy report, stale cost-comparison PDF (history preserved in git).

## [3.0.7] — 2026-08-23

### Fixed

- **Upload-format messaging caught up with reality** — the server never
  restricted reference audio to WAV/MP3: validation is libsndfile-based and
  OGG Vorbis/Opus (the WhatsApp voice-note format) plus FLAC already passed.
  Every surface that claimed "wav/mp3 only" now tells the truth: the
  `VoiceUploadError` hint, README, api-reference, voice-management,
  troubleshooting, the landing-page copy/`accept` filter/error toast, and
  the voice reference script. Regression test pins real OGG-Opus upload
  acceptance end to end so a dependency bump that drops the Opus decoder
  fails CI.

## [3.0.6] — 2026-08-23

### Changed

- **Over-engineering cleanup (repo audit round 2)** — zero behavior change:
  - CLI clock seam consolidated: `resolve_today_in_tz()` moved from the
    single-function `keys/cli/_clock.py` module into `timeutil.py` (already
    the stdlib-only bottom of the import graph); `_clock.py` deleted.
  - `torchao` is now pulled via pocket-tts's own `quantize` extra
    (`pocket-tts[audio,quantize]==2.1.0`) instead of a duplicate direct
    pin — same resolution, one authoritative declaration.
- **New `docs/voice-reference-script.md`** — a pt-BR read-aloud script for
  recording cloning reference audio, engineered for phonetic coverage
  (nasals, strong/tap rhotics, palatals, clusters) and prosody variety,
  with recording checklist and upload instructions.

### Removed

- Stray `usuario-teste.txt` from the repo root (contained a live test API
  key in plaintext; now gitignored so it can never be committed).

## [3.0.5] — 2026-08-23

### Fixed

- **`/health` reported a stale version after release bumps** — v3.0.4
  shipped with `version: "3.0.3"` in `/health` because
  `comadre/__init__.py` carried a hardcoded copy of the version string
  that the pyproject bump missed (dual source of truth).
  `__version__` now derives from installed package metadata
  (`importlib.metadata.version("comadre")`), which `uv sync --frozen`
  generates from `pyproject.toml` at image build — the hardcoded copy
  can no longer drift. Regression test pins metadata == pyproject.

## [3.0.4] — 2026-08-23

### Changed

- **Over-engineering cleanup (repo audit)** — net −870 lines, zero behavior
  change:
  - CLI verbs share one `open_registry()` contextmanager (connection +
    migrations + close, exit 5) instead of 20 hand-copied try/finally blocks.
  - `BillingProvider` ABC collapsed to a plain `is_payment_current()`;
    the never-called `on_key_issued`/`on_key_revoked` no-op hooks are gone
    (add the abstraction when a PSP adapter exists).
  - Dead code removed: module-level `set_active_registry`/
    `available_voices()`/`engine_status()` wrappers in service.py, the
    unused `apply_migrations` public alias, and the voice response models
    (`VoiceListItem`/`VoiceListResponse`/`VoiceCreateResponse`) that no
    route or test referenced.
  - ISO-UTC helpers consolidated into `comadre.timeutil`
    (`utc_now_iso` / `parse_iso_utc`) — was 3 divergent copies of each.
  - `first_charge_date()` drops the accepted-but-unused `tz` parameter.
- **Removed Portuguese duplicate cost report** —
  `docs/relatorio-comparativo-custos.{md,pdf}` duplicated
  `cost-comparison-report.md` verbatim and violated the English-only
  language policy; the migration plan's v2-era annotation list now points
  at the English original only.

## [3.0.3] — 2026-08-23

### Fixed

- **Landing footer tagline must render on a single line** — the previous
  fix moved the wrap point instead of removing it (misread requirement).
  The tagline measures 509px in the page font; `.footer-text` max-width
  raised 320px → 560px so the full sentence renders as one line on
  desktop (the ≤720px mobile layout already uses `max-width: 100%`).

## [3.0.2] — 2026-08-22

### Fixed

- **Landing footer tagline wrapped mid-clause** — the browser broke the
  line after "in-house," (first line measured 318px against the 320px
  cap — 2px of headroom). The split now happens deterministically at the
  em dash (220px / 285px), matching the sentence's semantic boundary.

## [3.0.1] — 2026-08-22

### Added

- **Dynamic project version in the landing page footer** — `/health` now
  includes `version` in the unauthenticated (minimal) envelope, and the
  landing footer renders it (`v3.0.1`) fetched live from the backend —
  no hardcoded version string in the HTML.

### Fixed

- **Customer clones leaked into the public `/health` voice list** —
  `available_voices()` predated v3 persisted clones and listed every
  filesystem entry, so unauthenticated `/health` exposed other callers'
  `pocket/u_<ULID>` clone IDs, and the landing voice picker rendered them
  raw (coded IDs instead of display names). Customer-owned entries are now
  excluded from the public catalog (same ownership predicate as
  `list_for()`/`delete()`); the landing picker merges the caller's own
  voices with their `display_name` labels when an API key is present and
  strips them when the key is removed.
- **Short pt-BR phrases truncated to ~0.5 s** — pocket-tts's EOS detector
  (upstream threshold `-4.0`) fired early on short inputs and the auto tail
  (~3 frames) cut the ending mid-word, in any voice. New
  `POCKET_EOS_THRESHOLD` (default `-2.0`, measured on production VPS:
  "Que voz é essa?" 0.48 s → 0.96–1.36 s full audio, medium/long phrases
  unaffected).
- **Persisted clone references were not real WAV files** — uploads were
  raw-copied with a `.wav` name, so an mp3/webm payload produced a
  non-RIFF file that `pocket_tts.audio_read` cannot open on later state
  regeneration. Uploads are now transcoded to PCM WAV 24 kHz mono via
  ffmpeg before persisting.

### Changed

- **Agent tooling migrated from Claude Code to the DeepSeek Harness.**
  Removed `CLAUDE.md` (its content was already a strict subset of
  `AGENTS.md`), removed `docs/claude-code-instruction-quality-guide.md`,
  and repointed every in-repo reference (source comments, tests, docs) to
  `AGENTS.md` / the DeepSeek Harness. Dropped the `.claude/` gitignore
  entry and the pre-commit `.claude/` excludes. `AGENTS.md` gains a
  "Tooling" section declaring itself the single source of truth for the
  DeepSeek Harness and marking `CLAUDE.md` as intentionally absent.

## [3.0.0] — 2026-08-18

Single-engine rewrite: pocket-tts replaces Kokoro + Qwen3, with native
voice cloning, a new demo UI, and a full LGPD voice-data surface.

### Added

- **pocket-tts single engine** (kyutai-labs/pocket-tts 2.1.0, language
  `portuguese`, pinned HF revisions; `portuguese_24l` selectable via
  `POCKET_LANGUAGE`). CPU-only with torch CPU wheels (pytorch-cpu index),
  optional int8 quantization (`POCKET_QUANTIZE`, torchao),
  `POCKET_THREADS` re-applied after the upstream 1-thread import override,
  `POCKET_TEMPERATURE` (0.7).
- **Native voice cloning** — `POST/GET/DELETE /v1/voices`: upload 3-30 s
  audio (advertised 5-20 s, ≤10 MB, wav/mp3), get `pocket/u_<ULID>` clones
  usable immediately (ephemeral: idle TTL 3600 s, absolute TTL 86400 s,
  max 5 per key, global LRU cap 50, memory-only) or persisted (≤20 per
  customer, `.wav` + `.safetensors` + `.json` trio in `/voices/pocket/`).
- **VoiceRegistry** — filesystem scan, loaded-state LRU (16), lazy state
  materialization, `model_hash`-based state regeneration from the
  reference WAV, 60 s ephemeral sweeper.
- **LGPD voice coverage** — stored clones treated as biometric personal
  data: `export-customer` emits a `voices` array; `delete-customer --hard`
  purges voice files (audit row gains `voices_deleted`); uploads require
  consent (landing-page checkbox).
- **Landing page** — clone section (file input, display name, persist,
  LGPD consent, preview) + "Minhas vozes" list with delete; voice picker
  renders `pocket/*` voices from `/health`.
- **New errors** — `voice_upload_error` (400/413/422), `voice_limit_error`
  (429), `voice_delete_error` (403).
- **`scripts/spike_pocket_tts.py`** — permanent tuning harness (34 sigla
  phrases + WhatsApp corpus, RTF sweep, sigla-spacing A/B, clone timing).
- **`deploy/pocket-tts/{portuguese,portuguese_24l}.yaml`** — baked config
  YAMLs with local paths (no silent no-cloning fallback).
- **`deploy-models.yml` air-gapped path** — SCP `pocket_model_local` /
  `pocket_tokenizer_local` / `pocket_rafael_local` into
  `/models/pocket-tts/<lang>/`.

### Changed

- **Breaking voice names** — `kokoro/<name>` / `qwen/<name>` →
  `pocket/<name>`; `DEFAULT_VOICE` is now `pocket/rafael`.
- **Single char limit 1000** (was 500 kokoro / 300 qwen); library chunks
  internally — `chunk_text()` deleted.
- **`speed` honored for ALL voices** via ffmpeg `atempo` chains (0.25-4.0);
  single post-processing pipeline (ex radio_warm).
- **Health shape** — `engines: {pocket: {...}}`; ephemeral clones never
  appear in `/health`.
- **Auth/rate-limit unchanged** — uploads share the per-key RPM bucket;
  the per-IP speech gate covers the voices endpoints.
- **Compose** — voices mount `rw`, memory limit 4G, healthcheck
  `start_period: 300s`; `.env.example`/inventory rewritten for the
  pocket surface + `HF_TOKEN`/`HF_HUB_OFFLINE`.
- **Docker image** — espeak-ng build, qwen3-tts-cli, kokoro toolchain
  removed; ≈3-3.5 GB (torch CPU).

### Removed

- Kokoro (kokoro-onnx), Qwen3-TTS (qwen3-tts-cli / GGUF), the espeak-ng
  source build + pt_extra dictionary, misaki/espeakng_loader copies,
  onnxruntime, `chunk_text`, `_apply_whatsapp_subtle`, EngineRouter, and
  every v2 engine artifact (code, lockfile, image, deploy assets, docs).

## [2.0.0] — 2026-04-26

Multi-tenant key registry, automated billing lifecycle, LGPD-compliant
customer data handling, multi-replica scaling, and a hardening pass that
closed 23 acceptance defects across 5 review rounds.

### Added

- **Customer + API-key registry** (Epics 1–5). SQLite-backed `comadre-keys`
  CLI replaces the single `API_KEY` env var. 21 verbs covering customer
  CRUD, key issue/rotate/revoke, billing lifecycle (mark-paid / suspend /
  reactivate / suspend-sweep / at-risk / revenue), LGPD export/delete,
  encryption-key rotation, and operational health checks.
- **At-rest CPF/CNPJ encryption** via Fernet with deterministic HMAC-SHA256
  lookup digest (Story 4.1). Schema v3 partial UNIQUE INDEX prevents
  duplicate registrations across formatted vs. unformatted tax IDs while
  keeping ciphertext non-comparable.
- **Per-key rate limiting** via the `limits` library
  (`MovingWindowRateLimiter`). Keyed on the registry `key_id`, so two keys
  for the same customer bucket independently and rotation preserves the
  bucket. `/v1/audio/speech` 429 envelope ships `Retry-After` plus
  `X-RateLimit-*` headers; `/health` is unrate-limited.
- **Per-key counters** (Story 2.3) — `requests_total`, `auth_success`,
  `rate_limit_429`, `peak_rpm`, `avg_rpm_last_60s`. Snapshotted every 15s
  to per-replica JSON files; `comadre-keys cache-status` and
  `comadre-keys show <prefix>` aggregate across replicas (sum / max / min
  per metric semantics).
- **Multi-replica horizontal scaling** via `compose.yaml` `deploy.replicas`.
  Caddy `dynamic a` upstream resolver re-resolves Docker DNS every 5s and
  uses `least_conn` to exploit the single-FIFO-lock-per-replica design
  (queue-depth-aware load balancing).
- **Caddy bounded-payload policy** for `@api` (`/v1/*` + `/health`):
  rejects oversized bodies (>1 MiB), missing Content-Length on writes,
  Transfer-Encoding, and malformed Content-Length — all with the canonical
  ComadreError JSON envelope and full security-header overlay.
- **Caddy error-envelope rewrite** (`handle_errors`) so 404 / 405 /
  4xx-other / 5xx responses ship the same `{"error": {message, type,
  hint}}` shape as upstream, with security headers and `Server`/`Via`
  stripped.
- **Encrypted nightly backup** of the key registry. `backup-keys.yml`
  produces `registry.db.backup-<ISO8601>.tar.gz.enc` (AES-256-GCM,
  PBKDF2-SHA256, 600k iters); `restore-keys.yml` round-trip restores onto
  a live deployment with key-divergence detection. Daily cron at 02:00
  operator-TZ; 14-day retention.
- **Operational assertion playbook** `health.yml` (Story 4.4) — exits
  non-zero on DB mode drift, missing crons, UFW misconfig, `/health`
  unhealthy, or any `comadre-keys health` warn/fail. Wireable into
  monitoring.
- **CI non-regression suites** for security headers, docs-endpoints-
  disabled, timing-safe key comparison, oversized-body rejection, rate-
  limit wiring, no-raw-HTTPException scan, SQL-injection static analysis
  (bandit B608) — Stories 4.5a–4.5g.
- **Field-specific validation messages** for `/v1/audio/speech` body —
  pydantic taxonomy (string_too_short / string_too_long / missing /
  enum / numeric bounds / dict_type / json_invalid) all surface
  field-tagged messages instead of the legacy generic envelope.
- **Public landing page** at `/` with interactive form (API key + voice
  selector + text + speed + format + post-processing toggle), audio
  player, and download. Loads voices via `/health`. Bind-mounted in
  Caddy; gated by `landing_enabled` ansible variable.
- **Voice management playbooks** `deploy-voices.yml` (Kokoro `.npy` +
  Qwen3 `.wav` reference samples) and `deploy-models.yml` (Qwen3 GGUF
  for air-gapped deploys). Voice cloning workflow: customer sends `.wav`,
  operator runs the playbook, voice becomes available immediately.
- **New custom voices** (Kokoro): `pm_galvani`, `pm_deyvin`,
  `pf_influencer_01`, `pf_influencer_02`, `pm_influencer_01`,
  `pm_influencer_02`.

### Changed

- **Auth model retired**: legacy single-`API_KEY` env-var path removed.
  All requests authenticate against the registry; the dispatch layer is
  gone.
- **API errors** now route exclusively through the `ComadreError`
  hierarchy. Raw `FastAPI`/`HTTPException` calls are statically banned
  (CI scan in Story 4.5f).
- **Suspension sweep predicate** uses strict `paid_until < today`
  (Story 3.3). A key with `paid_until == today` is paid through today;
  the sweep catches it the next morning. Cron fires at 00:30 in the
  configured `BILLING_TIMEZONE` (default UTC; settable to operator TZ).
- **`mark-paid --months`** anchors on `paid_until` if today-or-later,
  otherwise on today (Story 5.1 Gap 3). Companion `--price-monthly` is
  atomic; audit row carries `{price_monthly_changed, old, new}`.
- **`revenue --as-of`** replays the audit log to reconstruct status,
  paid_until, and price_monthly per key on any historical date
  (Story 5.1 Gap 8). Out-of-range `--as-of` exits 2.
- **`export-customer --include-audit`** emits chronological events with
  `audit_events_total` + `audit_events_truncated` markers (Story 5.1
  review-pass), so LGPD Art. 18 II/V responses are provably complete or
  provably partial.
- **`update-customer`** distinguishes `--add-note` (append) vs `--notes`
  (replace) via `notes_op` audit discriminator. Same-value writes are
  no-ops at field granularity (no UPDATE, no audit row).

### Fixed

- 23 defects closed during the 5-round acceptance pass:
  - **B2** — partial UNIQUE INDEX on encrypted tax-ID lookup digest;
    duplicates blocked across formatted/unformatted variants and across
    Fernet rotations.
  - **B10** — manual key with `paid_until=NULL` correctly admitted as
    trial-window; expired keys correctly 401.
  - **B16** — backup cron uses bundled `comadre-keys-backup` binary +
    `/etc/comadre/backup-env`; honors retention.
  - **B19** — Caddy 4xx/5xx errors emit the project's JSON envelope.
  - **B20** — pydantic validation surfaces field-tagged messages
    (`string_*`, `missing`, `enum`, numeric bounds, dict shape,
    `json_invalid`).
  - **B21** — Caddy bounded-payload rejections (411 / 413 / 400) ship
    `application/json` envelope inline, not Caddy's text/plain default.
  - **B23** — `restore-stage.sh` magic-header detect uses portable `od`
    (the slim image lacks `xxd`).
  - **B24** — `restore-keys.yml` health probe uses bundled `python3`
    (the slim image lacks `wget`).
  - **B25** — `update-key` skips same-value writes (no audit row,
    "No changes" rendering).
  - **B26** — `deploy-models.yml` / `deploy-voices.yml` set
    `mode_parse: modern` so `"0644"` is parsed as octal (was: decimal
    644 → octal 1204).
  - Plus 13 minor exit-code, message-shape, and audit-detail fixes
    (B1 / B3–B9 / B11 / B12 / B15).

### Security

- **CPF/CNPJ encrypted at rest** with operator-rotatable Fernet key
  (`comadre-keys rotate-encryption-key`). Single decrypt site
  (`crypto.py::decrypt_tax_id`) enforced by static invariant.
- **LGPD tombstone pattern** — hard-delete preserves the audit chain
  while purging name / email / encrypted tax_id / notes (Art. 18 VI).
- **Bounded request body** (1 MiB) enforced at the Caddy layer before
  reverse_proxy runs, eliminating the silent-truncation
  `request_body { max_size }` anti-pattern.
- **Security-header overlay** (HSTS / CSP / X-Content-Type-Options /
  X-Frame-Options / Referrer-Policy / Permissions-Policy) re-applied on
  every Caddy-level error response. `Server` / `Via` stripped
  everywhere.
- **HTTPS-only** via Caddy auto Let's Encrypt or self-signed; the TTS
  service is not exposed on the host network.
- **UFW** active by default (22 / 80 / 443).
- **Encrypted backups** with AES-256-GCM + PBKDF2-SHA256 600k iters.

[2.0.0]: https://github.com/docg1701/comadre/releases/tag/v2.0.0
