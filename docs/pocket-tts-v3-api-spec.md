# Pocket TTS v3 — API Specification (target contract)

**Version:** Comadre 3.1.2
**Status:** NORMATIVE — implement exactly as written. `docs/api-reference.md` is
regenerated from this document during Phase 5.
**Engine:** kyutai-labs/pocket-tts 2.1.0, language `portuguese` (sole engine).

## 1. Breaking changes vs v2 (no back-compat — accepted by decision)

| v2 | v3 |
|---|---|
| `kokoro/<name>`, `qwen/<name>` voices | `pocket/<name>` only |
| `DEFAULT_VOICE=kokoro/pm_santa` | `DEFAULT_VOICE=pocket/rafael` |
| `input` max 500 (kokoro) / 300 (qwen) chars | single limit: **1000 chars** |
| `speed` honored natively only by Kokoro | honored for ALL voices via ffmpeg `atempo` post-processing (0.25–4.0) |
| no voice upload | new `/v1/voices` endpoints (clone from uploaded audio) |
| `/health` `engines: {kokoro, qwen3}` | `engines: {pocket}` |
| `__version__ == "2.1.1"` | `__version__ == "3.1.2"` |

## 2. Endpoints

### 2.1 `POST /v1/voices` — create a voice clone

Multipart form upload. Creates a clone of the uploaded voice. The clone is
immediately usable in the caller's session; with `persist=true` it is also
stored on the server for future requests.

- **Auth:** `Authorization: Bearer <api-key>` (required). Dependencies run in
  order: `verify_ready` → per-IP gate (reuse the speech gate, 600/min) →
  `verify_api_key` → per-key rate-limit bucket (same RPM bucket as speech).
- **Processing:** voice-state encoding runs under the same per-replica FIFO
  queue lock as speech generation (CPU-bound), timeout 120 s.

#### Form fields

| Field | Type | Required | Constraints |
|---|---|---|---|
| `file` | file | yes | anything libsndfile/soundfile reads: WAV, MP3, OGG (Vorbis/Opus), FLAC; ≤ `VOICE_UPLOAD_MAX_MB` (10 MB) |
| `display_name` | string | no | ≤ 64 chars; no NUL/CR/LF; alphanumeric, spaces, `-_'` allowed |
| `persist` | bool | no | default `false`. Values `true/false/1/0` |

