# CUMADRE — Implementation Guide

> **CUMADRE** = **Cu**madre **M**anda **A**udio **D**ireto, **R**apido e **E**ficiente

Self-hosted text-to-speech service with voice cloning, optimized for automated customer service responses in Brazilian Portuguese. Integrates with customer support platforms via n8n to convert LLM text responses into audio messages using a cloned human voice.

---

## What is KokoClone

KokoClone is a complete, self-contained TTS solution with voice cloning. When you install KokoClone, you get:

| Component | Purpose | Shipped as |
|---|---|---|
| **Kokoro-ONNX** (82M params) | Generates speech from text | pip dependency |
| **Kanade** (120M params) | Converts generated voice to the cloned voice | pip dependency (GitHub) |
| **Vocoder** (Vocos 24kHz) | Synthesizes final audio | included in Kanade |
| **Misaki** | Phonemizer (en, ja, zh; pt via espeak-ng) | pip dependency |
| **Gradio UI** | Web interface for testing | pip dependency |

There is no other project to install. No need for Kokoro-FastAPI or anything separate. KokoClone's `pip install -r requirements.txt` brings everything.

### Internal pipeline (per request)

```
Text → Kokoro TTS (generates speech with base voice) → Kanade (converts to cloned voice) → WAV audio
```

Both steps run on every request. The employee reference audio (3-10s WAV) is loaded and processed by Kanade on each generation. There is no persistent voice profile — it is pure zero-shot.

### What KokoClone does NOT have

- **REST API** — only Gradio UI, CLI, and Python API
- **Dockerfile** — none exists in the repository
- **Releases/versions** — no published GitHub releases

Therefore, the implementation work is:
1. Write a thin FastAPI wrapper (~80 lines) on top of the Python API
2. Write a Dockerfile
3. Write a docker-compose.yml
4. Configure n8n to call the endpoint

---

## Estimated Resources

### Disk

| Item | Size |
|---|---|
| Kokoro ONNX (82M params) | ~300-400 MB |
| Kanade + Vocoder (120M params) | ~500 MB - 1 GB |
| PyTorch CPU + Python dependencies | ~1-1.5 GB |
| Voice models (.bin) | ~50-100 MB |
| **Total** | **~2-3 GB** |

Models are downloaded automatically from HuggingFace on first run. No manual download required.

### RAM

| Item | Usage |
|---|---|
| Kokoro ONNX in memory | ~400-600 MB |
| Kanade + Vocoder in memory | ~600 MB - 1 GB |
| PyTorch runtime + buffers | ~300-500 MB |
| FastAPI + overhead | ~100 MB |
| **Estimated total** | **~1.5-2.5 GB** |

KokoClone caches the Kokoro model per language (`self.kokoro_cache`), so after the first pt-BR generation, subsequent ones do not reload the model.

### CPU

Kokoro ONNX uses configurable threads. Kanade uses PyTorch CPU. For short phrases of ~15 words:

| Step | Estimated time (4 vCPU) |
|---|---|
| Kokoro TTS (generate base speech) | ~200-500 ms |
| Kanade voice conversion | ~500 ms - 2 s |
| **Total per request** | **~1-3 s** |

**Estimated throughput: 20-60 req/min** on 4 vCPUs. This is an estimate — no published benchmarks exist for KokoClone on CPU. Actual values must be measured on the VPS.

**Important note:** The 200-400 req/min throughput mentioned in the previous guide was for Kokoro-FastAPI alone (without Kanade). With KokoClone's extra voice conversion step, throughput is significantly lower. If 20-60 req/min is insufficient for actual demand, the options are:
- Run 2 workers (doubles throughput, doubles RAM to ~4-5 GB)
- Cache frequent responses (reduces actual TTS calls)
- Add a GPU to the VPS

### Resource distribution on VPS (4 vCPU / 8 GB RAM)

| Service | CPU | RAM |
|---|---|---|
| TTS Service (KokoClone + FastAPI) | 2-3 vCPUs | 2-3 GB |
| n8n | 0.5-1 vCPU | 0.5-1 GB |
| OS + overhead | 0.5 vCPU | 0.5 GB |
| **Total** | **~4 vCPUs** | **~3-4.5 GB** |
| **Available** | — | **~3.5-5 GB** |

RAM headroom is comfortable. Adding Chatwoot+Postgres+Redis in Phase 4 (+1.5-2 GB) still fits.

