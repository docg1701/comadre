# API Reference

Comadre exposes an OpenAI-compatible TTS endpoint and a health endpoint.

## Authentication

All requests to `/v1/audio/speech` require a Bearer token in the `Authorization` header. The token must match the `API_KEY` environment variable.

```text
Authorization: Bearer YOUR_API_KEY
```

The `/health` endpoint does not require authentication.

## POST /v1/audio/speech

Generate speech audio from text input.

### Request

**Headers:**

| Header | Required | Value |
| --- | --- | --- |
| `Authorization` | Yes | `Bearer YOUR_API_KEY` |
| `Content-Type` | Yes | `application/json` |

**Body:**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `input` | string | Yes | -- | Text to synthesize (1-500 chars for Kokoro, 1-300 chars for Qwen3) |
| `voice` | string | No | per `DEFAULT_VOICE` env var (default: `kokoro/pm_santa`) | Voice name in `engine/name` format (see voice routing table below and [voice-management.md](voice-management.md)) |
| `response_format` | string | No | `ogg` | Output format: `ogg` or `wav` |
| `speed` | float | No | `1.0` | Speed multiplier: 0.25 to 4.0. Accepted by schema but not yet applied by engines. |
| `destination` | string | No | `whatsapp` | Target platform: `whatsapp`, `telegram`, `messenger`, or `instagram`. Accepted by schema but not yet applied -- all output currently uses OGG Opus regardless of destination. |
| `raw` | boolean | No | `false` | Skip audio post-processing (vibrato, EQ, compression, echo, noise mixing). Returns the raw TTS engine output encoded to the requested format. Useful for testing or custom downstream processing. |

### Voice Routing

The `voice` parameter determines which TTS engine processes the request:

| Voice | Engine | Character Limit | Typical Latency (4 vCPU) |
| --- | --- | --- | --- |
| `kokoro/pm_santa` (M) | Kokoro fp32 | 500 | 5-16s |
| `kokoro/pf_dora` (F) | Kokoro fp32 | 500 | 5-16s |
| `kokoro/pm_alex` (M) | Kokoro fp32 | 500 | 5-16s |
| `kokoro/<name>` | Kokoro fp32 | 500 | 5-16s |
| `qwen/<name>` | Qwen3-TTS C++ Q8_0 | 300 | 12-37s |

Voices are discovered from the filesystem. See [voice-management.md](voice-management.md) for how to add or list voices.

### Engine-Specific Preprocessing

Each engine applies different text preprocessing before synthesis:

**Kokoro:**

- `normalize_text()` -- normalizes Unicode, expands abbreviations
- `chunk_text()` -- splits long text into chunks for sequential synthesis
- espeak-ng pt_extra dictionary -- handles sigla pronunciation (CPF, CNPJ, FGTS, etc.) via 67 custom dictionary entries

**Qwen3:**

- `expand_siglas()` -- converts siglas to spaced letter format (e.g., `CNPJ` becomes `C N P J`) for correct pronunciation

### Post-Processing Pipelines

Each engine has a dedicated audio post-processing pipeline applied before output:

**vibrato_warm (Kokoro):** vibrato effect, EQ shaping, exciter, dynamic compression, echo, room/hiss noise layer.

**whatsapp-subtle (Qwen3):** EQ shaping, dynamic compression, atempo 1.15x speed adjustment, echo, room/hiss noise layer.

Both pipelines produce the final audio optimized for messaging platform voice notes.

### Platform Output Formats

The `destination` parameter is intended to control the output audio format. Currently all destinations produce OGG Opus. The planned format mapping is:

| Destination | Planned Format | Sample Rate | Bitrate | Channels |
| --- | --- | --- | --- | --- |
| `whatsapp` | OGG Opus | 16kHz | 24kbps | Mono |
| `telegram` | OGG Opus | 16kHz | 24kbps | Mono |
| `messenger` | OGG Opus | 16kHz | 24kbps | Mono |
| `instagram` | AAC M4A | 44.1kHz | 64kbps | Mono |

### Success Response

**Status:** 200 OK

**Headers:**

- `Content-Type: audio/ogg` (for OGG Opus) or `Content-Type: audio/wav` (for WAV)

**Body:** Binary audio data.

### Error Responses

All errors return JSON with this structure:

```json
{
  "error": {
    "message": "description of what went wrong",
    "type": "error_type_identifier",
    "hint": "actionable recovery instructions"
  }
}
```

**400 -- Invalid Request:**

```json
{
  "error": {
    "message": "Input exceeds 300 character limit for Qwen3 engine (voice 'qwen/galvani')",
    "type": "invalid_request_error",
    "hint": "Reduce text length or switch to a Kokoro voice (kokoro/pm_santa, kokoro/pf_dora, kokoro/pm_alex) which supports up to 500 characters."
  }
}
```

**401 -- Authentication Error:**

Missing or malformed `Authorization` header:

```json
{
  "error": {
    "message": "Missing or malformed Authorization header",
    "type": "authentication_error",
    "hint": "Check the API_KEY environment variable and ensure your Authorization header uses 'Bearer <key>'."
  }
}
```

