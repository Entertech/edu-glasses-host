"""EDU-CTRL wire protocol: frame codec, enums, dataclasses, image reassembly.

Everything in this module is pure Python (stdlib only) so it can be unit
tested without hardware.

Ground truth: the wire-protocol specification in ``docs/PROTOCOL.md``
(verified against the education firmware on real hardware).

Frame layout (all multi-byte fields little-endian)::

    | 0xA5 0x5A | ver(1)=1 | type(1) | seq(1) | len(2 LE) | payload(len) | crc16(2 LE) |

crc16 = CRC-16/CCITT-FALSE (see crc16.py) over ver..payload (sync bytes and
the CRC itself are excluded).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from enum import IntEnum
from typing import List, Optional, Union

from .crc16 import crc16

# ---------------------------------------------------------------------------
# Frame-layer constants (docs/PROTOCOL.md §2)
# ---------------------------------------------------------------------------

SYNC0 = 0xA5
SYNC1 = 0x5A
PROTO_VERSION = 1

HDR_LEN = 7          # sync(2) + ver(1) + type(1) + seq(1) + len(2)
CRC_LEN = 2
MAX_FRAME = 990      # max on-wire frame size
OVERHEAD = 9         # sync(2)+ver+type+seq+len(2)+crc(2)
MAX_PAYLOAD = MAX_FRAME - OVERHEAD  # 981 bytes


class FrameType(IntEnum):
    """Frame ``type`` byte (docs/PROTOCOL.md §2).

    Images do NOT travel inside EDU frames: they arrive on the separate
    air-img SPP channel (UUID 0x2025) as raw sub-frames — see
    :class:`AirImgStreamParser` below.
    """

    HELLO = 0x01       # host -> device
    HELLO_ACK = 0x02   # device -> host
    CMD = 0x10         # host -> device
    RSP = 0x11         # device -> host (echoes the CMD's seq)
    EVT = 0x20         # device -> host


class CommandId(IntEnum):
    """CMD/RSP payload byte 0 (docs/PROTOCOL.md §3)."""

    TAKE_PHOTO = 0x01
    AUDIO_START = 0x02
    AUDIO_STOP = 0x03
    GET_SENSORS = 0x04
    GET_DEVICE_INFO = 0x05
    REBOOT = 0x06
    SET_LED = 0x07
    PLAY_TONE = 0x08


class Status(IntEnum):
    """RSP payload byte 1 (docs/PROTOCOL.md §2)."""

    OK = 0x00
    BUSY = 0x01
    INVALID = 0x02
    NOT_READY = 0x03
    ERROR = 0xFF


class EventId(IntEnum):
    """EVT payload byte 0 (docs/PROTOCOL.md §4)."""

    BUTTON = 0x01
    KNOB = 0x02
    AUDIO_STATE = 0x03
    IMG_STATE = 0x04


class LedId(IntEnum):
    """SET_LED ``led_id`` byte."""

    INNER = 0   # inner RGB indicator
    OUTER = 1   # outer (capture) indicator; color is ignored


class LedMode(IntEnum):
    """SET_LED ``mode`` byte. OFF also returns the LED to automatic control."""

    OFF = 0
    ON = 1
    BLINK = 2
    BREATH = 3


class LedColor(IntEnum):
    """SET_LED ``color`` byte (inner RGB only)."""

    RED = 0
    GREEN = 1
    BLUE = 2
    ORANGE = 3
    PURPLE = 4
    WHITE = 5


class LedSpeed(IntEnum):
    """SET_LED ``speed`` byte (blink/breath only)."""

    SLOW = 0
    NORMAL = 1
    FAST = 2


class Tone(IntEnum):
    """PLAY_TONE ``tone_event`` byte — the device's built-in prompt sounds."""

    POWER_ON = 0
    POWER_OFF = 1
    ENTER_CONNECTION_MODE = 2
    BLUETOOTH_CONNECTED = 3
    BLUETOOTH_DISCONNECTED = 4
    CONNECT_TO_APP = 6
    WEAR_DETECTION = 8
    BATTERY_LOW_WARNING = 9
    BATTERY_CRITICALLY_LOW = 10
    PHOTO_CAPTURING = 11
    PHOTO_CAPTURED = 12
    VIDEO_RECORDING_STARTED = 13
    VIDEO_RECORDING_STOPPED = 14
    RECORDING_FAILED = 15
    HANG_UP_CALL = 16
    UNABLE_TO_OPERATE = 22
    STORAGE_LOW = 23
    TEMPERATURE_TOO_HIGH = 24
    CHARGE = 25
    AUDIO_RECORDING_STARTED = 27
    AUDIO_RECORDING_STOPPED = 28
    CLICK = 29


