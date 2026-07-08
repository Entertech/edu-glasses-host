"""Host-side Python library for the Looktech glasses education firmware.

Modules:

* :mod:`edu_host.crc16` — firmware CRC-16 port;
* :mod:`edu_host.protocol` — EDU-CTRL frame codec, enums, image reassembly;
* :mod:`edu_host.transport` — serial transport abstraction;
* :mod:`edu_host.client` — EduClient (handshake, request/response, events);
* :mod:`edu_host.image_client` — air-img image channel receiver (photos);
* :mod:`edu_host.audio_client` — EDU-AUDIO stream parser and OPUS->WAV writer.
"""

from .client import (EduClient, EduClientError, EduStatusError,
                     EduTimeoutError, Response)
from .audio_client import AudioStats, AudioStreamClient
from .image_client import ImageClient
from .transport import SerialTransport, Transport, list_serial_ports

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
]

__version__ = "0.1.0"
