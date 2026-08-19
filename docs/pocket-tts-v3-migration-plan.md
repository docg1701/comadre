# Pocket TTS v3 — Complete Migration & Implementation Plan

**Date:** 2026-08-18
**Status:** APPROVED FOR IMPLEMENTATION — handoff document for the implementing agent.
**Version target:** Comadre 3.0.0 (major). No fallback engines, no back-compat,
no dead code, no abandoned artifacts.
**Related docs:** `docs/pocket-tts-migration-feasibility.md` (why),
`docs/pocket-tts-v3-api-spec.md` (the normative API contract).

## 0.1 Single-engine policy (absolute)

Pocket TTS is the **only** TTS in Comadre v3. There is no second engine, no
fallback engine, no compatibility shim, and no code path that reaches any
other TTS. Kokoro (kokoro-onnx), Qwen3-TTS (qwen3-tts-cli / GGUF), and every
piece of tooling that exists only to serve them — the espeak-ng source build
and pt_extra dictionary, the misaki/espeakng_loader data copy, onnxruntime,
and their transitive lockfile entries — are **deleted from the repository, the
lockfile, the container image, the deployment assets and the documentation**.
The only allowed historical traces are `CHANGELOG.md` entries and dated
reports (see §10).

**Upstream reference:** kyutai-labs/pocket-tts, pin `pocket-tts==2.1.0`
(repo cloned for study at `/tmp/pocket-tts`, HEAD `891886a6`).

## 0. How to use this plan

Execute the phases in order. Every "DO" bullet is a work item; every phase has
exit criteria. Do not invent fallback paths: there is exactly one engine
(pocket-tts) and one voice format (`pocket/<name>`). Where a value is marked
"DECIDED", implement it as written; where it is marked "TUNED IN PHASE 0",
Phase 0 produces the constant that gets baked into code/config before Phase 1
starts.

## 1. Objective, scope, non-goals

**Objective:** replace Kokoro fp32 and Qwen3-TTS C++ with kyutai-labs/pocket-tts
as the sole engine, and add **native voice cloning**: an authenticated user
uploads a 5–20 s audio sample, gets a clone of their own voice usable in that
session, optionally stored server-side for future use. Ship a new demo web UI
and a fully updated API + documentation. Release as major v3.0.0.

**In scope:** engine replacement; voice-clone endpoints; voice storage &
lifecycle; landing page; configuration surface; Docker/Ansible deploy assets;
tests; docs; cleanup of every v2 engine artifact.

**Non-goals:** multi-language runtime switching (only `portuguese` — `24l`
variant is a deploy-time choice, not a runtime switch); streaming HTTP audio
responses (keep full-audio responses); GPU support; changes to the key
registry/billing/auth/rate-limit internals (only their voice-adjacent surfaces
listed in §7.4).

## 2. Locked decisions (DECIDED — rationale in the feasibility doc)

| # | Decision |
|---|---|
| D1 | `pocket-tts==2.1.0` pinned; `language="portuguese"` default, `portuguese_24l` selectable via `POCKET_LANGUAGE` (one variant per replica) |
| D2 | Weights come from the **gated** `kyutai/pocket-tts` repo (voice cloning requires it) + public `kyutai/pocket-tts-without-voice-cloning` for tokenizer/embeddings. Downloaded once with `HF_TOKEN`; runtime is fully offline (`HF_HUB_OFFLINE=1`) |
| D3 | Voice format `pocket/<name>`; `u_<ULID>` reserved for API uploads; operator voices = filesystem |
| D4 | Voice artifacts in `/voices/pocket/`: `<name>.wav` (reference — provenance + regen source), `<name>.safetensors` (state), `<name>.json` (metadata incl. `model_hash`). State regenerated lazily when `model_hash` changes |
| D5 | Reference audio: min 3 s, recommended 5–20 s, hard max 30 s (library truncates); upload ≤ 10 MB; wav/mp3 |
| D6 | Clone endpoints: `POST/GET/DELETE /v1/voices` (contract in the API spec) |
| D7 | Ephemeral voices: keyed by registry `key_id`, idle TTL 3600 s, absolute TTL 86400 s, max 5 per key, global LRU cap 50, memory-only |
| D8 | Stored quota: 20 per customer (env-tunable); deletion via API (own voices) or operator filesystem/Ansible |
| D9 | All model work (clone encode + speech) behind the existing per-replica FIFO `asyncio.Lock` |
| D10 | `speed` honored for all voices via ffmpeg `atempo` chains (0.25–4.0); pipeline has no fixed tempo |
| D11 | One post-processing pipeline (rename `_apply_radio_warm` → `_apply_pipeline`); filter/noise constants TUNED IN PHASE 0; OGG Opus 24 kbps 16 kHz mono unchanged |
| D12 | Preprocessing = `normalize_text()` + `expand_siglas()` (spaced siglas); flag `POCKET_SIGLA_SPACING` (default `true`; value confirmed in Phase 0) |
| D13 | Single char limit 1000; `chunk_text()` deleted (library chunks internally) |
| D14 | No API `seed`; tests use `torch.manual_seed` internally if determinism is needed |
| D15 | `torch.set_num_threads(POCKET_THREADS)` (default 4) called by Comadre after importing `pocket_tts` |
| D16 | int8 quantization optional at runtime (`POCKET_QUANTIZE`, default `false`); `torchao` installed |
| D17 | `POCKET_TEMPERATURE=0.7` (the PT model default) |
| D18 | `RegistrySettings` gains `voices_dir` (LGPD purge needs it) — documented change to the F33 split |
| D19 | Stored clones are biometric personal data under LGPD: added to `export-customer` output and purged by `delete-customer --hard` |
| D20 | Version 3.0.0 everywhere; Kyutai attribution (cc-by-4.0) added to README/landing |

