# Preprocessing Fix Plan — v2 heritage audit (2026-08-23)

Audit of `src/comadre/preprocessing.py` against actual pocket-tts 2.1.0
behavior (source: kyutai-labs/pocket-tts @ master, Aug 2026). Driver:
operator-reported defects — decimal commas stall generation, `/` and
siglas like ABS garble output.

## How pocket-tts actually consumes text

- `prepare_text_prompt` (engine-side): strips, collapses whitespace, drops
  newlines, capitalizes first letter, appends "." when the text ends
  alphanumeric. Semicolons→commas only if the config sets
  `remove_semicolons` (portuguese.yaml does not).
- Sentence-aware chunking (`split_into_best_sentences`) — long inputs are
  fine.
- sentencepiece tokenizer trained on natural pt-BR prose: standard
  punctuation is in-distribution; glued punctuation ("dez,cinquenta"),
  bare symbols ("/", "%", emoji) are not.
- No SSML / emotion markup exists in the engine.

## Audit verdicts (this cycle)

| Routine | Verdict | Notes |
|---|---|---|
| `normalize_currency` | keep | Correct regex (thousands dots + decimal comma), natural word output |
| `normalize_dates` | keep | dd/mm/yyyy correct; short forms still open (below) |
| `normalize_times` | keep | HH:MM correct; `9h30` form still open (below) |
| `normalize_numbers` | **fixed this cycle** | Was integer-only: `10,50` → glued `dez,cinquenta`, `1.234` → `um.duzentos…`. Now decimals read as "dez vírgula cinquenta", thousands groups as one number |
| `expand_siglas` | **needs A/B before changing** | Letter-spacing was Kokoro-era tuning; pocket-tts's sentencepiece may handle intact siglas better. Decide via scripts/spike_pocket_tts.py A/B (ABS/CNPJ/CPF with spacing on/off), not by inspection |

## Remaining fixes (planned, in priority order)

1. **Times like `9h30`** → "nove e trinta" (regex `\b(\d{1,2})h(\d{0,2})\b`,
   also bare `9h`). Very common in WhatsApp messages.
2. **Short dates `12/05`** → "doze de maio" (disambiguate from scores/fractions
   by context? start with month-range validation like normalize_dates).
3. **Percent `50%`** → "cinquenta por cento".
4. **Residual slashes**: after dates/times consume theirs, map remaining
   patterns — `24/7` → "vinte e quatro por sete"; `e/ou` → "e ou";
   any other `/` → space (never feed a raw slash to the engine).
5. **Phone numbers** `(11) 99999-8888` / `+55 11 99999-8888` → digit-by-digit
   reading with pauses ("onze, nove nove nove oito oito...").
6. **Emoji/symbol stripping** — strip emoji, dingbats and stray punctuation
   runs before generation; they tokenize as garbage.
7. **Sigla A/B harness run** — extend spike_pocket_tts.py corpus with the
   operator's failing cases (ABS inside a sentence), record WER/RTF +
   subjective quality, then either keep letter-spacing, invert the default,
   or drop expand_siglas entirely.

Items 1–6 are mechanical regex work behind the existing pipeline order
(currency → dates → times → numbers → siglas) plus a final sanitize pass;
each lands with its own regression test in tests/test_preprocessing.py.
Item 7 is empirical and gates any change to expand_siglas.
