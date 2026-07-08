"""EDU-AUDIO channel: recordsv package parser + OPUS -> WAV writer.

The audio SPP service (UUID 0x2024) continuously streams *recordsv packages*
while recording is active. Package format (ground truth:
``docs/PROTOCOL.md`` §6, verified against the firmware on real hardware)::

    8-byte header (all little-endian):
        tag       u8   = 0x52 ('R')
        cmd       u8   channel id: 2 LEFT, 3 RIGHT (8/9 = dual variants, unused here)
        len       u16  = section-area length + 4  (firmware adds 4; see below)
        sn        u16  sequence number of the LAST frame in this package
                       (it increments per FRAME, so consecutive packages
                       differ by `sections`)
        sections  u8   number of frames in the package (8 with the OPUS encoder)
        reserved  u8   sub-id bits of the recording session

    followed by `sections` x [ frame_len u8 | OPUS frame (frame_len bytes) ]

The section area is exactly ``len - 4`` bytes: the firmware sets
``pkt_hdr.len = evt.len + 4`` where ``evt.len`` is the length of the section
area (RECORDSV_EVT_PACKAGE reports the payload after the 8-byte header).

OPUS parameters (record_stream.c, 7036AX defaults): 16 kHz, mono, 16 kbps,
20 ms frames (320 samples per frame).

Decoding uses ``opuslib`` (ctypes bindings for libopus). If it is not
available we degrade gracefully and store the raw frames to a ``.opusraw``
file with layout: repeated ``[u8 frame_len][OPUS frame]``.
"""

from __future__ import annotations

import logging
import struct
import threading
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .transport import Transport

log = logging.getLogger("edu_host.audio")

# 每个流内"帧"是带 8 字节头的封装（dcore 编码器输出格式）：
#   [payload_len u32 大端][encoder final_range u32 大端][OPUS 包(payload_len 字节)]
# 直接把整个 blob 喂给解码器时，长度头首字节 0x00 会被误读成
# SILK-NB-10ms 的 TOC，"成功"解出半时长的噪声——必须先剥头。
FRAME_HEADER_LEN = 8


def extract_opus_packet(frame: bytes) -> bytes:
    """从帧 blob 中取出真正的 OPUS 包；格式不符时原样返回（向后兼容）。"""
    if len(frame) > FRAME_HEADER_LEN:
        payload_len = int.from_bytes(frame[0:4], "big")
        if payload_len + FRAME_HEADER_LEN == len(frame):
            return frame[FRAME_HEADER_LEN:]
    return frame


# -- package format constants (docs/PROTOCOL.md §6) --------------------------

PKG_TAG = 0x52
PKG_HDR = struct.Struct("<BBHHBB")   # tag, cmd, len, sn, sections, reserved
PKG_HDR_LEN = PKG_HDR.size           # 8
PKG_LEN_EXTRA = 4                    # firmware: pkt_hdr.len = section_area + 4

# cmd values (RECORDSV_PKG_CMD_*)
PKG_CMD_LEFT = 2
PKG_CMD_RIGHT = 3
PKG_CMD_R_DUAL = 8
PKG_CMD_L_DUAL = 9

# sanity bounds used during resynchronization
_MAX_SECTIONS = 16                   # firmware uses 8 (OPUS) or 3 (mSBC)
_MAX_SECTION_BYTES = 1 + 255         # frame_len u8 + up to 255 data bytes

# -- OPUS stream parameters (record_stream.c) ---------------------------------

OPUS_SAMPLE_RATE = 16000
OPUS_CHANNELS = 1
OPUS_FRAME_MS = 20
OPUS_FRAME_SAMPLES = OPUS_SAMPLE_RATE * OPUS_FRAME_MS // 1000   # 320


@dataclass
class RecordPackage:
    """One parsed recordsv package."""

    cmd: int
    sn: int
    sections: int
    reserved: int
    frames: List[bytes] = field(default_factory=list)


