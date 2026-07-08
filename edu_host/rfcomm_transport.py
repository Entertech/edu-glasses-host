"""macOS-native RFCOMM transport (pyobjc / IOBluetooth).

On macOS a Classic-BT SPP service is NOT auto-exposed as a ``/dev/cu.*``
serial port, so :class:`edu_host.transport.SerialTransport` cannot reach the
glasses. This transport instead opens the RFCOMM channel of an SPP service
directly through IOBluetooth, presenting the same synchronous
open/read/write/close interface as :class:`Transport`.

IMPORTANT: macOS aborts (SIGABRT, TCC) any process that touches Bluetooth
unless the *responsible* application's Info.plist declares
``NSBluetoothAlwaysUsageDescription``. A bare ``python3`` has no such key, so
this module only works when launched from an .app bundle that provides it
(see edu_host/macos/). It requires ``pyobjc-framework-IOBluetooth``.

The channel's delegate callbacks are driven by a private run-loop thread; RX
bytes land in a thread-safe buffer that :meth:`read` drains, and :meth:`write`
is marshalled onto the run-loop thread (IOBluetooth channel ops must run on
the thread that opened the channel).
"""

from __future__ import annotations

import threading
import time
from typing import List, Optional

import objc
from Foundation import (NSObject, NSRunLoop, NSDefaultRunLoopMode, NSDate,
                        NSAutoreleasePool)
import IOBluetooth

from .transport import Transport


def sdp_channel_for_uuid16(device_addr: str, uuid16: int,
                           sdp_timeout: float = 6.0) -> Optional[int]:
    """SDP-query *device_addr* and return the RFCOMM channel for *uuid16*.

    Returns ``None`` if the service is not found. Must run in a process that
    is allowed to use Bluetooth (see module docstring).
    """
    dev = IOBluetooth.IOBluetoothDevice.deviceWithAddressString_(
        device_addr.replace(":", "-"))
    if dev is None:
        return None
    dev.performSDPQuery_(None)
    deadline = time.time() + sdp_timeout
    while time.time() < deadline:
        for rec in (dev.services() or []):
            if rec.matchesUUID16_(uuid16):
                err, ch = rec.getRFCOMMChannelID_(None)
                if err == 0 and ch:
                    return int(ch)
        time.sleep(0.3)
    return None


class _ChannelDelegate(NSObject):
    """IOBluetoothRFCOMMChannel delegate — bridges callbacks to the transport."""

    def initWithOwner_(self, owner):
        self = objc.super(_ChannelDelegate, self).init()
        if self is None:
            return None
        self._owner = owner
        return self

    # status 0 == kIOReturnSuccess
    def rfcommChannelOpenComplete_status_(self, channel, status):
        self._owner._on_open_complete(int(status))

    def rfcommChannelData_data_length_(self, channel, data, length):
        try:
            chunk = bytes(data[:length]) if length else b""
        except Exception:
            chunk = bytes(data) if data else b""
        if chunk:
            self._owner._on_rx(chunk)

    def rfcommChannelClosed_(self, channel):
        self._owner._on_closed()


class RFCOMMTransport(Transport):
    """Synchronous Transport over an IOBluetooth RFCOMM channel."""

    def __init__(self, device_addr: str, channel_id: int,
                 open_timeout: float = 15.0, name: str = "") -> None:
        self._addr = device_addr.replace(":", "-")
        self._channel_id = int(channel_id)
        self._open_timeout = open_timeout
        self._name = name or ("rfcomm-ch%d" % channel_id)

        self._rx_buf = bytearray()
        self._rx_lock = threading.Lock()
        self._tx_queue: List[bytes] = []
        self._tx_lock = threading.Lock()

        self._opened_evt = threading.Event()
        self._open_status: Optional[int] = None
        self._closed = False
        self._stop = False

        self._rfcomm = None
        self._delegate = None
        self._thread: Optional[threading.Thread] = None

    # -- Transport interface -------------------------------------------------

    def open(self) -> None:
        self._thread = threading.Thread(target=self._run_loop,
                                        name=self._name, daemon=True)
        self._thread.start()
        if not self._opened_evt.wait(self._open_timeout):
            self._stop = True
            raise IOError("%s: RFCOMM open timed out after %.0fs"
                          % (self._name, self._open_timeout))
        if self._open_status != 0:
            raise IOError("%s: RFCOMM open failed, IOReturn=0x%x"
                          % (self._name, self._open_status & 0xFFFFFFFF))

    def read(self, size: int = 4096) -> bytes:
        # Poll the RX buffer; the run-loop thread fills it from delegate cbks.
        deadline = time.time() + 0.2
        while time.time() < deadline:
            with self._rx_lock:
                if self._rx_buf:
                    n = min(size, len(self._rx_buf))
                    out = bytes(self._rx_buf[:n])
                    del self._rx_buf[:n]
                    return out
            if self._closed:
                return b""
            time.sleep(0.005)
        return b""

    def write(self, data: bytes) -> None:
        if self._closed:
            raise IOError("%s: channel closed" % self._name)
        with self._tx_lock:
            self._tx_queue.append(bytes(data))

    def close(self) -> None:
        self._stop = True
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None

    @property
    def is_open(self) -> bool:
        return (self._thread is not None and self._thread.is_alive()
                and not self._closed and self._open_status == 0)

    # -- run-loop thread -----------------------------------------------------

    def _run_loop(self) -> None:
        pool = NSAutoreleasePool.alloc().init()
        try:
            dev = IOBluetooth.IOBluetoothDevice.deviceWithAddressString_(self._addr)
            if dev is None:
                self._open_status = -1
                self._opened_evt.set()
                return
            self._delegate = _ChannelDelegate.alloc().initWithOwner_(self)
            res, chan = dev.openRFCOMMChannelAsync_withChannelID_delegate_(
                None, self._channel_id, self._delegate)
            if res != 0:
                self._open_status = int(res)
                self._opened_evt.set()
                return
            self._rfcomm = chan

            rl = NSRunLoop.currentRunLoop()
            while not self._stop:
                rl.runMode_beforeDate_(
                    NSDefaultRunLoopMode,
                    NSDate.dateWithTimeIntervalSinceNow_(0.05))
                self._flush_tx()
            # graceful close
            if self._rfcomm is not None:
                try:
                    self._rfcomm.closeChannel()
                except Exception:
                    pass
        finally:
            del pool

    def _flush_tx(self) -> None:
        if self._rfcomm is None:
            return
        with self._tx_lock:
            pending, self._tx_queue = self._tx_queue, []
        for buf in pending:
            # writeSync_length_ blocks until the data is queued to the baseband
            self._rfcomm.writeSync_length_(buf, len(buf))

    # -- delegate hooks (called on run-loop thread) --------------------------

    def _on_open_complete(self, status: int) -> None:
        self._open_status = status
        self._opened_evt.set()

    def _on_rx(self, chunk: bytes) -> None:
        with self._rx_lock:
            self._rx_buf.extend(chunk)

    def _on_closed(self) -> None:
        self._closed = True
