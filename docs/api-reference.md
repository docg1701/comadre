# API Reference

CUMADRE exposes an OpenAI-compatible TTS endpoint and a health endpoint.

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
| `voice` | string | No | per `DEFAULT_VOICE` env var (default: `santa`) | Voice name (see voice routing table below) |
| `response_format` | string | No | `ogg` | Output format: `ogg` or `wav` |
| `speed` | float | No | `1.0` | Speed multiplier: 0.25 to 4.0. Accepted by schema but not yet applied by engines. |
| `destination` | string | No | `whatsapp` | Target platform: `whatsapp`, `telegram`, `messenger`, or `instagram`. Accepted by schema but not yet applied -- all output currently uses OGG Opus regardless of destination. |

### Voice Routing

The `voice` parameter determines which TTS engine processes the request:

| Voice | Engine | Character Limit | Typical Latency (4 vCPU) |
| --- | --- | --- | --- |
| `santa` (M) | Kokoro fp32 | 500 | 5-16s |
| `dora` (F) | Kokoro fp32 | 500 | 5-16s |
| `alex` (M) | Kokoro fp32 | 500 | 5-16s |
| `clone` | Qwen3-TTS C++ Q8_0 | 300 | 12-37s |
| `qwen-female` | Qwen3-TTS C++ Q8_0 | 300 | 12-37s |
| `qwen-male` | Qwen3-TTS C++ Q8_0 | 300 | 12-37s |

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
    "message": "Input exceeds 300 character limit for Qwen3 engine (voice 'clone')",
    "type": "invalid_request_error",
    "hint": "Reduce text length or switch to a Kokoro voice (santa, dora, alex) which supports up to 500 characters."
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
    "hint": "Available voices: ['santa', 'dora', 'alex', 'clone', 'qwen-female', 'qwen-male']. Place WAV files (3-10s) in the /voices/ directory."
  }
}
```

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
  "voices": ["santa", "dora", "alex", "clone", "qwen-female", "qwen-male"],
  "engines": {
    "kokoro": {"loaded": true, "voices": ["santa", "dora", "alex"]},
    "qwen3": {"loaded": true, "clone_configured": true, "voices": ["clone", "qwen-female", "qwen-male"]}
  },
  "queue_depth": 0,
  "clone_configured": true,
  "uptime_seconds": 3600,
  "memory_mb": 4200,
  "version": "0.1.0"
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
  "clone_configured": false,
  "uptime_seconds": 15,
  "memory_mb": 800,
  "version": "0.1.0"
}
```

### Status Values

| Status | HTTP Code | Meaning |
| --- | --- | --- |
| `healthy` | 200 | All engines loaded, service ready |
| `warming_up` | 503 | Models still downloading or loading |

## Voice Cloning

Voice cloning uses Qwen3-TTS with a pre-configured reference WAV file. The reference audio is placed on the server at deploy time, not uploaded per-request.

**How it works:**

1. A reference WAV (3-10s of clear speech) is placed in the voices volume
2. `CLONE_REFERENCE_PATH` environment variable points to the WAV file
3. Requests with `"voice": "clone"` use this reference for synthesis

**Seed reproducibility:** Qwen3-TTS uses a fixed seed for consistent voice characteristics. The same text + reference WAV + seed produces similar results across runs.

**Clone disabled:** If `CLONE_REFERENCE_PATH` is not set, the `clone` voice is unavailable. The `/health` endpoint reports `clone_configured: false`. Requests for the `clone` voice return a 404 error.

## Examples

**Kokoro request (fast, built-in voice):**

```bash
curl -X POST http://YOUR_VPS_IP:8000/v1/audio/speech \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"input":"Bom dia, como posso ajudar?", "voice":"santa"}' \
  --output test.ogg
```

**Qwen3 request (cloned voice):**

```bash
curl -X POST http://YOUR_VPS_IP:8000/v1/audio/speech \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"input":"Seu CPF foi validado com sucesso.", "voice":"clone"}' \
  --output test_clone.ogg
```

**Instagram destination (AAC M4A output):**

```bash
curl -X POST http://YOUR_VPS_IP:8000/v1/audio/speech \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"input":"Confira nosso novo produto!", "voice":"dora", "destination":"instagram"}' \
  --output test.m4a
```

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