# Capability bits reported in HELLO_ACK (docs/PROTOCOL.md §2)
CAP_AUDIO_STREAM = 1 << 0
CAP_PHOTO = 1 << 1
CAP_SENSORS = 1 << 2
CAP_INPUT_EVENTS = 1 << 3
CAP_CONTROL = 1 << 4

CAP_NAMES = {
    CAP_AUDIO_STREAM: "AUDIO_STREAM",
    CAP_PHOTO: "PHOTO",
    CAP_SENSORS: "SENSORS",
    CAP_INPUT_EVENTS: "INPUT_EVENTS",
    CAP_CONTROL: "CONTROL",
}


def caps_to_names(caps: int) -> List[str]:
    """Turn the HELLO_ACK capability bitmap into readable names."""
    names = [name for bit, name in CAP_NAMES.items() if caps & bit]
    unknown = caps & ~sum(CAP_NAMES)
    if unknown:
        names.append("UNKNOWN(0x%X)" % unknown)
    return names


# ---------------------------------------------------------------------------
# Business enums forwarded in events
# ---------------------------------------------------------------------------


class ButtonId(IntEnum):
    """BUTTON event ``btn`` byte (docs/PROTOCOL.md §4)."""

    AI = 0        # AI button
    CAPTURE = 1   # photo / video button
    MEDIA = 2     # media button


class KeyAction(IntEnum):
    """BUTTON event ``action`` byte — full name table, values 0..23.

    This is the ``action`` byte of the BUTTON event.
    """

    SINGLE = 0
    DOUBLE = 1
    TRIPLE = 2
    QUADRUPLE = 3
    QUINTUPLE = 4
    SEXTUPLE = 5
    SHORT = 6
    LONG = 7
    LONG_RELEASE = 8
    VLONG = 9
    VLONG_RELEASE = 10
    VVLONG = 11
    VVLONG_RELEASE = 12
    REPEAT = 13
    PRESS = 14
    RELEASE = 15
    SINGLE_LONG = 16
    DOUBLE_LONG = 17
    TRIPLE_LONG = 18
    SINGLE_VLONG = 19
    DOUBLE_VLONG = 20
    TRIPLE_VLONG = 21
    SLIDE_UP = 22
    SLIDE_DOWN = 23


class KnobEvt(IntEnum):
    """KNOB event ``dir`` byte (docs/PROTOCOL.md §4).

    Note the numeric order: RIGHT=1 comes before LEFT=2.
    Only LEFT/RIGHT are dispatched to the host in practice.
    """

    NONE = 0
    RIGHT = 1
    LEFT = 2
    DOWN = 3
    UP = 4
    TURNING_DONE = 5


class AudioSubSource(IntEnum):
    """AUDIO_STATE event ``source`` byte (docs/PROTOCOL.md §4)."""

    MIC = 0
    CALL = 1


class CaptureEvt(IntEnum):
    """IMG_STATE event ``capture_evt`` byte (docs/PROTOCOL.md §4)."""

    START = 0
    DONE = 1
    ERROR = 2
    REMOTE_ERROR = 3
    CANCEL = 4


class CaptureErrorCode(IntEnum):
    """IMG_STATE event ``error`` byte (docs/PROTOCOL.md §4)."""

    OK = 0
    BUSY = 1
    TIMEOUT = 2
    RES_ACQUIRE_FAILED = 3
    RES_DEPRIVED = 4
    UNKNOWN = 0xFF


def enum_name(enum_cls, value: int) -> str:
    """Readable name for *value*, tolerating values outside the enum."""
    try:
        return enum_cls(value).name
    except ValueError:
        return "UNKNOWN(%d)" % value


# ---------------------------------------------------------------------------
# Frame encode / decode
# ---------------------------------------------------------------------------


@dataclass
class Frame:
    """One validated EDU-CTRL frame (sync/crc already stripped/verified)."""

    type: int
    seq: int
    payload: bytes