## 3. The 5/10/20-second question (decided)

Accept **3–30 s** server-side; advertise **5–20 s** in UI/docs; recommend
**5–10 s**. Rationale: 5 s is Kyutai's documented minimum; state size grows
linearly with duration (≈3 MB per 5 s for the 6-layer model), so 5–10 s keeps
clone latency ≈1–2 s and memory small; 20 s is the UX ceiling for WhatsApp
voice notes; 30 s is the library's own truncation cap (`truncate=True`).

## 4. Target architecture

```text
POST /v1/voices (multipart)
   verify_ready -> per-IP gate -> verify_api_key -> per-key rate limit
   -> FIFO lock -> validate (size/duration/format)
   -> get_state_for_audio_prompt(tmp_wav, truncate=True)
   -> [persist] export_model_state -> /voices/pocket/u_<ulid>.safetensors
      + .wav + .json{display_name, customer_id, key_id, model_hash, ...}
   -> register in VoiceRegistry -> 201

POST /v1/audio/speech
   ... same auth chain ...
   -> FIFO lock -> PocketEngine.generate_speech:
      normalize_text() [+ expand_siglas()] -> registry.resolve(name)
      (LRU of loaded states; deepcopy per call via copy_state=True)
      -> TTSModel.generate_audio(state, text) -> 24 kHz float32 tensor
      -> _samples_to_wav() -> _apply_pipeline(wav, fmt, noise_dir, speed) -> bytes
```

```text
src/comadre/service.py
  PocketEngine        # load, warm-up, generate_speech, _samples_to_wav, ffmpeg pipeline
  VoiceRegistry       # filesystem scan, state LRU (16), ephemeral registry + TTL sweep,
                      # create_from_upload(), resolve(), delete(), model_hash, available_voices()
  engine_status() -> {"pocket": {...}}
src/comadre/voices_api.py   # NEW router: POST/GET/DELETE /v1/voices (or extend api.py —
                      #   decision: NEW module, keeps api.py speech-only, mirrors module boundaries)
```

Module boundaries (AGENTS.md invariant): HTTP concerns in `api.py` /
`voices_api.py`; no business logic there — voice validation/encoding/storage
lives in `service.py` (`VoiceRegistry`) and a new small
`src/comadre/voice_storage.py` for file operations (used by both the API and
the `comadre-keys` CLI LGPD verbs — no duplicated file logic).

## 5. API contract

Implemented exactly per `docs/pocket-tts-v3-api-spec.md`. Phase 2 transcribes
it into code; Phase 5 regenerates `docs/api-reference.md` from it.

## 6. Configuration spec

### 6.1 `Settings` (app surface) — new fields

| Env var | Type / default | Notes |
|---|---|---|
| `POCKET_LANGUAGE` | `str = "portuguese"` | `portuguese` \| `portuguese_24l` (validator) |
| `POCKET_CONFIG_PATH` | `str = "models/pocket-tts-config/portuguese.yaml"` | custom yaml baked in image (local paths) |
| `POCKET_MODEL_PATH` | `str = "models/pocket-tts/portuguese/model.safetensors"` | |
| `POCKET_TOKENIZER_PATH` | `str = "models/pocket-tts/portuguese/tokenizer.model"` | |
| `POCKET_DEFAULT_VOICE_PATH` | `str = "models/pocket-tts/portuguese/embeddings/rafael.safetensors"` | default catalog voice state |
| `POCKET_THREADS` | `int = 4` (ge 1) | applied via `torch.set_num_threads` after import |
| `POCKET_QUANTIZE` | `bool = False` | int8 attention+FFN via torchao |
| `POCKET_TEMPERATURE` | `float = 0.7` (ge 0) | |
| `POCKET_SIGLA_SPACING` | `bool = True` | `expand_siglas` on/off |
| `VOICE_UPLOAD_MAX_MB` | `int = 10` (1–50) | |
| `VOICE_REF_MIN_SECONDS` | `int = 3` (ge 1) | |
| `VOICE_REF_MAX_SECONDS` | `int = 30` (ge min) | |
| `VOICE_EPHEMERAL_IDLE_TTL_SECONDS` | `int = 3600` | |
| `VOICE_EPHEMERAL_ABSOLUTE_TTL_SECONDS` | `int = 86400` | |
| `VOICE_EPHEMERAL_MAX_PER_KEY` | `int = 5` | |
| `VOICE_EPHEMERAL_GLOBAL_MAX` | `int = 50` | LRU eviction |
| `VOICE_STORED_MAX_PER_CUSTOMER` | `int = 20` | |

Keep: `voices_dir` (`/voices`), `noise_dir`, `default_voice` (default now
`"pocket/rafael"`), `per_ip_*` limits, `port`.

**REMOVE (and every reference to them):** `espeak_data_path`,
`kokoro_model_path`, `kokoro_voices_path`, `qwen3_enabled`,
`qwen3_cli_path`, `qwen3_model_path`, `qwen3_tokenizer_path`,
`qwen3_threads`, `kokoro_model_url`, `kokoro_voices_url`,
`qwen3_model_url`, `qwen3_tokenizer_url`.

