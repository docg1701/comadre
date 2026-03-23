# CUMADRE API & Architecture Specification

**Date:** 2026-03-23
**Status:** Definitive specification for implementation
**Last updated:** 2026-03-23

## Overview

CUMADRE is a self-hosted pt-BR TTS API for WhatsApp automation via n8n. Dual-engine: Kokoro (fast, no cloning) and Qwen3-TTS C++ (voice cloning). Single FIFO queue per instance, horizontal scaling via Caddy load balancer.

## API Endpoint

### `POST /v1/audio/speech`

OpenAI-compatible endpoint. n8n sends text, receives audio.

#### Request

```json
{
  "input": "O INSS confirmou que o seu benefício BPC LOAS foi concedido.",
  "voice": "santa",
  "response_format": "ogg",
  "speed": 1.0,
  "enhance": true,
  "seed": -1
}
```

#### Parameters

| Parameter | Type | Required | Default | Values | Description |
|---|---|---|---|---|---|
| `input` | string | Yes | — | max 500 chars (Kokoro) / 300 chars (Qwen3) | Text to synthesize in pt-BR |
| `voice` | string | Yes | — | `santa`, `dora`, `alex`, `clone`, `qwen-female`, `qwen-male` | Voice selection (determines engine) |
| `response_format` | string | No | `"ogg"` | `ogg`, `wav` | Output format |
| `speed` | float | No | `1.0` | 0.5 — 2.0 | Speed multiplier (stacks with enhance speed) |
| `enhance` | bool | No | `true` | true/false | Apply post-processing pipeline |
| `seed` | int | No | `-1` | -1 or any positive int | Qwen3 random seed (-1 = random). Ignored for Kokoro. |

#### Engine routing (fixed, based on `voice`)

| voice | Engine | Behavior |
|---|---|---|
| `santa` | Kokoro fp32 + pm_santa | Fast (RTF 1.1x), perfect siglas via espeak-ng pt_extra |
| `dora` | Kokoro fp32 + pf_dora | Female voice, fast |
| `alex` | Kokoro fp32 + pm_alex | Male alternative, fast |
| `clone` | Qwen3 C++ Q8_0 + pre-configured reference audio | Voice cloning (RTF 2.5x) |
| `qwen-female` | Qwen3 C++ Q8_0, no reference | Natural female voice |
| `qwen-male` | Qwen3 C++ Q8_0, no reference | Natural male voice |

#### Preprocessing (automatic, not configurable)

**Kokoro path:**
- `normalize_text()`: numbers, currency (R$), dates (dd/mm/yyyy), times (HH:MM) → pt-BR words
- `chunk_text()`: split at sentence boundaries, max 200 tokens per chunk
- Siglas handled natively by espeak-ng custom `pt_extra` dictionary (67 entries)

**Qwen3 path:**
- `expand_siglas()`: CNPJ → `C N P J`, INSS → `I N S S` (spaced format for spelled siglas)
- Word acronyms kept as-is: SUS, PIX, PIS, LOAS, CEP, DETRAN, ENEM, SAMU, ANVISA
- Siglas must be embedded between normal words (never start sentence with spelled sigla)

#### Post-processing (`enhance=true`)

**Kokoro pipeline (vibrato_warm):**
```
vibrato(4.5Hz, 6%) → highpass(80Hz) → bass(+3dB) →
EQ(+1.5dB@200Hz, -2dB@700Hz, +2dB@2.5kHz, -2dB@6kHz) →
exciter(4.5kHz, drive=3.5) → softclip(tanh) →
compressor(4:1) → lowpass(8kHz) → echo(40ms, 0.12) →
loudnorm(-18 LUFS) → noise(room=0.45, hiss=0.24) →
loudnorm(-17 LUFS) → OGG Opus 24kbps 16kHz mono
```

**Qwen3 pipeline (whatsapp-subtle):**
```
highpass(100Hz) → EQ(+1.5dB@200Hz, -2dB@700Hz, +3dB@3kHz, -4dB@7kHz) →
compressor(6:1) → lowpass(8kHz) → echo(40ms, 0.12) →
atempo(1.15x) → loudnorm(-18 LUFS) →
noise(room=0.15, hiss=0.08) → loudnorm(-17 LUFS) →
OGG Opus 24kbps 16kHz mono
```