def encode_frame(frame_type: int, seq: int, payload: bytes = b"") -> bytes:
    """Build one on-wire frame (docs/PROTOCOL.md §2)."""
    if len(payload) > MAX_PAYLOAD:
        raise ValueError("payload too long: %d > %d" % (len(payload), MAX_PAYLOAD))
    body = struct.pack("<BBBH", PROTO_VERSION, frame_type & 0xFF, seq & 0xFF,
                       len(payload)) + payload
    crc = crc16(body)
    return bytes([SYNC0, SYNC1]) + body + struct.pack("<H", crc)


class FrameParser:
    """Incremental frame parser for the EDU-CTRL byte stream.

    Feed it raw bytes from the serial port; it returns complete, CRC-verified
    frames and silently resynchronizes on garbage — like the firmware, a bad
    length or CRC skips 2 bytes (past the false sync pair) and rescans.
    """

    # Safety cap: a valid frame is at most MAX_FRAME bytes, so an unbounded
    # buffer only happens if the peer floods garbage. Keep some slack.
    MAX_BUFFER = 8 * MAX_FRAME

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> List[Frame]:
        """Consume *data*, return every complete valid frame found so far."""
        self._buf.extend(data)
        frames: List[Frame] = []
        buf = self._buf
        pos = 0

        while len(buf) - pos >= HDR_LEN + CRC_LEN:
            if buf[pos] != SYNC0 or buf[pos + 1] != SYNC1:
                pos += 1
                continue

            payload_len = buf[pos + 5] | (buf[pos + 6] << 8)
            if payload_len > MAX_PAYLOAD:
                pos += 2  # firmware behavior: skip the false sync pair
                continue

            frame_len = HDR_LEN + payload_len + CRC_LEN
            if len(buf) - pos < frame_len:
                break  # incomplete frame, wait for more data

            body = bytes(buf[pos + 2:pos + HDR_LEN + payload_len])
            crc_actual = buf[pos + HDR_LEN + payload_len] | \
                (buf[pos + HDR_LEN + payload_len + 1] << 8)
            if crc16(body) != crc_actual:
                pos += 2
                continue

            frames.append(Frame(type=buf[pos + 3], seq=buf[pos + 4],
                                payload=body[5:]))
            pos += frame_len

        if pos > 0:
            del buf[:pos]
        if len(buf) > self.MAX_BUFFER:
            # Should never happen with a sane peer; drop old garbage.
            del buf[:len(buf) - MAX_FRAME]
        return frames


# ---------------------------------------------------------------------------
# Payload dataclasses (device -> host)
# ---------------------------------------------------------------------------


def version_to_string(packed: int) -> str:
    """Decode the 8-byte firmware version (lt_version.h).

    Layout of the u64 (from the most significant bits down):
    major u16 | minor u8 | patch u8 | preRelease u16 | build u16.
    Example: 0x0001020300040005 -> "1.2.3-4+5".
    """
    major = (packed >> 48) & 0xFFFF
    minor = (packed >> 40) & 0xFF
    patch = (packed >> 32) & 0xFF
    pre_release = (packed >> 16) & 0xFFFF
    build = packed & 0xFFFF
    s = "%d.%d.%d" % (major, minor, patch)
    if pre_release:
        s += "-%d" % pre_release
    if build:
        s += "+%d" % build
    return s


@dataclass
class HelloAck:
    """HELLO_ACK payload: proto_ver u8 | fw_version u64 LE | caps u16 LE."""

    proto_ver: int
    fw_version: int
    caps: int

    _STRUCT = struct.Struct("<BQH")

    @classmethod
    def parse(cls, payload: bytes) -> "HelloAck":
        if len(payload) < cls._STRUCT.size:
            raise ValueError("HELLO_ACK payload too short: %d" % len(payload))
        return cls(*cls._STRUCT.unpack_from(payload))

    @property
    def fw_version_str(self) -> str:
        return version_to_string(self.fw_version)

    @property
    def cap_names(self) -> List[str]:
        return caps_to_names(self.caps)


@dataclass
class DeviceInfo:
    """GET_DEVICE_INFO response data: fw u64 LE | battery u8 % | charging u8."""

    fw_version: int
    battery_level: int      # percent
    charging: bool

    _STRUCT = struct.Struct("<QBB")

    @classmethod
    def parse(cls, data: bytes) -> "DeviceInfo":
        if len(data) < cls._STRUCT.size:
            raise ValueError("DEVICE_INFO data too short: %d" % len(data))
        fw, level, charging = cls._STRUCT.unpack_from(data)
        return cls(fw_version=fw, battery_level=level, charging=bool(charging))

    @property
    def fw_version_str(self) -> str:
        return version_to_string(self.fw_version)


