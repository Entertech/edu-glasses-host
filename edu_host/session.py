"""Synchronous, platform-aware SDK session for the frozen EDU v1 protocol.

macOS Bluetooth sessions must be used on the process main thread. Call
``wait``/``poll`` while idle so IOBluetooth can deliver asynchronous callbacks.
"""
from __future__ import annotations

import logging
import math
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Callable, List, Optional, Tuple, Union

from . import protocol
from .audio_client import AudioStats, AudioStreamClient
from .client import EduClient, EduClientError, EduStatusError, EduTimeoutError, Response
from .image_client import ImageClient
from .ota_client import OTAClient, OTAFirmwareImage, ProgressCallback, UpdateResultResponse
from .protocol import (CommandId, CompletedImage, DeviceInfo, EduEvent, HelloAck,
                       ImgStateEvent, CaptureEvt, SensorData, Status, Tone)
from .transport import SerialTransport

log = logging.getLogger(__name__)
PathLike = Union[str, Path]


class EduUnsupportedError(EduClientError):
    """The firmware capability or required channel is unavailable."""


class EduSession:
    """One sequential SDK session; construction does not connect.

    Use ``with EduSession(bt="auto") as glasses`` or call ``connect()``.
    Existing EduClient/transport APIs remain usable independently.
    """

    def __init__(self, bt: Optional[str] = "auto", *,
                 ctrl_port: Optional[str] = None, audio_port: Optional[str] = None,
                 img_port: Optional[str] = None, ota_port: Optional[str] = None,
                 ctrl_channel: int = 6, audio_channel: int = 5,
                 img_channel: int = 4, ota_channel: int = 7,
                 out_dir: PathLike = "captures") -> None:
        self.bt = None if ctrl_port else bt
        self.out_dir = Path(out_dir).resolve()
        self._ports = (ctrl_port, audio_port, img_port, ota_port)
        self._channels = (ctrl_channel, audio_channel, img_channel, ota_channel)
        self._transports = None
        self._pump = None
        self._client: Optional[EduClient] = None
        self._audio: Optional[AudioStreamClient] = None
        self._audio_transport = None
        self._recording = False
        self._image: Optional[ImageClient] = None
        self._ota_transport = None
        self._ota_running = False
        self._media_import = None
        self._video_operation = None
        self.hello_ack: Optional[HelloAck] = None
        self._incoming: queue.Queue = queue.Queue()
        self._images: queue.Queue = queue.Queue()
        self._event_listeners: List[Callable[[EduEvent], None]] = []
        self._image_listeners: List[Callable[[Path, CompletedImage], None]] = []
        self._photo_pending = False
        self._completed_photo: Optional[Path] = None
        self._photo_error: Optional[EduClientError] = None

    @classmethod
    def from_transports(cls, ctrl, audio=None, image=None, ota=None,
                        out_dir: PathLike = "captures") -> "EduSession":
        """Use existing serial/socket Transport instances (background readers)."""
        session = cls(bt=None, out_dir=out_dir)
        session._transports = (ctrl, audio, image, ota)
        return session

    def _check_thread(self) -> None:
        if self._pump is not None and threading.current_thread() is not threading.main_thread():
            raise EduClientError("macOS Bluetooth requires the process main thread")

    def _make_transports(self):
        if self._ports[0]:
            return tuple(SerialTransport(p) if p else None for p in self._ports)
        if not self.bt:
            raise ValueError("provide bt or ctrl_port")
        if sys.platform == "darwin":
            if threading.current_thread() is not threading.main_thread():
                raise EduClientError("macOS Bluetooth requires the process main thread")
            try:
                from . import mac_bt
            except ImportError as exc:
                raise EduClientError("macOS Bluetooth needs pyobjc-core and "
                                     "pyobjc-framework-IOBluetooth") from exc
            self._pump = mac_bt.pump
            dev = mac_bt.find_device(self.bt)
            if dev is None:
                raise EduClientError("device not found; pair EDU-* glasses in system Bluetooth settings")
            if not dev.isConnected():
                dev.openConnection()
                self._pump(2.0)
            uuids = [mac_bt.UUID_CTRL, mac_bt.UUID_AUDIO, mac_bt.UUID_IMG, mac_bt.UUID_OTA]
            channels = mac_bt.sdp_channels(dev, uuids)
            if mac_bt.UUID_CTRL not in channels:
                raise EduUnsupportedError("EDU-CTRL service (0x2028) not found")
            return tuple(mac_bt.MacRFCOMMChannel(dev, channels[u], name)
                         if u in channels else None
                         for u, name in zip(uuids, ("ctrl", "audio", "img", "ota")))
        from .bt_socket import SocketRFCOMMTransport, bt_socket_supported
        if not bt_socket_supported():
            raise EduUnsupportedError("this Python has no Bluetooth socket support; use serial ports")
        address = self.bt
        if address == "auto":
            from .bt_discovery import find_paired_device
            found = find_paired_device()
            if found is None:
                raise EduClientError("no paired EDU-* glasses found; pair first or provide bt=<address>")
            address, name = found
            log.info("auto-selected %s (%s)", name, address)
        return tuple(SocketRFCOMMTransport(address, ch, name=name)
                     for ch, name in zip(self._channels, ("ctrl", "audio", "img", "ota")))

    def connect(self, timeout: float = 6.0) -> "EduSession":
        self._check_thread()
        if self.is_connected:
            return self
        self._incoming = queue.Queue()
        self._images = queue.Queue()
        self._photo_pending = False
        self._completed_photo = self._photo_error = None
        self._video_operation = None
        try:
            ctrl, audio, image, self._ota_transport = self._transports or self._make_transports()
            self._client = EduClient(ctrl, pump=self.poll if self._pump else None)
            self._client.add_event_listener(self._incoming.put)
            if self._pump:
                self._client.start()
            if self._pump and audio:
                try:
                    audio.open()
                except OSError as exc:
                    audio.close()
                    audio = None
                    log.warning("audio channel unavailable: %s", exc)
            self._audio_transport = audio
            self._audio = AudioStreamClient(audio) if audio else None
            if image:
                self._image = ImageClient(image, output_dir=str(self.out_dir))
                self._image.add_image_listener(lambda path, got: self._images.put((path, got)))
                try:
                    self._image.start(threaded=self._pump is None)
                except OSError as exc:
                    self._image.close()
                    self._image = None
                    log.warning("image channel unavailable: %s", exc)
            if self._pump is None:
                self._client.start()
            self.hello_ack = self._client.hello(timeout=timeout)
            if self.hello_ack.proto_ver != protocol.PROTO_VERSION:
                raise EduUnsupportedError("unsupported EDU protocol version %d" % self.hello_ack.proto_ver)
            return self
        except BaseException:
            self.close()
            raise

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self.hello_ack is not None and self._client.is_open

    @property
    def capabilities(self) -> Tuple[str, ...]:
        self._require_connected()
        return tuple(self.hello_ack.cap_names)

    def supports(self, capability: Union[int, str]) -> bool:
        self._require_connected()
        if isinstance(capability, str):
            bits = {name: bit for bit, name in protocol.CAP_NAMES.items()}
            try:
                capability = bits[capability.upper()]
            except KeyError:
                raise ValueError("unknown capability %r" % capability) from None
        return (self.hello_ack.caps & capability) == capability

    def _require_connected(self) -> None:
        self._check_thread()
        if not self.is_connected:
            raise EduClientError("session is not connected; call connect() first")
        if self._ota_running:
            raise EduClientError("OTA upgrade is in progress")

    def _require(self, capability: int, channel=True) -> None:
        self._require_connected()
        if not self.supports(capability):
            raise EduUnsupportedError("firmware does not advertise %s" %
                                      ", ".join(protocol.caps_to_names(capability)))
        if not channel:
            raise EduUnsupportedError("required channel is unavailable; reconnect with that channel configured")

    def _request(self, command: int, args: bytes = b"", timeout: float = 5.0) -> Response:
        self._require_connected()
        response = self._client.request(command, args, timeout)
        if response.cmd_id != command:
            raise EduClientError("response command does not match request")
        if response.status != Status.OK:
            raise EduStatusError(command, response.status, response.data)
        self.poll(0)
        return response

    def info(self, timeout: float = 5.0) -> DeviceInfo:
        return DeviceInfo.parse(self._request(CommandId.GET_DEVICE_INFO, timeout=timeout).data)

    def wifi_capabilities(self):
        from .wifi import WifiClient
        return WifiClient(self).capabilities()

    def wifi_scan(self, timeout: float = 30.0):
        from .wifi import WifiClient
        return WifiClient(self).scan(timeout)

    def wifi_connect(self, ssid: str, password: str = '', security=5, timeout: float = 70.0):
        from .wifi import WifiClient
        return WifiClient(self).connect(ssid, password, security, timeout)

    def wifi_status(self):
        from .wifi import WifiClient
        return WifiClient(self).status()

    def wifi_disconnect(self) -> None:
        from .wifi import WifiClient
        WifiClient(self).disconnect()

    def media_import(self, ssid: str, password: str = '', security=5):
        from .media import MediaImport
        return MediaImport(self, ssid, password, security)

    def media_capabilities(self):
        from .capture import CaptureClient
        return CaptureClient(self).capabilities()

    def capture_saved_photo(self, timeout: float = 45.0):
        from .capture import CaptureClient
        return CaptureClient(self).photo(timeout)

    def media_status(self, operation: int):
        from .capture import CaptureClient
        return CaptureClient(self).status(operation)

    def video_start(self, timeout: float = 20.0):
        from .capture import CaptureClient
        return CaptureClient(self).video_start(timeout)

    def video_stop(self, operation: Optional[int] = None, timeout: float = 45.0):
        from .capture import CaptureClient
        return CaptureClient(self).video_stop(operation, timeout)

    def video_status(self, operation: Optional[int] = None):
        return self.media_status(self._video_operation if operation is None else operation)

    def sensors(self, timeout: float = 5.0) -> SensorData:
        self._require(protocol.CAP_SENSORS)
        return SensorData.parse(self._request(CommandId.GET_SENSORS, timeout=timeout).data)

    def add_event_listener(self, callback: Callable[[EduEvent], None]) -> None:
        """Callbacks run on the caller's thread during poll/wait (keep them short)."""
        self._event_listeners.append(callback)

    def add_image_listener(self, callback: Callable[[Path, CompletedImage], None]) -> None:
        """Called after a complete image has been written to disk."""
        self._image_listeners.append(callback)

    def poll(self, seconds: float = 0.05) -> List[EduEvent]:
        self._check_thread()
        seconds = self._duration(seconds)
        if self._pump:
            self._pump(seconds)
            if self._client:
                self._client.poll()
            if self._image:
                self._image.poll()
            if self._audio:
                self._audio.poll()
        elif seconds:
            time.sleep(seconds)
        events = []
        while True:
            try:
                event = self._incoming.get_nowait()
            except queue.Empty:
                break
            events.append(event)
            if self._photo_pending and isinstance(event, ImgStateEvent) and event.capture_evt in (
                    CaptureEvt.ERROR, CaptureEvt.REMOTE_ERROR, CaptureEvt.CANCEL):
                self._photo_error = EduClientError("photo failed: %s" % event)
                self._photo_pending = False
            for callback in self._event_listeners:
                self._notify(callback, event)
        while True:
            try:
                path, image = self._images.get_nowait()
            except queue.Empty:
                break
            self._completed_photo = path
            self._photo_pending = False
            for callback in self._image_listeners:
                self._notify(callback, path, image)
        return events

    @staticmethod
    def _notify(callback, *args) -> None:
        try:
            callback(*args)
        except Exception:
            log.exception("session listener failed")

    @staticmethod
    def _duration(seconds: float) -> float:
        value = float(seconds)
        if not math.isfinite(value) or value < 0:
            raise ValueError("seconds must be finite and non-negative")
        return value

    def wait(self, seconds: float) -> None:
        """Keep channels and callbacks alive; use instead of sleep on macOS."""
        self._require_connected()
        deadline = time.monotonic() + self._duration(seconds)
        self.poll(0)
        while time.monotonic() < deadline:
            self.poll(min(0.05, max(0.0, deadline - time.monotonic())))

    def events(self, seconds: float) -> List[EduEvent]:
        """Collect new typed events during this interval."""
        self._require_connected()
        self.poll(0)
        found: List[EduEvent] = []
        self._event_listeners.append(found.append)
        try:
            self.wait(seconds)
        finally:
            self._event_listeners.remove(found.append)
        return found

    def _output_path(self, filename: PathLike) -> Path:
        return (self.out_dir / filename).resolve()

    def trigger_photo(self, filename: Optional[PathLike] = None,
                      timeout: float = 5.0) -> Response:
        """Acknowledge capture only; call wait_photo for a saved JPEG."""
        self._require(protocol.CAP_PHOTO, self._image is not None)
        self.poll(0)
        if self._photo_pending:
            raise EduClientError("a photo is already pending")
        self._completed_photo = None
        self._photo_error = None
        self._photo_pending = True
        self._image.set_next_photo_path(self._output_path(filename) if filename else None)
        try:
            return self._request(CommandId.TAKE_PHOTO, timeout=timeout)
        except EduTimeoutError:
            # The capture may have started; keep its filename and pending state.
            raise
        except BaseException:
            self._photo_pending = False
            self._image.set_next_photo_path(None)
            raise

    def wait_photo(self, timeout: float = 30.0) -> Path:
        self._require_connected()
        deadline = time.monotonic() + self._duration(timeout)
        while True:
            self.poll(0)
            if self._completed_photo is not None:
                return self._completed_photo
            if self._photo_error is not None:
                raise self._photo_error
            if time.monotonic() >= deadline:
                raise EduTimeoutError("photo was not saved within %.1fs" % timeout)
            self.poll(min(0.05, max(0.0, deadline - time.monotonic())))

    def photo(self, filename: Optional[PathLike] = None, timeout: float = 30.0) -> Path:
        self.trigger_photo(filename)
        return self.wait_photo(timeout)

    @property
    def is_recording(self) -> bool:
        return self._recording

    def record_start(self, filename: PathLike = "record.wav", timeout: float = 5.0) -> Path:
        self._require(protocol.CAP_AUDIO_STREAM, self._audio is not None)
        if self.is_recording:
            raise EduClientError("recording already running")
        actual = self._audio.start(self._output_path(filename), threaded=self._pump is None)
        self._recording = True
        try:
            self._request(CommandId.AUDIO_START, timeout=timeout)
        except BaseException as exc:
            try:
                if isinstance(exc, EduTimeoutError):
                    try:
                        self._request(CommandId.AUDIO_STOP, timeout=2.0)
                    except Exception:
                        log.debug("audio cleanup after start timeout failed", exc_info=True)
            finally:
                self._recording = False
                self._audio.stop(close_transport=self._pump is None)
            raise
        return actual

    def record_stop(self, timeout: float = 5.0) -> AudioStats:
        self._require_connected()
        if not self.is_recording:
            raise EduClientError("no recording in progress")
        try:
            self._request(CommandId.AUDIO_STOP, timeout=timeout)
            self.wait(0.1)
        finally:
            self._recording = False
            stats = self._audio.stop(close_transport=self._pump is None)
        if stats.frames_written == 0:
            raise EduClientError("recording produced no usable audio: %s" % stats.output_path)
        return stats

    def record(self, filename: PathLike, seconds: float, timeout: float = 5.0) -> Path:
        seconds = self._duration(seconds)
        self.record_start(filename, timeout)
        try:
            self.wait(seconds)
        finally:
            stats = self.record_stop(timeout)
        return stats.output_path

    def reboot(self, timeout: float = 5.0) -> Response:
        self._require(protocol.CAP_CONTROL)
        return self._request(CommandId.REBOOT, timeout=timeout)

    def set_led(self, led: int, mode: int, color: int = protocol.LedColor.WHITE,
                speed: int = protocol.LedSpeed.NORMAL, timeout: float = 5.0) -> Response:
        self._require(protocol.CAP_CONTROL)
        values = (protocol.LedId(led), protocol.LedMode(mode),
                  protocol.LedColor(color), protocol.LedSpeed(speed))
        return self._request(CommandId.SET_LED, bytes(values), timeout)

    def play_tone(self, tone: Union[int, str] = Tone.CLICK, timeout: float = 5.0) -> Response:
        self._require(protocol.CAP_CONTROL)
        if isinstance(tone, str):
            try:
                tone = int(tone) if tone.isdigit() else Tone[tone.upper()]
            except KeyError:
                raise ValueError("unknown tone %r" % tone) from None
        if not 0 <= tone <= 255:
            raise ValueError("tone id must fit in one byte")
        return self._request(CommandId.PLAY_TONE, bytes([tone]), timeout)

    def ota(self, filename: PathLike, progress: Optional[ProgressCallback] = None,
            chunk_size: int = 512, packet_interval_ms: float = 10.0) -> UpdateResultResponse:
        self._require_connected()
        self.poll(0)
        if self.is_recording or self._photo_pending:
            raise EduClientError("stop recording or finish the pending photo before OTA")
        if self._ota_transport is None:
            raise EduUnsupportedError("OTA service (0x2026) unavailable")
        # Reject invalid files before touching any live Bluetooth channel.
        OTAFirmwareImage.parse(Path(filename).read_bytes())
        client = OTAClient(self._ota_transport, pump=self.poll if self._pump else None,
                           max_send_data_payload=chunk_size,
                           packet_interval_s=packet_interval_ms / 1000.0)
        try:
            self._ota_running = True
            client.open()
            return client.upgrade(Path(filename), progress=progress)
        finally:
            try:
                client.close()
            finally:
                self._ota_running = False

    def close(self) -> None:
        self._check_thread()
        try:
            if self._media_import is not None:
                try:
                    self._media_import.close()
                except Exception:
                    log.exception("media import cleanup on close failed")
            if self._video_operation is not None and self.is_connected:
                try:
                    import struct
                    self._request(CommandId.VIDEO_STOP, struct.pack('<I', self._video_operation), timeout=2.0)
                except Exception:
                    log.warning("video stop on close unconfirmed; device continues owner cleanup", exc_info=True)
            if self.is_recording:
                try:
                    if self.is_connected:
                        self._request(CommandId.AUDIO_STOP, timeout=2.0)
                except Exception:
                    log.debug("audio stop on close failed", exc_info=True)
                finally:
                    self._recording = False
                    self._audio.stop(close_transport=self._pump is None)
        finally:
            # Mac closes must follow open order; reverse order can leave an RFCOMM channel alive.
            first = self._client if self._pump else self._image
            last = self._image if self._pump else self._client
            try:
                if first:
                    first.close()
            finally:
                try:
                    if self._audio_transport:
                        self._audio_transport.close()
                finally:
                    try:
                        if last:
                            last.close()
                    finally:
                        self._client = self._image = self._audio = None
                        self._audio_transport = self._ota_transport = None
                        self.hello_ack = None

    def __enter__(self) -> "EduSession":
        return self.connect()

    def __exit__(self, *exc) -> None:
        self.close()