---

## Architecture

```
┌────────────────────────────────────────────────────────┐
│                  VPS (4 vCPU / 8 GB RAM)               │
│                                                         │
│  ┌──────────────┐     ┌──────────────────────────┐     │
│  │     n8n      │     │    TTS Service (FastAPI)  │     │
│  │              │────>│                           │     │
│  │  Workflows:  │     │  KokoClone engine:        │     │
│  │  - STT(Groq) │     │    Kokoro (TTS)           │     │
│  │  - LLM       │     │    + Kanade (voice conv.) │     │
│  │  - TTS call  │<────│                           │     │
│  │  - Telegram  │     │  POST /v1/audio/speech    │     │
│  │  - Chatwoot  │     │  GET  /health             │     │
│  └──────────────┘     └──────────────────────────┘     │
│                                                         │
│  voices/employee.wav   (single file, copied once)       │
└────────────────────────────────────────────────────────┘
```

### Full flow (customer audio → response audio)

```
1. Customer sends audio (WhatsApp/Telegram/etc)
2. n8n receives via webhook/trigger
3. n8n detects audio → downloads the file
4. n8n sends audio to Groq Whisper (STT) → receives text
5. n8n sends text to LLM → receives text response
6. n8n sends POST /v1/audio/speech with the response text
7. TTS Service: Kokoro generates base speech → Kanade converts to cloned voice
8. TTS Service returns WAV/OGG audio
9. n8n sends audio back to customer
```

---

## Implementation

### Project structure

```
kokoclone-service/
├── docker-compose.yml
├── tts-service/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── server.py              # FastAPI wrapper (~80 lines)
│   └── voices/
│       └── employee.wav       # Reference audio (3-10s)
```

### requirements.txt

```
# TTS + Voice Cloning (KokoClone and its dependencies)
torch --index-url https://download.pytorch.org/whl/cpu
torchaudio --index-url https://download.pytorch.org/whl/cpu
kokoro-onnx
misaki[en,ja,zh]
git+https://github.com/frothywater/kanade-tokenizer
soundfile
huggingface_hub
numpy

# API Server
fastapi
uvicorn[standard]
python-multipart
```

**Note:** These requirements are based on KokoClone's official `requirements.txt` [1]. At build time, verify whether the original repository has been updated.

### server.py

```python
"""
TTS Service: FastAPI wrapper on top of KokoClone's Python API.
Single relevant endpoint: POST /v1/audio/speech (OpenAI-compatible).
"""
import io
import os
import time
import logging
from pathlib import Path
from contextlib import asynccontextmanager

import soundfile as sf
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("tts")

VOICES_DIR = Path(os.getenv("VOICES_DIR", "/app/voices"))
DEFAULT_VOICE = os.getenv("DEFAULT_VOICE", "employee")
PORT = int(os.getenv("PORT", "8880"))

engine = None  # KokoClone instance


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine
    # Import here to avoid breaking if dependencies are missing
    from core.cloner import KokoClone

    log.info("Loading KokoClone (Kokoro + Kanade)...")
    engine = KokoClone()

    # Warm up: first generation loads models and is slower
    ref = VOICES_DIR / f"{DEFAULT_VOICE}.wav"
    if ref.exists():
        log.info(f"Warming up with default voice: {ref}")
        engine.generate("Test.", lang="pt", reference_audio=str(ref), output_path="/tmp/_warmup.wav")
        os.unlink("/tmp/_warmup.wav")
        log.info("Warm-up complete.")
    else:
        log.warning(f"Default voice not found at {ref}")

    yield
    log.info("Shutting down TTS Service.")


app = FastAPI(title="KokoClone TTS Service", lifespan=lifespan)


class SpeechRequest(BaseModel):
    model: str = "kokoclone"
    input: str
    voice: str = DEFAULT_VOICE
    response_format: str = "wav"


@app.get("/health")
def health():
    voices = [f.stem for f in VOICES_DIR.glob("*.wav")]
    return {"status": "ok", "engine": "kokoclone", "voices": voices}


@app.post("/v1/audio/speech")
def speech(req: SpeechRequest):
    if not req.input.strip():
        raise HTTPException(400, "Empty text")

    ref = VOICES_DIR / f"{req.voice}.wav"
    if not ref.exists():
        raise HTTPException(404, f"Voice '{req.voice}' not found in {VOICES_DIR}")

    out_path = f"/tmp/tts_{os.getpid()}_{time.time_ns()}.wav"
    t0 = time.perf_counter()

    try:
        engine.generate(
            text=req.input,
            lang="pt",
            reference_audio=str(ref),
            output_path=out_path,
        )
        elapsed = time.perf_counter() - t0
        data, sr = sf.read(out_path)
        duration = len(data) / sr
        log.info(f"Generated {duration:.1f}s of audio in {elapsed:.2f}s (RTF {elapsed/duration:.2f})")

        buf = io.BytesIO()
        fmt = "OGG" if req.response_format == "ogg" else "WAV"
        subtype = "VORBIS" if fmt == "OGG" else None
        sf.write(buf, data, sr, format=fmt, subtype=subtype)
        buf.seek(0)

        media = "audio/ogg" if fmt == "OGG" else "audio/wav"
        return Response(content=buf.read(), media_type=media)
    finally:
        if os.path.exists(out_path):
            os.unlink(out_path)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT, workers=1)
```

