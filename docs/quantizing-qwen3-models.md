# Quantizing and Deploying Qwen3 TTS Models

## Overview

The Qwen3 TTS engine requires two GGUF model files:

| File | Size | Purpose |
|------|------|---------|
| `qwen3-tts-0.6b-q8_0.gguf` | ~1.3 GB | TTS transformer + text tokenizer (Q8_0 quantized) |
| `qwen3-tts-tokenizer-f16.gguf` | ~325 MB | Vocoder / audio decoder (F16, not quantized) |

We use Q8_0 for the TTS model (9% faster, 28% less RAM, quality equal to F16). The tokenizer/vocoder stays at F16 (sensitive to quantization).

Pre-quantized Q8_0 files are not available on HuggingFace. You must convert from the original HuggingFace safetensors using the upstream conversion script. This is a one-time operation done on your local machine, never on the VPS.

## What Doesn't Work

- **`llama-quantize`** from llama.cpp — does not recognize the `qwen3-tts` GGUF architecture.
- **`gpt-2-quantize`** from ggml — model-specific, rejects non-GPT-2 files.
- **F16 GGUF re-quantization** — no tool supports GGUF-to-GGUF quantization for `qwen3-tts`. Always convert from the original HuggingFace safetensors.

## Prerequisites

- `uv` (Python package manager)
- `git`
- ~6 GB free disk space
- Internet access to download from HuggingFace

## Step-by-Step Conversion

All steps run from the project root. Uses a temporary venv separate from the project's venv. Do NOT activate the venv — reference binaries directly via `tmp/convert-venv/bin/` to avoid polluting the project environment.

### 1. Create a temporary venv and install dependencies

CPU-only PyTorch (~300 MB). No CUDA needed — this is purely for reading safetensors and writing GGUF.

```bash
uv venv tmp/convert-venv
uv pip install --python tmp/convert-venv/bin/python torch --index-url https://download.pytorch.org/whl/cpu
uv pip install --python tmp/convert-venv/bin/python numpy safetensors tqdm gguf huggingface_hub
```

### 2. Download the HuggingFace model (~1.2 GB)

The CLI binary is `hf` (not `huggingface-cli`).

```bash
tmp/convert-venv/bin/hf download Qwen/Qwen3-TTS-12Hz-0.6B-Base --local-dir tmp/Qwen3-TTS-12Hz-0.6B-Base
```

### 3. Clone the upstream conversion scripts

```bash
git clone --depth 1 https://github.com/predict-woo/qwen3-tts.cpp.git tmp/qwen3-tts-convert
```

### 4. Convert TTS model to Q8_0

```bash
mkdir -p models
tmp/convert-venv/bin/python tmp/qwen3-tts-convert/scripts/convert_tts_to_gguf.py \
  --input tmp/Qwen3-TTS-12Hz-0.6B-Base \
  --output models/qwen3-tts-0.6b-q8_0.gguf \
  --type q8_0
```

### 5. Convert tokenizer/vocoder to F16

```bash
tmp/convert-venv/bin/python tmp/qwen3-tts-convert/scripts/convert_tokenizer_to_gguf.py \
  --input tmp/Qwen3-TTS-12Hz-0.6B-Base \
  --output models/qwen3-tts-tokenizer-f16.gguf \
  --type f16
```

### 6. Verify

```bash
ls -lh models/qwen3-tts-0.6b-q8_0.gguf
ls -lh models/qwen3-tts-tokenizer-f16.gguf
deploy/bin/qwen3-tts-cli -m models/ -t "Teste de quantização." -l pt --seed 42 -j 4 -o tmp/test-q8.wav
```

Expected: q8_0 ~1.3 GB, tokenizer ~325 MB, WAV file generated without errors.

### 7. Clean up

```bash
rm -rf tmp/convert-venv tmp/Qwen3-TTS-12Hz-0.6B-Base tmp/qwen3-tts-convert
```

## Deploying Models to the VPS

Models are too large for git (~1.6 GB total). Deploy via SSH.

Copy models to VPS and populate the Docker named volume using a helper container (no root needed):

```bash
scp models/qwen3-tts-0.6b-q8_0.gguf models/qwen3-tts-tokenizer-f16.gguf <user>@<vps-ip>:~/cumadre-models/
ssh <user>@<vps-ip> 'docker run --rm -v cumadre-models:/models -v ~/cumadre-models:/src:ro alpine cp /src/qwen3-tts-0.6b-q8_0.gguf /src/qwen3-tts-tokenizer-f16.gguf /models/ && rm -rf ~/cumadre-models'
```

Deploy models before `docker compose up`, or the service starts without Qwen3 (Kokoro still works).

## Ansible Integration Status

Not yet automated. The bootstrap playbook does NOT deploy model files. A future story should add Ansible tasks to copy models from operator's machine and populate the Docker volume before starting the service.

## Quick Reference

Run in a separate terminal from the project root (not inside Claude Code).

```bash
uv venv tmp/convert-venv
uv pip install --python tmp/convert-venv/bin/python torch --index-url https://download.pytorch.org/whl/cpu
uv pip install --python tmp/convert-venv/bin/python numpy safetensors tqdm gguf huggingface_hub
tmp/convert-venv/bin/hf download Qwen/Qwen3-TTS-12Hz-0.6B-Base --local-dir tmp/Qwen3-TTS-12Hz-0.6B-Base
git clone --depth 1 https://github.com/predict-woo/qwen3-tts.cpp.git tmp/qwen3-tts-convert
mkdir -p models
tmp/convert-venv/bin/python tmp/qwen3-tts-convert/scripts/convert_tts_to_gguf.py --input tmp/Qwen3-TTS-12Hz-0.6B-Base --output models/qwen3-tts-0.6b-q8_0.gguf --type q8_0
tmp/convert-venv/bin/python tmp/qwen3-tts-convert/scripts/convert_tokenizer_to_gguf.py --input tmp/Qwen3-TTS-12Hz-0.6B-Base --output models/qwen3-tts-tokenizer-f16.gguf --type f16
rm -rf tmp/convert-venv tmp/Qwen3-TTS-12Hz-0.6B-Base tmp/qwen3-tts-convert
```

## Known Issues

1. **Requires CPU-only PyTorch** (~300 MB) in a temp venv. There is no PyTorch-free path to Q8_0 because no standalone quantizer supports the `qwen3-tts` GGUF architecture.

2. **HuggingFace download is ~1.2 GB.** The original safetensors model is the only valid input for the conversion script.

3. **Run in a separate terminal** if using Claude Code. The installs and downloads will timeout in the Claude Code shell.

4. **The F16 GGUF from Volko76/HuggingFace cannot be re-quantized.** Always convert from the original HuggingFace safetensors.

5. **The HuggingFace CLI binary is `hf`, not `huggingface-cli`.** This changed in recent versions of the `huggingface_hub` package.

6. **Do NOT activate the temp venv with `source`.** Reference binaries directly via `tmp/convert-venv/bin/` to avoid polluting the project's venv.
