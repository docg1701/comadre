# Qwen3-TTS 0.6B-Base — Internal Architecture & Configuration

**Date:** 2026-03-23
**Source:** Python source code analysis + C++ implementation + arxiv paper

## Architecture Overview

Qwen3-TTS is an end-to-end TTS model. No separate text normalization or phoneme conversion stage.

```
Text → Qwen2Tokenizer (BPE) → Input IDs
                                    ↓
                        Text Embeddings + Codec Embeddings
                                    ↓
                        [Thinking Tokens: THINK/NOTHINK]
                                    ↓
                        Dual-Track LM (Talker) → Speech Codec Tokens
                                    ↓
                        Audio Decoder (Vocoder) → WAV
```

## Thinking Tokens

The model has two inference modes controlled by whether `language_id` is specified:

### THINK mode (language specified — ALWAYS USE THIS)

Codec prefill sequence: `[2154, 2156, language_id, 2157]`

The model generates intermediate "reasoning" tokens between BOS (2156) and EOS (2157) where it works out pronunciation of ambiguous text (abbreviations, numbers, heteronyms).

### NOTHINK mode (no language — AVOID)

Codec prefill sequence: `[2155, 2156, 2157]`

Skips reasoning. The model guesses pronunciation without internal normalization. Results in random accent, inconsistent siglas.

### Token IDs (confirmed from model config)

| Token | ID | Purpose |
|---|---|---|
| `codec_think_id` | 2154 | Activate thinking mode |
| `codec_nothink_id` | 2155 | Skip thinking mode |
| `codec_think_bos_id` | 2156 | Start of thinking |
| `codec_think_eos_id` | 2157 | End of thinking |
| `codec_pad_id` | 2148 | Padding |
| `codec_bos_id` | 2149 | Start of speech |
| `codec_eos_token_id` | 2150 | End of speech (EOS) |

## Language IDs (Portuguese = 2071)

| Language | ID |
|---|---|
| English | 2050 |
| German | 2053 |
| Spanish | 2054 |
| Chinese | 2055 |
| Japanese | 2058 |
| French | 2061 |
| Korean | 2064 |
| Russian | 2069 |
| Italian | 2070 |
| **Portuguese** | **2071** |

## qwen3-tts.cpp Configuration

The C++ implementation correctly implements THINK mode:
- `-l pt` → sets `language_id = 2071` → activates THINK mode
- Without `-l` → `language_id = -1` → NOTHINK mode (bad)
- Token IDs loaded from GGUF metadata, defaults match model config

### CLI parameters

| Parameter | Default | Recommended | Effect |
|---|---|---|---|
| `-l pt` | `en` | **Always use `pt`** | Activates THINK mode for Portuguese |
| `--temperature` | 0.9 | **0.7** | Lower = more stable timbre and pronunciation |
| `--top-k` | 50 | **50+** | k10 causes infinite loops; k50 best for siglas |
| `--seed` | -1 | Per-use | **Custom patch.** Fixed seed = reproducible output |
| `--top-p` | 1.0 | 0.95 | Nucleus sampling threshold |
| `--repetition-penalty` | 1.05 | 1.05 | Token repetition penalty |
| `--max-tokens` | 4096 | 4096 | Max audio tokens |
| `-j` | 4 | Match CPU cores | Thread count |

### Model files

| File | Size | Quantization | Recommended |
|---|---|---|---|
| `qwen3-tts-0.6b-q8_0.gguf` | 1.3 GB | INT8 | **Yes** — 9% faster, 28% less RAM, quality ≈ F16 |
| `qwen3-tts-0.6b-f16.gguf` | 1.8 GB | FP16 | Only if Q8 quality issues found |
| `qwen3-tts-0.6b-q4_k.gguf` | 1.8 GB | INT4 | Untested |
| `qwen3-tts-tokenizer-f16.gguf` | 341 MB | FP16 | Always (vocoder) |

### Thread scaling (measured, same phrase + seed 42)