class RecordStreamParser:
    """Incremental parser for the recordsv package stream.

    Tolerates partial reads (keeps a rolling buffer) and resynchronizes on
    the 0x52 tag byte: a candidate header must pass sanity checks *and* its
    section walk must be self-consistent before a package is accepted;
    otherwise we advance one byte and rescan.
    """

    MAX_BUFFER = 64 * 1024

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> List[RecordPackage]:
        """Consume raw bytes, return every complete package found."""
        self._buf.extend(data)
        packages: List[RecordPackage] = []
        buf = self._buf
        pos = 0

        while len(buf) - pos >= PKG_HDR_LEN:
            if buf[pos] != PKG_TAG:
                pos += 1
                continue

            tag, cmd, length, sn, sections, reserved = \
                PKG_HDR.unpack_from(buf, pos)
            section_area = length - PKG_LEN_EXTRA
            if not self._header_plausible(sections, section_area):
                pos += 1  # false tag inside data: resync byte by byte
                continue

            total = PKG_HDR_LEN + section_area
            if len(buf) - pos < total:
                break  # incomplete package, wait for more bytes

            frames = self._walk_sections(buf, pos + PKG_HDR_LEN, section_area,
                                         sections)
            if frames is None:
                pos += 1  # inconsistent section walk: not a real header
                continue

            packages.append(RecordPackage(cmd=cmd, sn=sn, sections=sections,
                                          reserved=reserved, frames=frames))
            pos += total

        if pos > 0:
            del buf[:pos]
        if len(buf) > self.MAX_BUFFER:
            # peer flooding garbage; keep only the tail
            del buf[:len(buf) - 4096]
        return packages

    @staticmethod
    def _header_plausible(sections: int, section_area: int) -> bool:
        if not 1 <= sections <= _MAX_SECTIONS:
            return False
        # each section is at least 1 byte (its length prefix)
        return sections <= section_area <= sections * _MAX_SECTION_BYTES

    @staticmethod
    def _walk_sections(buf: bytearray, start: int, section_area: int,
                       sections: int) -> Optional[List[bytes]]:
        """Split the section area into frames; None if layout is inconsistent."""
        end = start + section_area
        frames: List[bytes] = []
        off = start
        for _ in range(sections):
            if off >= end:
                return None
            frame_len = buf[off]
            off += 1
            if off + frame_len > end:
                return None
            frames.append(bytes(buf[off:off + frame_len]))
            off += frame_len
        if off != end:
            return None  # leftover bytes: header lied
        return frames


# ---------------------------------------------------------------------------
# Audio sinks: OPUS -> WAV, or raw fallback
# ---------------------------------------------------------------------------


class WavOpusSink:
    """Decode OPUS frames with opuslib and append PCM to a WAV file."""

    def __init__(self, path: Path) -> None:
        from .opus_loader import create_decoder

        self.path = Path(path)
        # raises ImportError/OSError when opuslib/libopus is missing
        self._decoder = create_decoder(OPUS_SAMPLE_RATE, OPUS_CHANNELS)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._wav = wave.open(str(self.path), "wb")
        self._wav.setnchannels(OPUS_CHANNELS)
        self._wav.setsampwidth(2)  # 16-bit PCM
        self._wav.setframerate(OPUS_SAMPLE_RATE)
        self.frames_decoded = 0
        self.decode_errors = 0

    def handle_frame(self, frame: bytes) -> None:
        if not frame:
            return
        try:
            pcm = self._decoder.decode(extract_opus_packet(bytes(frame)),
                                       OPUS_FRAME_SAMPLES)
        except Exception as exc:
            self.decode_errors += 1
            log.warning("opus decode failed (frame %d bytes): %s",
                        len(frame), exc)
            return
        self._wav.writeframes(pcm)
        self.frames_decoded += 1

    def close(self) -> None:
        self._wav.close()


