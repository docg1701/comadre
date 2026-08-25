# Comadre API Reference (v3.1.12)

Engine: kyutai-labs pocket-tts 2.1.0, language `portuguese` (sole engine).

## 1. Breaking changes vs v2

| v2 | v3 |
|---|---|
| `kokoro/<name>`, `qwen/<name>` voices | `pocket/<name>` only |
| `DEFAULT_VOICE=kokoro/pm_santa` | `DEFAULT_VOICE=pocket/rafael` |
| `input` max 500 (kokoro) / 300 (qwen) chars | single limit: **1000 chars** |
| `speed` native only on kokoro | honored for ALL voices via ffmpeg `atempo` post-processing (0.25-4.0) |
| no voice upload | `POST/GET/DELETE /v1/voices` (voice cloning) |
| `/health` `engines: {kokoro, qwen3}` | `engines: {pocket}` |
| `__version__ == "2.1.1"` | `__version__ == "3.1.12"` |

## 2. Authentication

All `/v1/*` endpoints require `Authorization: Bearer cmdr_live_<43 chars>`
(API key issued via `comadre-keys issue-key`). Denials return the standard
envelope with `authentication_error` (401). Suspended/revoked/expired keys
carry the operator-contact hint.

## 3. Endpoints

### 3.1 `POST /v1/audio/speech`

JSON body:

```json
{"input": "Bom dia!", "voice": "pocket/rafael",
 "response_format": "ogg", "speed": 1.0, "temperature": 0.7, "seed": 42, "raw": false}
```

| Field | Type | Required | Constraints |
|---|---|---|---|
| `input` | string | yes | 1-1000 chars |
| `voice` | string | no | `pocket/<name>`; default `pocket/rafael` |
| `response_format` | string | no | `ogg` (Opus 24 kbps, 16 kHz mono `-application voip` — WhatsApp-compatible) or `mp3` (64 kbps, 44.1 kHz mono — WhatsApp-compatible) or `wav` (24 kHz mono) |
| `speed` | float | no | 0.25-4.0, applied as an ffmpeg `atempo` chain (factors in [0.5, 2.0]) |
| `temperature` | float | no | 0.1-2.0; sampling temperature — lower = more consistent, higher = more expressive (default 0.7) |
| `seed` | int | no | 0-2147483647; RNG seed for reproducible prosody — same text+voice+seed → identical audio |
| `raw` | bool | no | skip EQ/compression/noise/tempo/lead-silence (still encodes to the format) |

Response: audio bytes with `Content-Disposition: attachment;
`attachment; filename="comadre-<voice-slug>.<fmt>"` and `audio/ogg`,
`audio/mpeg` or `audio/wav` content type.

Unknown voice → 404 `not_found_error` with the available list.

### 3.2 `POST /v1/voices` — create a voice clone

Multipart form upload. Creates a clone of the uploaded voice; with
`persist=true` it is also stored on the server for future requests.
Dependencies run in order: `verify_ready` → per-IP gate (600/min, shared
with speech) → `verify_api_key` → per-key rate-limit bucket (same bucket
as speech). Clone encoding runs under the same FIFO queue lock as speech
(120 s timeout).

Form fields:

| Field | Type | Required | Constraints |
|---|---|---|---|
| `file` | file | yes | WAV, MP3, OGG (Vorbis/Opus), or FLAC — anything libsndfile reads; ≤ `VOICE_UPLOAD_MAX_MB` (10 MB) |
| `display_name` | string | no | ≤ 64 chars; alphanumeric, spaces, `-` `_` and apostrophe |
| `persist` | bool | no | default `false`; values `true/false/1/0` |

Duration rules: minimum **3 s** (reject below), recommended **5-20 s**,
hard maximum **30 s** (server truncates at 30 s — the library's
`truncate=True` behavior).

201 response:

```json
{"voice": "pocket/u_01J2K4M6N8P0Q2R4S6", "display_name": "Minha voz",
 "persisted": true, "duration_s": 8.4, "sample_rate": 24000,
 "expires_at": null}
