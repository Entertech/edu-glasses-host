"""Host-side Python library for the Looktech glasses education firmware.

Modules:

* :mod:`edu_host.crc16` — firmware CRC-16 port;
* :mod:`edu_host.protocol` — EDU-CTRL frame codec, enums, image reassembly;
* :mod:`edu_host.transport` — serial transport abstraction;
* :mod:`edu_host.client` — EduClient (handshake, request/response, events);
* :mod:`edu_host.image_client` — air-img image channel receiver (photos);
* :mod:`edu_host.audio_client` — EDU-AUDIO stream parser and OPUS->WAV writer;
* :mod:`edu_host.session` — platform-aware EduSession SDK.
"""

from .client import (EduClient, EduClientError, EduStatusError,
                     EduTimeoutError, Response)
from .audio_client import AudioStats, AudioStreamClient
from .image_client import ImageClient
from .transport import SerialTransport, Transport, list_serial_ports
from .session import EduSession, EduUnsupportedError
from .bt_discovery import AmbiguousGlassesError
from .ota_client import OTAError, OTAStatusError, OTATimeoutError, UpdateResultResponse
from .protocol import (AudioStateEvent, ButtonEvent, CaptureEvt, CompletedImage,
                       DeviceInfo, EduEvent,
                       HelloAck, ImgStateEvent, KnobEvent, LedColor, LedId,
                       LedMode, LedSpeed, SensorData, Tone, UnknownEvent)

__all__ = [
    "EduClient",
    "EduClientError",
    "EduStatusError",
    "EduTimeoutError",
    "Response",
    "AudioStats",
    "AudioStreamClient",
    "ImageClient",
    "SerialTransport",
    "Transport",
    "list_serial_ports",
    "EduSession", "EduUnsupportedError",
    "AmbiguousGlassesError",
    "OTAError", "OTAStatusError", "OTATimeoutError",
    "UpdateResultResponse", "CompletedImage", "EduEvent",
    "HelloAck", "DeviceInfo", "SensorData", "ButtonEvent", "KnobEvent",
    "AudioStateEvent", "ImgStateEvent", "UnknownEvent", "CaptureEvt",
    "LedId", "LedMode", "LedColor", "LedSpeed", "Tone",
]

__version__ = "0.2.0"
