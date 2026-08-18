# Feasibility: Full Migration to kyutai-labs/pocket-tts (no fallback, no back-compat)

**Date:** 2026-08-18
**Author:** Engineering (agent-assisted feasibility analysis)
**Status:** DECIDED (2026-08-18) — full migration approved, including native voice-cloning uploads. Implementation plan: [docs/pocket-tts-v3-migration-plan.md](pocket-tts-v3-migration-plan.md); normative API contract: [docs/pocket-tts-v3-api-spec.md](pocket-tts-v3-api-spec.md). The Phase-0 spike (now "baseline capture & tuning", §11 of the plan) still produces the pipeline/sigla/thread constants, but the migration itself is committed.
**Sources:** official repo cloned and code-reviewed (HEAD `891886a6`, 2026-08-17),
Hugging Face model-card API, HeyNEO CPU TTS benchmark (2026-07-06), independent
reviews, and a full map of Comadre's engine-coupled surface.

## 1. Executive summary

The request: replace Kokoro fp32 and Qwen3-TTS C++ Q8_0 entirely with
[kyutai-labs/pocket-tts](https://github.com/kyutai-labs/pocket-tts) as Comadre's
sole engine — no fallback path, no back-compat for `kokoro/*` / `qwen/*` voices.

**Verdict: technically feasible and architecturally attractive, but not yet safe
to commit.** Pocket TTS is a Python library that embeds cleanly into Comadre's
existing FastAPI + FIFO-queue platform, and it would collapse two engines, a
C++ binary, a GGUF toolchain and an espeak-ng source build into one pip package.
Three hard quality gates are unverified and are the actual decision:

- **G1 — pt-BR accent/quality** of the "portuguese" model (English-first product;
  the non-English models were released 2026-05 and are clearly secondary).
- **G2 — sigla pronunciation** (Comadre's marquee feature: 34/34 phrases verified
  today via the espeak-ng pt_extra dictionary; Pocket TTS has no g2p/phoneme
  control at all — raw text in, audio out).
- **G3 — clone fidelity** vs Qwen3-TTS 0.6B for the commercial cloned voices
  (100M zero-shot vs 600M reference-conditioned; community consensus: zero-shot
  clones have a real ceiling).

Everything else — the platform — is engine-agnostic and survives untouched:
key registry, billing, rate limiting, auth, counters, LGPD ops, Caddy, Ansible,
the queue/replica scaling model (~70% of the repository).

## 2. What Pocket TTS is

Kyutai's streaming TTS: a ~100M-parameter CALM flow language model over the Mimi
neural codec. Raw-text input via a sentencepiece tokenizer (no phonemizer, no
g2p — this is the architectural fact behind G2). CPU-only PyTorch 2.5+,
Python 3.10–3.14, pip-installable (`pocket-tts` 2.1.0).

| Fact | Value |
|---|---|
| Languages | en, fr, de, es, pt, it — 6-layer base + 24-layer "24l" preview variants |
| Portuguese variants | `portuguese` (385 MB) and `portuguese_24l` (1.34 GB) — same repo, per-language dirs |
| Output | 24 kHz mono float32 tensor (streaming chunks); WAV via CLI |
| Speed | ~6x realtime on Apple M4 (2 cores); **1.4x realtime (RTF 0.714) on a Xeon 8272CL 4-core** (HeyNEO) |
| Quality (EN) | UTMOS 4.10 vs Kokoro-82M 4.44/4.46 (HeyNEO) — fixed-voice slightly below Kokoro |
| First-audio latency | ~200 ms (M4); streaming by design |
| Voice cloning | zero-shot from ~5 s reference; cross-lingual; reference must be clean (room tone is reproduced) |
| Voice state | KV-cache state exportable to `.safetensors` (`export-voice` CLI / `export_model_state`) — fast reload |
| Licenses | **code MIT; weights cc-by-4.0** (attribution required) |
| Gating | cloning weights are **gated on HF** (accept terms + `hf auth login`); a public `kyutai/pocket-tts-without-voice-cloning` repo exists but **disables voice cloning** (catalog voices only) — useless for Comadre's cloning product |
| Extras | int8 via torchao (−48% RAM, +27% speed on x86, "no measurable WER impact"); `serve` HTTP API (not OpenAI-compatible — irrelevant, Comadre keeps its own API) |
| Ecosystem | community ONNX exports and a ggml port (`0xShug0/audio.cpp`, supports PocketTTS) — unofficial, young |

Key API (from code review):

```python
model = TTSModel.load_model(language="portuguese")        # or config=<local .yaml>
state = model.get_state_for_audio_prompt("/voices/pocket/galvani.safetensors")  # or a .wav/.mp3/URL
audio = model.generate_audio(state, text, copy_state=True)  # -> [ch, samples] @ 24 kHz
```

## 3. Fit matrix against Comadre's requirements

| Requirement | Pocket TTS | Verdict |
|---|---|---|
| pt-BR output | `portuguese` model; default voice "rafael"; training data/accent unverified for pt-BR | **GATE 1 — RISK** |
| Siglas 34/34 (CPF, CNPJ, FGTS…) | no phoneme control; text is tokenized literally; `expand_siglas` spacing is the only lever | **GATE 2 — RISK (expected regression)** |
| Voice cloning (commercial voices) | yes, 5 s zero-shot, state exportable; quality vs Qwen3 0.6B unverified | **GATE 3 — RISK** |
| `speed` 0.25–4.0 (OpenAI-compat) | **not supported** by the model | **GAP** — implement via ffmpeg `atempo` post-processing or drop from API |
| 500/300-char limits | no hard limit (internal 50-token chunking, sentence-aware) | **CHANGE** — limits can be raised to one common value |
| Seed reproducibility (Qwen3) | no seed param; global torch RNG; `torch.manual_seed` works under the FIFO lock | OK (internal only; API never exposed seed) |
| OGG Opus 24kbps/16 kHz + radio pipelines | post-processing is Comadre's own ffmpeg stage | **CHANGE** — retune EQ/noise per engine (existing gotcha: noise calibration differs per engine) |
| Filesystem voice discovery (`engine/name`) | `/voices/pocket/*.safetensors` (or WAV refs encoded at boot) | **CHANGE** — same design, new artifact |
| OpenAI-compatible endpoint + n8n | Comadre keeps its FastAPI layer; pocket-tts is a library | OK |
| CPU-only, network-isolated | yes; runtime fully offline via a **local config .yaml** (local `weights_path`) | OK (download happens once, at deploy) |
| Air-gapped deployments | 2 files per language (`model.safetensors` + `tokenizer.model`); SCP path works | **CHANGE** — `deploy-models.yml` carries the pair instead of GGUFs |
| RAM budget (6 GB limit today) | ~0.4 GB weights + torch runtime + voice states ≈ 1–2 GB (vs ~3.4 + ~4 GB today); optional int8 | **BETTER** |
| CPU utilization (4 vCPU) | `torch.set_num_threads(1)` hardcoded at import + 1 decode thread ≈ 2 cores/request; overridable in Comadre's integration | **CHANGE** — tune 1 vs 2–4 threads in spike |
| Single FIFO queue / replicas | `generate_audio` is documented **not thread-safe** → Comadre's per-replica `asyncio.Lock` is exactly the right design | OK (1:1 match) |
| Per-request state safety | `copy_state=True` (default) deep-copies the voice state per call; cache states per voice | OK (bench deepcopy vs re-import in spike) |
| Licenses / LGPD | MIT + cc-by-4.0 (attribution); gated repo terms prohibit non-consensual cloning — Comadre clones customer-consented voices, compliant | OK + ops friction (HF token) |
| Keys/billing/rate-limit/auth/LGPD ops | engine-independent | **UNTOUCHED** |

## 4. Migration map (verified against the code)

Engine-coupled surface today → target state:

| Area | Today | After |
|---|---|---|
| `src/comadre/service.py` | `KokoroEngine` + `QwenEngine` + `EngineRouter` | single `PocketEngine` (load, warm-up, per-voice state cache, generate → tensor → WAV → ffmpeg); keep `_samples_to_wav`-style conversion and both ffmpeg pipelines; voice format `pocket/<name>` |
| `src/comadre/config.py` | `KOKORO_*`, `QWEN3_*`, `ESPEAK_DATA_PATH`, `qwen3_threads` | `POCKET_LANGUAGE`, `POCKET_CONFIG_PATH` (local yaml), `POCKET_THREADS`, `POCKET_QUANTIZE`, `POCKET_TEMPERATURE`; `RegistrySettings` untouched |
| `src/comadre/schemas.py` | 500/300 per-engine char limits | one limit (e.g. 1000); decide `speed` semantics |
| `src/comadre/main.py` | espeak verify + 2 engine loads + 2 warm-ups | model ensure (HF) + 1 load + warm-up; voice-dir scan; default-voice validation |
| `src/comadre/download.py` | urllib downloads of GitHub/HF URLs | huggingface-hub download (token-aware) of model+tokenizer into `/models`; runtime reads local paths only |
| `src/comadre/health.py` | `engines: {kokoro, qwen3}` | `engines: {pocket}` |
| `Dockerfile` | espeak-ng source build + pt_dict copy + qwen3 binary + build toolchain | **delete all of that**; add torch CPU wheel (~+2 GB image); keep ffmpeg + libsndfile (mp3 refs via optional `soundfile`) |
| `pyproject.toml` | `kokoro-onnx`, legacy `kokoclone` | `pocket-tts[audio]` (torch CPU), drop `kokoclone`; keep `num2words` (normalize_text still feeds the model) |
| `tests/` | `test_service`, `test_routing`, `test_api`, `test_feasibility`, `test_main_lifespan`, `test_config`, `test_download`, `test_health`, `test_schemas`, part of `test_preprocessing` | rewrite against a mocked `TTSModel` (same pattern as today's kokoro-onnx mocks); `keys/*` and `non_regression` untouched |
| `compose.yaml` | engine env vars, 6 GB limit | `POCKET_*` env; memory limit can drop (~3 GB) or stay |
| `deploy/ansible` | bootstrap model URLs; `deploy-models.yml` GGUFs; `deploy-voices.yml` `kokoro/`+`qwen/`; `health.yml` asserts `qwen/*` absent | bootstrap downloads the pair (token at deploy); voices → `pocket/` (`.safetensors` or WAV refs); health assertion → `pocket/*` |
| `deploy/landing/index.html` | voice picker hardcodes `kokoro/` locale heuristics + default `kokoro/pm_santa` | generic picker driven by `/health` voices (already fetches them); new default |
| `scripts/` | `loadtest.py` default `kokoro/pm_santa`; `capacity_test.py`; `feasibility_test.py` | update defaults; feasibility script obsolete |
| `docs/` | engine docs (§5) | rewrite per §5 |
| `AGENTS.md` | dual-engine architecture, espeak/misaki gotcha, qwen3 build gotchas | rewrite architecture + gotchas (gating, state copy, threads) |

## 5. Documentation impact

- **Delete or archive:** `docs/building-qwen3-tts-cli.md`, `docs/quantizing-qwen3-models.md`,
  `docs/qwen3-tts-internals.md`, `docs/espeak-ng-custom-dictionary.md`,
  `docs/feasibility-report-tts-engine.md` (superseded by this document + spike results).
- **Rewrite:** `docs/voice-management.md` (pocket states), `docs/configuration-reference.md`,
  `docs/deployment-guide.md` (HF token step, model deploy), `docs/troubleshooting.md`,
  `docs/api-reference.md` (voice names, limits), `README.md` (badges, engine section,
  requirements, features), `docs/replica-scaling-report.md` / cost reports (annotate as
  pre-migration or refresh with post-migration numbers).
- **Add:** `docs/pocket-tts-voice-export.md` (customer WAV → `.safetensors` runbook) if the
  operator keeps provisioning from raw WAVs.

## 6. Risks, gates and plan

### Hard gates (Phase-0 spike, 2–3 days, on Comadre's VPS class)

1. **pt-BR accent/diction** — generate the full battery (WhatsApp phrases, numbers via
   `normalize_text`, dates, slang, and the 34 sigla phrases) with `portuguese` and
   `portuguese_24l`; human listen + UTMOS-style scoring.
2. **Siglas** — test raw vs `expand_siglas` spaced format. Expect regression vs the
   34/34 espeak-ng bar; decide the acceptable floor (Qwen3 was 7/10).
3. **Clone fidelity** — A/B the current commercial voices (e.g. `galvani`) against
   Qwen3 outputs; check reference-cleaning interaction with the noise-mixing stage.
4. **Throughput** — RTF bench on the real VPS (1 vs 2–4 threads, int8 on/off,
   base vs 24l); state-cache cost (deepcopy vs re-import); re-run `capacity_test.py`
   to refresh the cost-comparison story.

Exit criteria: siglas ≥ acceptable floor, pt-BR accent natural to a native listener,
clone fidelity ≥ Qwen3 parity, RTF ≥ 1.0x on the target VPS.

### Secondary risks

- **HF gating ops friction** — one-time terms acceptance + `HF_TOKEN` at download; the
  air-gapped path requires an operator pre-download. Runtime stays offline (local yaml).
- **torch image weight** — +~2 GB image, +~1 GB RAM baseline vs today's lean
  onnxruntime+C++ image. Mitigations later: int8, or the unofficial ggml
  `audio.cpp` port (recovers the lean-image property once mature).
- **Voice-name contract change** — `kokoro/*` and `qwen/*` disappear for n8n clients;
  operator must migrate voice names and `DEFAULT_VOICE` and communicate to customers
  (accepted per the "no retrocompat" directive).
- **Upstream velocity** — English-first roadmap, no fine-tuning path published, 24l
  variants marked "preview"; pt-BR improvements are out of Comadre's control. Pin the
  version (`pocket-tts==2.1.0`) and vendor the config yaml.

### Plan (big-bang, per directive)

| Phase | Work | Estimate |
|---|---|---|
| 0 | Validation spike (gates above) — **go/no-go** | 2–3 days |
| 1 | Code migration (§4 map) + mocked tests + image build | 3–5 days |
| 2 | Ops & assets: voice export, model deploy, ansible, landing, health assertion | 1–2 days |
| 3 | Cutover, loadtest/capacity re-run, docs rewrite, customer comms | 1–2 days |

No rollback path is engineered (per directive). Residual risk is bounded: the registry,
billing and auth data live outside the engine surface, and the existing backup/restore
playbooks + git history remain available as manual safety nets.

## 7. What does NOT change (verified engine-agnostic)

`comadre-keys` CLI (all 21 verbs), key registry + migrations, auth cache, per-key rate
limiting, counters/snapshots, billing cron + suspension sweep, backup/restore playbooks,
Caddy + TLS + landing routing, the FIFO-queue/replica scaling model, LGPD data-operations
surface, and the pytest/ruff/mypy toolchain.

## 8. Recommendation

**Run Phase 0 before writing any migration code.** If G1–G3 pass, the big-bang migration
is a well-bounded ~1.5–2-week job with a large simplification payoff (one engine, no
espeak-ng build, no C++ binary, no GGUF, less RAM, faster cloning). If the sigla or
pt-BR gates fail, pocket-tts cannot carry Comadre's WhatsApp product alone — the honest
outcome is "no" for a full replacement (or re-scoping it to the cloning path only,
which conflicts with the no-fallback directive).
