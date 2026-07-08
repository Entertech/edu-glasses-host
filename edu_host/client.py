"""EduClient: high-level host-side client for the EDU-CTRL channel.

Responsibilities:

* HELLO handshake;
* request/response with sequence-number matching and timeouts
  (the device echoes the CMD's ``seq`` in its RSP);
* dispatch of asynchronous events (button / knob / audio-state / img-state)
  to registered callbacks.

Images do not travel on this channel: connect the separate air-img SPP
channel (UUID 0x2025) with :class:`edu_host.image_client.ImageClient`.

A single background thread reads from the transport and parses frames; all
callbacks run on that thread, so keep them quick.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from . import protocol
from .protocol import (CommandId, DeviceInfo, EduEvent, Frame, FrameParser,
                       FrameType, HelloAck, SensorData, Status, encode_frame,
                       parse_event)
from .transport import Transport

log = logging.getLogger("edu_host.client")

EventCallback = Callable[[EduEvent], None]


class EduClientError(Exception):
    """Generic client error."""


class EduTimeoutError(EduClientError):
    """The device did not answer within the timeout."""


class EduStatusError(EduClientError):
    """The device answered with a non-OK status."""

    def __init__(self, cmd_id: int, status: int, data: bytes = b"") -> None:
        self.cmd_id = cmd_id
        self.status = status
        self.data = data
        super().__init__("cmd 0x%02X failed: status=%s data=%s" % (
            cmd_id, protocol.enum_name(Status, status), data.hex()))


@dataclass
class Response:
    """One RSP frame, already split into fields."""

    cmd_id: int
    status: int
    data: bytes


class _Pending:
    """Bookkeeping for one in-flight request, keyed by seq."""

    def __init__(self, expected_type: int) -> None:
        self.expected_type = expected_type   # FrameType.RSP or HELLO_ACK
        self.event = threading.Event()
        self.frame: Optional[Frame] = None


class EduClient:
    """Host client for the EDU-CTRL SPP channel (UUID 0x2028)."""

    def __init__(self, transport: Transport) -> None:
        self._transport = transport
        self._parser = FrameParser()

        self._seq = 0
        self._seq_lock = threading.Lock()
        self._pending: Dict[int, _Pending] = {}
        self._pending_lock = threading.Lock()

        self._event_callbacks: List[EventCallback] = []

        self._reader: Optional[threading.Thread] = None
        self._stop = threading.Event()

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        """Open the transport and start the background reader thread."""
        self._transport.open()
        self._stop.clear()
        self._reader = threading.Thread(target=self._reader_loop,
                                        name="edu-ctrl-reader", daemon=True)
        self._reader.start()

    def close(self) -> None:
        """Stop the reader and close the transport."""
        self._stop.set()
        if self._reader is not None:
            self._reader.join(timeout=2.0)
            self._reader = None
        self._transport.close()

    # -- callbacks -----------------------------------------------------------

    def add_event_listener(self, callback: EventCallback) -> None:
        """Register a callback for asynchronous device events."""
        self._event_callbacks.append(callback)

    # -- protocol operations ---------------------------------------------------

    def hello(self, host_version: int = protocol.PROTO_VERSION,
              timeout: float = 3.0) -> HelloAck:
        """Perform the HELLO handshake, return the parsed HELLO_ACK."""
        frame = self._transact(FrameType.HELLO, bytes([host_version]),
                               FrameType.HELLO_ACK, timeout)
        return HelloAck.parse(frame.payload)

    def request(self, cmd_id: int, args: bytes = b"",
                timeout: float = 5.0) -> Response:
        """Send one CMD and wait for the matching RSP (same seq).

        Returns the response even for non-OK status; use :meth:`request_ok`
        if you want an exception on failure.
        """
        frame = self._transact(FrameType.CMD, bytes([cmd_id]) + args,
                               FrameType.RSP, timeout)
        if len(frame.payload) < 2:
            raise EduClientError("RSP payload too short: %s"
                                 % frame.payload.hex())
        rsp = Response(cmd_id=frame.payload[0], status=frame.payload[1],
                       data=bytes(frame.payload[2:]))
        if rsp.cmd_id != cmd_id:
            # seq matched but cmd echo did not: log loudly, still return it.
            log.warning("RSP cmd_id 0x%02X != sent 0x%02X", rsp.cmd_id, cmd_id)
        return rsp

    def request_ok(self, cmd_id: int, args: bytes = b"",
                   timeout: float = 5.0) -> Response:
        """Like :meth:`request` but raises :class:`EduStatusError` on non-OK."""
        rsp = self.request(cmd_id, args, timeout)
        if rsp.status != Status.OK:
            raise EduStatusError(rsp.cmd_id, rsp.status, rsp.data)
        return rsp

    # -- convenience wrappers ---------------------------------------------------

    def get_device_info(self, timeout: float = 5.0) -> DeviceInfo:
        rsp = self.request_ok(CommandId.GET_DEVICE_INFO, timeout=timeout)
        return DeviceInfo.parse(rsp.data)

    def get_sensors(self, timeout: float = 5.0) -> SensorData:
        rsp = self.request_ok(CommandId.GET_SENSORS, timeout=timeout)
        return SensorData.parse(rsp.data)

    def take_photo(self, timeout: float = 5.0) -> Response:
        """Trigger a photo. The RSP only acknowledges the request; the image
        itself arrives asynchronously on the air-img channel (see
        edu_host.image_client.ImageClient), while IMG_STATE events on this
        channel report capture progress."""
        return self.request(CommandId.TAKE_PHOTO, timeout=timeout)

    def audio_start(self, timeout: float = 5.0) -> Response:
        """Ask the device to start streaming mic audio on the EDU-AUDIO port."""
        return self.request(CommandId.AUDIO_START, timeout=timeout)

    def audio_stop(self, timeout: float = 5.0) -> Response:
        """Ask the device to stop the mic audio stream."""
        return self.request(CommandId.AUDIO_STOP, timeout=timeout)

    # -- internals -----------------------------------------------------------


    def reboot(self, timeout: float = 5.0) -> Response:
        """Ask the device to reboot (~500ms after the RSP arrives)."""
        return self.request(CommandId.REBOOT, timeout=timeout)

    def set_led(self, led: int, mode: int, color: int = 5, speed: int = 1,
                timeout: float = 5.0) -> Response:
        """Drive the inner RGB / outer indicator LED (see protocol enums).

        ``mode=LedMode.OFF`` returns the LED to the firmware's automatic
        control; business states (pairing, capture, ...) may also reclaim
        it at any time.
        """
        args = bytes([led & 0xFF, mode & 0xFF, color & 0xFF, speed & 0xFF])
        return self.request(CommandId.SET_LED, args, timeout=timeout)

    def play_tone(self, tone: int, timeout: float = 5.0) -> Response:
        """Play one of the device's built-in prompt tones (Tone enum)."""
        return self.request(CommandId.PLAY_TONE, bytes([tone & 0xFF]),
                            timeout=timeout)

    def _next_seq(self) -> int:
        with self._seq_lock:
            seq = self._seq
            self._seq = (self._seq + 1) & 0xFF
            return seq

    def _transact(self, send_type: int, payload: bytes,
                  expect_type: int, timeout: float) -> Frame:
        seq = self._next_seq()
        pending = _Pending(expected_type=expect_type)
        with self._pending_lock:
            self._pending[seq] = pending
        try:
            self._transport.write(encode_frame(send_type, seq, payload))
            if not pending.event.wait(timeout):
                raise EduTimeoutError(
                    "no answer for frame type 0x%02X seq %d within %.1fs "
                    "(is this really the EDU-CTRL port?)"
                    % (send_type, seq, timeout))
            assert pending.frame is not None
            return pending.frame
        finally:
            with self._pending_lock:
                self._pending.pop(seq, None)

    def _reader_loop(self) -> None:
        while not self._stop.is_set():
            try:
                data = self._transport.read(4096)
            except Exception as exc:  # port unplugged, BT dropped, ...
                if not self._stop.is_set():
                    log.error("transport read failed: %s", exc)
                break
            if not data:
                continue
            for frame in self._parser.feed(data):
                try:
                    self._handle_frame(frame)
                except Exception:
                    log.exception("error handling frame type 0x%02X",
                                  frame.type)

    def _handle_frame(self, frame: Frame) -> None:
        if frame.type in (FrameType.HELLO_ACK, FrameType.RSP):
            with self._pending_lock:
                pending = self._pending.get(frame.seq)
            if pending is not None and pending.expected_type == frame.type:
                pending.frame = frame
                pending.event.set()
            else:
                log.warning("unmatched %s seq %d (late answer?)",
                            protocol.enum_name(FrameType, frame.type),
                            frame.seq)
        elif frame.type == FrameType.EVT:
            event = parse_event(frame.payload)
            for cb in self._event_callbacks:
                cb(event)
        else:
            log.warning("unexpected frame type 0x%02X len %d", frame.type,
                        len(frame.payload))