**About the code:**
- `workers=1` because KokoClone loads models in memory and shares `self.kokoro_cache`. Multiple workers would load duplicate models.
- The warm-up on startup loads all models into memory and prevents the first real request from taking 10-30s.
- `engine.generate()` is exactly KokoClone's public API, as documented in its README and confirmed in the source code [1][2].
- The endpoint returns WAV by default. For Telegram voice notes, use `response_format: ogg`.

### Dockerfile

```dockerfile
FROM python:3.12-slim

# espeak-ng for pt-BR phonemization + ffmpeg + libsndfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    espeak-ng libespeak-ng-dev ffmpeg libsndfile1 git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Clone KokoClone (gets core/, model/, voice/ etc.)
RUN git clone --depth 1 https://github.com/Ashish-Patnaik/kokoclone.git /tmp/kokoclone \
    && cp -r /tmp/kokoclone/core /app/core \
    && rm -rf /tmp/kokoclone

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Server
COPY server.py .

# Voices directory (mounted as volume)
RUN mkdir -p /app/voices

ENV VOICES_DIR=/app/voices
ENV DEFAULT_VOICE=employee
ENV PORT=8880

EXPOSE 8880

# Models are downloaded automatically from HuggingFace on first run
CMD ["python", "server.py"]
```

### docker-compose.yml

```yaml
services:
  tts:
    build: ./tts-service
    container_name: tts-service
    ports:
      - "8880:8880"
    volumes:
      - ./tts-service/voices:/app/voices    # reference audio
      - tts-models:/root/.cache/huggingface # model cache
    environment:
      - DEFAULT_VOICE=employee
      - PORT=8880
      - PYTHONUNBUFFERED=1
    deploy:
      resources:
        limits:
          cpus: '3.0'
          memory: 4G
        reservations:
          memory: 2G
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8880/health')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 120s  # models take time to download on first run

  n8n:
    image: n8nio/n8n:latest
    container_name: n8n
    ports:
      - "5678:5678"
    volumes:
      - n8n-data:/home/node/.n8n
    environment:
      - N8N_HOST=0.0.0.0
      - WEBHOOK_URL=https://your-domain.com/
      - GENERIC_TIMEZONE=America/Sao_Paulo
    restart: unless-stopped

volumes:
  tts-models:
  n8n-data:
```

---

## Deployment

### 1. Prepare reference voice (DevOps, one-time)