### 6.2 `RegistrySettings` change

Add `voices_dir: str = "/voices"` (used by the LGPD purge/export verbs).
Update the class docstring: the F33 "CLI never touches voices" invariant now
has one exception — the LGPD data-subject operations.

## 7. File-by-file implementation spec

### 7.1 `pyproject.toml`

DO:

- `version = "3.0.0"`; description → "Comadre Manda Áudio Direto, Rápido e
  Eficiente — pocket-tts TTS API with native voice cloning".
- Dependencies: REMOVE `kokoro-onnx`; ADD `pocket-tts[audio]==2.1.0`
  (pulls `soundfile`), `python-multipart>=0.0.9`. KEEP `num2words`
  (used by `normalize_text`). Ensure `kokoclone` is absent (remove if
  present anywhere).
- ADD torch CPU index config (mirrors upstream pocket-tts pyproject):

```toml
[[tool.uv.index]]
name = "pytorch-cpu"
url = "https://download.pytorch.org/whl/cpu"
explicit = true

[tool.uv.sources]
torch = [
  { index = "pytorch-cpu" },
]
```

- `[tool.mypy.overrides]` module list: replace `kokoro_onnx.*` with
  `pocket_tts.*` (keep `num2words.*`, `cachetools.*`).
- Run `uv lock` and commit the updated `uv.lock` (torch CPU wheel).
  After the lock, `uv.lock` must contain **zero** entries for `kokoro-onnx`,
  `onnxruntime`, `espeakng-loader`, `misaki` or any other kokoro transitive
  dependency (verify with the §10 invariants).

### 7.2 `src/comadre/__init__.py`

`__version__ = "3.0.0"`.

### 7.3 `src/comadre/config.py`

Per §6. Validators: `POCKET_LANGUAGE` in the two allowed values;
`VOICE_REF_MAX_SECONDS >= VOICE_REF_MIN_SECONDS`; numeric bounds per table.
Remove the old `HttpUrl` validator block for engine URLs if no other URL
fields remain (check: none remain — delete the validator). Update module
docstring accordingly.

### 7.4 `src/comadre/exceptions.py`

DO:

- Update `VoiceNotFoundError` hint: only `pocket/<name>` (`/voices/pocket/`).
- ADD `VoiceUploadError(ComadreError)` — `status_code=400`,
  `error_type="voice_upload_error"`, message names the cause
  (`empty_file` / `unsupported_format` / `too_short` / `too_long`),
  hint includes the 3–30 s rule. Subclass or single class with a
  `reason` constructor arg — DECIDED: single class + `reason` string.
- ADD `VoiceUploadTooLargeError` — `status_code=413`, same error_type.
- ADD `VoiceUnreadableError` — `status_code=422`, same error_type.
- ADD `VoiceLimitError` — `status_code=429`, `error_type="voice_limit_error"`,
  message distinguishes stored vs ephemeral quota.
- ADD `VoiceDeleteError` — `status_code=403`, `error_type="voice_delete_error"`.
- Keep every other class unchanged.

### 7.5 `src/comadre/schemas.py`

- `SpeechRequest.input`: `max_length=1000` (single limit); remove the
  per-engine validator.
- ADD `VoiceListItem` (`voice`, `display_name`, `persisted`,
  `created_at: datetime | None`, `expires_at: datetime | None`) and
  `VoiceListResponse` (`voices: list[VoiceListItem]`).
- ADD `VoiceCreateResponse` per API spec §2.1.

### 7.6 `src/comadre/preprocessing.py`

- KEEP: `normalize_text` (+ currency/dates/times/numbers helpers),
  `expand_siglas`, `WORD_SIGLAS`.
- DELETE: `chunk_text` (library chunks internally) and its tests.

### 7.7 `src/comadre/download.py` (rewrite)

`ensure_pocket_models()`: downloads (skip if present) via
`huggingface_hub.hf_hub_download`:

| File | Repo | Revision | Filename |
|---|---|---|---|
| model | `kyutai/pocket-tts` (gated) | `39592ff23c9ef80098bb74895d104c26275fe2c9` | `languages/<lang>/model.safetensors` |
| tokenizer | `kyutai/pocket-tts-without-voice-cloning` | `d29db7978e464fb90cb3359ee0c69a273b9142cc` | `languages/<lang>/tokenizer.model` |
| rafael state | `kyutai/pocket-tts-without-voice-cloning` | `e041936c75475d350b405bc870bcf7c22da4e9e6` | `languages/<lang>/embeddings/rafael.safetensors` |

(`<lang>` = `POCKET_LANGUAGE` value.) Copies into the `POCKET_*_PATH`
destinations. Uses `local_files_only=False` when `HF_TOKEN` is set,
honors `HF_HUB_OFFLINE=1` (fail fast with a clear "run with HF_TOKEN once"
message when files are missing offline). Logs sizes like the old module.
DELETE the urllib-based helpers.

### 7.8 `src/comadre/voice_storage.py` (NEW)

