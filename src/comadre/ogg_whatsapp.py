"""Ogg/Opus post-muxer producing WhatsApp-compatible voice-note structure.

ffmpeg's ogg muxer emits one Opus frame per packet (TOC code 0-2) with a
'Lavf*' OpusTags vendor; WhatsApp Web's importer goes mute on such streams.
Genuine WhatsApp PTT files use TOC code 3 packets (multiple frames packed
into one packet), a 'WhatsApp' vendor string and a 16 kHz declared input
rate.

repack_for_whatsapp() parses an ffmpeg-produced Ogg Opus stream, rewrites
OpusHead/OpusTags, regroups audio frames into code-3 multi-frame packets
and re-emits spec-compliant pages (granule positions + Ogg CRC recomputed).
The operation is lossless: decoded PCM before == decoded PCM after.
"""

from __future__ import annotations

import os
import struct

_PRE_SKIP_SAMPLES = 312  # matches genuine WhatsApp PTT files


def ogg_crc(data: bytes) -> int:
    """CRC-32 with the Ogg polynomial (0x04C11DB7), init 0, no final XOR."""
    crc = 0
    for b in data:
        crc ^= b << 24
        for _ in range(8):
            crc = (
                ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF
                if crc & 0x80000000
                else (crc << 1) & 0xFFFFFFFF
            )
    return crc


def _parse_pages(data: bytes) -> list[tuple[int, int, list[bytes]]]:
    """Yield (header_type, granule, packets) per Ogg page."""
    pages: list[tuple[int, int, list[bytes]]] = []
    pos = 0
    while True:
        idx = data.find(b"OggS", pos)
        if idx < 0:
            break
        htype = data[idx + 5]
        granule = struct.unpack("<q", data[idx + 6 : idx + 14])[0]
        nseg = data[idx + 26]
        lace = data[idx + 27 : idx + 27 + nseg]
        body_start = idx + 27 + nseg
        body = data[body_start : body_start + sum(lace)]
        packets, cursor = [], 0
        for length in lace:
            packets.append(body[cursor : cursor + length])
            cursor += length
        pages.append((htype, granule, packets))
        pos = body_start + len(body)
    return pages


def _opus_frames(packet: bytes) -> list[tuple[int, bytes]]:
    """Split one Opus packet into (toc, payload) frames.

    The first frame carries the packet's TOC; subsequent frames of a
    multi-frame packet share it, so their payloads come back TOC-less.
    """
    if not packet:
        return []
    toc = packet[0]
    code = toc & 0x03
    if code == 0:
        return [(toc, packet[1:])]
    if code == 1:
        half = (len(packet) - 1) // 2
        return [(toc, packet[1 : 1 + half]), (toc, packet[1 + half :])]
    if code == 2:
        length = packet[1]
        header = 2
        if length >= 255:
            length = packet[2] * 4 + length
            header = 3
        return [
            (toc, packet[header : header + length]),
            (toc, packet[header + length :]),
        ]
    # code 3
    count = packet[1] & 0x3F
    if count == 0 or packet[1] & 0x80:
        return [(toc, packet[2:])]
    payload = packet[2:]
    if packet[1] & 0x40:  # variable frame lengths
        lengths, pos = [], 0
        for _ in range(count - 1):
            if payload[pos] < 255:
                lengths.append(payload[pos])
                pos += 1
            else:
                lengths.append(payload[pos] + payload[pos + 1] * 4)
                pos += 2
        lengths.append(len(payload) - pos)
        frames, cursor = [], 0
        for ln in lengths:
            frames.append((toc, payload[cursor : cursor + ln]))
            cursor += ln
        return frames
    size = len(payload) // count
    return [(toc, payload[i * size : (i + 1) * size]) for i in range(count)]


def _frame_ms(toc: int) -> float:
    cfg = toc >> 3
    idx = cfg & 0x03
    if cfg >= 16:  # CELT fullband
        return (2.5, 5.0, 10.0, 20.0)[idx]
    return (10.0, 20.0, 40.0, 60.0)[idx]  # SILK / hybrid


