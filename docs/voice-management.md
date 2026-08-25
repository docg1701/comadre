# Voice Management (v3.1.13)

Single voice format: `pocket/<name>`. Voices live in `/voices/pocket/`
(the `comadre-voices` volume, mounted `rw` so the app can write uploads).

## Artifact layout

Each voice is up to three files:

| File | Purpose |
|---|---|
| `<name>.wav` | Reference audio — provenance + regeneration source (always kept) |
| `<name>.safetensors` | Model state (precomputed or lazily generated) |
| `<name>.json` | Metadata: `display_name`, `customer_id`, `key_id`, `created_at`, `ref_duration_s`, `model_hash` |

`model_hash` is the sha256 of `POCKET_MODEL_PATH`, computed at startup.
When the meta `model_hash` differs from the current model, the state is
re-encoded from the reference WAV on the next request and the meta is
rewritten — model upgrades never orphan a voice.

## Voice kinds

- **Catalog voice** — `pocket/rafael` (Kyutai embedding, the default).
  Registered virtually from `POCKET_DEFAULT_VOICE_PATH`; not a filesystem
  file.
- **Operator voices** — `/voices/pocket/<name>.wav` (name matches
  `^[a-zA-Z0-9_-]+$`). Drop the WAV → available immediately, no restart.
  The state materializes lazily on first request. Optionally ship a
  precomputed `<name>.safetensors` + `<name>.json` via `deploy-voices.yml`
  (used when `model_hash` matches).
- **API uploads** — `pocket/u_<ULID>`, created by `POST /v1/voices`.
  The `u_` prefix is RESERVED for the API: operator files starting with
  `u_` that are not ULIDs are ignored by the scanner, so stray files can
  never shadow a clone.

### v2 migration note

Existing pre-v3 reference WAVs are reused **verbatim** as
`pocket/*.wav` — pocket-tts consumes them as voice-conditioning audio and
states materialize lazily on first request. Copy them into the `pocket/`
subdirectory of `voices_local_dir` and run `deploy-voices.yml`.

## Cloning lifecycle (API)

`POST /v1/voices` — multipart `file` (+ optional `display_name`,
`persist`). Reference audio: min 3 s, recommended 5-20 s, hard max 30 s
(server truncates), ≤ 10 MB, any libsndfile-decodable format (WAV, MP3,
OGG Vorbis/Opus, FLAC). LGPD consent is required (the
landing page enforces it with a checkbox). For a phonetically balanced
read-aloud script speakers can use to record their reference, see
[voice-reference-script.md](voice-reference-script.md).

| Mode | Storage | Lifetime | Quota |
|---|---|---|---|
| Ephemeral (`persist=false`) | memory-only | idle TTL 3600 s, absolute TTL 86400 s | 5 per key; global LRU cap 50 (oldest evicted) |
| Stored (`persist=true`) | `/voices/pocket/u_<ULID>.*` | until deleted | 20 per customer (`VOICE_STORED_MAX_PER_CUSTOMER`) |

`GET /v1/voices` lists operator voices + the caller-owned stored clones +
the caller-owned ephemeral clones (other customer clones are never
listed). `DELETE /v1/voices/pocket/<name>` removes a caller-owned clone
(204); operator voices return 403 and are managed on the filesystem.

## Operator provisioning

```bash
# Ship voices from the control node (voices_local_dir/pocket/*.wav
# + optional precomputed .safetensors/.json)
cd deploy/ansible
ansible-playbook playbooks/deploy-voices.yml -i inventory/production.yml

# Or drop a WAV directly into the volume:
docker compose exec tts-service mkdir -p /voices/pocket
docker cp minha-voz.wav comadre:/voices/pocket/minha-voz.wav
```

Voice discovery is per-request; new WAVs surface at the next request
(restart the service to force an immediate rescan).

## LGPD verbs (biometric data)

Stored clones are biometric personal data under LGPD:

- `comadre-keys export-customer <id>` now emits a `voices` array
  (`voice`, `display_name`, `created_at`) from
  `voice_storage.list_for_customer`.
- `comadre-keys delete-customer <id> --hard` deletes the customer voice
  files BEFORE the DB purge (files-first: a DB failure cannot leave
  biometrics behind) and records `voices_deleted: N` in the audit row.

## Troubleshooting

- Clone state too slow on first use of a fresh WAV → expected: the first
  request encodes the state (1-2 s for 5-10 s refs); subsequent requests
  load the `.safetensors` directly.
- State regenerating on every request → `model_hash` mismatch (model was
  replaced); correct behavior, not a bug.
- See `docs/troubleshooting.md` for upload validation errors and quotas.
