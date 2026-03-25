# Feasibility Report: TTS Engine Evaluation & Refactoring Decision

**Date:** 2026-03-22 — 2026-03-23
**Author:** Engineering (automated feasibility testing + human evaluation)
**Status:** DECISION MADE — Dual-engine architecture confirmed
**Last updated:** 2026-03-23 14:00

## Executive Summary

Comprehensive feasibility testing across **10+ engine configurations**, **400+ audio samples**, and 3 days of testing. Final architecture: dual-engine with post-processing pipelines tuned per engine.

### Final Decision

| Use case | Engine | RTF CPU | Post-processing | Status |
|---|---|---|---|---|
| **Fast inference (no cloning)** | Kokoro fp32 + pm_santa | **1.1x** | vibrato_warm + noise calibrated | **CONFIRMED** |
| **Voice cloning** | Qwen3-TTS C++ Q8_0 | **2.4-3.6x** | whatsapp-subtle + speed 1.15x | **CONFIRMED** |

### Why dual-engine

- **Kokoro** has perfect sigla pronunciation (via espeak-ng), RTF 1.1x, but no voice cloning
- **Qwen3-TTS** has good voice cloning with acceptable sigla pronunciation (using spaced format `C N P J`), but RTF 2.4-3.6x
- **Chatterbox** was rejected due to broken sigla pronunciation with no fix possible (no phoneme control)

## Engines Tested (Final Results)

| Engine | Diction | Cloning | Siglas | RTF CPU | RAM | Pipeline | Verdict |
|---|---|---|---|---|---|---|---|
| **Kokoro fp32 pm_santa** | 9/10 | No | **10/10** (pt_extra) | **1.1x** | 3.4 GB | vibrato_warm | **FAST PATH** |
| **Qwen3 C++ Q8_0** | 9/10 | Yes | **7/10** | **2.4-3.6x** | ~4 GB | whatsapp-subtle | **CLONE PATH** |
| Kokoro pf_dora | 8/10 | No | 10/10 | 1.1x | 3.4 GB | vibrato_warm | Alt female voice |
| Kokoro pm_alex | 8/10 | No | 10/10 | 1.1x | 3.4 GB | vibrato_warm | Alt male voice |
| Qwen3 default (no clone) | 9/10 | No | 7/10 | 2.4-3.6x | ~4 GB | whatsapp-subtle | Better accent than cloned |
| Chatterbox ONNX FP32 | 9/10 | Yes | **2/10** | 1.8x | ~5 GB | — | REJECTED (siglas) |
| Chatterbox PyTorch | 9/10 | Yes | 2/10 | 6.5x | 5.3 GB | — | REJECTED (slow + siglas) |
| Chatterbox INT8 | Poor | Yes | 2/10 | ~4x | ~4 GB | — | REJECTED (quality) |
| KokoClone + Kanade | 1/10 | Yes | N/A | 1.5x | 3.4 GB | — | REJECTED (Kanade CPU) |
| FreeVC | Poor | Yes | N/A | 0.2x | ~4 GB | — | REJECTED (diction) |

## Testing Timeline

### Day 1: Engine evaluation