```

`expires_at` is RFC 3339 UTC for ephemeral clones, `null` when persisted.

Errors:

| HTTP | `error.type` | Condition |
|---|---|---|
| 400 | `voice_upload_error` | missing/empty file, unsupported format, < 3 s, > 30 s |
| 413 | `voice_upload_error` | file larger than `VOICE_UPLOAD_MAX_MB` |
| 422 | `voice_upload_error` | audio decodes but is unreadable/corrupt |
| 429 | `voice_limit_error` | stored quota (20/customer) or ephemeral quota (5/key) |
| 429 | `rate_limit_error` | per-key RPM bucket (shared with speech) |
| 401 | `authentication_error` | invalid/suspended key |
| 503 | `service_unavailable` | warming up |
| 500 | `server_error` | state encoding failed |

### 3.3 `GET /v1/voices` — list voices visible to this key

Returns operator-provisioned voices (filesystem `/voices/pocket/*` with no
customer ownership) + the caller's stored clones + the caller's ephemeral
clones. Other customers' clones are never listed.

```json
{"voices": [
  {"voice": "pocket/rafael", "display_name": "Rafael", "persisted": true,
   "created_at": null, "expires_at": null},
  {"voice": "pocket/u_01J2K4M6N8P0Q2R4S6", "display_name": "Minha voz",
   "persisted": true, "created_at": "2026-08-18T10:00:00Z", "expires_at": null}
]}
```

### 3.4 `DELETE /v1/voices/{name}` — remove a clone

`{name}` is the full voice id, e.g. `/v1/voices/pocket/u_01J2K...`. A key
may delete only voices it created (stored clones are customer-owned,
ephemeral clones are key-owned). Operator voices are managed on the
filesystem.

- **204** No Content on success.
- **404** `not_found_error` — unknown voice.
- **403** `voice_delete_error` — not the caller's voice.

### 3.5 `GET /health`

```json
{"status": "healthy",
 "voices": ["pocket/rafael", "pocket/u_01J2K4M6N8P0Q2R4S6"],
 "engines": {"pocket": {"loaded": true, "voices": ["pocket/rafael", "..."]}},
 "queue_depth": 0, "uptime_seconds": 1234, "memory_mb": 1520,
 "version": "3.1.12"}
```

Unauthenticated callers get only `{status, voices}`. Ephemeral voices are
never listed in `/health` (they are per-key; use `GET /v1/voices`).

## 4. Error envelope

```json
{"error": {"type": "<error_type>", "message": "<human message>",
 "hint": "<remediation>"}}
```

Error types: `not_found_error`, `invalid_request_error`,
`authentication_error`, `rate_limit_error`, `service_unavailable`,
`server_error`, `method_not_allowed_error`, and (v3) `voice_upload_error`,
`voice_limit_error`, `voice_delete_error`.

## 5. Voice naming rules

- Operator-provisioned: `pocket/<name>`, `<name>` matches
  `^[a-zA-Z0-9_-]+$`, sourced from `/voices/pocket/<name>.wav` (reference)
  with optional precomputed `<name>.safetensors` + `<name>.json`.
- API uploads: `pocket/u_<ULID>` — the `u_` prefix is reserved; operators
  must not create `u_*` files.
- State files are model-variant-specific; a persisted clone stores its
  reference WAV so the state regenerates automatically when the model
  signature changes (`model_hash` in the metadata JSON).

## 6. Examples

```bash
# 1. Clone a voice (ephemeral, this session only)
curl -k -X POST https://localhost/v1/voices \
  -H "Authorization: Bearer cmdr_live_YOUR_PLAINTEXT" \
  -F "file=@minha-voz.wav" -F "display_name=Minha voz"

# 2. Clone and store for future use
curl -k -X POST https://localhost/v1/voices \
  -H "Authorization: Bearer cmdr_live_YOUR_PLAINTEXT" \
  -F "file=@minha-voz.wav" -F "persist=true"

# 3. Speak with the clone (use the returned voice)
curl -k -X POST https://localhost/v1/audio/speech \
  -H "Authorization: Bearer cmdr_live_YOUR_PLAINTEXT" \
  -H "Content-Type: application/json" \
  -d '{"input":"Olá! Esta é a minha voz clonada.","voice":"pocket/u_01J2K4M6N8P0Q2R4S6"}' \
  --output clone.ogg

# 4. List + delete
curl -k https://localhost/v1/voices -H "Authorization: Bearer cmdr_live_YOUR_PLAINTEXT"
curl -k -X DELETE https://localhost/v1/voices/pocket/u_01J2K4M6N8P0Q2R4S6 \
  -H "Authorization: Bearer cmdr_live_YOUR_PLAINTEXT"
```

**n8n HTTP Request nodes:** speech — JSON body as v2 (change `voice` to
`pocket/...`). Clone — `Method: POST`, `Send Body → Form-Data`, fields
`file` (binary data item) + `persist` (`true`), then use the response's
`voice` in the next speech node's `voice` field.
