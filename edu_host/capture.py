"""Public ISP capture control states; completed control does not identify a media file."""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import struct
import time
from typing import TYPE_CHECKING, Optional

from . import protocol
from .client import EduClientError, EduTimeoutError
from .catalog import MediaCapabilities

if TYPE_CHECKING:
    from .session import EduSession


class CaptureState(IntEnum):
    STARTING = 1
    RECORDING = 2
    STOPPING = 3
    DONE = 4
    FAILED = 6
    UNKNOWN = 7


@dataclass(frozen=True)
class CaptureResult:
    operation_id: int
    kind: int
    state: CaptureState
    error: int


class CaptureError(EduClientError):
    def __init__(self, result: CaptureResult) -> None:
        self.result = result
        text = 'capture completion unknown' if result.state == CaptureState.UNKNOWN else 'capture failed'
        super().__init__('%s: operation=%d error=%d; not retried' % (text, result.operation_id, result.error))


class CaptureTimeoutError(EduTimeoutError):
    def __init__(self, operation_id: int) -> None:
        self.operation_id = operation_id
        super().__init__('capture completion unknown: operation=%d; not retried' % operation_id)


class CaptureClient:
    def __init__(self, session: EduSession) -> None:
        self.session = session

    def capabilities(self) -> MediaCapabilities:
        from .catalog import CatalogClient
        return CatalogClient(self.session).capabilities()

    def _require_capture(self, capability: int) -> None:
        self.session._require(capability | protocol.CAP_MEDIA_CATALOG)

    def status(self, operation: int) -> CaptureResult:
        self.session._require(protocol.CAP_MEDIA_CATALOG)
        if type(operation) is not int or not 0 < operation <= 0xffffffff:
            raise ValueError('operation must be a nonzero uint32')
        data = self.session._request(protocol.CommandId.MEDIA_STATUS, struct.pack('<I', operation)).data
        if len(data) != 7:
            raise EduClientError('invalid capture status response')
        op, kind, state, error = struct.unpack('<IBBB', data)
        if op != operation or kind not in (1, 2):
            raise EduClientError('capture status identity does not match request')
        try:
            return CaptureResult(op, kind, CaptureState(state), error)
        except ValueError as exc:
            raise EduClientError('invalid capture state') from exc

    def _begin(self, command: int) -> int:
        data = self.session._request(command).data
        if len(data) != 4:
            raise EduClientError('invalid capture acceptance response')
        operation, = struct.unpack('<I', data)
        if not operation:
            raise EduClientError('capture accepted without an operation identity')
        return operation

    def wait(self, operation: int, timeout: float, started: bool = False) -> CaptureResult:
        owner = self.session._client
        deadline = time.monotonic() + self.session._duration(timeout)
        while True:
            if not self.session.is_connected or self.session._client is not owner:
                raise EduClientError('capture CTRL owner disconnected or changed')
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