| Cores | Generate | Decode | Total | vs 4 cores |
|---|---|---|---|---|
| 1 | 32.4s | 10.4s | 42.8s | 1.92x slower |
| 2 | 30.1s | 10.3s | 40.5s | 1.81x slower |
| **4** | **15.8s** | **6.6s** | **22.3s** | **baseline (recommended)** |
| 6 | 15.6s | 6.4s | 22.0s | 1.5% faster (no benefit) |

- 1→2: minimal (5%) — LLM is sequential
- 2→4: **45% faster** — vocoder benefits from parallelism
- 4→6: diminishing returns
- **4 cores = sweet spot.** 2 cores works but ~1.8x slower.
- **Parallel instances:** Not viable. GGML uses all threads per op. Use async queue instead.

### Q8_0 vs F16 (measured, same phrase + seed)

| | Q8_0 | F16 |
|---|---|---|
| Size | 1.3 GB | 1.8 GB |
| Total time | 29.2s | 32.2s |
| Speed diff | **9% faster** | baseline |
| Quality | Nearly identical | Maximum |
| RAM savings | ~500 MB | baseline |

## Sigla Comparison: Kokoro vs Qwen3

**Kokoro now has 100% perfect sigla pronunciation** via espeak-ng custom `pt_extra` dictionary (see `docs/espeak-ng-custom-dictionary.md`). No text preprocessing needed — siglas are handled natively.

**Qwen3 requires text preprocessing** (spaced format: `C N P J`) and is still inconsistent. Use Qwen3 only when voice cloning is needed.

## Why Qwen3 Siglas Are Inconsistent

1. **End-to-end learning:** The model learned pronunciation from training data. If Brazilian siglas were underrepresented, it doesn't know how to spell them out.
2. **Thinking tokens help but don't guarantee:** THINK mode gives the model more computation to reason, but it can't reason about something it never learned.
3. **Autoregressive sampling:** Each token is sampled, introducing variance. Same input can produce different pronunciation across runs.
4. **No phoneme control:** There is no way to inject pronunciation hints, IPA, or SSML. The model works exclusively at the character/BPE level.

## No Pronunciation Control Available

Confirmed through code analysis and GitHub discussion #53:

