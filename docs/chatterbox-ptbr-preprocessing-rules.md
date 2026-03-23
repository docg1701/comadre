# Chatterbox Multilingual — pt-BR Preprocessing Rules

**Date:** 2026-03-22
**Status:** Empirically tested, rules validated by human listener. **Sigla pronunciation remains unsolved — Chatterbox demoted to second choice for legal domain.**
**Model:** onnx-community/chatterbox-multilingual-ONNX (FP32)
**Inference:** ONNX Runtime with TokenLoopDetector (custom)

## Overview

Chatterbox Multilingual produces excellent pt-BR speech with voice cloning (RTF 1.8x on CPU), but has specific pronunciation issues with Brazilian Portuguese that require text preprocessing before synthesis. These rules were discovered through systematic testing of 100+ audio samples.

## Rule 1: Oxítonas terminadas em vogal acentuada — usar "h" final

**Problem:** The model mispronounces words ending in accented vowels. It either shifts stress to the wrong syllable or changes the vowel sound.

**Solution:** Replace the accented final vowel with the unaccented vowel + "h".

**Applies to:** Words where the LAST character is an accented vowel (á, é, ê, ó, ô).

### Tested and confirmed

| Original | Preprocessing | Model output |
|---|---|---|
| `está` (verb) | `estah` | Correct oxytone stress |
| `até` | `ateh` | Correct |
| `café` | `cafeh` | Correct |
| `você` | `voceh` | Correct |
| `já` | `jah` | Correct |
| `só` | `soh` | Correct |
| `lá` | `lah` | Correct |
| `avó` | `avoh` | Correct (open o) |

### DO NOT apply when

| Original | Keep as-is | Reason |
|---|---|---|
| `atrás` | `atrás` | Ends in consonant "s", not vowel — acento works |
| `através` | `através` | Same — ends in consonant |
| `porém` | `porém` | Ends in consonant "m" — acento works |
| `também` | `também` | Same |
| `três` | `três` | Ends in consonant "s" — acento works |
| `será` | `será` | **Exception:** works with Unicode accent |
| `bebê` | `bebê` | **Exception:** works with Unicode accent |

### NEVER add "h" after consonant

| Bad | Result | Why |
|---|---|---|
| `atrash` | "atrachi" | "sh" = "chi" sound |
| `mesh` | "mexi" | Same |
| `tresh` | "trexi" | Same |
| `atravesh` | "atravechi" | Same |

### Implementation rule (pseudocode)

```python
import re
import unicodedata

# Map: accented vowel → base vowel + h
ACCENT_TO_H = {
    'á': 'ah', 'é': 'eh', 'ê': 'eh', 'ó': 'oh', 'ô': 'oh',
    'Á': 'Ah', 'É': 'Eh', 'Ê': 'Eh', 'Ó': 'Oh', 'Ô': 'Oh',
}

# Known exceptions that work correctly WITH Unicode accent
EXCEPTIONS = {'será', 'bebê', 'atrás', 'através', 'porém', 'também', 'três', 'mês'}

def fix_oxytone_accent(word: str) -> str:
    """Replace final accented vowel with vowel+h for Chatterbox."""
    if word.lower() in EXCEPTIONS:
        return word
    if word and word[-1] in ACCENT_TO_H:
        return word[:-1] + ACCENT_TO_H[word[-1]]
    return word
```

**Key principle:** Only modify the LAST character if it's an accented vowel. Words ending in accented consonant clusters (atrás, porém, três) work correctly without modification.

## Rule 2: Siglas — soletrar com hífen (formato compact)

**Problem:** The model pronounces acronyms as words (CNPJ → "sempiege", INSS → "imsisi") instead of spelling letter by letter.

**Solution:** Replace acronyms with letter names in Portuguese separated by hyphens.

### Brazilian Portuguese letter names

```python
LETTER_NAMES_PTBR = {
    'A': 'ah', 'B': 'bê', 'C': 'cê', 'D': 'dê', 'E': 'eh',
    'F': 'éfe', 'G': 'gê', 'H': 'agah', 'I': 'ih', 'J': 'jóta',
    'K': 'cah', 'L': 'éle', 'M': 'ême', 'N': 'êne', 'O': 'oh',
    'P': 'pê', 'Q': 'quê', 'R': 'érre', 'S': 'ésse', 'T': 'tê',
    'U': 'uh', 'V': 'vê', 'W': 'dáblio', 'X': 'xis', 'Y': 'ípsilon',
    'Z': 'zê',
}

def expand_acronym(acronym: str) -> str:
    """Expand acronym to hyphenated letter names in pt-BR."""
    return '-'.join(LETTER_NAMES_PTBR.get(c, c) for c in acronym.upper())
```

### Tested siglas — INCONSISTENT RESULTS (deal-breaker)

Compact-hífen format is the best found but results are unreliable:

| Original | Preprocessing | Result |
|---|---|---|
| `INSS` | `î-êne-ésse-ésse` | Near-correct but slow/exaggerated |
| `CPF` | `cê-pê-éfe` | Closest to correct |
| `CNPJ` | `cê-êne-pê-jóta` | Inconsistent — sometimes garbled |
| `IPVA` | `î-pê-vê-ah` | Some tests produced "depiei" |
| `BPC` | `bê-pê-cê` | Sometimes becomes "bi-pi-esse" |
| `FGTS` | `éfe-gê-tê-ésse` | Inconsistent |
| `CEP` | raw `CEP` | Should be pronounced as word, not spelled — model says "ceepié" |
| `DPVAT` | `dê-pê-vê-ah-tê` | Came out as "depiei" |

**Conclusion:** Sigla preprocessing via text manipulation does NOT produce reliable results. The model's character-level tokenization fundamentally cannot spell out letters consistently in Portuguese. This makes Chatterbox unsuitable as primary engine for legal domain (INSS, BPC-LOAS, FGTS, STJ, etc.).

### Detection pattern

```python
import re

def detect_acronyms(text: str) -> list[tuple[int, int, str]]:
    """Find acronyms (2+ consecutive uppercase letters) in text."""
    return [(m.start(), m.end(), m.group()) for m in re.finditer(r'\b[A-Z]{2,}\b', text)]
```

### Known common acronyms (domain: legal/financial)

```python
COMMON_ACRONYMS = {
    # Previdência e trabalho
    'INSS': 'î-êne-ésse-ésse',
    'CPF': 'cê-pê-éfe',
    'CNPJ': 'cê-êne-pê-jóta',
    'FGTS': 'éfe-gê-tê-ésse',
    'BPC': 'bê-pê-cê',
    'LOAS': 'loas',  # pronounced as word, not spelled
    'CLT': 'cê-éle-tê',
    # Governo e documentos
    'RG': 'érre-gê',
    'CNH': 'cê-êne-agah',
    'SUS': 'ésse-uh-ésse',
    'OAB': 'oh-ah-bê',
    'TJ': 'tê-jóta',
    'STF': 'ésse-tê-éfe',
    'STJ': 'ésse-tê-jóta',
    'TRT': 'tê-érre-tê',
    'TRF': 'tê-érre-éfe',
    'MP': 'ême-pê',
    # Impostos
    'IPVA': 'î-pê-vê-ah',
    'IPTU': 'î-pê-tê-uh',
    'IRPF': 'î-érre-pê-éfe',
    'PIS': 'pê-î-ésse',
    'ICMS': 'î-cê-ême-ésse',
    # Tecnologia
    'CEP': 'cê-eh-pê',
    'PIX': 'pê-î-xis',
    'SMS': 'ésse-ême-ésse',
    'URL': 'uh-érre-éle',
}
```

## Rule 3: Loop Detection (ONNX only)

**Problem:** The ONNX model lacks the `AlignmentStreamAnalyzer` from PyTorch, causing infinite generation loops that produce silence for certain words.

**Solution:** `TokenLoopDetector` class monitors generated tokens and forces EOS when loops are detected.

### Detection methods

1. **Token 3x repetition:** Same token appears 3 times consecutively → force EOS
2. **ABAB pattern:** Alternating pair detected → force EOS
3. **Silence loop:** 5+ consecutive silence tokens (4299) → force EOS
4. **Max tokens:** Proportional to text length (`min(768, len(text) * 6 + 100)`) → force EOS
5. **EOS suppression:** Prevent premature EOS before `max(15, len(text) * 1.5)` tokens

### Constants

```python
START_SPEECH_TOKEN = 6561
STOP_SPEECH_TOKEN = 6562  # EOS
S3GEN_SIL = 4299          # silence token
```

## Rule 4: Pronome demonstrativo "esta" vs verbo "está"

**Problem:** "esta" (demonstrative pronoun, paroxytone) and "está" (verb, oxytone) are different words. The model handles "esta" correctly but not "está".

**Solution:** Always write the verb form as `estah`. The pronoun form `esta` needs no modification.

```python
# Context-dependent: requires NLP or simple heuristic
# Simple heuristic: if "está" has accent, it's the verb → estah
# If "esta" has no accent, it's the pronoun → keep as-is
```

## Performance Summary (ONNX FP32 + Loop Detection + Preprocessing)

| Metric | Value |
|---|---|
| RTF (CPU, 4 cores) | 1.8-2.1x |
| RAM | ~5 GB peak |
| Voice cloning | Zero-shot with reference audio |
| Audio sample rate | 24 kHz |
| Max phrase length | ~300 characters recommended |

## Known Remaining Issues

1. **Sigla pronunciation speed:** Hyphened siglas are spoken slightly slower than natural — acceptable but noticeable
2. **"aliás":** Unicode accent fails (pronounced "aliá"), but ends in consonant so "h" rule doesn't apply. Needs investigation.
3. **Some exceptions may exist:** The oxítona rules cover the tested words but untested words may behave differently
4. **ONNX Q4 quantization:** Broken for Portuguese — generates garbage. Use FP32 only.
5. **ONNX FP16:** Same RTF as FP32, no benefit. Use FP32.
