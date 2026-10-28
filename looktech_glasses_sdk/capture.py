"""Public ISP capture control states; completed control does not identify a media file."""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import struct
import time
from typing import TYPE_CHECKING, Optional

from . import protocol
from .client import GlassesClientError, GlassesTimeoutError
from .catalog import MediaCapabilities
from .protocol import CaptureState, DeviceCaptureState

if TYPE_CHECKING:
    from .session import GlassesSession


class VideoResolution(IntEnum):
    RES_2K = 0
    RES_1080P = 1


class VideoOrientation(IntEnum):
    LANDSCAPE = 0
    PORTRAIT = 1


class VideoConfigState(IntEnum):
    UNCONFIRMED = 0
    PENDING = 1
    APPLIED = 2


@dataclass(frozen=True)
class VideoConfig:
    resolution: VideoResolution
    orientation: VideoOrientation
    max_duration_s: int
    requested_resolution: VideoResolution
    requested_orientation: VideoOrientation
    sync_state: VideoConfigState


@dataclass(frozen=True)
class CaptureResult:
    operation_id: int
    kind: int
    state: CaptureState
    error: int


class CaptureError(GlassesClientError):
    def __init__(self, result: CaptureResult) -> None:
        self.result = result
        text = 'capture completion unknown' if result.state == CaptureState.UNKNOWN else 'capture failed'
        super().__init__('%s: operation=%d error=%d; not retried' % (text, result.operation_id, result.error))


class CaptureTimeoutError(GlassesTimeoutError):
    def __init__(self, operation_id: int) -> None:
        self.operation_id = operation_id
        super().__init__('capture completion unknown: operation=%d; not retried' % operation_id)