- No SSML support
- No IPA input
- No phoneme tags
- No pronunciation dictionary
- No `[ipa]` equivalent (unlike Chatterbox which had the token but not the implementation, Qwen3 doesn't even have the token)
- Community has requested SSML (80% voted) — not implemented

## Available Model Variants

| Model | Size | Clone | Emotion | Instruct | pt-BR voice |
|---|---|---|---|---|---|
| **0.6B-Base** (our choice) | 1.3-1.8 GB | Yes (x-vector) | No | No | Via cloning |
| 0.6B-CustomVoice | ~1.8 GB | 9 presets | Yes | Yes | **NO** (rejected) |
| 1.7B-Base | ~3.7 GB | Yes | No | No | Via cloning |
| 1.7B-CustomVoice | ~3.7 GB | 9 presets | Yes | Yes | No native |
| 1.7B-VoiceDesign | ~3.7 GB | Create by text | Yes | Yes | Too large for 8 GB |

## Sigla Best Practices (Empirical)

| Sigla | Best format | Notes |
|---|---|---|
| INSS | `I-N-S-S` | Hífen without trailing |
| CPF | `CPF` | Works raw |
| CNPJ | `C-N-P-J` | J sometimes mispronounced |
| FGTS | `FGTS` | Works raw |
| IPVA | `I.P.V.A` | Dots without final period |
| BPC-LOAS | `B.P.C LOAS` | LOAS as word |
| RG | `RG` | Works raw |
| STJ/STF/TRT | `S-T-J` | Inconsistent |

Lower temperature (0.7) + explicit formatting improves consistency but does not guarantee correctness.

## Seed-Based Reproducibility (Custom C++ Patch)

We patched `qwen3-tts.cpp` to add `--seed` parameter for deterministic generation.

### How it works

The C++ implementation uses `std::mt19937` for sampling randomness. By default it seeds from `std::random_device{}()` (random each run). Our patch adds:

- `--seed N` CLI parameter → sets `params.seed`
- `seed_rng(seed)` method on `TTSTransformer` → reseeds `rng_` before generation
- `--seed -1` = random (default behavior)

### Verified: same seed = identical output

```
$ ./qwen3-tts-cli ... --seed 42 -o run1.wav
$ ./qwen3-tts-cli ... --seed 42 -o run2.wav
$ md5sum run1.wav run2.wav
c72d8b729acadfcc7a5b4b56e7cce9ed  run1.wav   # IDENTICAL
c72d8b729acadfcc7a5b4b56e7cce9ed  run2.wav   # IDENTICAL
```

### Production strategy for siglas

1. Generate the same sigla-heavy phrase with N different seeds (e.g., seeds 1-100)
2. Human listener selects the seed that produces the best sigla pronunciation
3. Store that seed in the sigla preprocessing config
4. For each request containing siglas, use the known-good seed
5. This makes sigla pronunciation deterministic and high-quality

**Limitation:** The seed fixes the ENTIRE generation — the same text will always produce the same audio. Different texts with different seeds may produce different sigla quality. The ideal approach is to build a library of known-good seeds per sigla pattern.

### Patched files

- `/tmp/qwen3-tts-cpp/src/qwen3_tts.h` — added `int64_t seed = -1` to `tts_params`
- `/tmp/qwen3-tts-cpp/src/main.cpp` — added `--seed` CLI arg
- `/tmp/qwen3-tts-cpp/src/tts_transformer.h` — added `seed_rng()` method
- `/tmp/qwen3-tts-cpp/src/qwen3_tts.cpp` — calls `seed_rng()` before generation

## Reference Audio Strategy for Better Siglas

Theory: if the reference audio (for voice cloning) contains correctly pronounced siglas, the model's thinking tokens may produce better pronunciation for those same siglas in new text.

Proposed test: record a reference paragraph containing all common Brazilian siglas pronounced correctly:

> "O INSS confirmou que o CPF do beneficiário está regular. O CNPJ da empresa foi consultado junto ao FGTS. O processo no TJ aguarda decisão do STJ. A CNH e o RG foram apresentados. O IPVA e o IPTU estão em dia. O BPC-LOAS foi concedido pelo SUS."

Using this as reference audio for cloning may improve sigla consistency across all generated phrases.

## Post-Processing Pipeline (ffmpeg)

### WhatsApp-realistic audio pipeline

Goal: make synthetic audio sound like a real WhatsApp voice message recorded on a phone.

**Pipeline stages:**
1. High-pass 100Hz (remove rumble)
2. EQ: +1.5dB@200Hz (warmth), -2dB@700Hz (reduce boxiness), +3dB@3kHz (presence), -4dB@7kHz (reduce synthetic artifacts)
3. Compression: threshold 0.15, ratio 6:1, attack 15ms, release 200ms, makeup 5dB
4. Low-pass 8kHz
5. Room echo: aecho 0.8:0.85:40:0.12 (subtle office reflections)
6. Speed: 1.15x for Qwen3, 1.0x for Kokoro
7. Loudnorm: -18 LUFS
8. Mix noise: room tone + mic hiss
9. Final loudnorm: -17 LUFS
10. Encode: OGG Opus 24kbps 16kHz mono

### Noise calibration per engine

Kokoro generates 4x louder audio with 35% silence. Qwen3 generates quieter audio with 62% silence. Noise levels must be calibrated per engine:

| Engine | Room tone volume | Mic hiss volume | Reason |
|---|---|---|---|
| **Qwen3** | 0.15 | 0.08 | Lower signal = noise more audible |
| **Kokoro** | 0.45 | 0.24 | Higher signal = needs 3x more noise |

### Audio characteristics (measured)

| Engine | RMS | Peak | Silence % |
|---|---|---|---|
| Kokoro (all voices) | 0.063-0.069 | 0.66-0.76 | 35-38% |
| Qwen3 default | 0.016 | 0.10 | 62.6% |
| Qwen3 cloned | 0.031 | 0.23 | 54.4% |

### Best variant: `whatsapp-subtle`

Human evaluation confirmed `whatsapp-subtle` as the best post-processing preset. `phonecall` is too aggressive, `noisy` is too much. `subtle` adds just enough environmental realism.

### Best timbre preset: `vibrato_warm`

Tested 10 timbre presets across all 3 Kokoro voices (santa, dora, alex). Winner unanimously: **vibrato_warm**.

```bash
ffmpeg -y -i raw.wav -af \
"vibrato=f=4.5:d=0.06,\
highpass=f=80,\
bass=g=3,\
anequalizer=c0 f=200 w=120 g=1.5 t=1|c0 f=700 w=300 g=-2 t=1|c0 f=2500 w=700 g=2 t=1|c0 f=6000 w=1500 g=-2 t=1,\
aexciter=drive=3.5:freq=4500:amount=0.6,\
asoftclip=type=tanh,\
acompressor=threshold=0.12:ratio=4:attack=15:release=200:makeup=4,\
lowpass=f=8000,\
aecho=0.8:0.85:40:0.12,\
loudnorm=I=-18:TP=-2:LRA=9" \
processed.wav
```

What it does:
- **vibrato f=4.5 d=0.06** — micro pitch variation at 4.5Hz, 6% depth (humanizes)
- **bass=g=3** — warmth boost
- **EQ** — +1.5dB@200Hz (body), -2dB@700Hz (no boxiness), +2dB@2.5kHz (presence), -2dB@6kHz (no sibilance)
- **aexciter** — subtle harmonic richness at 4.5kHz
- **asoftclip=tanh** — analog warmth/saturation
- **acompressor** — consistent dynamics
- **lowpass 8kHz** — remove synthetic artifacts
- **aecho** — subtle room reflections
- **loudnorm** — consistent volume

Then add calibrated noise and encode for WhatsApp.

### Rejected timbre presets

| Preset | Reason |
|---|---|
| warm | Good but vibrato_warm is better |
| extra_warm | Too dark |
| bright | Too harsh |
| formant_down | Changes voice character too much |
| formant_up | Changes voice character too much |
| chorus_warm | Adds weird phasing |
| deessed_warm | Removes too much high end |
| combo_deep | **BROKEN** — too many chained filters causes audio corruption |
| combo_bright | Changes voice character too much |

### Complete Kokoro production pipeline

```bash
# Step 1: vibrato_warm processing
ffmpeg -y -i raw.wav -af \
"vibrato=f=4.5:d=0.06,highpass=f=80,bass=g=3,anequalizer=c0 f=200 w=120 g=1.5 t=1|c0 f=700 w=300 g=-2 t=1|c0 f=2500 w=700 g=2 t=1|c0 f=6000 w=1500 g=-2 t=1,aexciter=drive=3.5:freq=4500:amount=0.6,asoftclip=type=tanh,acompressor=threshold=0.12:ratio=4:attack=15:release=200:makeup=4,lowpass=f=8000,aecho=0.8:0.85:40:0.12,loudnorm=I=-18:TP=-2:LRA=9" \
_voice.wav

# Step 2: Add calibrated noise (Kokoro level)
ffmpeg -y -i _voice.wav -i noise-room-tone.wav -i noise-mic-hiss.wav \
-filter_complex \
"[1]volume=0.45,atrim=0:duration[room];[2]volume=0.24,atrim=0:duration[hiss];[room][hiss]amix=inputs=2[noise];[0][noise]amix=inputs=2:duration=first,loudnorm=I=-17:TP=-2:LRA=10" \
_final.wav

# Step 3: Encode for WhatsApp
ffmpeg -y -i _final.wav -c:a libopus -b:a 24k -ar 16000 -ac 1 output.ogg
```

### WhatsApp output format

- OGG Opus, 24kbps, 16kHz, mono
- WhatsApp applies its own AGC + noise suppression on top

## Padding/Silence/Runaway Generation Issue

### Problem

The model sometimes:
1. Generates seconds of silence before/after the actual speech
2. Enters infinite generation — fills all `max_tokens` (4096 = 5.5 min of silence)
3. Produces noise artifacts in the silent tail

Observed in: `space-pis.wav` (5.5 min), `space-stf.wav` (5.5 min) — both had valid speech in the first 2-3 seconds followed by 5+ minutes of silence/noise.

### Root Cause

The C++ implementation lacks the `AlignmentStreamAnalyzer` that PyTorch Chatterbox uses. The Qwen3-TTS model also lacks this — it relies on the EOS token (2150) being generated naturally. When the model fails to emit EOS, it generates until `max_tokens`.

### Safeguards (MUST IMPLEMENT for production)

#### 1. Dynamic max_tokens based on text length

```python
# ~12.5 tokens per second of audio
# ~8 characters per second of speech
# 5x safety margin
max_tokens = min(4096, max(100, len(text) * 8))
```

For CLI: `--max-tokens 300` for typical phrases (5-10 words).

#### 2. Post-processing: trim silence

After generation, trim leading and trailing silence from the WAV:

```python
import numpy as np

def trim_silence(audio, sr=24000, threshold=0.01, min_silence_ms=500):
    """Remove leading/trailing silence from audio."""
    min_samples = int(min_silence_ms * sr / 1000)
    abs_audio = np.abs(audio)

    # Find first non-silent sample
    start = 0
    for i in range(0, len(audio), min_samples):
        if abs_audio[i:i+min_samples].max() > threshold:
            start = max(0, i - min_samples)
            break

    # Find last non-silent sample
    end = len(audio)
    for i in range(len(audio), 0, -min_samples):
        if abs_audio[max(0,i-min_samples):i].max() > threshold:
            end = min(len(audio), i + min_samples)
            break

    return audio[start:end]
```

#### 3. Per-seed testing for sigla phrases

Some seeds cause runaway generation for specific phrases. Always test the chosen seed with all expected phrase patterns before deploying.

### Sigla categorization

```python
# Siglas pronounced as WORD (do NOT space out)
WORD_ACRONYMS = {'SUS', 'PIX', 'PIS', 'LOAS', 'CEP'}

# Siglas that must be SPELLED (space between letters)
# All other 2+ uppercase letter sequences
def expand_siglas(text):
    import re
    def replacer(match):
        sigla = match.group()
        if sigla in WORD_ACRONYMS:
            return sigla  # keep as word
        return ' '.join(sigla)  # "CNPJ" → "C N P J"
    return re.sub(r'\b[A-Z]{2,}\b', replacer, text)
```

### Tested results (space format, ref-04, temp 0.7, seed 42)

| Sigla | Format | Result |
|---|---|---|
| I N S S | Spaced | Correct |
| C P F | Spaced | Correct |
| **C N P J** | **Spaced** | **Correct** (breakthrough!) |
| F G T S | Spaced | Correct |
| B P C LOAS | Spaced + word | Correct |
| R G | Spaced | Correct |
| C N H | Spaced | Correct |
| SUS | Word (not spaced) | Correct |
| O A B | Spaced | Correct |
| T J | Spaced | Correct |
| S T J | Spaced | Correct |
| S T F | Spaced | **RUNAWAY** (seed 42 — try other seeds) |
| T R T | Spaced | Correct |
| M P | Spaced | Correct |
| I P V A | Spaced | Correct |
| I P T U | Spaced | Correct |
| I R P F | Spaced | Correct |
| PIS | Word (not spaced) | **RUNAWAY when spaced** — must use as word |
| I C M S | Spaced | Correct |
| C E P | Spaced | Needs testing (CEP is often said as word) |
| PIX | Word | Correct |