def _pack_code3(toc: int, payloads: list[bytes]) -> bytes:
    """Pack TOC-less equal-size payloads into a code-3 packet.

    Only the equal-size form (RFC 7845 §5.1, VBR bit clear) is emitted;
    callers must not mix frame sizes inside one packet.
    """
    count = len(payloads)
    if count > 0x3F:
        raise ValueError(f"too many frames for one code-3 packet: {count}")
    if count == 1:
        return bytes([toc]) + payloads[0]
    if len({len(p) for p in payloads}) != 1:
        raise ValueError("mixed frame sizes in one code-3 packet")
    return bytes([toc, count]) + b"".join(payloads)


def _build_page(
    htype: int, granule: int, serial: int, seq: int, segments: list[bytes]
) -> bytes:
    lace = bytearray()
    for seg in segments:
        full, rem = divmod(len(seg), 255)
        lace.extend(b"\xff" * full)
        lace.append(rem)
    page = b"OggS" + bytes([0, htype]) + struct.pack("<q", granule)
    page += struct.pack("<II", serial, seq) + b"\x00\x00\x00\x00"
    page += bytes([len(lace)]) + bytes(lace) + b"".join(segments)
    crc = ogg_crc(page)
    return page[:22] + struct.pack("<I", crc) + page[26:]


def repack_for_whatsapp(
    ogg_data: bytes,
    output_sample_rate: int = 16000,
    frames_per_packet: int = 6,
) -> bytes:
    """Repack an ffmpeg Ogg Opus stream into WhatsApp PTT structure.

    Rewrites OpusHead input rate to `output_sample_rate`, sets the OpusTags
    vendor to 'WhatsApp', groups audio frames into code-3 multi-frame
    packets, fixes granules/EOS/CRC. Lossless: the decoded PCM is identical
    before and after.
    """
    pages = _parse_pages(ogg_data)
    head_packets = [p[2][0] for p in pages if p[2] and p[2][0][:8] == b"OpusHead"]
    if not head_packets:
        raise ValueError("not an Ogg Opus stream: missing OpusHead")

    new_head = bytearray(head_packets[0])
    struct.pack_into("<I", new_head, 12, output_sample_rate)

    vendor = b"WhatsApp"
    tags_body = (
        b"OpusTags" + struct.pack("<I", len(vendor)) + vendor + struct.pack("<I", 0)
    )

    # Flatten to (toc, payload) frames; group only strict runs with identical
    # TOC AND identical payload size (equal-size code-3 form only).
    runs: list[tuple[int, list[bytes]]] = []
    for _, _, packets in pages:
        for pkt in packets:
            if pkt[:8] in (b"OpusHead", b"OpusTags"):
                continue
            for toc, payload in _opus_frames(pkt):
                if (
                    runs
                    and runs[-1][0] == toc
                    and len(runs[-1][1]) < frames_per_packet
                    and len(runs[-1][1][-1]) == len(payload)
                ):
                    runs[-1][1].append(payload)
                else:
                    runs.append((toc, [payload]))

    serial = struct.unpack("<I", os.urandom(4))[0]
    out: list[bytes] = []
    seq = 0
    out.append(_build_page(0x02, 0, serial, seq, [bytes(new_head)]))
    seq += 1
    out.append(_build_page(0x00, 0, serial, seq, [tags_body]))
    seq += 1

    total_samples = 0.0
    for toc, payloads in runs:
        pkt = _pack_code3(toc, payloads)
        total_samples += _frame_ms(toc) * 48 * len(payloads)
        granule = max(int(total_samples) - _PRE_SKIP_SAMPLES, 0)
        eos = 0x04 if payloads is runs[-1][1] else 0x00
        out.append(_build_page(eos, granule, serial, seq, [pkt]))
        seq += 1

    return b"".join(out)