**`speed` parameter stacks with enhance:** If `enhance=true` and Qwen3, the enhance applies 1.15x. Then `speed=1.1` results in 1.15 × 1.1 = 1.265x total. For Kokoro, enhance does not change speed, so `speed` is applied directly.

#### Response

```
HTTP 200
Content-Type: audio/ogg (or audio/wav)
Body: [audio bytes]
```

#### Errors

| Code | Condition |
|---|---|
| 400 | `input` empty or exceeds character limit |
| 400 | `voice` not recognized |
| 401 | Invalid or missing API_KEY |
| 500 | TTS generation failed |
| 503 | Engine not loaded |

### `GET /health`

```json
{
  "status": "healthy",
  "engines": {
    "kokoro": {"loaded": true, "voices": ["santa", "dora", "alex"]},
    "qwen3": {"loaded": true, "model": "q8_0", "clone_reference": "configured"}
  },
  "queue_depth": 3
}
```

### Authentication

```
Authorization: Bearer <API_KEY>
```

API_KEY configured via environment variable. Single key per instance.

## Queue Architecture

### Design: Single FIFO queue per instance

```python
lock = asyncio.Lock()

@app.post("/v1/audio/speech")
async def speech(request: SpeechRequest):
    async with lock:  # One generation at a time, FIFO order
        audio = await run_in_executor(generate_audio, request)
    return Response(content=audio, media_type="audio/ogg")
```

- No Redis, no Celery, no external queue
- `asyncio.Lock` ensures FIFO ordering
- FastAPI keeps HTTP connection open until audio is ready
- n8n waits for response (timeout configurable, default 300s)

### Why this is sufficient

- WhatsApp conversations are async — users don't expect instant responses
- Kokoro generates 5s audio in 5.5s — fast enough for sequential processing
- The queue depth is visible via `/health` endpoint for monitoring
- No complex infrastructure to maintain

### Capacity per VPS (4 CPU, 8 GB RAM)

| Engine | Time per request | Throughput | Max comfortable conversations |
|---|---|---|---|
| Kokoro | ~5.5s | ~10 req/min | ~15-20 |
| Qwen3 | ~12.5s | ~4.8 req/min | ~5-8 |

### Realistic queue behavior

Requests don't arrive simultaneously — they're spread across time because WhatsApp conversations have natural pauses (user reading, typing, thinking). Each conversation generates ~1 request every 30-60 seconds.

**Example: 15 conversations with Kokoro**
- Average request arrival: 1 every 2-4 seconds
- Kokoro processes 1 every 5.5 seconds
- Queue depth oscillates between 0-3 (rarely peaks above 4)
- Typical latency: 5.5s (no queue) to 16s (2-3 in queue)
- Burst scenario (rare): 5+ simultaneous → 27s max wait

**Example: 8 conversations with Qwen3**
- Average request arrival: 1 every 4-7 seconds
- Qwen3 processes 1 every 12.5 seconds
- Queue depth oscillates between 0-2
- Typical latency: 12.5s to 37s
- Burst scenario (rare): 4+ simultaneous → 50s max wait

### Theoretical worst-case (all requests arrive at once)

| Queue depth | Kokoro wait | Qwen3 wait |
|---|---|---|
| 1 | 5.5s | 12.5s |
| 5 | 27.5s | 62.5s |
| 10 | 55s | 125s |

These worst-case numbers rarely occur in practice due to the natural spacing of WhatsApp conversations.

## Horizontal Scaling

When a single instance isn't enough, add more VPS instances behind Caddy.

### Architecture

```
n8n (any server)
    │
    │ POST /v1/audio/speech
    ▼
Caddy (reverse proxy + load balancer)
    │
    ├── VPS 1: cumadre instance (own FIFO queue)
    ├── VPS 2: cumadre instance (own FIFO queue)
    └── VPS N: cumadre instance (own FIFO queue)
```

### Caddy configuration

```caddyfile
tts.example.com {
    reverse_proxy {
        to vps1.internal:8000 vps2.internal:8000
        lb_policy round_robin
        health_uri /health
        health_interval 30s
    }
}
```

### Scaling rules

| Conversations | Kokoro instances | Qwen3 instances |
|---|---|---|
| < 15 | 1 | 1 |
| 15-30 | 2 | 2-3 |
| 30-60 | 3-4 | 4-6 |
| 60+ | Auto-scale | Auto-scale |