Wrong API key:

```json
{
  "error": {
    "message": "Invalid or missing API key",
    "type": "authentication_error",
    "hint": "Check the API_KEY environment variable and ensure your Authorization header uses 'Bearer <key>'."
  }
}
```

**404 -- Voice Not Found:**

```json
{
  "error": {
    "message": "Voice 'unknown' not found",
    "type": "not_found_error",
    "hint": "Available voices: ['kokoro/pf_dora', 'kokoro/pm_alex', 'kokoro/pm_santa', 'qwen/female', 'qwen/galvani']. Use engine/name format. See /health for the current list."
  }
}
```

**429 -- Rate Limit Exceeded:**

```json
{
  "error": {
    "message": "Rate limit exceeded",
    "type": "rate_limit_error",
    "hint": "Too many requests. Try again in 60 seconds."
  }
}
```

The 429 response includes a `Retry-After` header. Default limits: 30 req/min for speech (per client IP), 60 req/min for health. Configurable via `RATE_LIMIT_SPEECH` and `RATE_LIMIT_HEALTH` environment variables.

**500 -- Server Error:**

```json
{
  "error": {
    "message": "An internal server error occurred",
    "type": "server_error",
    "hint": "Check server logs for the full traceback. The TTS model may need restarting."
  }
}
```

**503 -- Service Unavailable:**

```json
{
  "error": {
    "message": "Service is warming up",
    "type": "service_unavailable",
    "hint": "The service is still loading models. Retry in 30 seconds."
  }
}
```

The 503 response includes a `Retry-After` header with the recommended wait time in seconds.

## GET /health

Returns service health status. No authentication required.

### Success Response (200)

```json
{
  "status": "healthy",
  "voices": ["kokoro/pf_dora", "kokoro/pm_alex", "kokoro/pm_santa", "qwen/female", "qwen/galvani"],
  "engines": {
    "kokoro": {"loaded": true, "voices": ["kokoro/pf_dora", "kokoro/pm_alex", "kokoro/pm_santa"]},
    "qwen3": {"loaded": true, "voices": ["qwen/female", "qwen/galvani"]}
  },
  "queue_depth": 0,
  "uptime_seconds": 3600,
  "memory_mb": 4200,
  "version": "1.5.0"
}
```

### Warming Up Response (503)

Returned while models are still loading after startup:

```json
{
  "status": "warming_up",
  "voices": [],
  "engines": {},
  "queue_depth": 0,
  "uptime_seconds": 15,
  "memory_mb": 800,
  "version": "1.5.0"
}
```

### Status Values

| Status | HTTP Code | Meaning |
| --- | --- | --- |
| `healthy` | 200 | All engines loaded, service ready |
| `warming_up` | 503 | Models still downloading or loading |

## Voice Cloning

Qwen3-TTS voices use reference WAV files for voice cloning. Voices are discovered from the `/voices/qwen/` directory -- no environment variable configuration needed. For detailed setup instructions, see [voice-management.md](voice-management.md).

**How it works:**

1. Place a reference WAV (3-10s of clear speech) in `/voices/qwen/`
2. The voice is immediately available as `qwen/<filename-without-extension>`
3. No restart needed -- voices are discovered at request time

**Seed reproducibility:** Qwen3-TTS uses a fixed seed for consistent voice characteristics. The same text + reference WAV + seed produces similar results across runs.

**No Qwen3 voices:** If no WAV files are present in `/voices/qwen/`, no Qwen3 voices will appear in the `/health` endpoint. Requests for missing voices return a 404 error.

## Examples

**Kokoro request (fast, built-in voice):**

```bash
curl -X POST http://YOUR_VPS_IP:8000/v1/audio/speech \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"input":"Bom dia, como posso ajudar?", "voice":"kokoro/pm_santa"}' \
  --output test.ogg
```

**Qwen3 request (cloned voice):**

```bash
curl -X POST http://YOUR_VPS_IP:8000/v1/audio/speech \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"input":"Seu CPF foi validado com sucesso.", "voice":"qwen/galvani"}' \
  --output test_clone.ogg
```

**Instagram destination (AAC M4A output):**

```bash
curl -X POST http://YOUR_VPS_IP:8000/v1/audio/speech \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"input":"Confira nosso novo produto!", "voice":"kokoro/pf_dora", "destination":"instagram"}' \
  --output test.m4a
```

*Note: the `destination` parameter is not yet implemented. This request currently outputs OGG Opus regardless of the destination value.*

**Missing authentication (error example):**

```bash
curl -X POST http://YOUR_VPS_IP:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"input":"Teste sem autenticacao."}'
```

Response (401):

```json
{
  "error": {
    "message": "Missing or malformed Authorization header",
    "type": "authentication_error",
    "hint": "Check the API_KEY environment variable and ensure your Authorization header uses 'Bearer <key>'."
  }
}
```

**Health check:**

```bash
curl http://YOUR_VPS_IP:8000/health
```
