"""macOS Bluetooth RFCOMM support (pyobjc / IOBluetooth).

macOS's CPython has no Bluetooth sockets and does not expose SPP services as
serial ports, so this module drives IOBluetooth directly. Two hard-won rules
(verified on real hardware) shape the design:

1. Channels MUST be opened with ``openRFCOMMChannelAsync`` and their delegate
   callbacks are only delivered while the **main thread's** NSRunLoop is
   pumped — the sync variant and background-thread run loops fail.
2. A first open attempt can fail with ``kIOReturnError`` if bluetoothd holds
   stale channel state; closing and reopening the ACL connection fixes it.

Each native channel runs in its own child process to avoid the macOS 27
IOBluetooth bug that closes a sibling channel in the same process.

Therefore this module gives you :class:`MacRFCOMMChannel` objects plus an
explicit :func:`pump` you must call from the main thread; reads only drain
the RX buffer. ``demo_cli.py`` runs its REPL around this pump.

Requires ``pyobjc-core`` + ``pyobjc-framework-IOBluetooth`` and, on first
use, the OS Bluetooth permission prompt for the hosting app (run from
Terminal so Terminal is the responsible process).
"""

from __future__ import annotations

import time
import subprocess
import sys
import weakref
from multiprocessing import Pipe
from typing import Dict, List, Optional

import objc  # type: ignore
from Foundation import (NSObject, NSRunLoop, NSDefaultRunLoopMode,  # type: ignore
                        NSDate)
import IOBluetooth  # type: ignore

#: SPP service UUIDs (16-bit) of the developer firmware.
UUID_CTRL = 0x2028
UUID_AUDIO = 0x2024
UUID_IMG = 0x2025
UUID_OTA = 0x2026


def pump(seconds: float) -> None:
    """Pump the current (main) thread's run loop for *seconds*."""
    rl = NSRunLoop.currentRunLoop()
    end = time.time() + seconds
    while time.time() < end:
        rl.runMode_beforeDate_(NSDefaultRunLoopMode,
                               NSDate.dateWithTimeIntervalSinceNow_(0.05))


def find_device(bt_addr: Optional[str] = None,
                name_prefix: str = "EDU-"):
    """Return an IOBluetoothDevice by address, or auto-pick a paired one.

    Auto-pick prefers a device that is **currently connected** (isConnected),
    because that is the one the demo can actually talk to — a paired-but-
    offline device would just time out. If none is connected: a single
    match is returned; multiple matches raise
    :class:`~looktech_glasses_sdk.bt_discovery.AmbiguousGlassesError` so the caller asks
    for an explicit --bt <address> instead of guessing.
    """
    if bt_addr and bt_addr != "auto":
        return IOBluetooth.IOBluetoothDevice.deviceWithAddressString_(
            bt_addr.replace(":", "-"))

    matches = [dev for dev in (IOBluetooth.IOBluetoothDevice.pairedDevices() or [])
               if dev.name() and str(dev.name()).startswith(name_prefix)]
    for dev in matches:
        if dev.isConnected():
            return dev
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        from .bt_discovery import AmbiguousGlassesError
        raise AmbiguousGlassesError(
            [(str(d.getAddressString()), str(d.name())) for d in matches])
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


class _NativeRFCOMMChannel:
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

    def open(self, timeout: float = 12.0) -> None:
        self._delegate = _Delegate.alloc().initWithOwner_(self)
        status, self._chan = self._dev.openRFCOMMChannelAsync_withChannelID_delegate_(
            None, self.channel_id, self._delegate)
        if status != 0:
            raise IOError("RFCOMM open failed (status=%s)" % status)
        deadline = time.monotonic() + timeout
        while self._open_status is None and time.monotonic() < deadline:
            pump(0.1)
        if self._open_status != 0:
            raise IOError("RFCOMM open failed (status=%s)" % self._open_status)

    def write(self, data: bytes) -> None:
        if self._chan is None or self.closed:
            raise IOError("%s: channel not open" % self.name)
        status = self._chan.writeSync_length_(data, len(data))
        if status != 0:
            raise IOError("%s: RFCOMM write failed (status=%s)" % (self.name, status))

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
                deadline = time.monotonic() + 1.0
                while self._chan.isOpen() and time.monotonic() < deadline:
                    pump(0.05)
            except Exception:
                pass
            self._chan = None
        self.closed = True