- KokoClone model corrupted — REJECTED
- Kanade voice conversion broken on CPU (FlashAttention required) — REJECTED
- **Kokoro-onnx fp32 + pm_santa**: excellent diction, RTF 1.1x — CONFIRMED
- espeak-ng compiled from source (PR #2344): improves siglas and abbreviations
- FreeVC: poor diction — REJECTED
- Qwen3-TTS 0.6B PyTorch: excellent quality, RTF 6.5x — too slow
- Chatterbox Multilingual: best quality but sigla-broken

### Day 2: Deep Chatterbox testing

- Chatterbox ONNX FP32: RTF 1.8x with TokenLoopDetector — fast but siglas broken
- Chatterbox ONNX Q4: garbage for Portuguese — REJECTED
- Chatterbox INT8: quality loss — REJECTED
- Oxítona "h" suffix rules discovered and documented
- `[ipa]` token confirmed non-functional
- **Chatterbox demoted due to unfixable sigla pronunciation**

### Day 3: Qwen3-TTS C++ & post-processing

- **qwen3-tts.cpp** built from source with custom seed patch
- Q8_0 quantization: 9% faster, 28% less RAM, quality ≈ F16
- Sigla spaced format discovered: `C N P J` instead of `CNPJ`
- Thread scaling tested: 4 cores is sweet spot (2→4 = 45% faster, 4→6 = no gain)
- Seed reproducibility confirmed (identical output with same seed)
- **Post-processing pipeline developed**: vibrato_warm (Kokoro), whatsapp-subtle (Qwen3)
- Timbre study: 10 presets tested, vibrato_warm unanimously best for Kokoro
- Noise calibration per engine: Kokoro needs 3x more noise than Qwen3
- WhatsApp OGG Opus encoding: 24kbps 16kHz mono
- **Qwen3 default voice (no cloning) has better pt-BR accent than cloned voice**

## Kokoro Configuration

| Component | Detail |
|---|---|
| Model | Official fp32 from thewh1teagle/kokoro-onnx (325 MB) |
| Best voice | **pm_santa** (unanimously best of 3 pt-BR voices) |
| All voices | pm_santa (M), pf_dora (F), pm_alex (M) |
| Phonemizer | espeak-ng compiled from source (PR #2344 + custom pt_extra, 141 KB pt_dict) |
| Preprocessing | normalize_text(): currency, dates, times, numbers (NO sigla spacing needed) |
| Sigla handling | **Native via pt_extra dictionary** — 67 entries, $abbrev for spelled, custom phonemes for word-siglas |
| Word acronyms | SUS, PIX, PIS, LOAS, CEP, DETRAN, ENEM, SAMU, ANVISA — defined in pt_extra with word pronunciation |
| **Critical** | ALL data files (pt_dict + phondata + phonindex + phontab) must be copied to espeakng_loader path — misaki ignores ESPEAK_DATA_PATH |
| Sigla quality | **34/34 test phrases correct** — all siglas (CPF, CNPJ, INSS, FGTS, IPVA, IPTU, IRPF, STF, STJ, TRT, BPC, CLT, etc.) verified by human listener |

### Kokoro post-processing pipeline (vibrato_warm)

```bash
# Step 1: vibrato_warm
ffmpeg -y -i raw.wav -af \
"vibrato=f=4.5:d=0.06,\
highpass=f=80,bass=g=3,\
anequalizer=c0 f=200 w=120 g=1.5 t=1|c0 f=700 w=300 g=-2 t=1|c0 f=2500 w=700 g=2 t=1|c0 f=6000 w=1500 g=-2 t=1,\
aexciter=drive=3.5:freq=4500:amount=0.6,\
asoftclip=type=tanh,\
acompressor=threshold=0.12:ratio=4:attack=15:release=200:makeup=4,\
lowpass=f=8000,aecho=0.8:0.85:40:0.12,\
loudnorm=I=-18:TP=-2:LRA=9" _voice.wav

# Step 2: Add Kokoro-calibrated noise
ffmpeg -y -i _voice.wav -i noise-room-tone.wav -i noise-mic-hiss.wav \
-filter_complex \
"[1]volume=0.45,atrim=0:duration[room];[2]volume=0.24,atrim=0:duration[hiss];\
[room][hiss]amix=inputs=2[noise];\
[0][noise]amix=inputs=2:duration=first,loudnorm=I=-17:TP=-2:LRA=10" _final.wav

# Step 3: WhatsApp encode
ffmpeg -y -i _final.wav -c:a libopus -b:a 24k -ar 16000 -ac 1 output.ogg
```

## Qwen3-TTS C++ Configuration

| Component | Detail |
|---|---|
| Binary | predict-woo/qwen3-tts.cpp (built from source with seed patch) |
| Model | qwen3-tts-0.6b-q8_0.gguf (1.3 GB) + tokenizer-f16.gguf (341 MB) |
| Quantization | Q8_0 (9% faster, 28% less RAM vs F16, quality ≈ identical) |
| Language | `-l pt` (language_id=2071, activates THINK mode) |
| Temperature | 0.7 (more stable than default 0.9) |
| Top-k | 50+ (k10 causes infinite loops) |
| Seed | `--seed N` for reproducibility (custom patch) |
| Max tokens | Dynamic: `min(4096, max(100, len(text) * 8))` |
| Voice cloning | `-r reference.wav` (x-vector extraction) |
| Speed | 1.15x via ffmpeg atempo (Qwen3 tends to sound slow) |

### Qwen3 sigla format

```python
WORD_ACRONYMS = {'SUS', 'PIX', 'PIS', 'LOAS', 'CEP', 'DETRAN', 'ENEM', 'SAMU', 'ANVISA'}

def expand_siglas(text):
    import re
    def replacer(match):
        sigla = match.group()
        if sigla in WORD_ACRONYMS:
            return sigla
        return ' '.join(sigla)  # "CNPJ" → "C N P J"
    return re.sub(r'\b[A-Z]{2,}\b', replacer, text)
```

**Critical:** Siglas must be embedded between normal words, never starting a sentence. Bad: `O I N S S e o C P F...`. Good: `Confirmamos que o I N S S aprovou...`

### Qwen3 post-processing pipeline (whatsapp-subtle)

```bash
# Step 1: Process voice
ffmpeg -y -i raw.wav -af \
"highpass=f=100,\
anequalizer=c0 f=200 w=80 g=1.5 t=1|c0 f=700 w=300 g=-2 t=1|c0 f=3000 w=600 g=3 t=1|c0 f=7000 w=1000 g=-4 t=1,\
acompressor=threshold=0.15:ratio=6:attack=15:release=200:makeup=5,\
lowpass=f=8000,aecho=0.8:0.85:40:0.12,\
atempo=1.15,\
loudnorm=I=-18:TP=-2:LRA=9" _voice.wav

# Step 2: Add Qwen3-calibrated noise
ffmpeg -y -i _voice.wav -i noise-room-tone.wav -i noise-mic-hiss.wav \
-filter_complex \
"[1]volume=0.15,atrim=0:duration[room];[2]volume=0.08,atrim=0:duration[hiss];\
[room][hiss]amix=inputs=2[noise];\
[0][noise]amix=inputs=2:duration=first,loudnorm=I=-17:TP=-2:LRA=10" _final.wav

# Step 3: WhatsApp encode
ffmpeg -y -i _final.wav -c:a libopus -b:a 24k -ar 16000 -ac 1 output.ogg
```

### Qwen3 C++ seed patch

Patch file saved at `docs/qwen3-tts-cpp-seed-patch.diff`. Apply with:

```bash
cd qwen3-tts.cpp && git apply path/to/qwen3-tts-cpp-seed-patch.diff && cmake --build build -j4
```

### Known good seeds

| Seed | Phrase pattern | Quality |
|---|---|---|
| 7 | STF phrases | Good |
| 13 | STF phrases | Good |
| 42 | Most phrases | Good (fails on STF) |

### Thread scaling (measured)

| Cores | Total time | vs 4 cores |
|---|---|---|
| 1 | 42.8s | 1.92x slower |
| 2 | 40.5s | 1.81x slower |
| **4** | **22.3s** | **baseline (recommended)** |
| 6 | 22.0s | no benefit |

### Qwen3 default vs cloned voice

The default voice (no reference audio) produces **better pt-BR accent** than the cloned voice. Cloned voice sometimes has Portuguese-from-Portugal artifacts. For best quality without cloning, omit `-r` flag.

## Noise Calibration

| Engine | Room tone volume | Mic hiss volume | Reason |
|---|---|---|---|
| Qwen3 | 0.15 | 0.08 | Lower RMS signal, more silence gaps |
| Kokoro | 0.45 | 0.24 | Higher RMS signal, needs 3x more noise |

### Audio characteristics (measured)

| Engine | RMS | Peak | Silence % |
|---|---|---|---|
| Kokoro (all voices) | 0.063-0.069 | 0.66-0.76 | 35-38% |
| Qwen3 default | 0.016 | 0.10 | 62.6% |
| Qwen3 cloned | 0.031 | 0.23 | 54.4% |

## WhatsApp Output Format

- Container: OGG
- Codec: Opus (libopus)
- Bitrate: 24 kbps
- Sample rate: 16 kHz
- Channels: mono
- WhatsApp applies its own AGC + noise suppression on top

## Runaway Generation Safeguards (Qwen3 ONNX + C++)

- Dynamic `max_tokens` based on text length: `min(4096, max(100, len(text) * 8))`
- Post-generation silence trimming
- Seed-based reproducibility for known-good outputs
- Chatterbox ONNX: TokenLoopDetector (3x repeat, ABAB, silence loop detection)

## Production Architecture

```text
Request arrives
    │
    ├── Has voice cloning reference?
    │   ├── YES → Qwen3-TTS C++ Q8_0
    │   │         ├── Preprocessing: expand_siglas() + embed between words
    │   │         ├── Generate: -l pt --temperature 0.7 --top-k 50 -r ref.wav
    │   │         └── Post-process: whatsapp-subtle + speed 1.15x + noise 0.15/0.08
    │   │
    │   └── NO → Kokoro fp32
    │             ├── Voice: pm_santa (default), pf_dora (female), pm_alex (alt male)
    │             ├── Preprocessing: normalize_text() + chunk_text()
    │             ├── Phonemizer: espeak-ng compiled (PR #2344)
    │             └── Post-process: vibrato_warm + noise 0.45/0.24
    │
    └── Both paths → OGG Opus 24kbps 16kHz mono → WhatsApp
```

## Documentation Index

| File | Content | Status |
|---|---|---|
| `docs/feasibility-report-tts-engine.md` | This file — complete decision record | Current |
| `docs/espeak-ng-custom-dictionary.md` | Custom pt_extra dictionary for siglas + how to compile + critical data file notes | Current |
| `docs/qwen3-tts-internals.md` | Qwen3 architecture, thinking tokens, siglas, post-processing pipelines, thread scaling | Current |
| `docs/qwen3-tts-cpp-seed-patch.diff` | Patch for seed support in qwen3-tts.cpp | Current |
| `docs/chatterbox-ptbr-preprocessing-rules.md` | Chatterbox pt-BR rules (sigla preprocessing failed) | Historical |
| `docs/chatterbox-tokens-features.md` | Chatterbox token reference ([ipa] non-functional) | Historical |

## Key Discoveries

### 1. espeak-ng pt_extra dictionary (Kokoro sigla breakthrough)

- Custom `pt_extra` file with 67 entries makes Kokoro pronounce ALL siglas perfectly
- Uses `$abbrev` flag for spelled siglas (INSS, CPF, CNPJ) and custom phonemes for word-siglas (SUS, PIX, DETRAN)
- Must compile from `dictsource/` directory using `--compile=pt`
- **CRITICAL**: ALL data files (pt_dict + phondata + phonindex + phontab) must be copied together to espeakng_loader — misaki ignores ESPEAK_DATA_PATH env var
- See `docs/espeak-ng-custom-dictionary.md` for full details

### 2. Post-processing pipelines

- **Kokoro**: vibrato_warm (micro-vibrato 4.5Hz + warmth + exciter + saturation + noise calibrated at 0.45/0.24)
- **Qwen3**: whatsapp-subtle (EQ + compression + reverb + speed 1.15x + noise at 0.15/0.08)
- Noise levels must be calibrated per engine (Kokoro needs 3x more noise than Qwen3 due to higher RMS)
- Best overall effect: `whatsapp-subtle` for both, with `vibrato_warm` adding humanization to Kokoro

### 3. Qwen3-TTS C++ seed reproducibility

- Custom patch adds `--seed` parameter for deterministic output
- Same seed + same text = identical audio (verified with md5sum)
- Some seeds produce bad output for specific phrases (e.g., seed 42 fails on STF)

## Next Steps: Implementation

1. **Refactor comadre service** — Replace KokoClone with dual-engine (Kokoro + Qwen3 C++)
2. **Kokoro preprocessing** — normalize_text() + chunk_text() (siglas handled natively by pt_extra, no expand_siglas needed)
3. **Qwen3 preprocessing** — expand_siglas() with spaced format for Qwen3 path only
4. **Post-processing module** — ffmpeg pipeline per engine (vibrato_warm / whatsapp-subtle)
5. **Docker image** — espeak-ng compiled with pt_extra + copy ALL data files to espeakng_loader + Kokoro model + qwen3-tts.cpp binary + GGUF models
6. **API design** — endpoint accepts text + optional voice reference + engine preference
7. **Integration tests** — real audio generation with sigla phrases
8. **Seed library** — build per-sigla-pattern seed database for Qwen3 consistency
