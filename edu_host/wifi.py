"""Typed EDU WiFi commands; bulk media uses the separately negotiated HTTP endpoint."""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import struct
import time
from typing import Optional, Tuple, TYPE_CHECKING

from .client import EduClientError, EduTimeoutError
from . import protocol

if TYPE_CHECKING:
    from .session import EduSession


class WifiOperation(IntEnum):
    CAPABILITIES = 2
    SCAN = 3
    CONNECT = 7
    START_MEDIA = 8
    STATUS = 9
    DISCONNECT = 10


class WifiSecurity(IntEnum):
    UNSUPPORTED = 0
    OPEN = 1
    WEP = 2
    WEP_SHARED = 3
    WPA = 4
    WPA2 = 5
    WPA3 = 6


class WifiStage(IntEnum):
    IDLE = 0
    SCANNING = 1
    CONNECTING = 2
    DHCP = 3
    CONNECTED = 5
    SERVING = 6
    STOPPING = 7
    FAILED = 8


class WifiError(EduClientError):
    def __init__(self, code: int) -> None:
        self.code = code
        super().__init__("WiFi failed (code %d)" % code)


@dataclass(frozen=True)
class WifiCapabilities:
    version: int
    securities: Tuple[WifiSecurity, ...]


@dataclass(frozen=True)
class WifiNetwork:
    ssid: str
    channel: int
    rssi_dbm: int
    security: WifiSecurity


@dataclass(frozen=True)
class WifiScanPage:
    complete: bool
    next_offset: int
    has_more: bool
    networks: Tuple[WifiNetwork, ...]


@dataclass(frozen=True)
class WifiStatus:
    stage: WifiStage
    failure: int
    catalog_id: int
    port: int
    ipv4: str
    ssid: str
    security: WifiSecurity


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.offset = 0

    def unpack(self, fmt: str):
        size = struct.calcsize(fmt)
        if self.offset + size > len(self.data):
            raise EduClientError("truncated WiFi response")
        result = struct.unpack_from(fmt, self.data, self.offset)
        self.offset += size
        return result

    def string(self, length: Optional[int] = None) -> str:
        if length is None:
            length, = self.unpack('<B')
            if length > 32:
                raise EduClientError("invalid WiFi SSID length")
        value, = self.unpack('<%ds' % length)
        return value.rstrip(b'\0').decode('utf-8', errors='strict')


class WifiClient:
    def __init__(self, session: EduSession) -> None:
        self.session = session

    def execute(self, operation: WifiOperation, args: bytes = b''):
        self.session._require(protocol.CAP_WIFI)
        response = self.session._request(protocol.CommandId.WIFI_EXECUTE,
                                         bytes([operation]) + args, timeout=20.0)
        reader = _Reader(response.data)
        echoed, kind = reader.unpack('<BB')
        if echoed != operation:
            raise EduClientError("WiFi operation does not match response")
        if kind == 4:
            error, = reader.unpack('<B')
            raise WifiError(error)
        if kind == 0 and operation == WifiOperation.CAPABILITIES:
            version, securities = reader.unpack('<IB')
            result = WifiCapabilities(version, tuple(s for s in WifiSecurity
                                                     if s and securities & (1 << s)))
        elif kind == 1 and operation == WifiOperation.SCAN:
            complete, offset, more, count = reader.unpack('<?I?B')
            if count > 5:
                raise EduClientError("invalid WiFi scan page")
            networks = []
            for _ in range(count):
                ssid = reader.string()
                channel, rssi, security = reader.unpack('<IiB')
                networks.append(WifiNetwork(ssid, channel, rssi, WifiSecurity(security)))
            result = WifiScanPage(complete, offset, more, tuple(networks))
        elif kind == 2 and operation in (WifiOperation.CONNECT, WifiOperation.STATUS,
                                         WifiOperation.START_MEDIA):
            stage, failure, catalog_id, port = reader.unpack('<BBQH')
            ipv4 = reader.string(16)
            ssid = reader.string()
            security, = reader.unpack('<B')
            result = WifiStatus(WifiStage(stage), failure, catalog_id, port, ipv4,
                                ssid, WifiSecurity(security))
        elif kind == 3 and operation in (WifiOperation.CONNECT, WifiOperation.START_MEDIA,
                                        WifiOperation.DISCONNECT):
            result = None
        else:
            raise EduClientError("unexpected WiFi outcome %d" % kind)
        if reader.offset != len(reader.data):
            raise EduClientError("unexpected trailing WiFi response data")
        return result

    def capabilities(self) -> WifiCapabilities:
        return self.execute(WifiOperation.CAPABILITIES)

    def scan(self, timeout: float = 30.0) -> Tuple[WifiNetwork, ...]:
        deadline = time.monotonic() + self.session._duration(timeout)
        offset = 0
        networks = []
        while True:
            page = self.execute(WifiOperation.SCAN, struct.pack('<I', offset))
            if page.complete:
                networks.extend(page.networks)
                if not page.has_more:
                    return tuple(networks)
                if page.next_offset <= offset:
                    raise EduClientError("WiFi scan cursor did not advance")
                offset = page.next_offset
            if time.monotonic() >= deadline:
                raise EduTimeoutError("WiFi scan did not complete")
            self.session.wait(0.2)

    def connect(self, ssid: str, password: str = '', security: WifiSecurity = WifiSecurity.WPA2,
                timeout: float = 70.0) -> WifiStatus:
        security = WifiSecurity(security)
        name, key = ssid.encode('utf-8'), password.encode('utf-8')
        if not 1 <= len(name) <= 32 or len(key) > 64 or b'\0' in name + key:
            raise ValueError("SSID must be 1–32 UTF-8 bytes; password at most 64, without NUL")
        caps = self.capabilities()
        if security not in caps.securities:
            raise ValueError("WiFi security is not supported by the device")
        self.execute(WifiOperation.CONNECT, bytes([security, len(name), len(key)]) + name + key)
        deadline = time.monotonic() + self.session._duration(timeout)
        while True:
            status = self.status()
            if status.stage in (WifiStage.CONNECTED, WifiStage.SERVING):
                return status
            if status.stage == WifiStage.FAILED:
                raise WifiError(status.failure)
            if time.monotonic() >= deadline:
                raise EduTimeoutError("WiFi connection did not become ready")
            self.session.wait(0.2)

    def status(self) -> WifiStatus:
        return self.execute(WifiOperation.STATUS)

    def start_media(self) -> WifiStatus:
        self.execute(WifiOperation.START_MEDIA)
        deadline = time.monotonic() + 20.0
        while True:
            status = self.status()
            if status.stage == WifiStage.SERVING and status.ipv4 and status.port and status.catalog_id:
                return status
            if status.stage == WifiStage.FAILED:
                raise WifiError(status.failure)
            if time.monotonic() >= deadline:
                raise EduTimeoutError("media endpoint did not become SERVING with a catalog identity")
            self.session.wait(0.2)

    def disconnect(self) -> None:
        self.execute(WifiOperation.DISCONNECT)