@dataclass
class SensorData:
    """GET_SENSORS response data.

    als_raw u16 LE (raw ALS counts, NOT lux) | battery_temp i8 (deg C) |
    btcore_temp i16 LE (deg C).
    """

    als_raw: int
    battery_temp_c: int
    btcore_temp_c: int

    _STRUCT = struct.Struct("<Hbh")

    @classmethod
    def parse(cls, data: bytes) -> "SensorData":
        if len(data) < cls._STRUCT.size:
            raise ValueError("SENSORS data too short: %d" % len(data))
        return cls(*cls._STRUCT.unpack_from(data))


# ---------------------------------------------------------------------------
# Event dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ButtonEvent:
    """EVT BUTTON: btn u8 (ButtonId) | action u8 (KeyAction)."""

    btn: int
    action: int

    @property
    def btn_name(self) -> str:
        return enum_name(ButtonId, self.btn)

    @property
    def action_name(self) -> str:
        return enum_name(KeyAction, self.action)

    def __str__(self) -> str:
        return "BUTTON %s %s" % (self.btn_name, self.action_name)


@dataclass
class KnobEvent:
    """EVT KNOB: dir u8 (KnobEvt) | delta_x i16 LE | delta_y i16 LE."""

    direction: int
    delta_x: int
    delta_y: int

    @property
    def direction_name(self) -> str:
        return enum_name(KnobEvt, self.direction)

    def __str__(self) -> str:
        return "KNOB %s dx=%d dy=%d" % (self.direction_name, self.delta_x,
                                        self.delta_y)


@dataclass
class AudioStateEvent:
    """EVT AUDIO_STATE: state u8 (0 stopped / 1 running) | source u8 | err u8."""

    state: int
    source: int
    err: int

    @property
    def running(self) -> bool:
        return self.state == 1

    @property
    def source_name(self) -> str:
        return enum_name(AudioSubSource, self.source)

    def __str__(self) -> str:
        return "AUDIO_STATE %s source=%s err=%d" % (
            "running" if self.running else "stopped", self.source_name, self.err)


@dataclass
class ImgStateEvent:
    """EVT IMG_STATE: capture_evt u8 (CaptureEvt) | error u8."""

    capture_evt: int
    error: int

    @property
    def capture_evt_name(self) -> str:
        return enum_name(CaptureEvt, self.capture_evt)

    def __str__(self) -> str:
        return "IMG_STATE %s error=%s" % (self.capture_evt_name,
                                          enum_name(CaptureErrorCode, self.error))


@dataclass
class UnknownEvent:
    """An event id we do not know — kept raw so nothing is silently lost."""

    evt_id: int
    data: bytes

    def __str__(self) -> str:
        return "UNKNOWN_EVT 0x%02X %s" % (self.evt_id, self.data.hex())


EduEvent = Union[ButtonEvent, KnobEvent, AudioStateEvent, ImgStateEvent,
                 UnknownEvent]


def parse_event(payload: bytes) -> EduEvent:
    """Parse an EVT frame payload (evt_id u8 + event data) into a dataclass."""
    if not payload:
        raise ValueError("empty EVT payload")
    evt_id, data = payload[0], payload[1:]
    if evt_id == EventId.BUTTON and len(data) >= 2:
        return ButtonEvent(btn=data[0], action=data[1])
    if evt_id == EventId.KNOB and len(data) >= 5:
        direction, dx, dy = struct.unpack_from("<Bhh", data)
        return KnobEvent(direction=direction, delta_x=dx, delta_y=dy)
    if evt_id == EventId.AUDIO_STATE and len(data) >= 3:
        return AudioStateEvent(state=data[0], source=data[1], err=data[2])
    if evt_id == EventId.IMG_STATE and len(data) >= 2:
        return ImgStateEvent(capture_evt=data[0], error=data[1])
    return UnknownEvent(evt_id=evt_id, data=bytes(data))


