"""Cross-platform Bluetooth RFCOMM socket transport (Windows / Linux).

Uses only the Python standard library:

* Windows: ``socket.AF_BTH`` + ``BTHPROTO_RFCOMM`` (available in the official
  CPython Windows builds, Python 3.9+);
* Linux:   ``socket.AF_BLUETOOTH`` + ``BTPROTO_RFCOMM``.

macOS's CPython has neither — use :mod:`edu_host.mac_bt` there instead.

The device registers its SPP services in a fixed order, so the RFCOMM
channel numbers are stable across boots (verified against the firmware's
SDP records):

======  =======  ==================================
UUID    channel  purpose
======  =======  ==================================
0x2025  4        EDU-IMG   (photo JPEG stream)
0x2024  5        EDU-AUDIO (OPUS mic stream)
0x2028  6        EDU-CTRL  (commands/events)
======  =======  ==================================
"""

from __future__ import annotations

import socket
import sys

from .transport import Transport

# Default RFCOMM channels (see table above); override via constructor if the
# firmware's registration order ever changes.
CHANNEL_IMG = 4
CHANNEL_AUDIO = 5
CHANNEL_CTRL = 6


def bt_socket_supported() -> bool:
    """Whether this Python/OS supports Bluetooth RFCOMM sockets."""
    return hasattr(socket, "AF_BTH") or hasattr(socket, "AF_BLUETOOTH")


class SocketRFCOMMTransport(Transport):
    """Blocking RFCOMM socket with the small Transport read/write interface."""

    def __init__(self, bt_addr: str, channel: int,
                 read_timeout_s: float = 0.05, name: str = "") -> None:
        self.bt_addr = bt_addr
        self.channel = int(channel)
        self.read_timeout_s = read_timeout_s
        self.name = name or ("rfcomm-ch%d" % channel)
        self._sock = None

    def open(self) -> None:
        if self._sock is not None:
            return
        if hasattr(socket, "AF_BTH"):          # Windows
            sock = socket.socket(socket.AF_BTH, socket.SOCK_STREAM,
                                 socket.BTHPROTO_RFCOMM)
        elif hasattr(socket, "AF_BLUETOOTH"):  # Linux
            sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM,
                                 socket.BTPROTO_RFCOMM)
        else:
            raise OSError(
                "This Python has no Bluetooth socket support "
                "(platform: %s). On macOS use the IOBluetooth path (--bt); "
                "otherwise fall back to serial ports." % sys.platform)
        sock.connect((self.bt_addr, self.channel))
        # Short timeout gives read() the same "return b'' on idle" semantics
        # as SerialTransport, keeping the client reader thread responsive.
        sock.settimeout(self.read_timeout_s)
        self._sock = sock

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def read(self, max_bytes: int = 4096) -> bytes:
        if self._sock is None:
            raise RuntimeError("transport not open")
        try:
            data = self._sock.recv(max_bytes)
            if data == b"":
                # orderly shutdown by the peer
                raise IOError("%s: connection closed by device" % self.name)
            return data
        except socket.timeout:
            return b""

    def write(self, data: bytes) -> None:
        if self._sock is None:
            raise RuntimeError("transport not open")
        self._sock.sendall(data)

    @property
    def is_open(self) -> bool:
        return self._sock is not None
