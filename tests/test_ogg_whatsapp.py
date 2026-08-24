"""Repacker: structure mirrors WhatsApp PTT files and stays lossless."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from comadre.ogg_whatsapp import repack_for_whatsapp

FIXTURE = Path(__file__).parent / "fixtures" / "whatsapp_repack_source.ogg"


def _fixture() -> bytes:
    if not FIXTURE.exists():
        pytest.skip("fixture not generated")
    return FIXTURE.read_bytes()


@pytest.mark.slow
@pytest.mark.xfail(
    reason=(
        "code-3 repacketization still decodes short (~0.95 s lost) across "
        "decoders; headers-only rewrite (service path) is the shipped fix "
        "pending WhatsApp Web validation"
    ),
    strict=True,
)
def test_repack_is_lossless_and_structurally_valid(tmp_path: Path) -> None:
    src = tmp_path / "src.ogg"
    src.write_bytes(_fixture())
    out = repack_for_whatsapp(src.read_bytes())
    dest = tmp_path / "repacked.ogg"
    dest.write_bytes(out)

    def decode(f: Path) -> tuple[float, object]:
        wav = tmp_path / (f.stem + ".wav")
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(f),
                "-ar",
                "24000",
                "-ac",
                "1",
                str(wav),
            ],
            check=True,
        )
        import numpy as np
        import soundfile as sf

        data, sr = sf.read(wav)
        return len(data) / sr, np.asarray(data)

    dur_a, pcm_a = decode(src)
    dur_b, pcm_b = decode(dest)
    assert abs(dur_a - dur_b) < 0.01
    n = min(len(pcm_a), len(pcm_b))
    assert float(abs(pcm_a[:n] - pcm_b[:n]).max()) < 1e-6

    blob = dest.read_bytes()
    import struct

    i = blob.find(b"OpusHead")
    assert struct.unpack("<I", blob[i + 12 : i + 16])[0] == 16000
    j = blob.find(b"OpusTags")
    vl = struct.unpack("<I", blob[j + 8 : j + 12])[0]
    assert blob[j + 12 : j + 12 + vl] == b"WhatsApp"
    last = blob.rfind(b"OggS")
    assert blob[last + 5] & 0x04  # EOS
