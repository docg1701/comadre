# Voice Reference Recording Script

A read-aloud script for recording the 5-20 s reference audio that feeds
pocket-tts voice cloning (`POST /v1/voices`). The text below is designed
for Brazilian Portuguese phonetic coverage and natural prosody — the two
properties pocket-tts reproduces from a reference.

Why content matters: pocket-tts clones whatever the reference carries,
including its audio quality (Kyutai explicitly recommends cleaning the
sample before use). A noisy or rushed reference produces a noisy or rushed
clone. One continuous take with steady energy beats several stitched ones.

## Target specs

| Parameter    | Value                              |
| ------------ | ---------------------------------- |
| Duration     | 15-20 s recommended (3 s min, 30 s hard max — server truncates) |
| Format       | WAV, MP3, OGG/Opus (WhatsApp voice notes), or FLAC; ≤ 10 MB; mono or stereo |
| Speaker      | One person only, no music, no second voices |

## Before you record

1. Quiet room, no fan/AC hum, no echo (curtains and furniture help).
2. Microphone 15-25 cm from your mouth, slightly off-axis to avoid pops.
3. Speak at your normal pace and volume — as if answering a customer on
   WhatsApp. Do not whisper, shout, or over-articulate.
4. Keep the same energy from the first word to the last; pause naturally
   at commas and periods.
5. Read once silently first. Then record the whole paragraph in one take.

## The script

Read aloud in one take, relaxed and warm:

> Bom dia! Esta é a minha voz, gravada com calma e clareza, do jeito que eu
> falo todos os dias. O carro da minha irmã quebrou na estrada de terra, mas
> isso não nos impediu de chegar ao trabalho hoje pela manhã. Você gostaria
> de verificar um pagamento, agendar um horário ou falar com alguém da
> nossa equipe?

~58 words ≈ 19-21 s at a natural pace. If your take lands above 25 s,
record the short variant below instead of rushing the main script.

### Short variant (~8-10 s)

> Esta é a minha voz de verdade, falando com calma e alegria. Posso ajudar
> você a resolver tudo hoje mesmo?

## What each sentence exercises

| Feature | Where it appears | Why it matters for pt-BR TTS |
| ------- | ---------------- | ---------------------------- |
| Warm greeting register | "Bom dia! … do jeito que eu falo todos os dias" | Matches the WhatsApp assistant tone the clone will speak in |
| Nasal vowels/diphthongs | "Bom", "não", "irmã", "manhã", "impediu" | Nasality is the most distinctive pt-BR feature; underrepresented nasals flatten cloned speech |
| Strong rhotics /ʁ/ | "carro", "terra", "quebrou" | Contrasts with taps elsewhere ("estrada", "chegar"); anchors rhotic quality |
| Palatalized ti/di | "dias", "dia", "impediu" | Signature BR Portuguese affrication ([tʃi]/[dʒi]) |
| Palatal fricatives | "chegar" (/ʃ/), "hoje", "agendar" (/ʒ/) | Covers both voiced/voiceless palatals |
| /z/ between vowels | "voz", "dias" | Distinguishes s-/z- allophony |
| Palatal consonants lh/nh | "trabalho", "manhã" | Common pt-BR phonemes absent from many generic scripts |
| Consonant clusters | "gravada" (gr), "estrada" (str), "quebrou" (br), "trabalho" (tr) | Keeps clusters crisp instead of vowel-inserted |
| Declarative prosody | Sentence 2 | Falling final intonation, mid-sentence comma pause |
| Interrogative + enumeration | Final question | Rising contour plus list rhythm — tests phrasing and pacing control |

## After recording

1. Trim leading/trailing silence; keep internal pauses as-is.
2. Listen once for clicks, breath blasts, or background events — re-record
   rather than patching.
3. Optional cleanup (Kyutai's recommendation): run through an audio
   enhancer such as Adobe Podcast Enhance before uploading.
4. Upload:
   - Landing page → **Clonar voz** section, or
   - API:

     ```bash
     curl -k -X POST https://10.10.10.207/v1/voices \
       -H "Authorization: Bearer $COMADRE_API_KEY" \
       -F file=@minha-voz.wav \
       -F display_name="Minha Voz" \
       -F persist=true
     ```

The uploaded name is assigned automatically (`pocket/u_<ULID>`); use
`GET /v1/voices` to list it and pass it as `voice` on `POST /v1/audio/speech`.
Stored clones are biometric personal data (LGPD) — record only your own
voice or with documented consent.
