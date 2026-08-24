"""TTS engine service — pocket-tts single-engine integration with native voice cloning.

v3: pocket-tts is the ONLY engine. Voice format is pocket/<name>:
operator voices live on the filesystem as /voices/pocket/<name>.wav
(state materialized lazily), API uploads live as /voices/pocket/u_<ULID>
(persisted) or in the in-memory ephemeral registry.

All model work (state encode + speech generation) runs under the
per-replica FIFO asyncio.Lock owned by the API layer (api.py /
voices_api.py); this module never acquires it.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import subprocess
import wave
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import torch
import ulid
from pocket_tts import TTSModel, export_model_state

from comadre import voice_storage
from comadre.config import Settings
from comadre.exceptions import (
    GenerationError,
    InvalidRequestError,
    VoiceDeleteError,
    VoiceLimitError,
    VoiceNotFoundError,
    VoiceUnreadableError,
    VoiceUploadError,
)
from comadre.logging import get_logger
from comadre.preprocessing import normalize_text
from comadre.timeutil import iso_utc as _iso_utc
from comadre.timeutil import now_utc as _now_utc
from comadre.timeutil import parse_iso_utc as _parse_iso_utc

if TYPE_CHECKING:
    from numpy.typing import NDArray

logger = get_logger("request")
startup_logger = get_logger("startup")

_VOICE_PREFIX = "pocket/"

# Lead silence prepended to every generated audio: pocket-tts clips the
# first phoneme without it (operator-reported, 2026-08-23).
_LEAD_SILENCE_MS = 500


def _audio_duration_seconds(path: Path) -> float:
    """Duration of an audio file in seconds via soundfile."""
    import soundfile as sf

    info = sf.info(str(path))
    if info.samplerate <= 0:
        raise ValueError("audio file has no valid sample rate")
    return float(info.frames / info.samplerate)


@dataclass(slots=True)
class VoiceInfo:
    """Public-facing description of a voice (listing / create responses)."""

    voice: str
    display_name: str | None
    persisted: bool
    created_at: datetime | None
    expires_at: datetime | None


@dataclass(slots=True)
class EphemeralVoice:
    """In-memory ephemeral clone (per-key, never on disk)."""

    key_id: str
    customer_id: str
    display_name: str | None
    state: dict[str, Any]
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime


class PocketEngine:
    """Wraps pocket-tts TTSModel for speech generation."""

    CHAR_LIMIT = 1000

    def __init__(self) -> None:
        self._model: TTSModel | None = None
        self._registry: VoiceRegistry | None = None

    @property
    def is_loaded(self) -> bool:
        """Return True if the pocket-tts model is loaded."""
        return self._model is not None

    @property
    def sample_rate(self) -> int:
        """Model output sample rate (24000 for pocket-tts)."""
        if self._model is None:
            raise GenerationError("Model not loaded — call load_model() first")
        return int(self._model.sample_rate)

    def attach_registry(self, registry: VoiceRegistry) -> None:
        """Bind the voice registry used to resolve voice names."""
        self._registry = registry

    def load_model(
        self,
        config_path: str | Path,
        threads: int,
        quantize: bool,
        temperature: float,
        *,
        eos_threshold: float = -2.0,
    ) -> None:
        """Load the pocket-tts model from a local config YAML.

        The upstream pocket_tts import calls torch.set_num_threads(1);
        we override with the operator-configured thread count AFTER the
        import, per decision D15.
        """
        torch.set_num_threads(threads)
        startup_logger.info(
            "Loading pocket-tts model (config=%s, threads=%d, quantize=%s, "
            "temperature=%.2f, eos_threshold=%.2f)...",
            config_path,
            threads,
            quantize,
            temperature,
            eos_threshold,
        )
        self._model = TTSModel.load_model(
            config=config_path,
            quantize=quantize,
            temp=temperature,
            eos_threshold=eos_threshold,
        )
        startup_logger.info(
            "pocket-tts model loaded (sample_rate=%d)", self._model.sample_rate
        )

    def warm_up(self, default_state_path: Path) -> None:
        """Run dummy inference to preload model internals."""
        if self._model is None:
            raise GenerationError("Model not loaded — call load_model() first")
        startup_logger.info("Running warm-up inference...")
        state = self._model.get_state_for_audio_prompt(default_state_path)
        self._model.generate_audio(state, "Teste de aquecimento.", copy_state=True)
        startup_logger.info("Warm-up complete")

    def get_state_for_audio_prompt(
        self, audio_path: Path, *, truncate: bool = False
    ) -> dict[str, Any]:
        """Encode a reference audio into a model state (voice cloning)."""
        if self._model is None:
            raise GenerationError("Model not loaded — call load_model() first")
        return self._model.get_state_for_audio_prompt(  # type: ignore[no-any-return]
            audio_path, truncate=truncate
        )

    def generate_speech(
        self,
        text: str,
        voice_name: str,
        response_format: str,
        noise_dir: Path | None = None,
        speed: float = 1.0,
        *,
        raw: bool = False,
        key_id: str | None = None,
        temperature: float | None = None,
        seed: int | None = None,
    ) -> bytes:
        """Generate speech via pocket-tts.

        Args:
            text: Input text to synthesize.
            voice_name: Voice identifier as pocket/<name>.
            response_format: Output format — ogg, mp3 or wav.
            noise_dir: Directory containing room/hiss noise WAV files.
            speed: Playback speed multiplier (1.0 = normal). Applied for
                ALL voices as an ffmpeg atempo chain in post-processing
                (0.25-4.0 enforced upstream in schemas.py).
            raw: Skip the post-processing pipeline (no EQ/compression/
                noise/tempo) — still encodes to the requested format.
            key_id: Registry key id, used to resolve the callers
                ephemeral clones.
            temperature: Sampling temperature override (None = model
                default). Lower values sound more consistent, higher more
                expressive. Generation runs under the FIFO lock, so the
                per-request mutation of the shared model attribute is safe.
            seed: Torch RNG seed for reproducible generation; same text +
                voice + seed yields bit-identical prosody.

        Returns:
            Audio bytes in the requested format.

        Raises:
            InvalidRequestError: malformed voice / format / empty text /
                text over the character limit.
            VoiceNotFoundError: unknown voice name.
            GenerationError: model failure.
        """
        if response_format not in ("wav", "ogg", "mp3"):
            raise InvalidRequestError(
                message=f"Unsupported response format: {response_format!r}",
                hint="Supported formats: ogg, mp3, wav.",
            )

        if not text.strip():
            raise InvalidRequestError(
                message="Text must not be empty",
                hint="Provide non-empty text for speech synthesis.",
            )

        if len(text) > self.CHAR_LIMIT:
            raise InvalidRequestError(
                message=(
                    f"Text exceeds {self.CHAR_LIMIT} character limit"
                    f" ({len(text)} chars)"
                ),
                hint=f"Shorten your text to {self.CHAR_LIMIT} characters or fewer.",
            )

        name = _parse_voice(voice_name)
        if self._model is None:
            raise GenerationError("Model not loaded — call load_model() first")
        if self._registry is None:
            raise GenerationError(
                "Voice registry not attached — call attach_registry()"
            )

        normalized = normalize_text(text)
        state = self._registry.resolve(name, key_id=key_id)
        logger.info(
            "Generating speech for %d characters (voice=%s)", len(text), voice_name
        )

        try:
            if temperature is not None:
                self._model.temp = float(temperature)
            if seed is not None:
                torch.manual_seed(seed)
            # Leading ", " warms up the flow-LM: without it the first word
            # is frequently swallowed ("Consulte" -> "sulte") or tiny inputs
            # come out as noise (whisper-verified A/B, 2026-08-23). The comma
            # absorbs the under-formed early frames as an audible micro-pause.
            audio = self._model.generate_audio(
                state,
                ", " + normalized,
                copy_state=True,
                frames_after_eos=6,
            )
            samples = audio.detach().cpu().numpy()
            wav_bytes = _samples_to_wav(samples, self.sample_rate)
        except (InvalidRequestError, GenerationError):
            raise
        except Exception as exc:
            logger.error("TTS generation failed: %s", exc, exc_info=True)
            raise GenerationError(f"TTS generation failed: {exc}") from exc

        if raw:
            return _encode_final(wav_bytes, response_format)
        return _apply_pipeline(wav_bytes, response_format, noise_dir, speed)


def _parse_voice(voice_name: str) -> str:
    """Parse pocket/<name> and validate the name; returns the bare name."""
    parts = voice_name.split("/", 1)
    if len(parts) != 2 or parts[0] != "pocket" or not parts[1]:
        raise InvalidRequestError(
            message=f"Invalid voice format: {voice_name!r}",
            hint="Voice must be pocket/<name>.",
        )
    name = parts[1]
    if not voice_storage.is_valid_voice_name(name):
        raise InvalidRequestError(
            message=f"Invalid voice name: {name!r}",
            hint=(
                "Voice name may only contain letters, digits, hyphens, and underscores."
            ),
        )
    return name


def _transcode_to_wav(src: Path, dst: Path) -> None:
    """Transcode any soundfile-readable upload into PCM WAV 24 kHz mono."""
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(src),
            "-ar",
            "24000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(dst),
        ],
        capture_output=True,
        timeout=60,
    )
    if result.returncode != 0 or not dst.is_file() or dst.stat().st_size == 0:
        stderr = result.stderr.decode(errors="replace")[-300:]
        raise VoiceUnreadableError() from RuntimeError(
            f"ffmpeg transcode failed for {src.name}: {stderr}"
        )


def _samples_to_wav(samples: NDArray[np.float32], sample_rate: int) -> bytes:
    """Convert float32 audio samples to WAV bytes (mono, 16-bit)."""
    if samples.ndim > 1:
        samples = samples.reshape(-1)  # mono model: flatten [1, N]
    int16_samples = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(int16_samples.tobytes())
    return buf.getvalue()


def _atempo_chain(speed: float) -> str:
    """Decompose speed into ffmpeg atempo factors in [0.5, 2.0].

    atempo only accepts factors in [0.5, 2.0]; chain factors whose
    product equals speed (e.g. 0.25 -> 0.5,0.5; 4.0 -> 2.0,2.0;
    1.0 -> no filter).
    """
    if speed == 1.0:
        return ""
    factors: list[float] = []
    remaining = speed
    while remaining > 2.0:
        factors.append(2.0)
        remaining /= 2.0
    while remaining < 0.5:
        factors.append(0.5)
        remaining /= 0.5
    if abs(remaining - 1.0) > 1e-6:
        factors.append(round(remaining, 6))
    return ",".join(f"atempo={f}" for f in factors)


def _apply_pipeline(
    wav_bytes: bytes,
    response_format: str,
    noise_dir: Path | None = None,
    speed: float = 1.0,
) -> bytes:
    """Apply the single post-processing pipeline via ffmpeg.

    Stage 1: Audio effects (EQ, compression, saturation, loudnorm) plus
    the optional atempo speed chain. Stage 2: noise mixing + final
    encoding (OGG Opus, MP3 or WAV). Constants carried over from the v2
    radio_warm chain (Phase 0 starting point; re-tune via
    scripts/spike_pocket_tts.py against the v2 baselines).
    """
    # Stage 1: Audio effects
    stage1_filter = (
        "highpass=f=100,"
        "bass=g=5:f=150,"
        "equalizer=f=250:width_type=o:width=1:g=3,"
        "equalizer=f=600:width_type=o:width=2:g=-4,"
        "equalizer=f=3500:width_type=o:width=1.5:g=5,"
        "acompressor=ratio=6:threshold=-24dB:attack=2:release=100:makeup=2,"
        "asoftclip=type=tanh:param=0.3,"
        "lowpass=f=7000,"
        "loudnorm=I=-16:TP=-1:LRA=4"
    )
    atempo = _atempo_chain(speed)
    if atempo:
        stage1_filter += "," + atempo

    stage1_cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "wav",
        "-i",
        "pipe:0",
        "-af",
        stage1_filter,
        "-ar",
        "24000",
        "-f",
        "wav",
        "pipe:1",
    ]

    try:
        stage1 = subprocess.run(
            stage1_cmd,
            input=wav_bytes,
            capture_output=True,
            check=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        logger.error("ffmpeg stage 1 timed out after 30s")
        raise GenerationError("Audio post-processing timed out (stage 1)") from exc
    except subprocess.CalledProcessError as exc:
        logger.error("ffmpeg stage 1 failed: %s", exc.stderr.decode(errors="replace"))
        raise GenerationError("Audio post-processing failed (stage 1)") from exc

    processed_wav = stage1.stdout
    if not processed_wav:
        raise GenerationError("ffmpeg stage 1 produced empty output")

    # Stage 2: Noise mixing + final encoding
    room_noise = _find_noise_file(noise_dir, "room")
    hiss_noise = _find_noise_file(noise_dir, "hiss")

    if room_noise is not None and hiss_noise is not None:
        return _apply_noise_and_encode(
            processed_wav,
            room_noise,
            hiss_noise,
            response_format,
            room_volume=0.45,
            hiss_volume=0.24,
        )

    if noise_dir is not None:
        missing = []
        if room_noise is None:
            missing.append("room")
        if hiss_noise is None:
            missing.append("hiss")
        logger.warning(
            "Missing noise file(s) in %s: %s — skipping noise mixing",
            noise_dir,
            missing,
        )

    # No noise mixing — just encode to final format
    return _encode_final(processed_wav, response_format)


def _find_noise_file(noise_dir: Path | None, kind: str) -> Path | None:
    """Find a noise WAV file by kind (room/hiss) in the noise directory."""
    if noise_dir is None:
        return None
    candidates = [
        noise_dir / f"{kind}.wav",
        noise_dir / f"{kind}_noise.wav",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def _apply_noise_and_encode(
    processed_wav: bytes,
    room_noise: Path,
    hiss_noise: Path,
    response_format: str,
    room_volume: float = 0.45,
    hiss_volume: float = 0.24,
) -> bytes:
    """Mix noise and encode to final format (OGG Opus, MP3 or WAV)."""
    if response_format == "ogg":
        codec_args = [
            "-c:a",
            "libopus",
            "-b:a",
            "24k",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-application",
            "voip",
        ]
        fmt = "ogg"
    elif response_format == "mp3":
        codec_args = [
            "-c:a",
            "libmp3lame",
            "-b:a",
            "64k",
            "-ar",
            "24000",
            "-ac",
            "1",
        ]
        fmt = "mp3"
    else:
        codec_args = ["-ar", "24000", "-ac", "1"]
        fmt = "wav"

    filter_complex = (
        f"[1:a]volume={room_volume}[room];"
        f"[2:a]volume={hiss_volume}[hiss];"
        "[0:a][room][hiss]amix=inputs=3:duration=shortest,"
        f"adelay={_LEAD_SILENCE_MS}:all=1,"
        "loudnorm=I=-17:TP=-1.5:LRA=7"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "wav",
        "-i",
        "pipe:0",
        "-i",
        str(room_noise),
        "-i",
        str(hiss_noise),
        "-filter_complex",
        filter_complex,
        *codec_args,
        "-f",
        fmt,
        "pipe:1",
    ]

    try:
        result = subprocess.run(
            cmd,
            input=processed_wav,
            capture_output=True,
            check=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        logger.error("ffmpeg stage 2 timed out after 30s")
        raise GenerationError("Audio post-processing timed out (stage 2)") from exc
    except subprocess.CalledProcessError as exc:
        logger.error("ffmpeg stage 2 failed: %s", exc.stderr.decode(errors="replace"))
        raise GenerationError("Audio post-processing failed (stage 2)") from exc

    if not result.stdout:
        raise GenerationError("ffmpeg stage 2 produced empty output")

    return result.stdout


def _encode_final(processed_wav: bytes, response_format: str) -> bytes:
    """Encode processed WAV to final format without noise mixing.

    Prepends _LEAD_SILENCE_MS of silence (pocket-tts clips the first
    phoneme otherwise), applies the final loudnorm pass (-17 LUFS) that
    would normally come after noise mixing, then encodes to the requested
    format.
    """
    if response_format == "wav":
        codec_args = ["-ar", "24000", "-ac", "1", "-f", "wav"]
    elif response_format == "mp3":
        codec_args = [
            "-c:a",
            "libmp3lame",
            "-b:a",
            "64k",
            "-ar",
            "44100",
            "-ac",
            "1",
            "-f",
            "mp3",
        ]
    else:
        codec_args = [
            "-c:a",
            "libopus",
            "-b:a",
            "24k",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-application",
            "voip",
            "-f",
            "ogg",
        ]

    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "wav",
        "-i",
        "pipe:0",
        "-af",
        f"adelay={_LEAD_SILENCE_MS}:all=1,loudnorm=I=-17:TP=-1.5:LRA=7",
        *codec_args,
        "pipe:1",
    ]

    try:
        result = subprocess.run(
            cmd,
            input=processed_wav,
            capture_output=True,
            check=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        logger.error("ffmpeg encoding timed out after 30s")
        raise GenerationError("Audio encoding timed out") from exc
    except subprocess.CalledProcessError as exc:
        logger.error("ffmpeg encoding failed: %s", exc.stderr.decode(errors="replace"))
        raise GenerationError("Audio encoding failed") from exc

    if not result.stdout:
        raise GenerationError("ffmpeg encoding produced empty output")

    return result.stdout


class VoiceRegistry:
    """Filesystem scan + state LRU + ephemeral clone registry.

    Threading discipline: model-heavy methods (resolve, create_from_upload)
    run inside worker threads UNDER the API layer FIFO lock. The
    sweeper runs in the event loop. All dict mutations use snapshot
    iteration (list(...)) and single-key atomic ops so the two never
    corrupt each other; the GIL makes individual dict operations atomic.
    """

    LRU_MAXSIZE = 16
    SWEEP_INTERVAL_SECONDS = 60

    def __init__(
        self, engine: PocketEngine, voices_dir: Path, settings: Settings
    ) -> None:
        self._engine = engine
        self._settings = settings
        self._pocket_dir = voices_dir / "pocket"
        self._files: dict[str, voice_storage.VoiceFileEntry] = {}
        for entry in voice_storage.scan_entries(self._pocket_dir):
            self._files[entry.name] = entry
        self._loaded: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._ephemeral: dict[str, dict[str, EphemeralVoice]] = {}
        self._model_hash = self._hash_model_file()
        self._sweeper_task: asyncio.Task[None] | None = None
        # The catalog default voice (pocket/rafael) is a model-level
        # embedding, not a filesystem entry: register it virtually so
        # it resolves and appears in available_voices() / /health.
        self._rafael_path = Path(settings.pocket_default_voice_path)
        if self._rafael_path.is_file():
            self._files.setdefault(
                "rafael",
                voice_storage.VoiceFileEntry(
                    name="rafael",
                    ref_path=self._rafael_path,
                    state_path=self._rafael_path,
                    meta={
                        "display_name": "Rafael",
                        "model_hash": self._model_hash,
                    },
                ),
            )
        else:
            startup_logger.warning(
                "Default voice state not found: %s — pocket/rafael will not resolve",
                self._rafael_path,
            )
        startup_logger.info(
            "Voice registry built: %d filesystem voice(s), model_hash=%s...",
            len(self._files),
            self._model_hash[:12],
        )

    @property
    def model_hash(self) -> str:
        """SHA-256 of POCKET_MODEL_PATH, computed once at startup."""
        return self._model_hash

    def _hash_model_file(self) -> str:
        path = Path(self._settings.pocket_model_path)
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    def _state_matches_model(self, entry: voice_storage.VoiceFileEntry) -> bool:
        # model_hash drives lazy state regen; it fingerprints the public
        # model weights and is not secret material.
        return entry.meta.get("model_hash") == (
            self._model_hash  # scan-allow[timing-safe-compare]: not secret
        )

    def _load_state(self, entry: voice_storage.VoiceFileEntry) -> dict[str, Any]:
        """Load (or lazily materialize) the model state for an entry.

        Loads a precomputed .safetensors when its meta model_hash matches
        the current model; otherwise encodes the reference .wav, persists
        the state + metadata, and returns the fresh state. Callers must
        hold the FIFO queue lock (model work).
        """
        if entry.state_path.is_file() and self._state_matches_model(entry):
            state = self._engine.get_state_for_audio_prompt(entry.state_path)
            return state
        startup_logger.info(
            "Materializing voice state for %r from %s",
            entry.name,
            entry.ref_path,
        )
        state = self._engine.get_state_for_audio_prompt(entry.ref_path, truncate=True)
        export_model_state(state, entry.state_path)
        try:
            duration = _audio_duration_seconds(entry.ref_path)
        except (OSError, ValueError, RuntimeError):
            duration = 0.0
        voice_storage.write_meta(
            self._pocket_dir,
            entry.name,
            model_hash=self._model_hash,
            ref_duration_s=duration,
        )
        refreshed = voice_storage.scan_entries(self._pocket_dir)
        for refreshed_entry in refreshed:
            if refreshed_entry.name == entry.name:
                self._files[entry.name] = refreshed_entry
                break
        return state

    def _refresh_files(self) -> None:
        """Re-scan /voices/pocket so operator WAV drops appear without a
        restart (documented voice-management contract). Cheap: small dir
        glob + meta reads. Keeps the virtual rafael entry. Callers that
        hold the FIFO lock (resolve) and lock-free readers (health) both
        use this; the dict rebind is atomic under the GIL.
        """
        files: dict[str, voice_storage.VoiceFileEntry] = {
            entry.name: entry for entry in voice_storage.scan_entries(self._pocket_dir)
        }
        if "rafael" not in files and self._rafael_path.is_file():
            files["rafael"] = self._files.get("rafael") or voice_storage.VoiceFileEntry(
                name="rafael",
                ref_path=self._rafael_path,
                state_path=self._rafael_path,
                meta={
                    "display_name": "Rafael",
                    "model_hash": self._model_hash,
                },
            )
        # Deleted-on-disk entries must vanish from the live map too.
        self._files = files

    def resolve(self, name: str, *, key_id: str | None = None) -> dict[str, Any]:
        """Resolve a bare voice name to a model state (LRU-cached)."""
        if key_id is not None:
            ephemeral = self._ephemeral.get(key_id, {}).get(name)
            if ephemeral is not None:
                ephemeral.last_used_at = _now_utc()
                return ephemeral.state

        entry = self._files.get(name)
        if entry is None:
            # Miss may mean an operator dropped a WAV after startup.
            self._refresh_files()
            entry = self._files.get(name)
        if entry is None:
            raise VoiceNotFoundError(
                voice=f"{_VOICE_PREFIX}{name}", available=self.available_voices()
            )
        state = self._loaded.pop(name, None)
        if state is None:
            state = self._load_state(entry)
        self._loaded[name] = state  # refresh LRU order
        while len(self._loaded) > self.LRU_MAXSIZE:
            self._loaded.popitem(last=False)
        return state

    def create_from_upload(
        self,
        path: Path,
        *,
        key_id: str,
        customer_id: str,
        display_name: str | None,
        persist: bool,
    ) -> VoiceInfo:
        """Encode a clone from an uploaded audio file.

        Runs under the API layer FIFO lock (model work). Duration was
        validated upstream by the API layer; re-checked defensively here.
        """
        settings = self._settings
        stored_count = voice_storage.count_by_customer(self._pocket_dir, customer_id)
        if persist and stored_count >= settings.voice_stored_max_per_customer:
            raise VoiceLimitError(
                f"Stored voice quota reached: {settings.voice_stored_max_per_customer}"
                " stored clones per customer",
            )
        ephemeral_count = len(self._ephemeral.get(key_id, {}))
        if not persist and ephemeral_count >= settings.voice_ephemeral_max_per_key:
            raise VoiceLimitError(
                f"Ephemeral voice quota reached: {settings.voice_ephemeral_max_per_key}"
                " ephemeral clones per API key",
            )

        try:
            duration = _audio_duration_seconds(path)
        except (OSError, ValueError, RuntimeError) as exc:
            raise VoiceUploadError("unreadable_audio") from exc
        if duration < settings.voice_ref_min_seconds:
            raise VoiceUploadError("too_short")
        if duration > settings.voice_ref_max_seconds:
            raise VoiceUploadError("too_long")

        state = self._engine.get_state_for_audio_prompt(path, truncate=True)
        now = _now_utc()
        name = f"u_{ulid.ULID()}"

        if persist:
            ref_path = self._pocket_dir / f"{name}.wav"
            self._pocket_dir.mkdir(parents=True, exist_ok=True)
            # Persist a REAL PCM WAV: pocket_tts.audio_read dispatches on the
            # .wav suffix to the stdlib wave module (RIFF only, no fallback),
            # so a raw copy of an mp3/webm upload would be unreadable on any
            # later state regeneration. Transcode also normalizes rate/channels.
            _transcode_to_wav(path, ref_path)
            state = self._engine.get_state_for_audio_prompt(ref_path, truncate=True)
            export_model_state(state, self._pocket_dir / f"{name}.safetensors")
            voice_storage.write_meta(
                self._pocket_dir,
                name,
                display_name=display_name,
                customer_id=customer_id,
                key_id=key_id,
                created_at=_iso_utc(now),
                ref_duration_s=duration,
                model_hash=self._model_hash,
            )
            self._files[name] = voice_storage.VoiceFileEntry(
                name=name,
                ref_path=ref_path,
                state_path=self._pocket_dir / f"{name}.safetensors",
                meta=voice_storage.read_meta(self._pocket_dir, name),
            )
            self._loaded[name] = state
            while len(self._loaded) > self.LRU_MAXSIZE:
                self._loaded.popitem(last=False)
            return VoiceInfo(
                voice=f"{_VOICE_PREFIX}{name}",
                display_name=display_name,
                persisted=True,
                created_at=now,
                expires_at=None,
            )

        # Ephemeral: register in memory + enforce the global LRU cap.
        expires_at = now + timedelta(
            seconds=settings.voice_ephemeral_absolute_ttl_seconds
        )
        self._enforce_ephemeral_global_cap()
        self._ephemeral.setdefault(key_id, {})[name] = EphemeralVoice(
            key_id=key_id,
            customer_id=customer_id,
            display_name=display_name,
            state=state,
            created_at=now,
            last_used_at=now,
            expires_at=expires_at,
        )
        return VoiceInfo(
            voice=f"{_VOICE_PREFIX}{name}",
            display_name=display_name,
            persisted=False,
            created_at=now,
            expires_at=expires_at,
        )

    def _enforce_ephemeral_global_cap(self) -> None:
        """Evict least-recently-used ephemeral clones beyond the global cap."""
        max_voices = self._settings.voice_ephemeral_global_max
        all_voices = [
            (voice, key_id, name)
            for key_id, voices in list(self._ephemeral.items())
            for name, voice in list(voices.items())
        ]
        if len(all_voices) < max_voices:
            return
        all_voices.sort(key=lambda item: item[0].last_used_at)
        for _voice, key_id, name in all_voices[: len(all_voices) - max_voices + 1]:
            voices = self._ephemeral.get(key_id)
            if voices is not None:
                voices.pop(name, None)
                if not voices:
                    self._ephemeral.pop(key_id, None)

    def delete(self, name: str, *, key_id: str, customer_id: str) -> None:
        """Remove a stored or ephemeral clone owned by the caller.

        Stored clones are customer-owned (any key of the customer may
        delete them); ephemeral clones are key-owned. Operator voices
        (no customer_id meta) cannot be deleted via the API.
        """
        entry = self._files.get(name)
        if entry is None:
            # Miss may mean an operator dropped a WAV after startup.
            self._refresh_files()
            entry = self._files.get(name)
        if entry is not None:
            if entry.meta.get("customer_id") != customer_id:
                raise VoiceDeleteError(f"{_VOICE_PREFIX}{name}")
            voice_storage.delete_entries(self._pocket_dir, name)
            self._files.pop(name, None)
            self._loaded.pop(name, None)
            return
        ephemeral = self._ephemeral.get(key_id, {}).pop(name, None)
        if ephemeral is None:
            raise VoiceNotFoundError(
                voice=f"{_VOICE_PREFIX}{name}", available=self.available_voices()
            )

    def list_for(self, *, key_id: str, customer_id: str) -> list[VoiceInfo]:
        """Operator voices + the callers stored and ephemeral clones.

        Other customer clones are never listed (API spec section 2.2).
        """
        self._refresh_files()
        result: list[VoiceInfo] = []
        for name, entry in sorted(self._files.items()):
            owner = entry.meta.get("customer_id")
            if owner is not None and owner != customer_id:
                continue
            result.append(
                VoiceInfo(
                    voice=f"{_VOICE_PREFIX}{name}",
                    display_name=_meta_str(entry.meta.get("display_name")),
                    persisted=True,
                    created_at=_parse_iso_utc(entry.meta.get("created_at")),
                    expires_at=None,
                )
            )
        for name, voice in sorted((self._ephemeral.get(key_id) or {}).items()):
            result.append(
                VoiceInfo(
                    voice=f"{_VOICE_PREFIX}{name}",
                    display_name=voice.display_name,
                    persisted=False,
                    created_at=voice.created_at,
                    expires_at=voice.expires_at,
                )
            )
        return result

    def available_voices(self) -> list[str]:
        """Public catalog voices (operator drops + virtual rafael).

        Persisted API clones carry a customer_id meta and are excluded:
        /health is unauthenticated, so other callers' clones must never
        surface here — own clones are listed via list_for() instead.
        """
        self._refresh_files()
        return [
            f"{_VOICE_PREFIX}{name}"
            for name, entry in sorted(self._files.items())
            if entry.meta.get("customer_id") is None
        ]

    def engine_status(self) -> dict[str, dict[str, object]]:
        """Per-engine status for the health endpoint (single engine)."""
        return {
            "pocket": {
                "loaded": self._engine.is_loaded,
                "voices": self.available_voices(),
            },
        }

    def start_sweeper(self, loop: asyncio.AbstractEventLoop) -> asyncio.Task[None]:
        """Start the periodic ephemeral-voice sweeper task."""
        if self._sweeper_task is not None and not self._sweeper_task.done():
            return self._sweeper_task
        self._sweeper_task = loop.create_task(self._sweep_loop())
        return self._sweeper_task

    async def stop_sweeper(self) -> None:
        """Cancel the sweeper task (lifespan shutdown)."""
        if self._sweeper_task is not None:
            self._sweeper_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._sweeper_task
            self._sweeper_task = None

    async def _sweep_loop(self) -> None:
        while True:
            await asyncio.sleep(self.SWEEP_INTERVAL_SECONDS)
            self._sweep_ephemerals()

    def _sweep_ephemerals(self) -> None:
        """Evict expired ephemerals (idle + absolute TTL) and enforce cap."""
        settings = self._settings
        now = _now_utc()
        for key_id, voices in list(self._ephemeral.items()):
            for name, voice in list(voices.items()):
                idle_s = (now - voice.last_used_at).total_seconds()
                absolute_s = (now - voice.created_at).total_seconds()
                if (
                    idle_s > settings.voice_ephemeral_idle_ttl_seconds
                    or absolute_s > settings.voice_ephemeral_absolute_ttl_seconds
                ):
                    voices.pop(name, None)
            if not voices:
                self._ephemeral.pop(key_id, None)
        self._enforce_ephemeral_global_cap()


def _meta_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