# ---------------------------------------------------------------------------
# Air-img sub-frames + JPEG reassembly (docs/PROTOCOL.md §5)
# ---------------------------------------------------------------------------
#
# Images arrive on their OWN SPP channel (UUID 0x2025, the firmware's native
# air-img image channel) as a raw byte stream of sub-frames with no outer
# framing and no CRC (integrity relies on RFCOMM):
#
#   HEAD (8 bytes) : 0x01 | data_type=0x01 | group u8 | seq u32 LE (=0) | format u8
#   BODY (9+N)     : 0x02 | data_type=0x01 | group u8 | seq u32 LE | data_len u16 LE | data
#   TAIL (7 bytes) : 0x03 | data_type=0x01 | group u8 | seq u32 LE
#
# NOTE: a comment in the firmware claims the tail also carries
# "2 data_length + 2 end_marker" bytes, but the code only ever builds a
# 7-byte tail — trust the code, not the comment.
#
# ``seq`` starts at 0 for the HEAD and increments by 1 for every sub-frame of
# the same image (group). ``format``: 1 = JPEG, 2 = HEIF.
#
# Because RFCOMM is a byte stream, sub-frames can be split across reads:
# use AirImgStreamParser to cut the stream back into sub-frames.

AIR_IMG_HEAD = 0x01
AIR_IMG_BODY = 0x02
AIR_IMG_TAIL = 0x03

AIR_IMG_DATA_TYPE_IMAGE = 0x01

FORMAT_JPEG = 0x01
FORMAT_HEIF = 0x02

_FORMAT_EXT = {FORMAT_JPEG: ".jpg", FORMAT_HEIF: ".heif"}


@dataclass
class AirImgSubFrame:
    """One parsed air-img sub-frame (payload of one EDU IMG frame)."""

    frame_type: int    # AIR_IMG_HEAD / AIR_IMG_BODY / AIR_IMG_TAIL
    data_type: int     # always AIR_IMG_DATA_TYPE_IMAGE today
    group_id: int
    sequence: int
    img_format: int = FORMAT_JPEG   # HEAD only
    data: bytes = b""               # BODY only


class AirImgStreamParser:
    """Cut the raw 0x2025 byte stream back into air-img sub-frames.

    RFCOMM delivers an ordered byte stream with arbitrary read boundaries, so
    a sub-frame may arrive split across several reads. Sub-frames have no
    sync word; resynchronization relies on the (frame_type, data_type) pair
    being one of the three known combinations — on garbage we drop one byte
    and rescan.
    """

    _FIXED_LEN = {AIR_IMG_HEAD: 8, AIR_IMG_TAIL: 7}

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> List["AirImgSubFrame"]:
        """Consume *data*, return every complete sub-frame found so far."""
        self._buf.extend(data)
        frames: List[AirImgSubFrame] = []
        buf = self._buf
        pos = 0

        while len(buf) - pos >= 2:
            frame_type = buf[pos]
            if frame_type not in (AIR_IMG_HEAD, AIR_IMG_BODY, AIR_IMG_TAIL) \
                    or buf[pos + 1] != AIR_IMG_DATA_TYPE_IMAGE:
                pos += 1  # not a frame start: resync byte by byte
                continue

            if frame_type == AIR_IMG_BODY:
                if len(buf) - pos < 9:
                    break  # header incomplete, wait for more bytes
                data_len = buf[pos + 7] | (buf[pos + 8] << 8)
                if data_len > 4096:
                    # far above the SPP chunk size: garbage length, resync
                    pos += 1
                    continue
                frame_len = 9 + data_len
            else:
                frame_len = self._FIXED_LEN[frame_type]

            if len(buf) - pos < frame_len:
                break  # frame incomplete, wait for more bytes

            try:
                frames.append(parse_air_img_frame(bytes(buf[pos:pos + frame_len])))
                pos += frame_len
            except ValueError:
                pos += 1  # should not happen after the length check; resync

        if pos > 0:
            del buf[:pos]
        return frames


def parse_air_img_frame(payload: bytes) -> AirImgSubFrame:
    """Parse one air-img sub-frame; raise ValueError on malformed input."""
    if len(payload) < 7:
        raise ValueError("air-img frame too short: %d" % len(payload))
    frame_type, data_type, group_id = payload[0], payload[1], payload[2]
    sequence = struct.unpack_from("<I", payload, 3)[0]

    if frame_type == AIR_IMG_HEAD:
        if len(payload) < 8:
            raise ValueError("air-img HEAD too short: %d" % len(payload))
        return AirImgSubFrame(frame_type, data_type, group_id, sequence,
                              img_format=payload[7])
    if frame_type == AIR_IMG_BODY:
        if len(payload) < 9:
            raise ValueError("air-img BODY too short: %d" % len(payload))
        data_len = struct.unpack_from("<H", payload, 7)[0]
        if len(payload) < 9 + data_len:
            raise ValueError("air-img BODY truncated: want %d have %d"
                             % (9 + data_len, len(payload)))
        return AirImgSubFrame(frame_type, data_type, group_id, sequence,
                              data=bytes(payload[9:9 + data_len]))
    if frame_type == AIR_IMG_TAIL:
        return AirImgSubFrame(frame_type, data_type, group_id, sequence)
    raise ValueError("unknown air-img frame type 0x%02X" % frame_type)