Pure file operations on `/voices/pocket/` (no model, no HTTP):
`scan_entries() -> list[VoiceFileEntry]`, `read_meta(name)`,
`write_meta(...)`, `delete_entries(name)`, `count_by_customer(customer_id)`,
`delete_by_customer(customer_id)` (LGPD purge), `list_for_customer(...)`
(export). `VoiceFileEntry` dataclass: `name`, `ref_path`,
`state_path`, `meta` (`display_name`, `customer_id`, `key_id`,
`created_at`, `ref_duration_s`, `model_hash`). Path names are built from
the validated voice name only (no traversal: reuse `_VOICE_NAME_RE` / ULID
format check).

### 7.9 `src/comadre/service.py` (rewrite — this is the core)

DO:

- Imports: `pocket_tts.TTSModel`, `export_model_state`; delete
  `kokoro_onnx`, `subprocess`-based Qwen engine, `expand_siglas`/chunk
  usage per §7.6.
- After importing `pocket_tts`: `torch.set_num_threads(settings.pocket_threads)`.
- `class PocketEngine`:
  - `load_model(config_path, threads, quantize, temperature)`:
    `self._model = TTSModel.load_model(config=config_path, quantize=quantize, temp=temperature)`.
    (config yaml has local paths → fully offline.)
  - `warm_up(default_state)`: `generate_audio(state, "Teste de aquecimento.")`.
  - `generate_speech(text, voice_name, response_format, noise_dir, speed, *, raw)`:
    validate (format/empty/limit), `normalize_text()` →
    [`expand_siglas()` if `pocket_sigla_spacing`] → `registry.resolve(name)`
    → `self._model.generate_audio(state, text, copy_state=True)` → tensor
    `[channels, samples]` @ 24 kHz → `_samples_to_wav()` →
    `raw ? _encode_final(...) : _apply_pipeline(wav, fmt, noise_dir, speed)`.
  - `sample_rate` property delegates to `self._model.sample_rate`.
- `_samples_to_wav()`: keep as-is.
- `_apply_pipeline(wav_bytes, response_format, noise_dir, speed)` (renamed
  from `_apply_radio_warm`): stage 1 ffmpeg filter (constants TUNED IN
  PHASE 0; starting point = the current radio_warm chain), stage 2 noise mix +
  encode (unchanged helpers `_find_noise_file`, `_apply_noise_and_encode`,
  `_encode_final`). The `atempo` chain for `speed != 1.0` is appended to
  the stage-1 filter (chain factors in [0.5, 2.0] multiplying to `speed`).
- `class VoiceRegistry`:
  - `__init__(engine, voices_dir: Path, settings)`: filesystem scan
    (`voice_storage.scan_entries`), `_loaded: OrderedDict[str, dict]`
    (LRU maxsize 16), `_ephemeral: dict[key_id, dict[name, EphemeralVoice]]`.
  - `resolve(name) -> dict`: check ephemeral (caller context passed in as
    `key_id`), then filesystem: load `.safetensors` via
    `get_state_for_audio_prompt(path)` into LRU; if only `.wav` exists,
    encode state (under lock) + persist `.safetensors` + write `.json`
    meta with current `model_hash`; if `model_hash` in meta differs from
    current, re-encode from `.wav` and rewrite. Refresh LRU order.
  - `create_from_upload(path, key_id, customer_id, display_name, persist)`:
    quota checks (stored/ephemeral), duration validation was done upstream
    (API layer validates BEFORE calling — see §7.10; registry re-checks
    defensively), `get_state_for_audio_prompt(tmp, truncate=True)`,
    if persist: write `u_<ulid>.` trio via `voice_storage` and register in
    LRU; else register ephemeral with TTLs. Returns a `VoiceInfo` object.
  - `delete(name, key_id, customer_id)`: own-voice check (meta.customer_id
    or ephemeral owner), unregister + `voice_storage.delete_entries`.
  - `list_for(key_id, customer_id)`: operator voices (no `customer_id`
    meta) + own stored + own ephemeral → `list[VoiceInfo]`.
  - `available_voices() -> ["pocket/<name>", ...]` (filesystem only);
    `engine_status() -> {"pocket": {"loaded", "voices"}}`.
  - `start_sweeper(loop)`: asyncio task evicting expired ephemerals every
    60 s (idle TTL from `last_used_at`, absolute TTL from `created_at`),
    and enforcing the global LRU cap.
  - `model_hash` property: sha256 of `POCKET_MODEL_PATH` computed once
    (cached) at startup.
- DELETE `KokoroEngine`, `QwenEngine`, `EngineRouter`,
  `_apply_whatsapp_subtle`, `_build_command`, and the Qwen seed logic.
- `engine_status()` / `available_voices()` module-level functions keep
  their names (health.py imports them) but return the pocket shape.

### 7.10 `src/comadre/voices_api.py` (NEW) + `src/comadre/api.py`

- `api.py`: speech route unchanged except default-voice/validation updates;
  log line unchanged shape.
- `voices_api.py`: `voices_router = APIRouter(prefix="/v1/voices")` with
  the three endpoints per API spec §2.1–2.3. Dependency chain per endpoint as
  specified. Upload handling: `Content-Length` pre-check (413), stream to
  temp file with a running size guard, `soundfile` duration/readability
  validation (3–30 s → 400/422), then hand off to `registry.create_from_upload`
  under the FIFO lock with the same 120 s `asyncio.wait_for` pattern as
  speech. Temp file cleanup in `finally`. `key_id`/`customer_id` come
  from `AuthPayload` (already returned by `verify_api_key` — verify the
  field names in `keys/auth.py` and use them).
