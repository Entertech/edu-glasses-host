"""Stored captures wait for an operation-correlated ISP publication result."""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import IntEnum
import struct
import time
from typing import TYPE_CHECKING, Optional

from . import protocol
from .client import EduClientError, EduTimeoutError
from .media import MediaFile, _media_file

if TYPE_CHECKING:
    from .session import EduSession

CAPTURE_RESULT = 1 << 7
INDEXED_HTTP = 1 << 8


class CaptureState(IntEnum):
    STARTING = 1
    RECORDING = 2
    STOPPING = 3
    PUBLISHED = 4
    SAVED_UNPUBLISHED = 5
    FAILED = 6
    UNKNOWN = 7


@dataclass(frozen=True)
class MediaCapabilities:
    schema_version: int
    catalog_id: int
    features: int


@dataclass(frozen=True)
class CaptureResult:
    operation_id: int
    kind: int
    state: CaptureState
    error: int
    catalog_id: int
    media_id: int
    revision: int
    file: Optional[MediaFile] = None


class CaptureError(EduClientError):
    def __init__(self, result: CaptureResult) -> None:
        self.result = result
        saved = ('capture completion unknown' if result.state == CaptureState.UNKNOWN else
                 'file saved but unpublished' if result.state == CaptureState.SAVED_UNPUBLISHED else 'capture failed')
        super().__init__('%s: operation=%d error=%d; not retried' % (saved, result.operation_id, result.error))


class CaptureDescriptionError(EduClientError):
    def __init__(self, result: CaptureResult) -> None:
        self.result = result
        super().__init__('media published but descriptor unavailable: operation=%d media=%d; not retried'
                         % (result.operation_id, result.media_id))


class CaptureTimeoutError(EduTimeoutError):
    def __init__(self, operation_id: int) -> None:
        self.operation_id = operation_id
        super().__init__('capture completion unknown: operation=%d; not retried' % operation_id)


class CaptureClient:
    def __init__(self, session: EduSession) -> None:
        self.session = session

    def capabilities(self) -> MediaCapabilities:
        from .session import EduUnsupportedError
        self.session._require_connected()
        if not (self.session.supports(protocol.CAP_SAVED_PHOTO) or self.session.supports(protocol.CAP_VIDEO)):
            raise EduUnsupportedError('firmware does not support stored capture')
        data = self.session._request(protocol.CommandId.MEDIA_CAPS, timeout=20.0).data
        if len(data) != 13:
            raise EduClientError('invalid media capabilities response')
        version, catalog, features = struct.unpack('<BQI', data)
        if version != 1 or not catalog:
            raise EduUnsupportedError('ISP media catalog schema is unavailable')
        return MediaCapabilities(version, catalog, features)

    def _require_capture(self, capability: int) -> None:
        from .session import EduUnsupportedError
        self.session._require(capability)
        if not self.capabilities().features & CAPTURE_RESULT:
            raise EduUnsupportedError('ISP needs operation-correlated media publication support')

    def status(self, operation: int) -> CaptureResult:
        if type(operation) is not int or not 0 < operation <= 0xffffffff:
            raise ValueError('operation must be a nonzero uint32')
        data = self.session._request(protocol.CommandId.MEDIA_STATUS, struct.pack('<I', operation)).data
        if len(data) != 27:
            raise EduClientError('invalid capture status response')
        op, kind, state, error, catalog, media, revision = struct.unpack('<IBBBQQI', data)
        if op != operation or kind not in (1, 2):
            raise EduClientError('capture status identity does not match request')
        result = CaptureResult(op, kind, CaptureState(state), error, catalog, media, revision)
        if result.state == CaptureState.PUBLISHED and (error or not catalog or not media or not revision):
            raise EduClientError('published capture is missing its real media identity')
        return result

    def describe(self, result: CaptureResult) -> CaptureResult:
        try:
            return self._describe(result)
        except (EduClientError, ValueError) as exc:
            raise CaptureDescriptionError(result) from exc

    def _describe(self, result: CaptureResult) -> CaptureResult:
        data = self.session._request(protocol.CommandId.MEDIA_DESCRIPTOR,
            struct.pack('<I', result.operation_id), timeout=35.0).data
        if len(data) < 20:
            raise EduClientError('invalid capture descriptor response')
        operation, revision, size, name_length, path_length = struct.unpack_from('<IIQHH', data)
        if operation != result.operation_id or not revision or len(data) != 20 + name_length + path_length:
            raise EduClientError('capture descriptor identity or size is invalid')
        file = _media_file({'name': data[20:20 + name_length].decode('utf-8'),
                            'path': data[20 + name_length:].decode('utf-8'), 'size': size})
        return replace(result, revision=revision, file=file)

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
            if result.state in (CaptureState.SAVED_UNPUBLISHED, CaptureState.FAILED, CaptureState.UNKNOWN):
                raise CaptureError(result)
            if result.state == CaptureState.PUBLISHED or (started and result.state == CaptureState.RECORDING):
                return self.describe(result) if result.state == CaptureState.PUBLISHED else result
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
        self.session._require(protocol.CAP_VIDEO)
        operation = self.session._video_operation if operation is None else operation
        result = self.status(operation)
        if result.kind != 2:
            raise ValueError('operation is not a video capture')
        if result.state in (CaptureState.PUBLISHED, CaptureState.SAVED_UNPUBLISHED, CaptureState.FAILED, CaptureState.UNKNOWN):
            if result.state != CaptureState.PUBLISHED:
                raise CaptureError(result)
            return self.describe(result)
        self.session._request(protocol.CommandId.VIDEO_STOP, struct.pack('<I', operation))
        return self.wait(operation, timeout)