class CaptureClient:
    def __init__(self, session: GlassesSession) -> None:
        self.session = session

    def capabilities(self) -> MediaCapabilities:
        from .catalog import CatalogClient
        return CatalogClient(self.session).capabilities()

    def _video_config(self, command, args=b'') -> VideoConfig:
        self.session._require(protocol.CAP_VIDEO_CONFIG)
        data = self.session._request(command, args).data
        if len(data) != 9:
            raise GlassesClientError('invalid video config response length')
        resolution, orientation, duration, wanted_res, wanted_mode, state = struct.unpack('<BBIBBB', data)
        try:
            config = VideoConfig(VideoResolution(resolution), VideoOrientation(orientation), duration,
                                 VideoResolution(wanted_res), VideoOrientation(wanted_mode), VideoConfigState(state))
        except ValueError as exc:
            raise GlassesClientError('invalid video config response value') from exc
        if config.sync_state == VideoConfigState.APPLIED and (resolution, orientation) != (wanted_res, wanted_mode):
            raise GlassesClientError('confirmed video profile does not match the requested profile')
        return config

    def get_video_config(self) -> VideoConfig:
        return self._video_config(protocol.CommandId.GET_VIDEO_CONFIG)

    def set_video_config(self, *, resolution=None, orientation=None, max_duration_s=None,
                         timeout: float = 45.0) -> VideoConfig:
        deadline = time.monotonic() + self.session._duration(timeout)
        mask, level, mode, duration = 0, 0, 0, 0
        if resolution is not None:
            if isinstance(resolution, str):
                names = {'2k': VideoResolution.RES_2K, '1080p': VideoResolution.RES_1080P}
                if resolution.lower() not in names:
                    raise ValueError('resolution must be 2k or 1080p')
                resolution = names[resolution.lower()]
            if isinstance(resolution, bool) or not isinstance(resolution, int):
                raise ValueError('resolution must be a VideoResolution or name')
            level, mask = VideoResolution(resolution), mask | 1
        if orientation is not None:
            if isinstance(orientation, str):
                names = {'landscape': VideoOrientation.LANDSCAPE, 'portrait': VideoOrientation.PORTRAIT}
                if orientation.lower() not in names:
                    raise ValueError('orientation must be landscape or portrait')
                orientation = names[orientation.lower()]
            if isinstance(orientation, bool) or not isinstance(orientation, int):
                raise ValueError('orientation must be a VideoOrientation or name')
            mode, mask = VideoOrientation(orientation), mask | 2
        if max_duration_s is not None:
            if type(max_duration_s) is not int or max_duration_s not in (30, 60, 180):
                raise ValueError('max_duration_s must be 30, 60 or 180')
            duration, mask = max_duration_s, mask | 4
        if not mask:
            raise ValueError('provide at least one video config field')
        owner = self.session._client
        config = self._video_config(protocol.CommandId.SET_VIDEO_CONFIG, struct.pack('<BBBI', mask, level, mode, duration))
        if not mask & 3:
            return config
        expected = config.requested_resolution, config.requested_orientation
        while True:
            if not self.session.is_connected or self.session._client is not owner:
                raise GlassesClientError('video config CTRL owner disconnected or changed')
            if (config.requested_resolution, config.requested_orientation) != expected:
                raise GlassesClientError('video config request failed or was superseded; query current config')
            if config.sync_state == VideoConfigState.APPLIED:
                return config
            if time.monotonic() >= deadline:
                raise GlassesTimeoutError('video config application unconfirmed; query get_video_config(); not retried')
            self.session.wait(0.1)
            config = self.get_video_config()

    def _require_capture(self, capability: int) -> None:
        self.session._require(capability | protocol.CAP_MEDIA_CATALOG)

    def device_state(self) -> DeviceCaptureState:
        self.session._require(protocol.CAP_DEVICE_CAPTURE_STATE)
        data = self.session._request(protocol.CommandId.GET_CAPTURE_STATE).data
        try:
            return DeviceCaptureState.parse(data)
        except ValueError as exc:
            raise GlassesClientError('invalid device capture state') from exc

    def status(self, operation: int) -> CaptureResult:
        self.session._require(protocol.CAP_MEDIA_CATALOG)
        if type(operation) is not int or not 0 < operation <= 0xffffffff:
            raise ValueError('operation must be a nonzero uint32')
        data = self.session._request(protocol.CommandId.MEDIA_STATUS, struct.pack('<I', operation)).data
        if len(data) != 7:
            raise GlassesClientError('invalid capture status response')
        op, kind, state, error = struct.unpack('<IBBB', data)
        if op != operation or kind not in (1, 2) or state == CaptureState.IDLE:
            raise GlassesClientError('capture status identity does not match request')
        try:
            return CaptureResult(op, kind, CaptureState(state), error)
        except ValueError as exc:
            raise GlassesClientError('invalid capture state') from exc

    def _begin(self, command: int) -> int:
        data = self.session._request(command).data
        if len(data) != 4:
            raise GlassesClientError('invalid capture acceptance response')
        operation, = struct.unpack('<I', data)
        if not operation:
            raise GlassesClientError('capture accepted without an operation identity')
        return operation

    def wait(self, operation: int, timeout: float, started: bool = False) -> CaptureResult:
        owner = self.session._client
        deadline = time.monotonic() + self.session._duration(timeout)
        while True:
            if not self.session.is_connected or self.session._client is not owner:
                raise GlassesClientError('capture CTRL owner disconnected or changed')
            result = self.status(operation)
            if result.state in (CaptureState.FAILED, CaptureState.UNKNOWN):
                raise CaptureError(result)
            if result.state == CaptureState.DONE or (started and result.state == CaptureState.RECORDING):
                return result
            if time.monotonic() >= deadline:
                raise CaptureTimeoutError(operation)
            self.session.wait(0.1)

    def photo(self, timeout: float = 45.0) -> CaptureResult:
        self._require_capture(protocol.CAP_SAVED_PHOTO)
        return self.wait(self._begin(protocol.CommandId.SAVED_PHOTO), timeout)

    def video_start(self, timeout: float = 20.0) -> CaptureResult:
        self._require_capture(protocol.CAP_VIDEO)
        operation = self._begin(protocol.CommandId.VIDEO_START)
        self.session._video_operation = operation
        return self.wait(operation, timeout, started=True)

    def video_stop(self, operation: Optional[int] = None, timeout: float = 45.0) -> CaptureResult:
        self._require_capture(protocol.CAP_VIDEO)
        operation = self.session._video_operation if operation is None else operation
        result = self.status(operation)
        if result.kind != 2:
            raise ValueError('operation is not a video capture')
        if result.state in (CaptureState.DONE, CaptureState.FAILED, CaptureState.UNKNOWN):
            if result.state != CaptureState.DONE:
                raise CaptureError(result)
            return result
        self.session._request(protocol.CommandId.VIDEO_STOP, struct.pack('<I', operation))
        return self.wait(operation, timeout)
