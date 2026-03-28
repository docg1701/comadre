# Voice Management

COMADRE discovers voices from the filesystem at request time. Drop a file in the right directory and it's immediately available — no restart needed.

## Volume Structure

The `comadre-voices` Docker volume is mounted at `/voices/` with two subdirectories:

```text
/voices/
  kokoro/          <- Kokoro custom voice profiles (.npy)
  qwen/            <- Qwen3 reference audio for cloning (.wav)
```

## Adding Voices

### Kokoro Voices (.npy files)

Kokoro uses voice style vectors stored as numpy arrays. Two sources:

1. **Built-in voices** — bundled in `voices-v1.0.bin` (the .npz archive). These work automatically without any files. Examples: `pm_santa`, `pf_dora`, `pm_alex`, and 50+ others.

2. **Custom voices** — `.npy` files placed in `/voices/kokoro/`. These are voice style vectors exported from your voice cloning pipeline.

To add a custom Kokoro voice:

```bash
# Copy the .npy file into the volume
docker cp joao.npy tts-service:/voices/kokoro/
```

The voice is immediately available as `kokoro/joao`.

### Qwen3 Voices (.wav files)

Qwen3 uses reference audio files (3-10 seconds, WAV format) for voice cloning via the `-r` flag.

To add a Qwen3 voice:

```bash
# Copy the reference WAV into the volume
docker cp galvani.wav tts-service:/voices/qwen/
```

The voice is immediately available as `qwen/galvani`.

**WAV requirements:**

- Format: WAV (16-bit PCM)
- Duration: 3-10 seconds recommended
- Content: clean speech sample of the target voice

## API Usage

The `voice` parameter uses the format `{engine}/{name}`:

```json
{
  "input": "Hello, this is a test.",
  "voice": "kokoro/pm_santa",
  "response_format": "ogg"
}
```

### Examples for n8n HTTP Request node

**Kokoro built-in voice:**

```json
{
  "input": "{{ $json.message }}",
  "voice": "kokoro/pm_santa"
}
```

**Kokoro custom cloned voice:**

```json
{
  "input": "{{ $json.message }}",
  "voice": "kokoro/joao"
}
```

**Qwen3 cloned voice:**

```json
{
  "input": "{{ $json.message }}",
  "voice": "qwen/galvani"
}
```

### Default voice

If `voice` is omitted, the service uses the `DEFAULT_VOICE` environment variable (default: `kokoro/pm_santa`).

## Listing Available Voices

The `/health` endpoint returns all available voices:

```bash
curl -s http://localhost:8000/health | jq '.voices'
```

Output:

```json
[
  "kokoro/pf_dora",
  "kokoro/pm_alex",
  "kokoro/pm_santa",
  "qwen/female-reference",
  "qwen/galvani"
]
```

## Voice Name Rules

- Names may contain: letters, digits, hyphens (`-`), underscores (`_`)
- No spaces, dots, slashes, or special characters
- The filename stem (without extension) becomes the voice name
- Example: `my-voice_01.wav` -> voice name `qwen/my-voice_01`

## Migration from Previous Versions

Old voice names map to the new format:

| Old name      | New name                   | Notes                          |
|---------------|----------------------------|--------------------------------|
| `santa`       | `kokoro/pm_santa`          | Built-in, no file needed       |
| `dora`        | `kokoro/pf_dora`           | Built-in, no file needed       |
| `alex`        | `kokoro/pm_alex`           | Built-in, no file needed       |
| `qwen-female` | `qwen/female-reference`    | Requires .wav in /voices/qwen/ |
| `qwen-male`   | `qwen/male-reference`      | Requires .wav in /voices/qwen/ |
| `clone`       | `qwen/<your-reference>`    | Use the actual filename         |

## Deploy via Ansible

Use the `deploy-voices.yml` playbook to deploy voice files to the VPS:

```bash
cd deploy/ansible
ansible-playbook playbooks/deploy-voices.yml -i inventory/production.yml
```

Set `voices_local_dir` in `inventory/production.yml` to the local directory containing your `kokoro/` and `qwen/` subdirectories with voice files.

After deploying voices, the service picks them up immediately — no restart needed. Run `ansible-playbook playbooks/health.yml` to verify.