- Register `voices_router` in `main.py` next to `api_router`.

### 7.11 `src/comadre/main.py`

Lifespan updates (keep the registry/auth/counters phases untouched):

- Phase 2.5 → `ensure_pocket_models(...)` (only when `HF_HUB_OFFLINE` is
  not `"1"`; when offline, verify files exist and fail fast otherwise).
- Remove the espeak-ng verification phase entirely.
- Phase 4 voices-dir checks → `/voices/pocket` only.
- Engine load → `PocketEngine.load_model(...)`; warm-up with the rafael
  state (`POCKET_DEFAULT_VOICE_PATH`).
- NEW Phase: `VoiceRegistry` build (scan + `model_hash`) + sweeper task
  start (`asyncio.create_task` in lifespan; cancel on shutdown).
- Default-voice validation against `registry.available_voices()` +
  `pocket/rafael` presence warning (same pattern as v2).

### 7.12 `src/comadre/health.py`

Minimal change: `engines` dict now comes from the new `engine_status()`.
No other field changes.

### 7.13 `src/comadre/keys/cli/commands/customers.py` (LGPD)

- `export-customer`: add `voices` array to the output — the customer's
  stored clones (`voice_storage.list_for_customer`) with `voice`,
  `display_name`, `created_at`. Update `docs/monetization.md` §LGPD to
  call clones biometric data.
- `delete_customer_hard`: after DB purge, call
  `voice_storage.delete_by_customer(customer_id)`; audit row `details_json`
  gains `voices_deleted: N`. (The CLI now imports `voice_storage` — the
  only new cross-surface import; document in AGENTS.md.)

### 7.14 `Dockerfile` (rewrite)

- Keep: `python:3.12-slim` base; `ffmpeg`, `libsndfile1` (soundfile),
  `openssl`, `sqlite3`; uv copy; non-root `appuser`; volume mount
  points; `EXPOSE 8000`; entrypoint.
- DELETE: the espeak-ng source build (git/cmake/gcc/g++/make/pkg-config +
  `libsonic-dev`), the pt_extra compile step, the misaki/espeakng_loader
  copy step, the toolchain purge step, the `qwen3-tts-cli` COPY.
- ADD: `COPY deploy/pocket-tts/<lang>.yaml /app/models/pocket-tts-config/`
  for both variants (baked; local paths inside).
- `uv sync --frozen --no-dev` now installs torch (CPU wheel, ~190 MB
  download, ~1.5–2 GB installed). Expected image ≈ 3–3.5 GB; build ≈ 8–12 min.

### 7.15 `deploy/pocket-tts/portuguese.yaml` + `portuguese_24l.yaml` (NEW)

Copies of the upstream `pocket_tts/config/<lang>.yaml` (verbatim structure
— pydantic is strict, `extra=forbid`) with only:

- `weights_path: /models/pocket-tts/<lang>/model.safetensors`
- `flow_lm.lookup_table.tokenizer_path: /models/pocket-tts/<lang>/tokenizer.model`
- `weights_path_without_voice_cloning` omitted (fail fast — no silent
  degradation to the no-cloning model).

### 7.16 `compose.yaml` + `.env.example`

- `tts-service` env: replace the KOKORO_*/QWEN3_* block with the §6.1
  POCKET_*/VOICE_* block (+ `DEFAULT_VOICE=pocket/rafael`); `comadre-voices`
  mount becomes `rw` (app writes uploads); `deploy.resources.limits`
  memory → `4G` (pocket-tts ≈ 1.5–2 GB RSS; 4 G is comfortable headroom —
  tune after Phase 4); `healthcheck.start_period: 300s` (first-boot model
  download).
- `.env.example`: rewrite engine section per §6.1 with comments in the same
  style; keep registry/backup/billing/domain sections unchanged.

### 7.17 `deploy/ansible`

- `bootstrap.yml`: env block → POCKET_*/VOICE_*; add optional
  `pocket_hf_token` inventory var passed as `HF_TOKEN` (one-time download;
  unset after first boot — document); `mkdir -p /voices/pocket` instead of
  kokoro/qwen; smoke test → `{"input":"Olá mundo","voice":"pocket/rafael"}`.
- `deploy-models.yml` (rewrite for air-gapped): inventory vars
  `pocket_model_local`, `pocket_tokenizer_local`,
  `pocket_rafael_local`; prereq asserts (intentional-fail design preserved);
  SCP → `~/comadre/deploy/staging/pocket-tts/` → docker cp into
  `/models/pocket-tts/<lang>/`; summary table updated (model ~370 MB,
  tokenizer ~1 MB, rafael ~1 MB).
- `deploy-voices.yml`: ship a `pocket/` subdir of `voices_local_dir`
  (reference `.wav`s; optional precomputed `.safetensors`/`.json`); drop
  kokoro/qwen logic. NOTE for the runbook: **existing `qwen/*.wav`
  references are reused verbatim as `pocket/*.wav`** — states materialize
  lazily on first request (document in voice-management.md).
- `health.yml`: replace the qwen-absence probe with: `engines.pocket.loaded
  == true` and ≥ 1 `pocket/*` voice in `voices`; keep every other probe.
- Inventory examples: update comments + new vars.

### 7.18 `deploy/landing/index.html`

Keep the existing API-key + TTS form; changes:

