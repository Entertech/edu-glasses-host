"""Host-side Python library for Looktech Glasses developer firmware.

Modules:

* :mod:`looktech_glasses_sdk.crc16` — firmware CRC-16 port;
* :mod:`looktech_glasses_sdk.protocol` — EDU-CTRL frame codec, enums, image reassembly;
* :mod:`looktech_glasses_sdk.transport` — serial transport abstraction;
* :mod:`looktech_glasses_sdk.client` — GlassesClient (handshake, request/response, events);
* :mod:`looktech_glasses_sdk.image_client` — air-img image channel receiver (photos);
* :mod:`looktech_glasses_sdk.audio_client` — EDU-AUDIO stream parser and OPUS->WAV writer;
* :mod:`looktech_glasses_sdk.session` — platform-aware GlassesSession SDK.
"""

from .client import (GlassesClient, GlassesClientError, GlassesStatusError,
                     GlassesTimeoutError, Response)
from .audio_client import AudioStats, AudioStreamClient
from .image_client import ImageClient
from .transport import SerialTransport, Transport, list_serial_ports
from .session import GlassesSession, GlassesUnsupportedError
from .wifi import (WifiCapabilities, WifiError, WifiNetwork, WifiSecurity,
                   WifiStage, WifiStatus)
from .media import (DeleteResult, DownloadResult, MediaCancelled, MediaError,
                    MediaFile, MediaImport, MediaItem, MediaSessionError)
from .capture import (CaptureError, CaptureResult, CaptureState,
                      CaptureTimeoutError, MediaCapabilities, VideoConfig, VideoConfigState,
                      VideoOrientation, VideoResolution)
from .bt_discovery import AmbiguousGlassesError
from .ota_client import OTAError, OTAStatusError, OTATimeoutError, UpdateResultResponse
from .protocol import (AudioRecordRequestEvent, CaptureKind, CaptureSource,
                       DeviceCaptureEntry, DeviceCaptureState, AudioStateEvent, ButtonEvent, CaptureEvt, CompletedImage,
                       DeviceInfo, GlassesEvent,
                       HelloAck, ImgStateEvent, KnobEvent, LedColor, LedId,
                       LedMode, LedSpeed, SensorData, Tone, UnknownEvent)

__all__ = [
    "GlassesClient",
    "GlassesClientError",
    "GlassesStatusError",
    "GlassesTimeoutError",
    "Response",
    "AudioStats",
    "AudioStreamClient",
    "ImageClient",
    "SerialTransport",
    "Transport",
    "list_serial_ports",
    "GlassesSession", "GlassesUnsupportedError",
    "WifiCapabilities", "WifiError", "WifiNetwork", "WifiSecurity", "WifiStage", "WifiStatus",
    "DeleteResult", "DownloadResult", "MediaCancelled", "MediaError", "MediaFile",
    "MediaImport", "MediaItem", "MediaSessionError",
    "CaptureError", "CaptureResult", "CaptureState", "CaptureTimeoutError", "MediaCapabilities",
    "VideoConfig", "VideoConfigState", "VideoOrientation", "VideoResolution",
    "AmbiguousGlassesError",
    "OTAError", "OTAStatusError", "OTATimeoutError",
    "UpdateResultResponse", "CompletedImage", "GlassesEvent",
    "HelloAck", "DeviceInfo", "SensorData", "ButtonEvent", "KnobEvent",
    "AudioRecordRequestEvent", "CaptureKind", "CaptureSource", "DeviceCaptureEntry", "DeviceCaptureState",
    "AudioStateEvent", "ImgStateEvent", "UnknownEvent", "CaptureEvt",
    "LedId", "LedMode", "LedColor", "LedSpeed", "Tone",
]

__version__ = "0.6.0"
