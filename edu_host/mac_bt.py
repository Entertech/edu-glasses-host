"""macOS Bluetooth RFCOMM support (pyobjc / IOBluetooth).

macOS's CPython has no Bluetooth sockets and does not expose SPP services as
serial ports, so this module drives IOBluetooth directly. Two hard-won rules
(verified on real hardware) shape the design:

1. Channels MUST be opened with ``openRFCOMMChannelAsync`` and their delegate
   callbacks are only delivered while the **main thread's** NSRunLoop is
   pumped — the sync variant and background-thread run loops fail.
2. A first open attempt can fail with ``kIOReturnError`` if bluetoothd holds
   stale channel state; closing and reopening the ACL connection fixes it.

Therefore this module gives you :class:`MacRFCOMMChannel` objects plus an
explicit :func:`pump` you must call from the main thread; reads only drain
the RX buffer. ``demo_cli.py`` runs its REPL around this pump.

Requires ``pyobjc-core`` + ``pyobjc-framework-IOBluetooth`` and, on first
use, the OS Bluetooth permission prompt for the hosting app (run from
Terminal so Terminal is the responsible process).
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional

import objc  # type: ignore
from Foundation import (NSObject, NSRunLoop, NSDefaultRunLoopMode,  # type: ignore
                        NSDate)
import IOBluetooth  # type: ignore

#: SPP service UUIDs (16-bit) of the education firmware.
UUID_CTRL = 0x2028
UUID_AUDIO = 0x2024
UUID_IMG = 0x2025


def pump(seconds: float) -> None:
    """Pump the current (main) thread's run loop for *seconds*."""
    rl = NSRunLoop.currentRunLoop()
    end = time.time() + seconds
    while time.time() < end:
        rl.runMode_beforeDate_(NSDefaultRunLoopMode,
                               NSDate.dateWithTimeIntervalSinceNow_(0.05))


def find_device(bt_addr: Optional[str] = None,
                name_prefix: str = "EDU-"):
    """Return an IOBluetoothDevice by address, or by paired-name prefix."""
    if bt_addr:
        return IOBluetooth.IOBluetoothDevice.deviceWithAddressString_(
            bt_addr.replace(":", "-"))
    for dev in (IOBluetooth.IOBluetoothDevice.pairedDevices() or []):
        name = dev.name()
        if name and str(name).startswith(name_prefix):
            return dev
    return None


def sdp_channels(dev, uuids: List[int], timeout: float = 6.0) -> Dict[int, int]:
    """SDP-query *dev*, return {uuid16: rfcomm_channel} for found services."""
    dev.performSDPQuery_(None)
    found: Dict[int, int] = {}
    deadline = time.time() + timeout
    while time.time() < deadline and len(found) < len(uuids):
        pump(0.3)
        for rec in (dev.services() or []):
            for u in uuids:
                if u in found:
                    continue
                if rec.matchesUUID16_(u):
                    err, ch = rec.getRFCOMMChannelID_(None)
                    if err == 0 and ch:
                        found[u] = int(ch)
    return found


class _Delegate(NSObject):
    def initWithOwner_(self, owner):
        self = objc.super(_Delegate, self).init()
        if self is None:
            return None
        self._owner = owner
        return self

    def rfcommChannelOpenComplete_status_(self, chan, status):
        self._owner._open_status = int(status)

    def rfcommChannelData_data_length_(self, chan, data, length):
        try:
            b = bytes(data[:length])
        except Exception:
            b = bytes(data) if data else b""
        if b:
            self._owner._rx.extend(b)

    def rfcommChannelClosed_(self, chan):
        self._owner.closed = True


class MacRFCOMMChannel:
    """One RFCOMM channel. Main-thread only; drive it with :func:`pump`."""

    def __init__(self, dev, channel_id: int, name: str = "") -> None:
        self._dev = dev
        self.channel_id = int(channel_id)
        self.name = name or ("ch%d" % channel_id)
        self._rx = bytearray()
        self._open_status: Optional[int] = None
        self._chan = None
        self._delegate = None
        self.closed = False

    def open(self, timeout: float = 12.0, retries: int = 1) -> None:
        """Open the channel (blocking; pumps the main run loop)."""
        for attempt in range(retries + 1):
            self._open_status = None
            self._delegate = _Delegate.alloc().initWithOwner_(self)
            res, chan = self._dev.openRFCOMMChannelAsync_withChannelID_delegate_(
                None, self.channel_id, self._delegate)
            if res == 0:
                self._chan = chan
                end = time.time() + timeout
                while self._open_status is None and time.time() < end:
                    pump(0.1)
                if self._open_status == 0:
                    self.closed = False
                    return
                try:
                    chan.closeChannel()
                except Exception:
                    pass
            if attempt == 0 and retries > 0:
                # stale bluetoothd channel state: rebuild the ACL once
                self._dev.closeConnection()
                pump(3.0)
                self._dev.openConnection()
                pump(2.0)
        raise IOError("%s: RFCOMM open failed (status=%s)"
                      % (self.name, self._open_status))

    def write(self, data: bytes) -> None:
        if self._chan is None or self.closed:
            raise IOError("%s: channel not open" % self.name)
        self._chan.writeSync_length_(data, len(data))

    def read(self, max_bytes: int = 65536) -> bytes:
        """Drain up to *max_bytes* from the RX buffer (non-blocking)."""
        if not self._rx:
            return b""
        n = min(max_bytes, len(self._rx))
        out = bytes(self._rx[:n])
        del self._rx[:n]
        return out

    def close(self) -> None:
        if self._chan is not None:
            try:
                self._chan.closeChannel()
            except Exception:
                pass
            self._chan = None
        self.closed = True