- Voice picker: remove the `LOCALE_PREFIX_RE` / kokoro locale heuristic
  block (lines ~723–727) and the hardcoded `kokoro/pm_santa` default; render
  all `/health` voices with `pocket/rafael` preselected.
- NEW "Clonar voz" section: file input (`accept=".wav,.mp3,audio/*"`),
  duration hint "grave 5–20 segundos", optional display name, `persist`
  checkbox ("salvar para uso futuro"), LGPD consent checkbox (required before
  upload: "autorizo o processamento da minha biometria de voz…"), create
  button → `POST /v1/voices` (FormData), on success: play a preview by
  calling `/v1/audio/speech` with a fixed PT text ("Olá! Esta é a minha
  voz.") and add the voice to the picker.
- NEW "Minhas vozes" list: `GET /v1/voices` (own entries only rendered with
  a delete button → `DELETE /v1/voices/<name>`; operator voices shown
  without delete).
- Footer: attribution "TTS: Kyutai Pocket TTS (cc-by-4.0)".

### 7.19 `scripts/`

- `loadtest.py` + `capacity_test.py`: default `--voice pocket/rafael`;
  any scenario text using old voice names → `pocket/rafael`.
- DELETE `scripts/feasibility_test.py`.
- ADD `scripts/spike_pocket_tts.py` (kept — the permanent tuning harness;
  content defined in Phase 0 below).

### 7.20 Deletions (artifacts)

DELETE: `deploy/bin/qwen3-tts-cli`, `deploy/espeak-ng/` (whole dir),
`tests/test_feasibility.py`, `tests/test_routing.py`,
`docs/building-qwen3-tts-cli.md`, `docs/quantizing-qwen3-models.md`,
`docs/qwen3-tts-internals.md`, `docs/espeak-ng-custom-dictionary.md`,
`docs/qwen3-tts-cpp-seed-patch.diff`,
`docs/chatterbox-tokens-features.md`,
`docs/chatterbox-ptbr-preprocessing-rules.md`,
`docs/feasibility-report-tts-engine.md` (superseded by the pocket
feasibility doc + this plan). Inspect `docs/local-file-dependency.txt` and
delete if engine-related. `noise/` stays (pipeline still uses it).
`docs/pentest-report*`, `docs/ansible-deploy-report*` stay (dated records).

## 8. Test plan

| File | Action |
|---|---|
| `tests/conftest.py` | ADD `pocket_model` fixture: MagicMock `TTSModel` (methods `load_model`, `generate_audio` → fake 24 kHz tensor, `get_state_for_audio_prompt` → fake state dict, `sample_rate=24000`) + `fake_export_model_state` patch. Keep existing fixtures. |
| `tests/test_service.py` | REWRITE: PocketEngine (preprocess applied — normalize + sigla spacing; format/empty/limit validation; `copy_state=True` asserted; raw bypass; GenerationError on model failure); `_apply_pipeline` (ffmpeg called with expected filter incl. atempo chains for 0.25/0.5/2.0/4.0, mocked subprocess); voice parse rules (traversal rejection, `u_` ULID shape). |
| `tests/test_voice_registry.py` | NEW: filesystem scan; lazy state materialization from `.wav` (persists `.safetensors`+meta); regen on `model_hash` mismatch; LRU cap 16; ephemeral TTL expiry + per-key max 5 + global 50 eviction; `create_from_upload` persist/quotas (stored 20/customer, ephemeral 5/key); `delete` own-only; `list_for` visibility rules; `delete_by_customer`. |
| `tests/test_voices_api.py` | NEW: POST 201 (persist true/false), 400 too short/long/unsupported/empty, 413 size, 422 corrupt, 429 quotas + rate limit, 401, 503; GET visibility (operator + own, other customers' hidden); DELETE 204/404/403; FIFO-lock serialization asserted (mock queue lock). |
| `tests/test_api.py` | UPDATE: voice strings → `pocket/rafael`; char-limit 1000 boundary; speed honored (mock service asserts speed forwarded). |
| `tests/test_schemas.py` | UPDATE: 1000-char limit; new response models validated. |
| `tests/test_config.py` | UPDATE: new env fields + validators; assert removed fields are gone. |
| `tests/test_download.py` | REWRITE: mocked `hf_hub_download` per table §7.7 (revision pins), skip-if-present, offline fail-fast. |
| `tests/test_health.py` | UPDATE: engines shape `{pocket: ...}`. |
| `tests/test_main_lifespan.py` | UPDATE: new phases (model ensure, engine load, registry build, sweeper task, default-voice validation). |
| `tests/test_preprocessing.py` | UPDATE: drop `chunk_text` tests; keep the rest. |
| `tests/test_non_regression/` | UPDATE voice strings to `pocket/rafael` in `test_rate_limit_wired.py`/fixtures. |
| `tests/test_slow_pocket.py` | NEW (`@pytest.mark.slow`): real model — load from local files (skip if absent), clone a 5 s WAV, `generate_audio` returns non-silent audio, export/import roundtrip. |
| `tests/_keys_fixtures.py` | Only if it references engines (grep — expect no change). |

## 9. Documentation update checklist (Phase 5)

| Doc | Action |
|---|---|
| `README.md` | Rewrite: badges (TTS pocket-tts, version 3.0.0); architecture section (single engine + cloning); new feature bullets (voice cloning endpoint, session + storage, LGPD consent); quick start adds the clone curl; requirements (4 vCPU / 8 GB host unchanged; ~600 MB models; image ~3–3.5 GB); license section adds Kyutai cc-by-4.0 attribution |
| `docs/api-reference.md` | Regenerate from `docs/pocket-tts-v3-api-spec.md` (endpoints, schemas, error table, curl + n8n examples) |
| `docs/api-architecture.md` | Rewrite diagrams/module boundaries: speech path, clone path, VoiceRegistry/LRU/ephemeral, `voice_storage` shared with CLI, queue semantics unchanged |
| `docs/configuration-reference.md` | New env table (§6.1) + removed vars marked "removed in v3" |
| `docs/voice-management.md` | Rewrite: `pocket/` artifacts (.wav/.safetensors/.json), upload flow + quotas/TTLs, operator provisioning (drop WAV → lazy materialization), reuse of former qwen refs, delete/export LGPD verbs, `u_` reserved prefix, model-hash regen behavior |
| `docs/deployment-guide.md` | HF token step (accept terms on the gated model card + `HF_TOKEN`), models deploy (auto or `deploy-models.yml`), bootstrap/update/health unchanged flow |
| `docs/troubleshooting.md` | Rewrite engine entries: HF 401/gating error, offline missing files, torch import/RAM, state-regen on model change, upload validation errors |
| `docs/monetization.md` | LGPD section: clones = biometric data; `export-customer` `voices` array; `delete-customer --hard` purge; consent requirement on upload |
| `docs/rate-limiting.md` | Note: uploads consume the same per-key bucket |
| `docs/local-testing-guide.md` | Local dev with `uv sync`, `HF_TOKEN`, download-on-boot, spike script usage |
| `docs/replica-scaling-report.md` + `docs/cost-comparison-report.md` + `docs/relatorio-comparativo-custos.md` | Annotate as v2-era; after Phase 4 add a v3 addendum with the new capacity/cost numbers |
| `CHANGELOG.md` | v3.0.0 entry: engine swap, cloning endpoints, breaking voice names, speed semantics, config surface, LGPD voice coverage, deletions |
| `AGENTS.md` | Rewrite: Overview (single engine + cloning); Architecture (voice format, VoiceRegistry, upload path, `u_` prefix, `RegistrySettings.voices_dir` exception); Key File Locations (delete qwen3-tts-cli/espeak entries; add `deploy/pocket-tts/*.yaml`, `voice_storage.py`, `voices_api.py`); Gotchas: REPLACE misaki/espeak-ng, Qwen3 `-l pt`, 4-core sweet spot, kokoclone, qwen build, GGUF prebuilt with NEW: gated weights + `HF_TOKEN` + pinned revisions, `torch.set_num_threads(1)` upstream override, `copy_state=True` deepcopy semantics, model-hash state regen, `u_` reserved prefix, torch CPU index in pyproject, image size, rafael embedding revision pin. Ansible runbook section: bootstrap `HF_TOKEN`/env changes. |
| `docs/pocket-tts-migration-feasibility.md` | Status → `DECIDED — see migration plan` |

## 10. Cleanup invariants (must hold before tagging)

```bash
rg -i "kokoro|qwen|espeak|kokoclone|chatterbox" src/ deploy/ scripts/ tests/    --glob '!deploy/ansible/inventory/*.yml' ; echo "expect: 0 hits"
rg -i "kokoro|qwen|espeak|kokoclone|chatterbox|onnxruntime|misaki|espeakng" pyproject.toml uv.lock ; echo "expect: 0 hits"
rg "2.1.1" . --glob '!CHANGELOG.md' ; echo "expect: 0 hits"
rg "chunk_text" src/ tests/ ; echo "expect: 0 hits"
```

(`CHANGELOG.md` and dated historical reports are the only allowed
exceptions.)

## 11. Phases and acceptance criteria

### Phase 0 — Baseline capture & spike tuning (0.5–1 day)

- CAPTURE baseline v2 outputs FIRST (before any teardown): run the current
  stack, save WAV/OGG samples of (a) the 34 sigla phrases (list extracted
  from `tests/test_feasibility.py`/`scripts/feasibility_test.py` into
  `scripts/spike_pocket_tts.py` before deleting them), (b) 10 WhatsApp
  messages, (c) 2 cloned voices (operator + one customer).
- Spike with `uvx pocket-tts generate --language portuguese`: same texts;
  A/B vs baselines; test `expand_siglas` on/off; RTF at threads 1/2/4,
  int8 on/off, base vs 24l; clone encode times for 5/10/20 s refs; rafael
  embedding + cloning model compatibility.
- OUTPUTS (recorded in this doc, baked into code): pipeline filter/noise
  constants, `POCKET_SIGLA_SPACING` value, `POCKET_THREADS`,
  `POCKET_QUANTIZE`, `POCKET_TEMPERATURE`, variant choice.
- EXIT: all outputs recorded; spike script committed.

### Phase 0 execution record (2026-08-18, host galvani 12 cores / 27 GB)

- **Baselines captured** (v2 stack, pre-teardown): 34 sigla phrases + 10
  WhatsApp messages via KokoroEngine (pm_santa, radio_warm pipeline),
  operator clone via QwenEngine (voices/qwen/female.wav), customer clone via
  kokoro pm_galvani.npy → `tmp/v2-baseline/{siglas,whatsapp,clones}/*.{wav,ogg}`
  (gitignored).
- **Spike** (real pocket-tts, HF cache, no-cloning distilled weights — the
  gated cloning model 401s without HF_TOKEN; clone-encode timing therefore
  deferred to the operator's first HF_TOKEN boot): 51-utterance corpus
  (34 siglas + 10 WhatsApp + 7 edge) at 24 kHz.
- **RTF** (3-utterance sweep, distilled 6-layer model): threads=1 → 0.30,
  threads=2 → 0.33, threads=4 → 0.34; threads=4+int8 → 0.43; sigla
  spacing on/off → no measurable RTF delta (preprocessing is negligible).
  Full-corpus run at threads=4: mean 0.34, median 0.33, max 0.43
  (≈3x faster than real-time; v2 comparison: kokoro ≈0.3–0.5, qwen 2.4–3.6x).
- **Baked constants**: pipeline = radio_warm chain carried over (listening
  A/B: `tmp/spike` + `tmp/spike-nospace` vs `tmp/v2-baseline` — human
  ear check pending); `POCKET_SIGLA_SPACING=true` (spacing kept as the only
  sigla lever; on/off audio pairs in tmp/spike*/siglas);
  `POCKET_THREADS=4` (1 was marginally faster on the small distilled model,
  but 4 is the documented sweet spot for the larger gated model and matches
  D15); `POCKET_QUANTIZE=false` (int8 cost +26% RTF on this host with no
  memory pressure; remains an env opt-in); `POCKET_TEMPERATURE=0.7`;
  variant `portuguese` (base; `portuguese_24l` remains the deploy-time
  quality lever per D1).

### Phase 1 — Core code (3–5 days)

§7.1–7.6, 7.8–7.9, 7.11–7.12 + unit tests §8.

- EXIT: `uv run pytest` (non-slow) green; `ruff check .`; `mypy src/`
  strict clean; `pre-commit run --all-files` clean.

### Phase 2 — API + landing (1–2 days)

§7.10 + landing §7.18 + API tests.

- EXIT: curl smoke sequence (API spec §5) passes against a dev server with
  mocked/real model; manual landing walkthrough (clone → preview → persist →
  delete).

### Phase 3 — Ops & deploy assets (1–2 days)

§7.14–7.17, `.env.example`.

- EXIT: `docker compose build` succeeds; fresh boot downloads models
  (with `HF_TOKEN`) and passes healthcheck; `health.yml` adapted and
  passing on a staging host (or documented dry-run).

### Phase 4 — Cutover & capacity (1–2 days)

Deploy to the production VPS (ansible update), migrate voices (copy former
`qwen/*.wav` → `pocket/*.wav`), re-run `loadtest.py` +
`capacity_test.py`, refresh cost/replica docs, announce new voice names to
customers.

- EXIT: loadtest 100% audio integrity; capacity report updated in docs.

### Phase 5 — Docs sweep & cleanup (1–2 days)

§9 + §10 + version bump verification + `CHANGELOG`.

- EXIT: cleanup invariants hold; docs checklist complete.

### Phase 6 — QA gate & release

Full suite (`pytest`, slow tests if model available, `ruff`, `mypy`,
`pre-commit`, docker build, health playbook), git tag `v3.0.0`.

- EXIT: all green; tag pushed.

## 12. Definition of done

1. One engine (pocket-tts), zero kokoro/qwen/espeak artifacts (invariants §10).
2. `POST/GET/DELETE /v1/voices` behave exactly per the API spec (Phase 2 exit).
3. Landing page: clone flow works end-to-end with consent + persistence + delete.
4. LGPD: export includes voices; purge deletes voice files (tested in
   `test_voice_registry.py` + a CLI test in `tests/test_keys_cli_*/`).
5. All docs updated per §9; `README` reflects v3 truthfully.
6. `v3.0.0` tag; CHANGELOG entry; Kyutai attribution present.

## 13. Risk register

| Risk | Mitigation |
|---|---|
| pt-BR accent/sigla quality below the bar | Phase 0 decides `POCKET_SIGLA_SPACING` + variant (base vs 24l) + temperature; 24l is the quality lever if base disappoints |
| HF gating blocks downloads | Operator accepts terms once; `deploy-models.yml` air-gapped path; `HF_TOKEN` documented |
| torch image size / RAM | int8 flag; 4 G compose limit; audio.cpp ggml port noted as a future alternative (not in scope) |
| State incompatibility after model upgrades | reference `.wav` always stored; `model_hash` regen; documented |
| Upload abuse (CPU) | per-key RPM bucket + FIFO queue + size/duration caps |

## 14. Handoff notes for the implementing agent

- Upstream repo for reference: `git clone --depth 1 https://github.com/kyutai-labs/pocket-tts /tmp/pocket-tts`
  (HEAD `891886a6` studied in this analysis; pin `pocket-tts==2.1.0` from PyPI).
- Accept the gated-model terms at <https://huggingface.co/kyutai/pocket-tts>
  with the operator's HF account; keep `HF_TOKEN` out of git (ansible vault
  / env, same discipline as `COMADRE_*` secrets).
- The two feasibility docs (`docs/pocket-tts-migration-feasibility.md` and
  this plan) contain every fact needed; the API spec is normative — when in
  doubt, the spec wins.
- Do not reintroduce any deleted artifact (§7.20); if something is genuinely
  missing, flag it in the Phase summary instead of adding a fallback.