Each instance is independent — own model loaded, own queue, own processing. No shared state. Adding/removing instances requires only Caddy config update.

### Failover pattern (n8n-side)

When a cumadre instance times out, the n8n workflow handles failover — not the load balancer. This gives the workflow control over retry logic and alerting.

```
n8n workflow:
    │
    ├── HTTP Request to cumadre primary (timeout: 120s)
    │   ├── Success → send audio to WhatsApp
    │   └── Timeout/Error ─┐
    │                       ▼
    │   HTTP Request to cumadre backup (timeout: 120s)
    │   ├── Success → send audio to WhatsApp
    │   └── Timeout/Error → send text message instead + alert sysop
    │
    └── On any failover: notify sysop (Slack/email/webhook)
        "cumadre primary overloaded, failover triggered"
```

**Why n8n-side failover (not Caddy):**
- n8n can alert the sysop about overload
- n8n can fall back to text message if both instances fail
- n8n controls retry logic per conversation context
- Caddy round-robin doesn't know about queue depth or overload

**n8n timeout configuration:**
- Primary request: 120 seconds (enough for ~20 in queue with Kokoro)
- Backup request: 120 seconds
- Total worst case: 240 seconds (within n8n's 300s workflow timeout)

### When to use Caddy load balancer vs n8n failover

| Scenario | Approach |
|---|---|
| Predictable high volume (always 30+ conversations) | Caddy load balancer across N instances |
| Normal volume with occasional spikes | n8n failover to backup instance |
| Mixed: high volume + need for alerting | Both: Caddy for primary pool + n8n failover to separate backup |

## Voice Cloning Configuration

Voice cloning reference audio is **pre-configured on the server**, not uploaded per request.

### Setup (done by DevOps at deploy time)

1. Place reference WAV in `/app/voices/clone-reference.wav`
2. Set `CLONE_REFERENCE=/app/voices/clone-reference.wav` in environment
3. When `voice=clone` is requested, Qwen3 uses this reference

### Consistency

- Same reference audio + same seed = same voice characteristics
- The seed can be set per request (`seed` parameter) or left random (`-1`)
- For consistent bot personality, the n8n workflow should send the same `seed` value for all messages in a conversation

## Docker Compose

```yaml
services:
  cumadre:
    build: .
    ports:
      - "8000:8000"
    environment:
      - API_KEY=${API_KEY}
      - DEFAULT_VOICE=santa
      - CLONE_REFERENCE=/app/voices/clone-reference.wav
      - ESPEAK_DATA_PATH=/usr/local/share/espeak-ng-data
    volumes:
      - ./voices:/app/voices:ro
    restart: unless-stopped
```

No Redis. No workers. Single container.

## Character Limits

| Engine | Max chars | Rationale |
|---|---|---|
| Kokoro | 500 | Chunked internally at 200 tokens; 500 chars ≈ 2-3 chunks |
| Qwen3 | 300 | No chunking; longer text = longer generation + risk of runaway |

Exceeding the limit returns HTTP 400 with error message.

## File Dependencies

### Kokoro

| File | Source | Size |
|---|---|---|
| `kokoro-v1.0.onnx` | thewh1teagle/kokoro-onnx releases | 325 MB |
| `voices-v1.0.bin` | thewh1teagle/kokoro-onnx releases | 27 MB |
| `pt_dict` + phoneme files | Compiled espeak-ng with pt_extra | 141 KB + ~660 KB |
| `pt_extra` | `deploy/espeak-ng/pt_extra` in this repo | 3 KB |

### Qwen3

| File | Source | Size |
|---|---|---|
| `qwen3-tts-0.6b-q8_0.gguf` | Converted via qwen3-tts.cpp scripts | 1.3 GB |
| `qwen3-tts-tokenizer-f16.gguf` | Converted via qwen3-tts.cpp scripts | 341 MB |
| `qwen3-tts-cli` | Built from predict-woo/qwen3-tts.cpp + seed patch | ~600 KB |

### Post-processing

| File | Source | Size |
|---|---|---|
| `noise-room-tone.wav` | Generated via ffmpeg (anoisesrc pink) | ~1 MB |
| `noise-mic-hiss.wav` | Generated via ffmpeg (anoisesrc white) | ~1 MB |
| `ffmpeg` | System package | — |
