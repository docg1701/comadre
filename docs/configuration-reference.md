# Configuration Reference

Comadre is configured via environment variables. All variables are loaded at startup using pydantic-settings.

## Environment Variables

| Variable | Default | Description | Example |
| --- | --- | --- | --- |
| `API_KEY` | *(required)* | API authentication key. Startup fails if not set. Uses `SecretStr` internally. | `my-secret-key-2024` |
| `DEFAULT_VOICE` | `kokoro/pm_santa` | Voice used when request omits the `voice` field. Uses `engine/name` format. | `kokoro/pf_dora` |
| `PORT` | `8000` | HTTP port for the FastAPI server. Range: 1-65535. | `9000` |
| `ESPEAK_DATA_PATH` | `None` | Override bundled espeak-ng data path for custom pt-BR pronunciation. | `/usr/local/share/espeak-ng-data` |
| `NOISE_DIR` | `/app/noise` | Directory containing room/hiss noise WAV files for post-processing pipelines. | `/app/noise` |
| `KOKORO_MODEL_PATH` | `models/kokoro-v1.0.onnx` | Path to the Kokoro ONNX model file. | `/models/kokoro-v1.0.onnx` |
| `KOKORO_VOICES_PATH` | `models/voices-v1.0.bin` | Path to the Kokoro voices binary file. | `/models/voices-v1.0.bin` |
| `QWEN3_CLI_PATH` | `/usr/local/bin/qwen3-tts-cli` | Path to the qwen3-tts-cli binary. | `/usr/local/bin/qwen3-tts-cli` |
| `QWEN3_MODEL_PATH` | `models/qwen3-tts-0.6b-q8_0.gguf` | Path to the Qwen3 TTS Q8_0 GGUF model file. | `/models/qwen3-tts-0.6b-q8_0.gguf` |
| `QWEN3_TOKENIZER_PATH` | `models/qwen3-tts-tokenizer-f16.gguf` | Path to the Qwen3 TTS tokenizer GGUF file. | `/models/qwen3-tts-tokenizer-f16.gguf` |
| `VOICES_DIR` | `/voices` | Root directory for voice discovery. Must contain `kokoro/` (`.npy` files) and/or `qwen/` (`.wav` files) subdirectories. See [voice-management.md](voice-management.md). | `/voices` |
| `QWEN3_THREADS` | `4` | Number of CPU threads for Qwen3 inference. Minimum: 1. Beyond 4 cores, diminishing returns. | `4` |
| `KOKORO_MODEL_URL` | *(GitHub release URL)* | URL to download Kokoro ONNX model on first start. | `https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx` |
| `KOKORO_VOICES_URL` | *(GitHub release URL)* | URL to download Kokoro voices binary on first start. | `https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin` |
| `QWEN3_MODEL_URL` | *(empty)* | URL to download Qwen3 GGUF model. Empty string skips auto-download. | *(empty string)* |
| `QWEN3_TOKENIZER_URL` | *(empty)* | URL to download Qwen3 tokenizer GGUF. Empty string skips auto-download. | *(empty string)* |
| `DOMAIN` | `localhost` | Domain for Caddy HTTPS. Set to a public domain for Let's Encrypt auto-cert, or `localhost` for self-signed. Caddy/compose-level variable, not part of the Python application settings. | `tts.example.com` |
| `RATE_LIMIT_SPEECH` | `30/minute` | Rate limit for the speech endpoint, per client IP. Uses `limits` syntax. | `20/minute` |
| `RATE_LIMIT_HEALTH` | `60/minute` | Rate limit for the health endpoint, per client IP. | `120/minute` |

## Required vs Optional

**Required:** `API_KEY` is the only required variable. The application exits on startup if it is not set or is empty.

**Optional:** All other variables have sensible defaults. The default configuration runs Kokoro without additional setup (models auto-download). Qwen3 requires either pre-deployed GGUF models or configured download URLs.

## URL Validation

All URL variables (`KOKORO_MODEL_URL`, `KOKORO_VOICES_URL`, `QWEN3_MODEL_URL`, `QWEN3_TOKENIZER_URL`) are validated at config load time:

- Non-empty values must be valid HTTP or HTTPS URLs
- Empty string is allowed for Qwen3 URLs (disables auto-download for that model)
- Invalid URLs cause a startup error with a validation message

## Docker Compose Environment

In production, environment variables are set in `compose.yaml` (not `.env` directly). The compose file maps host `.env` values to container environment:

```yaml
environment:
  API_KEY: ${API_KEY:?API_KEY must be set}
  PORT: "${PORT:-8000}"
```

The `API_KEY` uses the `?` syntax, which causes Docker Compose to error immediately if the variable is not set in `.env`.

This is a simplified example. The actual `compose.yaml` maps 18+ environment variables. See the full `compose.yaml` for all mappings.

## Complete .env.example

```bash
# Comadre -- Environment Configuration
# Copy to .env and fill in values

# API authentication key (required)
API_KEY=your-secret-api-key-here

# Default voice for TTS when none specified
DEFAULT_VOICE=kokoro/pm_santa

# Domain for HTTPS (Caddy auto-provisions Let's Encrypt cert)
# Use "localhost" for self-signed cert on private networks
DOMAIN=localhost

# Rate limiting (per client IP)
RATE_LIMIT_SPEECH=30/minute
RATE_LIMIT_HEALTH=60/minute

# Override bundled espeak-ng data for updated pt-BR pronunciation (optional)
# ESPEAK_DATA_PATH=/usr/share/espeak-ng-data-custom

# Directory containing room/hiss noise WAV files for post-processing
# NOISE_DIR=/app/noise

# --- Kokoro engine paths ---
# KOKORO_MODEL_PATH=models/kokoro-v1.0.onnx
# KOKORO_VOICES_PATH=models/voices-v1.0.bin

# --- Qwen3 engine paths ---
# QWEN3_CLI_PATH=/usr/local/bin/qwen3-tts-cli
# QWEN3_MODEL_PATH=models/qwen3-tts-0.6b-q8_0.gguf
# QWEN3_TOKENIZER_PATH=models/qwen3-tts-tokenizer-f16.gguf
# QWEN3_THREADS=4

# --- Model download URLs (auto-download on first start) ---
# KOKORO_MODEL_URL=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
# KOKORO_VOICES_URL=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
# QWEN3_MODEL_URL=
# QWEN3_TOKENIZER_URL=

# --- Voice directory ---
# Root directory for filesystem-based voice discovery (see docs/voice-management.md)
# VOICES_DIR=/voices
```
