"""Transport abstraction for talking to the glasses.

Today the only implementation is :class:`SerialTransport`, which uses a
Bluetooth *virtual serial port* created by the operating system after pairing
(macOS: ``/dev/cu.*``; Windows: outgoing ``COMx`` ports). The interface is
deliberately tiny so a native RFCOMM transport (e.g. via a Bluetooth socket)
can be added later without touching the protocol or client code.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import List


class Transport(abc.ABC):
    """Minimal byte-pipe interface used by EduClient / AudioStreamClient."""

    @abc.abstractmethod
    def open(self) -> None:
        """Open the underlying connection. Idempotent."""

    @abc.abstractmethod
    def close(self) -> None:
        """Close the connection. Idempotent."""

    @abc.abstractmethod
    def read(self, max_bytes: int = 4096) -> bytes:
        """Read up to *max_bytes*. Blocks briefly; returns b"" on timeout."""

    @abc.abstractmethod
    def write(self, data: bytes) -> None:
        """Write all of *data*."""

    @property
    @abc.abstractmethod
    def is_open(self) -> bool:
        """Whether the transport is currently open."""


class SerialTransport(Transport):
    """pyserial-based transport over an OS Bluetooth virtual serial port.

    The baudrate is meaningless for Bluetooth RFCOMM virtual ports (there is
    no physical UART) but pyserial requires one, so we default to 115200.
    """

    def __init__(self, port: str, baudrate: int = 115200,
                 read_timeout_s: float = 0.05) -> None:
        self.port = port
        self.baudrate = baudrate
        self.read_timeout_s = read_timeout_s
        self._serial = None  # created lazily in open()

    def open(self) -> None:
        if self._serial is not None and self._serial.is_open:
            return
        import serial  # imported here so protocol tests don't need pyserial

        # timeout: makes read() return whatever arrived within the window,
        # so the reader thread stays responsive without busy-waiting.
        self._serial = serial.Serial(self.port, baudrate=self.baudrate,
                                     timeout=self.read_timeout_s)

    def close(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            finally:
                self._serial = None

    def read(self, max_bytes: int = 4096) -> bytes:
        if self._serial is None:
            raise RuntimeError("transport not open")
        # Read at least 1 byte (or hit the timeout), then drain what's pending.
        data = self._serial.read(1)
        if data:
            waiting = self._serial.in_waiting
            if waiting:
                data += self._serial.read(min(waiting, max_bytes - 1))
        return data

    def write(self, data: bytes) -> None:
        if self._serial is None:
            raise RuntimeError("transport not open")
        self._serial.write(data)
        self._serial.flush()

    @property
    def is_open(self) -> bool:
        return self._serial is not None and self._serial.is_open


@dataclass
class PortInfo:
    """One candidate serial port for the --list helper."""

    device: str
    description: str

    def __str__(self) -> str:
        return "%-40s %s" % (self.device, self.description)


def list_serial_ports() -> List[PortInfo]:
    """List candidate serial ports (uses serial.tools.list_ports).

    On macOS prefer the ``/dev/cu.*`` entries; on Windows these are ``COMx``.
    """
    from serial.tools import list_ports

    ports = []
    for p in list_ports.comports():
        ports.append(PortInfo(device=p.device, description=p.description or ""))
    return sorted(ports, key=lambda p: p.device)