**Duration rules (the 5/10/20 question — decision):** minimum **3 s** (reject
below), recommended **5–20 s** (UI hint; 5 s is Kyutai's stated minimum, 5–10 s
is the quality/cost sweet spot), hard maximum **30 s** (server truncates at
30 s — mirror of the library's `truncate=True` behavior).

#### 201 response

```json
{
  "voice": "pocket/u_01J2K4M6N8P0Q2R4S6",
  "display_name": "Minha voz",
  "persisted": true,
  "duration_s": 8.4,
  "sample_rate": 24000,
  "expires_at": null
}
```

- `expires_at`: RFC 3339 UTC timestamp for ephemeral clones
  (idle TTL 3600 s / absolute TTL 86400 s), `null` when `persisted=true`.
- `voice` is the value to pass as `voice` to `POST /v1/audio/speech`.

**Errors** (all in the standard Comadre envelope `{"error": {"type", "message", "hint"}}`)

| HTTP | `error.type` | Condition |
|---|---|---|
| 400 | `voice_upload_error` | missing/empty file, unsupported format, `duration < 3 s`, `duration > 30 s` (message names the cause: `too_short` / `too_long` / `unsupported_format` / `empty_file`) |
| 413 | `voice_upload_error` | file larger than `VOICE_UPLOAD_MAX_MB` |
| 422 | `voice_upload_error` | audio decodes but is unreadable/corrupt (message says `unreadable_audio`) |
| 429 | `voice_limit_error` | stored quota reached (`VOICE_STORED_MAX_PER_CUSTOMER` = 20) or ephemeral quota reached (`VOICE_EPHEMERAL_MAX_PER_KEY` = 5) |
| 429 | `rate_limit_error` | per-key RPM bucket (existing behavior) |
| 401 | `authentication_error` | invalid/suspended key (existing) |
| 503 | `service_unavailable_error` | warming up (existing) |
| 500 | `server_error` | state encoding failed (log traceback) |

### 2.2 `GET /v1/voices` — list voices visible to this key

- **Auth:** required (same dependency chain as 2.1 minus the queue).
- **Returns:** operator-provisioned voices (filesystem `/voices/pocket/*` with
  no customer ownership) + the caller's own stored clones + the caller's
  ephemeral clones. Other customers' clones are never listed.

```json
{
  "voices": [
    {"voice": "pocket/rafael", "display_name": "Rafael", "persisted": true,
     "created_at": null, "expires_at": null},
    {"voice": "pocket/u_01J2K4M6N8P0Q2R4S6", "display_name": "Minha voz",
     "persisted": true, "created_at": "2026-08-18T10:00:00Z", "expires_at": null},
    {"voice": "pocket/u_01J2K5A1B2C3D4E5F6", "display_name": null,
     "persisted": false, "created_at": "2026-08-18T11:30:00Z",
     "expires_at": "2026-08-19T11:30:00Z"}
  ]
}
```

- `created_at` is `null` for operator-provisioned voices without metadata.

### 2.3 `DELETE /v1/voices/{name}` — remove a stored or ephemeral clone

- **Auth:** required. A key may delete only voices it created (stored or
  ephemeral). Operator cleanup of arbitrary files stays on the filesystem /
  Ansible (documented in `voice-management.md`).
- **204 No Content** on success (ephemeral: unregister; stored: unregister +
  delete `.wav`/`.safetensors`/`.json` files).
- **Errors:** 404 `not_found_error` (unknown voice), 403
  `voice_delete_error` (not the caller's voice), 401/429/503 as usual.

### 2.4 `POST /v1/audio/speech` — unchanged shape, new semantics

```json
{"input": "Bom dia!", "voice": "pocket/rafael",
 "response_format": "ogg", "speed": 1.0, "temperature": 0.7, "seed": 42, "raw": false}
```

- `voice`: `pocket/<name>`; omitting it uses `DEFAULT_VOICE`
  (`pocket/rafael`). Unknown voice → 404 `not_found_error` with the
  available list.
- `input`: 1–1000 chars.
- `speed`: 0.25–4.0, applied post-generation as an ffmpeg `atempo` filter
  chain (chain of factors in `[0.5, 2.0]` whose product equals `speed`:
  e.g. 0.25 → `0.5,0.5`; 4.0 → `2.0,2.0`; 1.0 → no filter).
- `temperature`: 0.1–2.0 sampling temperature — lower = more consistent, higher = more expressive (default 0.7).
- `seed`: 0–2147483647 RNG seed for reproducible prosody — same text+voice+seed → identical audio.
- `raw=true`: skips the post-processing pipeline (no EQ/compression/noise/
  tempo) — still encodes to the requested format.
- `response_format`: `ogg` (Opus 24 kbps, 16 kHz mono `-application voip` — WhatsApp-compatible),
  `mp3` (64 kbps, 44.1 kHz mono — WhatsApp-compatible) or `wav` (24 kHz mono). Headers:
  `Content-Disposition: attachment; filename="comadre-<voice-slug>.<fmt>"`.

### 2.5 `GET /health` — same contract, new engine key

```json
{
  "status": "healthy",
  "voices": ["pocket/rafael", "pocket/u_01J2K4M6N8P0Q2R4S6"],
  "engines": {"pocket": {"loaded": true, "voices": ["pocket/rafael", "…"]}},
  "queue_depth": 0,
  "uptime_seconds": 1234,
  "memory_mb": 1520,
  "version": "3.1.2"
}
```

- `voices` = all filesystem `pocket/*` voices (names only — ULIDs carry no PII).
- Ephemeral voices are NOT in `/health` (they are per-key; list via
  `GET /v1/voices`).

## 3. Voice naming rules

- Operator-provisioned: `pocket/<name>` where `<name>` matches
  `^[a-zA-Z0-9_-]+$` (existing rule), sourced from `/voices/pocket/<name>.wav`
  (reference) with optional precomputed `<name>.safetensors` + `<name>.json`.
- API uploads: `pocket/u_<ULID>` — `u_` prefix is **reserved** for API
  uploads; operators must not create `u_*` files.
- State files are model-variant-specific (6-layer vs 24-layer); a persisted
  clone stores its reference WAV so the state can be regenerated if the model
  signature changes (`model_hash` in the metadata JSON).

## 4. Error envelope (unchanged shape)

```json
{"error": {"type": "<error_type>", "message": "<human message>", "hint": "<remediation>"}}
```

New `error_type` values in v3: `voice_upload_error`, `voice_limit_error`,
`voice_delete_error`. Existing values (`not_found_error`,
`invalid_request_error`, `authentication_error`, `rate_limit_error`,
`service_unavailable_error`, `server_error`, `method_not_allowed_error`)
are unchanged.

## 5. Examples

```bash
# 1. Clone a voice (ephemeral, this session only)
curl -k -X POST https://localhost/v1/voices \
  -H "Authorization: Bearer cmdr_live_YOUR_PLAINTEXT" \
  -F "file=@minha-voz.wav" -F "display_name=Minha voz"

# 2. Clone and store for future use
curl -k -X POST https://localhost/v1/voices \
  -H "Authorization: Bearer cmdr_live_YOUR_PLAINTEXT" \
  -F "file=@minha-voz.wav" -F "persist=true"

# 3. Speak with the clone (use the returned "voice")
curl -k -X POST https://localhost/v1/audio/speech \
  -H "Authorization: Bearer cmdr_live_YOUR_PLAINTEXT" \
  -H "Content-Type: application/json" \
  -d '{"input":"Olá! Esta é a minha voz clonada.",
       "voice":"pocket/u_01J2K4M6N8P0Q2R4S6"}' --output clone.ogg

# 4. List + delete
curl -k https://localhost/v1/voices -H "Authorization: Bearer cmdr_live_YOUR_PLAINTEXT"
curl -k -X DELETE https://localhost/v1/voices/pocket/u_01J2K4M6N8P0Q2R4S6 \
  -H "Authorization: Bearer cmdr_live_YOUR_PLAINTEXT"
```

**n8n HTTP Request nodes:** speech — JSON body as v2 (change `voice` to
`pocket/…`). Clone — `Method: POST`, `Send Body → Form-Data`, fields
`file` (binary data item) + `persist` (`true`), then use the response's
`voice` in the next speech node's `voice` field.

## 6. Implementation notes (normative)

1. Uploads are written to a temp file in `/tmp` (size-checked while
   streaming), validated with `soundfile` (duration + readability), encoded
   via `TTSModel.get_state_for_audio_prompt(path, truncate=True)`, then
   exported with `export_model_state()` when `persist=true`. Temp file
   deleted in `finally`.
2. The clone-creation call shares the per-replica `asyncio.Lock` with speech
   (single FIFO — never run two model operations concurrently in one replica).
3. Ephemeral voices are keyed by the registry's `key_id` (stable across key
   rotation), evicted by idle TTL / absolute TTL / global LRU cap
   (`VOICE_EPHEMERAL_GLOBAL_MAX` = 50).
4. Rate limiting: uploads consume the caller's existing per-key RPM bucket;
   no new bucket (documented in `docs/rate-limiting.md`).