class MacRFCOMMChannel:
    """One RFCOMM channel, owned by an isolated process's main run loop.

    macOS 27 can close the first channel belonging to a process instead of
    the requested channel. One native channel per process avoids that alias.
    """

    _live = weakref.WeakSet()

    def __init__(self, dev, channel_id: int, name: str = "") -> None:
        self._dev = dev
        self.channel_id = int(channel_id)
        self.name = name or ("ch%d" % channel_id)
        self.closed = False
        self._rx = bytearray()
        self._conn = self._proc = None

    def _receive(self, expected=None, timeout=0.0):
        deadline = time.monotonic() + timeout
        while self._conn is not None:
            if not self._conn.poll(max(0.0, deadline - time.monotonic())):
                if expected:
                    raise IOError("%s: worker %s timed out" % (self.name, expected))
                return
            try:
                kind, value = self._conn.recv()
            except (EOFError, OSError) as exc:
                self.closed = True
                raise IOError("%s: RFCOMM worker exited" % self.name) from exc
            if kind == "data":
                self._rx.extend(value)
            elif kind == "closed":
                self.closed = True
                if expected:
                    raise IOError("%s: channel closed" % self.name)
                return
            elif kind == "error":
                self.closed = True
                raise IOError("%s: %s" % (self.name, value))
            elif kind == expected:
                return value

    def open(self, timeout: float = 12.0, retries: int = 1) -> None:
        if self._proc is not None and not self.closed:
            try:
                self._receive()
            except OSError:
                self.closed = True
            if not self.closed:
                return
        self.close()
        address = str(self._dev.getAddressString())
        # -c also works for notebooks and scripts without a __main__ guard.
        code = ("import sys; sys.path[:0] = %r; "
                "from looktech_glasses_sdk.mac_bt import _channel_worker; "
                "_channel_worker(int(sys.argv[1]), sys.argv[2], "
                "int(sys.argv[3]), float(sys.argv[4]))") % sys.path
        for attempt in range(retries + 1):
            self._conn, child = Pipe()
            try:
                self._proc = subprocess.Popen(
                    [sys.executable, "-c", code, str(child.fileno()), address,
                     str(self.channel_id), str(timeout)],
                    pass_fds=(child.fileno(),), stdin=subprocess.DEVNULL)
            except BaseException:
                self.close()
                raise
            finally:
                child.close()
            try:
                self._receive("open", timeout + 3.0)
                self._rx.clear()
                self.closed = False
                self._live.add(self)
                return
            except BaseException as exc:
                self.close()
                if not isinstance(exc, OSError):
                    raise
                others = any(str(t._dev.getAddressString()) == address
                             and not t.closed for t in self._live)
                if attempt == retries or others:
                    raise
                # Rebuilding an ACL is safe only before any sibling is open.
                self._dev.closeConnection()
                pump(3.0)
                self._dev.openConnection()
                pump(2.0)

    def write(self, data: bytes) -> None:
        if self._conn is None or self.closed:
            raise IOError("%s: channel not open" % self.name)
        try:
            self._conn.send(("write", data))
            self._receive("write", 10.0)
        except OSError:
            self.close()
            raise

    def read(self, max_bytes: int = 65536) -> bytes:
        if not self.closed:
            self._receive()
        out = bytes(self._rx[:max_bytes])
        del self._rx[:max_bytes]
        return out

    def close(self) -> None:
        try:
            if self._conn is not None:
                try:
                    self._conn.send(("close", None))
                    self._receive("close", 2.0)
                except (OSError, EOFError):
                    pass
        finally:
            if self._conn is not None:
                self._conn.close()
            if self._proc is not None:
                try:
                    self._proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
                    self._proc.wait()
            self._conn = self._proc = None
            self._rx.clear()
            self.closed = True
            self._live.discard(self)


def _channel_worker(fd: int, address: str, channel_id: int, timeout: float) -> None:
    """Private pipe endpoint; each native channel stays on its main thread."""
    from multiprocessing.connection import Connection
    conn = Connection(fd)
    dev = find_device(address)
    channel = _NativeRFCOMMChannel(dev, channel_id)
    try:
        # IOBluetooth needs a process-local SDP query before opening a new peer.
        sdp_channels(dev, [UUID_CTRL, UUID_AUDIO, UUID_IMG, UUID_OTA])
        channel.open(timeout=timeout)
        conn.send(("open", None))
        run_loop = NSRunLoop.currentRunLoop()
        while True:
            run_loop.runMode_beforeDate_(
                NSDefaultRunLoopMode, NSDate.dateWithTimeIntervalSinceNow_(0.005))
            data = channel.read()
            if data:
                conn.send(("data", data))
            if channel.closed:
                conn.send(("closed", None))
                break
            if not conn.poll():
                continue
            command, data = conn.recv()
            if command == "close":
                channel.close()
                conn.send(("close", None))
                break
            if command != "write":
                raise ValueError("unknown worker command")
            channel.write(data)
            conn.send(("write", None))
    except (EOFError, BrokenPipeError):
        pass
    except Exception as exc:
        try:
            conn.send(("error", str(exc)))
        except (EOFError, OSError):
            pass
    finally:
        channel.close()
        conn.close()
