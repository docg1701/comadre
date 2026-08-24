# Comadre API Architecture (v3.1.7)

Single-engine design: kyutai-labs/pocket-tts 2.1.0 (language `portuguese`)
with native voice cloning. The v2 dual-engine (Kokoro + Qwen3) architecture
was removed entirely.

## Module boundaries

Import graph flows downward only:

```text
config / logging
    ↓
exceptions / schemas
    ↓
preprocessing  (normalize_text)
    ↓
service (PocketEngine + VoiceRegistry)   voice_storage (pure file ops)
    ↓
rate_limit → api (speech) / voices_api (clones) → main
```

- HTTP concerns live only in `api.py` / `voices_api.py`; no business
  logic there.
- Model/registry logic lives in `service.py`; no HTTP there.
- `voice_storage.py` is pure filesystem ops on `/voices/pocket/`, shared
  by the API-side VoiceRegistry and the `comadre-keys` CLI LGPD verbs
  (export-customer voices array, delete-customer purge) — the only
  cross-surface import.

## Speech path

```text
POST /v1/audio/speech
   verify_ready -> per-IP gate (600/min) -> verify_api_key -> per-key RPM
   -> FIFO asyncio.Lock (queue_depth++ / --)
   -> PocketEngine.generate_speech(text, voice, fmt, noise_dir, speed, raw, key_id, temperature, seed)
        normalize_text()   # currency/dates/times/phones/percent/numbers → ", " prefix warm-up
        registry.resolve(name, key_id)   # ephemeral first, then filesystem LRU
        model.generate_audio(state, ", " + text, copy_state=True, frames_after_eos=6) -> [1, N] f32 @ 24 kHz
        _samples_to_wav() -> mono 16-bit WAV bytes
        raw ? _encode_final(...) : _apply_pipeline(wav, fmt, noise_dir, speed)
   -> Response(audio bytes, Content-Disposition)
```

`_apply_pipeline` (single pipeline, ex radio_warm): stage-1 ffmpeg filter
(highpass/bass/EQ/acompressor/asoftclip/lowpass/loudnorm) + the `atempo`
chain for `speed != 1.0` (factors in [0.5, 2.0] whose product equals
speed) → stage-2 noise mix (room/hiss WAVs from `noise_dir`) → 500 ms
lead silence (`adelay`, masks the engine's clipped first phoneme) →
encode (OGG Opus 24 kbps 16 kHz mono `-application voip` — verified
against genuine WhatsApp PTT structure — MP3 64 kbps 44.1 kHz mono, or WAV
24 kHz).

## Clone path

```text
POST /v1/voices (multipart: file, display_name, persist)
   verify_ready -> per-IP gate -> verify_api_key -> per-key RPM (same bucket)
   -> Content-Length pre-check (413) -> stream to /tmp with size guard
   -> soundfile validation: empty/format (400), duration 3-30 s (400),
      unreadable (422)
   -> FIFO asyncio.Lock (shared with speech, 120 s timeout)
   -> registry.create_from_upload(tmp, key_id, customer_id, display_name, persist)
        quota checks (stored 20/customer | ephemeral 5/key)
        model.get_state_for_audio_prompt(tmp, truncate=True)  # 30 s cap
        persist: shutil.copyfile -> /voices/pocket/u_<ULID>.wav
                 export_model_state -> u_<ULID>.safetensors
                 write_meta -> u_<ULID>.json {display_name, customer_id,
                    key_id, created_at, ref_duration_s, model_hash}
        ephemeral: in-memory EphemeralVoice with TTLs + global LRU cap
   -> 201 {voice, display_name, persisted, duration_s, sample_rate, expires_at}
   finally: temp file deleted
```

## VoiceRegistry

- **Filesystem scan** at startup: every `/voices/pocket/<name>.wav` (plus
  optional `.safetensors` / `.json`). Names validated against
  `^[a-zA-Z0-9_-]+$` or `u_<ULID>` — traversal impossible by construction.
- **`pocket/rafael`** is a virtual entry backed by
  `POCKET_DEFAULT_VOICE_PATH` (a catalog embedding), so it resolves and
  appears in `/health` like a filesystem voice.
- **State LRU** (maxsize 16): `resolve()` loads `.safetensors` when its
  meta `model_hash` matches the current model; otherwise it re-encodes
  from the reference `.wav` (under the FIFO lock), persists the state, and
  rewrites the meta. `generate_audio(copy_state=True)` deep-copies the
  state per call so generation never mutates the LRU-cached state.
- **Ephemeral registry**: `{key_id: {name: EphemeralVoice}}` in memory.
  Swept every 60 s by an asyncio task (idle TTL 3600 s, absolute TTL
  86400 s, global LRU cap 50). Mutations use snapshot iteration — model
  work happens in worker threads under the FIFO lock; the sweeper runs in
  the event loop.
- **model_hash**: sha256 of `POCKET_MODEL_PATH`, computed once at startup.

## Queue semantics (unchanged from v2)

One `asyncio.Lock` per replica; every model operation (speech generation
AND clone encoding) runs inside it with a 120 s `asyncio.wait_for`. The
API layer owns the lock (`app.state.queue_lock`); `queue_depth` tracks
queued + in-flight requests and surfaces in `/health`. Horizontal scaling
via `deploy.replicas` — Caddy's `least_conn` upstream policy pairs with
the single-lock-per-replica design (active connections ≈ queue depth).

## Lifespan phases

1. Config + logging; registry DB + migrations + auth cache + counters.
2. Model check: `HF_HUB_OFFLINE=1` → verify files exist (fail fast),
   else `ensure_pocket_models()` (HF download, pinned revisions).
3. Noise dir + voices dir checks (`/voices/pocket`).
4. `PocketEngine.load_model(config, threads, quantize, temperature)` and warm-up with the rafael state (seed/temperature are per-request overrides via `torch.manual_seed` / `model.temp`).
5. `VoiceRegistry` build (scan + model_hash) + ephemeral sweeper task
   (cancelled on shutdown) + default-voice validation.