@dataclass
class CompletedImage:
    """A fully reassembled image."""

    data: bytes
    group_id: int
    img_format: int

    @property
    def suggested_extension(self) -> str:
        return _FORMAT_EXT.get(self.img_format, ".bin")


class ImageReassembler:
    """Reassemble JPEG images from a stream of air-img sub-frames.

    Rules (matching the firmware sender; see docs/PROTOCOL.md §5):

    * a HEAD always starts a new image — if one was in progress it is dropped;
    * BODY frames must belong to the current group and arrive with strictly
      consecutive ``sequence`` values (the SPP link is ordered, so a gap means
      a frame was lost and the image cannot be trusted);
    * a TAIL with the expected sequence completes the image.

    ``feed()`` returns a :class:`CompletedImage` when a TAIL closes a healthy
    image, otherwise ``None``. Problems are recorded in :attr:`last_error`.
    """

    def __init__(self) -> None:
        self._collecting = False
        self._broken = False
        self._group_id = 0
        self._expected_seq = 0
        self._img_format = FORMAT_JPEG
        self._chunks: List[bytes] = []
        self.last_error: Optional[str] = None
        self.images_completed = 0
        self.images_dropped = 0

    def reset(self) -> None:
        """Drop any partial image (e.g. on disconnect)."""
        if self._collecting and self._chunks:
            self.images_dropped += 1
        self._collecting = False
        self._broken = False
        self._chunks = []

    def feed(self, payload: bytes) -> Optional[CompletedImage]:
        """Process one raw sub-frame buffer; return an image when complete."""
        try:
            sub = parse_air_img_frame(payload)
        except ValueError as exc:
            self.last_error = str(exc)
            self._mark_broken()
            return None
        return self.feed_subframe(sub)

    def feed_subframe(self, sub: AirImgSubFrame) -> Optional[CompletedImage]:
        """Process one already-parsed sub-frame; return an image when complete."""
        if sub.frame_type == AIR_IMG_HEAD:
            return self._on_head(sub)
        if sub.frame_type == AIR_IMG_BODY:
            return self._on_body(sub)
        return self._on_tail(sub)

    # -- internal ----------------------------------------------------------

    def _on_head(self, sub: AirImgSubFrame) -> None:
        if self._collecting:
            # New image started before the previous one finished.
            self.last_error = "new HEAD (group %d) while group %d in progress" \
                % (sub.group_id, self._group_id)
            self.images_dropped += 1
        self._collecting = True
        self._broken = False
        self._group_id = sub.group_id
        self._img_format = sub.img_format
        self._chunks = []
        # HEAD itself uses sequence 0; the first BODY continues from there.
        self._expected_seq = sub.sequence + 1
        return None

    def _on_body(self, sub: AirImgSubFrame) -> None:
        if not self._collecting or self._broken:
            return None  # already dropped; wait for the next HEAD
        if sub.group_id != self._group_id:
            self.last_error = "BODY group %d != current %d" % (sub.group_id,
                                                               self._group_id)
            self._mark_broken()
            return None
        if sub.sequence != self._expected_seq:
            self.last_error = "BODY seq %d != expected %d (frame lost?)" \
                % (sub.sequence, self._expected_seq)
            self._mark_broken()
            return None
        self._chunks.append(sub.data)
        self._expected_seq += 1
        return None

    def _on_tail(self, sub: AirImgSubFrame) -> Optional[CompletedImage]:
        if not self._collecting or self._broken:
            return None
        if sub.group_id != self._group_id or sub.sequence != self._expected_seq:
            self.last_error = "TAIL group/seq mismatch (group %d seq %d, " \
                "expected group %d seq %d)" % (sub.group_id, sub.sequence,
                                               self._group_id, self._expected_seq)
            self._mark_broken()
            return None
        image = CompletedImage(data=b"".join(self._chunks),
                               group_id=self._group_id,
                               img_format=self._img_format)
        self._collecting = False
        self._chunks = []
        self.images_completed += 1
        return image

    def _mark_broken(self) -> None:
        if self._collecting and not self._broken:
            self.images_dropped += 1
        self._broken = True
        self._chunks = []
