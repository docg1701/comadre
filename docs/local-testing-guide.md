# Local Testing Guide (v3.1.2)

How to run Comadre end-to-end on your machine with all features working.

## Prerequisites

- Python 3.12 + `uv`
- Docker and Docker Compose v2 (optional, for the container path)
- 4 vCPU, 12+ GB RAM (pocket-tts RSS ~1.5-2 GB; 8 GB works but is tight
  with a browser + dev tools)
- ~5 GB free disk (model ~370 MB, torch ~1.5-2 GB, HF cache)
- A HuggingFace account that accepted the gated-model terms at
  <https://huggingface.co/kyutai/pocket-tts> + a HF token (one-time
  download only)

## What is already in the repo

| Item | Location | Purpose |
| --- | --- | --- |
| Noise WAVs | `noise/` | hiss + room tone for post-processing |
| pocket config YAMLs | `deploy/pocket-tts/` | baked image configs (production paths) |
| Spike harness | `scripts/spike_pocket_tts.py` | tuning corpus + RTF sweep |
| Operator voice | `voices/pocket/female.wav` | reference WAV (ex v2) |

## What must be obtained separately

gitignored model artifacts (auto-download on first boot, or staged by
`deploy-models.yml` for air-gapped hosts):

| Item | Size | Source |
| --- | --- | --- |
| `model.safetensors` | ~370 MB | gated `kyutai/pocket-tts` (pinned revision) |
| `tokenizer.model` | ~1 MB | public `kyutai/pocket-tts-without-voice-cloning` |
| `embeddings/rafael.safetensors` | ~1 MB | public repo (pinned revision) |

## Step 1: Dependencies

```bash
uv sync   # installs torch (CPU index), pocket-tts, and the dev tools
```

## Step 2: Model files

Set `HF_TOKEN` in the environment (one time), then let the app download:

```bash
export HF_TOKEN=hf_your_token
.venv/bin/python -c \
  "from comadre.download import ensure_pocket_models; \
   ensure_pocket_models('portuguese', 'models/pocket-tts/portuguese/model.safetensors', \
   'models/pocket-tts/portuguese/tokenizer.model', \
   'models/pocket-tts/portuguese/embeddings/rafael.safetensors')"
```

Or boot the server once with `HF_TOKEN` set and `HF_HUB_OFFLINE` unset —
the lifespan downloads on startup. Afterwards, `export HF_HUB_OFFLINE=1`
makes everything cache-only.

## Step 3: Seed a registry + boot the dev server

```bash
# One-off registry seed (temp DB + customer + key with known plaintext)
.venv/bin/python tmp/smoke_setup.py   # writes tmp/smoke/env.sh + plaintext.txt

. tmp/smoke/env.sh
VOICES_DIR=tmp/smoke/voices NOISE_DIR=noise \
POCKET_MODEL_PATH=models/pocket-tts/portuguese/model.safetensors \
.venv/bin/python -m uvicorn comadre.main:create_app --factory \
  --host 127.0.0.1 --port 8391
```

Then run the curl smoke sequence from `docs/api-reference.md` §6 against
`http://127.0.0.1:8391` (speech, clone upload, list, delete).

## Docker path (optional)

```bash
cp .env.example .env            # set KEY_REGISTRY_ENCRYPTION_KEY + HF_TOKEN
docker compose up --build -d    # first boot downloads the gated model
docker compose exec tts-service comadre-keys create-customer \
  --name "Local Dev" --email dev@localhost --cpf 11144477735
docker compose exec tts-service comadre-keys issue-key \
  --customer <cust_id> --rpm 1000 --billing-mode complimentary
```

## Tuning harness (spike)

```bash
uv run python scripts/spike_pocket_tts.py \
  --config models/pocket-tts-config/portuguese.yaml \
  --output-dir tmp/spike --threads 4

# variant sweep + clone-encode timing
uv run python scripts/spike_pocket_tts.py --config ... --quantize
uv run python scripts/spike_pocket_tts.py --config ... --clone-timing
```

Note: a local config YAML with local paths lives at
`models/pocket-tts-config/portuguese.yaml` (gitignored); generate it from
`deploy/pocket-tts/portuguese.yaml` by replacing the `/models/...` paths
with relative local ones. The deploy YAMLs use container paths.

## Tests

```bash
uv run pytest                    # mocked suite (no model needed)
uv run pytest -m slow            # real model: generation + clone roundtrip
uv run ruff check . && uv run mypy src/
uv run pre-commit run --all-files
```