class RawOpusSink:
    """Fallback when opuslib/libopus is unavailable.

    Stores raw frames as repeated ``[u8 frame_len][OPUS frame]`` records —
    the same layout as the on-air section area, so it can be decoded later
    on any machine that has libopus.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self.path, "wb")
        self.frames_decoded = 0   # counts stored frames here
        self.decode_errors = 0

    def handle_frame(self, frame: bytes) -> None:
        if len(frame) > 255:
            log.warning("dropping oversized frame (%d bytes)", len(frame))
            return
        self._file.write(bytes([len(frame)]) + frame)
        self.frames_decoded += 1

    def close(self) -> None:
        self._file.close()


def create_sink(wav_path: Path):
    """Create the best available sink for *wav_path*.

    Returns ``(sink, decoded)`` where *decoded* says whether real WAV output
    is produced. On fallback the file gets a ``.opusraw`` suffix instead.
    """
    wav_path = Path(wav_path)
    try:
        return WavOpusSink(wav_path), True
    except Exception as exc:
        raw_path = wav_path.with_suffix(".opusraw")
        print("[audio] opuslib/libopus unavailable (%s)." % exc)
        print("[audio] Saving RAW opus frames to %s instead." % raw_path)
        print("[audio] Layout: repeated [u8 frame_len][OPUS frame]; decode "
              "later with libopus (16 kHz mono, 20 ms frames).")
        print("[audio] To get WAV output: pip install opuslib && "
              "brew install opus (macOS) / place opus.dll next to python "
              "(Windows).")
        return RawOpusSink(raw_path), False


# ---------------------------------------------------------------------------
# Audio stream client
# ---------------------------------------------------------------------------


@dataclass
class AudioStats:
    """Statistics collected while recording."""

    packages: int = 0
    frames: int = 0
    lost_packages: int = 0   # detected via sn gaps
    decode_errors: int = 0
    output_path: Optional[Path] = None
    decoded_to_wav: bool = False

    @property
    def seconds(self) -> float:
        return self.frames * OPUS_FRAME_MS / 1000.0


class AudioStreamClient:
    """Reads the EDU-AUDIO serial port and writes a growing WAV file.

    Usage::

        audio = AudioStreamClient(SerialTransport(port))
        audio.start(Path("out.wav"))   # open port + start parsing
        ...  # meanwhile send AUDIO_START on the CTRL channel
        stats = audio.stop()
    """

    def __init__(self, transport: Transport) -> None:
        self._transport = transport
        self._parser = RecordStreamParser()
        self._sink = None
        self._stats = AudioStats()
        self._last_sn: Optional[int] = None
        self._reader: Optional[threading.Thread] = None
        self._stop = threading.Event()

    @property
    def is_running(self) -> bool:
        return self._reader is not None and self._reader.is_alive()

    @property
    def stats(self) -> AudioStats:
        return self._stats

    def start(self, wav_path: Path) -> Path:
        """Open the audio port and start capturing into *wav_path*.

        Returns the actual output path (may be ``.opusraw`` on fallback).
        """
        if self.is_running:
            raise RuntimeError("audio capture already running")
        self._sink, decoded = create_sink(wav_path)
        self._stats = AudioStats(output_path=self._sink.path,
                                 decoded_to_wav=decoded)
        self._last_sn = None
        self._parser = RecordStreamParser()
        self._transport.open()
        self._stop.clear()
        self._reader = threading.Thread(target=self._reader_loop,
                                        name="edu-audio-reader", daemon=True)
        self._reader.start()
        return self._sink.path

    def stop(self) -> AudioStats:
        """Stop capturing, close the port and finalize the output file."""
        self._stop.set()
        if self._reader is not None:
            self._reader.join(timeout=2.0)
            self._reader = None
        self._transport.close()
        if self._sink is not None:
            self._stats.decode_errors = self._sink.decode_errors
            self._sink.close()
            self._sink = None
        return self._stats

    # -- internals -----------------------------------------------------------

    def _reader_loop(self) -> None:
        while not self._stop.is_set():
            try:
                data = self._transport.read(4096)
            except Exception as exc:
                if not self._stop.is_set():
                    log.error("audio transport read failed: %s", exc)
                break
            if not data:
                continue
            for package in self._parser.feed(data):
                self._handle_package(package)

    def _handle_package(self, package: RecordPackage) -> None:
        self._check_sn(package)
        self._stats.packages += 1
        for frame in package.frames:
            self._stats.frames += 1
            if self._sink is not None:
                self._sink.handle_frame(frame)

    def _check_sn(self, package: RecordPackage) -> None:
        """Detect lost packages: sn increments per *frame*, so consecutive
        packages should differ by exactly ``sections``."""
        if self._last_sn is not None and package.sections > 0:
            expected = (self._last_sn + package.sections) & 0xFFFF
            if package.sn != expected:
                gap = (package.sn - expected) & 0xFFFF
                lost = max(1, gap // package.sections)
                self._stats.lost_packages += lost
                log.warning("audio sn jump: expected %d got %d (~%d package(s)"
                            " lost)", expected, package.sn, lost)
        self._last_sn = package.sn