Record 3-10 seconds of the employee speaking naturally. Requirements:
- Quiet environment, no echo
- Natural speech, not read from a script
- WAV format, 16kHz+ sample rate (24kHz ideal — Kanade's native sample rate)
- Content is irrelevant — what matters is the timbre, not the words

```bash
# Save as employee.wav in the voices/ directory
cp employee_recording.wav kokoclone-service/tts-service/voices/employee.wav
```

### 2. Build and deploy

```bash
cd kokoclone-service
docker compose up --build -d

# Follow first boot (model download ~1-3 GB)
docker compose logs -f tts

# When "Warm-up complete." appears, the service is ready
```

### 3. Test

```bash
# Health check
curl http://localhost:8880/health

# Generate pt-BR audio
curl -X POST http://localhost:8880/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"input":"Bom dia, sua solicitacao foi registrada com sucesso.","voice":"employee"}' \
  --output test.wav

# Listen to the audio and evaluate quality
```

### 4. Preventive restart (Kokoro memory leak)

```bash
# Cron on host: daily restart at 4 AM
(crontab -l 2>/dev/null; echo "0 4 * * * docker restart tts-service") | crontab -
```

---

## n8n Integration

### Phase 1: Basic chat (text → audio)

n8n workflow: `Chat Trigger → HTTP Request (TTS) → Respond to Chat`

**HTTP Request node:**

| Field | Value |
|---|---|
| Method | POST |
| URL | `http://tts-service:8880/v1/audio/speech` |
| Body Content Type | JSON |
| Response Format | File |

**Body (JSON):**
```json
{
  "input": "={{ $json.output }}",
  "voice": "employee",
  "response_format": "wav"
}
```

This works because n8n and tts-service are on the same Docker network (same docker-compose).

### Phase 2: Telegram (audio → audio)

```
[Telegram Trigger] → [Switch: message type]
     ├── text → [LLM] → [TTS] → [Telegram: send audio]
     └── voice → [Download .oga file]
                      → [Groq Whisper STT] → text
                      → [LLM] → text response
                      → [TTS: POST /v1/audio/speech] → audio
                      → [Telegram: send audio]
```

**Sending a voice note on Telegram (not a music file):**

n8n's Telegram node only has `sendAudio` (sends as music). To send as a voice note, use HTTP Request directly to the Bot API [3]:

```
Method: POST
URL: https://api.telegram.org/bot{{ $credentials.telegramApi }}/sendVoice
Body: Form-Data / Multipart
  chat_id: {{ $json.message.chat.id }}
  voice: [audio binary in OGG format]
```

The audio MUST be OGG/Opus. Configure TTS to return `response_format: ogg`.

### Phase 3: Chatwoot + Human-in-the-Loop

**Setup:**
1. Chatwoot → Settings → Integrations → Webhooks
2. Webhook URL: `https://your-domain.com/webhook/chatwoot`
3. Event: `message_created`

**Bot pause/resume logic:**

```
Webhook receives message from Chatwoot
    → Check: does the conversation have a "human" label?
        YES → Ignore (human is responding)
        NO → Process with LLM + TTS → respond via Chatwoot API
```

The human agent in the Chatwoot dashboard:
- **Pause bot:** add the `human` label to the conversation
- **Resume bot:** remove the `human` label
- **Correct:** delete the bot's response and send manually

Chatwoot adds ~1.5-2 GB of RAM (app + Postgres + Redis). The 8 GB VPS still handles it (total ~6-6.5 GB).

---

## Items Requiring Empirical Validation

| Item | How to validate | Risk if it fails |
|---|---|---|
| KokoClone pt-BR quality | Generate 20 customer service phrases, listen | Low — espeak-ng pt-BR is functional |
| Actual VPS latency | Measure with `time curl ...` | Medium — if >3s per request, throughput drops |
| Actual container RAM | `docker stats tts-service` | Low — 2-3 GB estimate is conservative |
| Memory leak over hours | Monitor RAM for 24h | Mitigated by daily restart |
| OGG format via soundfile | Test `response_format: ogg` | If it fails, convert with ffmpeg on server |

---

## Timeline

| Phase | What | Time |
|---|---|---|
| 1 | Docker build + deploy TTS + test pt-BR | Day 1 |
| 2 | n8n workflow: text chat → audio | Day 1 |
| 3 | Telegram bot: bidirectional audio | Day 2 |
| 4 | Chatwoot + human-in-the-loop | Day 3-4 |

---

## References

[1] Ashish-Patnaik. "KokoClone: Voice Cloning, Now Inside Kokoro". GitHub. https://github.com/Ashish-Patnaik/kokoclone

[2] KokoClone source: `core/cloner.py`. https://github.com/Ashish-Patnaik/kokoclone/blob/main/core/cloner.py

[3] n8n Community. "Add Telegram sendVoice". https://community.n8n.io/t/add-telegram-sendvoice/69712

[4] frothywater. "Kanade Tokenizer". GitHub. https://github.com/frothywater/kanade-tokenizer

[5] n8n. "Telegram node documentation". https://docs.n8n.io/integrations/builtin/app-nodes/n8n-nodes-base.telegram/

[6] n8n. "Build a multichannel customer support AI assistant with Chatwoot". https://n8n.io/workflows/8260

[7] n8n. "Human-in-the-loop for AI tool calls". https://docs.n8n.io/advanced-ai/human-in-the-loop-tools/
