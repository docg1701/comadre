# Preprocessing Fix Plan — v2 heritage audit (2026-08-23, closed 3.1.2)

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
| `normalize_currency` | **shipped 3.1.2** | Correct regex (thousands dots + decimal comma), natural word output |
| `normalize_dates` | **shipped 3.1.2** | dd/mm/yyyy + short `12/05` → "doze de maio" (validated ranges) |
| `normalize_times` | **shipped 3.1.2** | `14:00` + `9h30`/`9h` → "nove e trinta" / "nove horas" |
| `normalize_numbers` | **shipped 3.1.2** | Was integer-only: `10,50` → glued `dez,cinquenta`, `1.234` → `um.duzentos…`. Now decimals + thousands read naturally |
| `expand_siglas` | **removed** | Letter-spacing was Kokoro-era tuning. The 2026-08-23 A/B (same voice, same seed) showed pocket-tts reads intact siglas (`ABS`, `CNPJ`) more naturally — the routine and its `POCKET_SIGLA_SPACING` flag were deleted. |

## Fixes shipped in 3.1.2 (all items closed)

1. **Times `9h30`/`9h`** → "nove e trinta" / "nove horas" — `normalize_times`.
2. **Short dates `12/05`** → "doze de maio" — `normalize_short_dates`.
3. **Percent `50%`** → "cinquenta por cento" — `normalize_percent`.
4. **Residual slashes** — `24/7` → "vinte e quatro por sete"; remaining `/` → space.
5. **Phone numbers** `(11) 99999-8888` → digit groups `"um um. nove nove..."` — `normalize_phones` (period-separated, Whisper-verified).
6. **Emoji/URL/symbol stripping** — `sanitize_text` drops URLs, emoji blocks, stray slashes.
7. **Sigla A/B — RESOLVED 2026-08-23**: intact siglas won decisively;
   `expand_siglas()` and `POCKET_SIGLA_SPACING` were removed entirely.

All items landed with regression tests in `tests/test_preprocessing.py`.
Order: currency → dates → times → phones → numbers (thousands/decimal/ordinal/integer) →
percent → 24/7 → short dates → sanitize.
