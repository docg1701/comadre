# Chatterbox TTS — Complete Token & Feature Reference

**Date:** 2026-03-22
**Source:** Analysis of resemble-ai/chatterbox source code (v0.1.6)

## Overview

Chatterbox is a character-level TTS model. It does NOT support phoneme input, SSML, or pronunciation overrides. The only text control is through character-level preprocessing and special bracket tokens.

## Special Tokens

### Text Control Tokens

| Token | ID | Purpose |
|---|---|---|
| `[START]` | 255 | Start of text sequence |
| `[STOP]` | 0 | End of text sequence |
| `[SPACE]` | 2 | Word space (replaces literal spaces internally) |
| `[UNK]` | 1 | Unknown token |
| `[PAD]` | 705 | Padding |

### Speech Tokens

| Token | ID | Purpose |
|---|---|---|
| Start speech | 6561 | Beginning of speech generation |
| Stop speech | 6562 | End of speech generation (EOS) |
| Silence | 4299 | S3Gen silence token |

Speech vocabulary: 6561 tokens (IDs 0-6560). Rate: 25 tokens/second.

### Language Tags (Multilingual model only)

Prepended to text before tokenization: `[pt]Olá mundo.`

Supported: ar, da, de, el, en, es, fi, fr, he, hi, it, ja, ko, ms, nl, no, pl, **pt**, ru, sv, sw, tr, zh

### Paralinguistic Tags (Turbo model ONLY — NOT available in Multilingual)

```text
[clear throat] [sigh] [shush] [cough] [groan]
[sniff] [gasp] [chuckle] [laugh]
```

These are recognized by the Turbo model's GPT2 tokenizer. They do NOT work in the Multilingual model.

### Non-Functional Tokens

| Token | ID | Status |
|---|---|---|
| `[ipa]` | 638 | **EXISTS in vocabulary but NOT implemented.** Model pronounces "ipa" literally. No phoneme control. |
| `[end_of_label]` | 639 | Reserved, no documented behavior |
| `[PLACEHOLDER45-63]` | 695-703, 2065 | Reserved for future use |

## Text Preprocessing Pipeline

### punc_norm() — Applied to ALL input text

```text
1. Capitalize first letter
2. Collapse multiple spaces
3. Replace: ... → ,  : → ,  ; → ,  — → -  " → "  ' → '
4. Ensure final punctuation (. ! ? - ,)
```

No acronym detection, no pronunciation control, no phoneme expansion.

### Language-Specific Normalization (Multilingual tokenizer)

| Language | Normalization | Library |
|---|---|---|
| Chinese (zh) | Characters → Cangjie codes (`[cj_a][cj_b][cj_.]`) | pkuseg |
| Japanese (ja) | Kanji → Hiragana, keep Katakana | pykakasi |
| Hebrew (he) | Add diacritical marks (vowelization) | dicta_onnx |
| Korean (ko) | Syllables → Jamo decomposition | Built-in |
| Russian (ru) | Add stress marks (accent diacritics) | russian_text_stresser |
| **Portuguese (pt)** | **NFKD Unicode normalization only** | Built-in |

**Key finding:** Portuguese has NO special normalization. Russian gets stress marks — Portuguese does not.

## Generation Parameters

| Parameter | Default | Range | Models | Purpose |
|---|---|---|---|---|
| `temperature` | 0.8 | 0.0-2.0 | All | Sampling randomness |
| `top_p` | 0.95-1.0 | 0.0-1.0 | All | Nucleus sampling |
| `repetition_penalty` | 1.2-2.0 | 1.0+ | All | Token repetition penalty |
| `exaggeration` | 0.5 | 0.0-1.0 | English/MTL | Emotion intensity |
| `cfg_weight` | 0.5 | 0.0-1.0 | English/MTL | Text adherence strength |
| `min_p` | 0.05 | 0.0-1.0 | English/MTL | Minimum probability |

## Voice Cloning

- Speaker embedding: 256-dimensional vector from VoiceEncoder
- Reference audio: 6+ seconds recommended, 16kHz
- Zero-shot: no training needed per voice

## Model Variants

| Feature | English (500M) | **Multilingual (500M)** | Turbo (350M) |
|---|---|---|---|
| Languages | 1 | **23** | 1 |
| Paralinguistic tags | No | **No** | Yes |
| Exaggeration control | Yes | **Yes** | No |
| CFG weight | Yes | **Yes** | No |
| Alignment analyzer | No | **Yes** | No |
| Voice cloning | Yes | **Yes** | Yes |

## What Does NOT Exist

- **No SSML support** — no `<say-as>`, no `<phoneme>`, no `<break>`
- **No IPA input** — `[ipa]` token exists but is non-functional
- **No pronunciation dictionary** — cannot override word pronunciation
- **No stress marking for Portuguese** — only Russian has stress support
- **No acronym expansion** — model treats uppercase sequences as regular text
- **No phoneme-level control** — model works exclusively at character/grapheme level

## Implications for pt-BR

All pronunciation fixes must be done via **text preprocessing** before the model sees the text:

1. **Siglas:** Must be expanded in text — but results are INCONSISTENT. Deal-breaker for legal domain.
2. **Oxítonas com acento final:** Unicode accents on final vowels often fail; "h" suffix works better (`está` → `estah`)
3. **No fallback:** There is no way to provide pronunciation hints to the model inline

## Final Verdict

**Chatterbox is demoted to second choice** for the cumadre project due to unreliable sigla pronunciation. It remains an excellent engine for non-legal contexts where siglas are rare. Qwen3-TTS is being evaluated as replacement for voice cloning with sigla support.
