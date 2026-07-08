"""Host-side client for the firmware OTA SPP channel (UUID 0x2026).

The firmware OTA channel uses the existing device-as-server OTA protocol:
the host sends opcode packets and the device replies with the same opcode.
Packet layout, little-endian::

    | prefix u32=0xFEDCBA98 | opcode u8 | len u16 | payload | appendix u32=0x76543210 |

Firmware upgrade packages are provided by the firmware maintainers; this
client validates the package header (CRC) before pushing it. The transfer is
device-driven: the device requests blocks (offset/length), the host streams
them as small sub-packets and the device ACKs at block boundaries only.
"""

from __future__ import annotations

import struct
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from .transport import Transport

UUID_OTA = 0x2026

PACKET_PREFIX = 0xFEDCBA98
PACKET_APPENDIX = 0x76543210
PACKET_HEADER_LEN = 7
PACKET_OVERHEAD = 11
MAX_PACKET_PAYLOAD = 0xFFFF
SEND_DATA_STRUCT_OVERHEAD = 12
DEFAULT_SEND_DATA_PAYLOAD = 512
DEFAULT_PACKET_INTERVAL_S = 0.010

OP_GET_INFO = 0x01
OP_CAN_UPDATE = 0x02
OP_ENTER_UPDATE = 0x03
OP_SEND_DATA = 0x04
OP_VERIFY_DATA = 0x05
OP_UPDATE_RESULT = 0x06

RESULT_OK = 0
RESULT_FAIL = 1

ASYNC_OK = 0
ASYNC_IN_PROGRESS = 1
ASYNC_FAIL = 2

CAN_UPDATE_RESULT_NAMES = {
    0: "OK",
    1: "BATTERY_LOW",
    2: "FIRMWARE_ERROR",
    3: "NO_MEM",
    4: "TIMEOUT",
    5: "BUSY",
    100: "UNKNOWN",
}

CAN_UPDATE_REASON_NAMES = {
    0: "NONE",
    1: "ALREADY_OTA",
    2: "CALLING",
    3: "CAPTURING",
    4: "RECORDING_VIDEO",
    5: "RECORDING_AUDIO",
    6: "AI_CHATTING",
    7: "MEDIA_SYNCING",
    8: "TRANSLATING",
    100: "UNKNOWN",
}


class OTAError(Exception):
    """Base OTA client error."""


class OTATimeoutError(OTAError):
    """The device did not reply within the expected window."""


class OTAStatusError(OTAError):
    """The device rejected or failed one OTA step."""


def crc32(data: bytes) -> int:
    """CRC32 compatible with firmware ``getcrc32()``."""
    return zlib.crc32(data) & 0xFFFFFFFF


def pack_packet(opcode: int, payload: bytes = b"") -> bytes:
    """Build one OTA packet."""
    if len(payload) > MAX_PACKET_PAYLOAD:
        raise ValueError("OTA payload too long: %d" % len(payload))
    return (
        struct.pack("<IBH", PACKET_PREFIX, opcode & 0xFF, len(payload))
        + payload
        + struct.pack("<I", PACKET_APPENDIX)
    )


@dataclass
class OTAPacket:
    opcode: int
    payload: bytes


class OTAPacketParser:
    """Incremental OTA packet parser."""

    MAX_BUFFER = 256 * 1024

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> List[OTAPacket]:
        self._buf.extend(data)
        packets: List[OTAPacket] = []
        buf = self._buf
        pos = 0

        while len(buf) - pos >= PACKET_OVERHEAD:
            prefix = struct.unpack_from("<I", buf, pos)[0]
            if prefix != PACKET_PREFIX:
                pos += 1
                continue

            payload_len = struct.unpack_from("<H", buf, pos + 5)[0]
            total_len = PACKET_OVERHEAD + payload_len
            if len(buf) - pos < total_len:
                break

            appendix = struct.unpack_from("<I", buf, pos + total_len - 4)[0]
            if appendix != PACKET_APPENDIX:
                pos += 1
                continue

            packets.append(OTAPacket(
                opcode=buf[pos + 4],
                payload=bytes(buf[pos + PACKET_HEADER_LEN:
                                  pos + PACKET_HEADER_LEN + payload_len]),
            ))
            pos += total_len

        if pos > 0:
            del buf[:pos]
        if len(buf) > self.MAX_BUFFER:
            del buf[:len(buf) - PACKET_OVERHEAD]
        return packets


@dataclass
class OTAModuleHeader:
    module_type: int
    start_offset: int
    length: int
    version: int
    crc: int


@dataclass
class OTAFirmwareImage:
    product_id: int
    version: int
    file_len: int
    modules: List[OTAModuleHeader]
    content_crc: int
    header_crc: int
    header_info: bytes
    data: bytes

    @classmethod
    def parse(cls, data: bytes) -> "OTAFirmwareImage":
        if len(data) < 72:
            raise ValueError("firmware image too short: %d" % len(data))
        product_id, version, file_len = struct.unpack_from("<QQI", data, 0)
        module_count = data[20]
        if module_count <= 0 or module_count >= 4:
            raise ValueError("invalid module_count: %d" % module_count)

        header_size = 32 + module_count * 32
        header_info_len = header_size + 8
        if len(data) < header_info_len:
            raise ValueError("firmware header truncated: want %d have %d"
                             % (header_info_len, len(data)))
        if file_len > len(data):
            raise ValueError("firmware file_len %d exceeds file size %d"
                             % (file_len, len(data)))

        modules: List[OTAModuleHeader] = []
        for i in range(module_count):
            off = 32 + i * 32
            module_type = data[off]
            start_offset = struct.unpack_from("<I", data, off + 1)[0]
            length = struct.unpack_from("<I", data, off + 5)[0]
            module_version = struct.unpack_from("<Q", data, off + 9)[0]
            module_crc = struct.unpack_from("<I", data, off + 17)[0]
            if module_type <= 0 or module_type >= 4:
                raise ValueError("invalid module type at index %d: %d"
                                 % (i, module_type))
            if start_offset + length > file_len:
                raise ValueError("module %d exceeds file_len: offset=%d len=%d file_len=%d"
                                 % (i, start_offset, length, file_len))
            modules.append(OTAModuleHeader(module_type, start_offset, length,
                                           module_version, module_crc))

        content_crc = struct.unpack_from("<I", data, header_size)[0]
        header_crc = struct.unpack_from("<I", data, header_size + 4)[0]
        calc_header_crc = crc32(data[:header_size + 4])
        if calc_header_crc != header_crc:
            raise ValueError("firmware header CRC mismatch: expected 0x%08X got 0x%08X"
                             % (header_crc, calc_header_crc))

        return cls(product_id=product_id, version=version, file_len=file_len,
                   modules=modules, content_crc=content_crc,
                   header_crc=header_crc, header_info=bytes(data[:header_info_len]),
                   data=bytes(data[:file_len]))


@dataclass
class OTADeviceModuleInfo:
    module_type: int
    version: int


@dataclass
class OTADeviceInfo:
    sn: int
    hw_version: int
    fw_version: int
    battery: int
    modules: List[OTADeviceModuleInfo]

    @classmethod
    def parse(cls, payload: bytes) -> "OTADeviceInfo":
        if len(payload) < 20:
            raise ValueError("GET_INFO response too short: %d" % len(payload))
        sn, hw_version, fw_version, battery, module_count = struct.unpack_from(
            "<HQQBB", payload, 0)
        expected_len = 20 + module_count * 9
        if len(payload) < expected_len:
            raise ValueError("GET_INFO module data truncated: want %d have %d"
                             % (expected_len, len(payload)))
        modules: List[OTADeviceModuleInfo] = []
        off = 20
        for _ in range(module_count):
            module_type = payload[off]
            module_version = struct.unpack_from("<Q", payload, off + 1)[0]
            modules.append(OTADeviceModuleInfo(module_type, module_version))
            off += 9
        return cls(sn, hw_version, fw_version, battery, modules)


@dataclass
class CanUpdateResponse:
    sn: int
    result: int
    reason: int

    @classmethod
    def parse(cls, payload: bytes) -> "CanUpdateResponse":
        if len(payload) < 4:
            raise ValueError("CAN_UPDATE response too short: %d" % len(payload))
        return cls(*struct.unpack_from("<HBB", payload, 0))

    @property
    def result_name(self) -> str:
        return CAN_UPDATE_RESULT_NAMES.get(self.result, "UNKNOWN(%d)" % self.result)

    @property
    def reason_name(self) -> str:
        return CAN_UPDATE_REASON_NAMES.get(self.reason, "UNKNOWN(%d)" % self.reason)


@dataclass
class BlockResponse:
    sn: int
    result: int
    offset: int
    length: int

    @classmethod
    def parse(cls, payload: bytes) -> "BlockResponse":
        if len(payload) < 11:
            raise ValueError("block response too short: %d" % len(payload))
        return cls(*struct.unpack_from("<HBII", payload, 0))


@dataclass
class AsyncResponse:
    sn: int
    result: int

    @classmethod
    def parse(cls, payload: bytes) -> "AsyncResponse":
        if len(payload) < 3:
            raise ValueError("async response too short: %d" % len(payload))
        return cls(*struct.unpack_from("<HB", payload, 0))


@dataclass
class UpdateResultResponse:
    sn: int
    result: int
    offset: int
    length: int
    reboot: int

    @classmethod
    def parse(cls, payload: bytes) -> "UpdateResultResponse":
        if len(payload) < 12:
            raise ValueError("UPDATE_RESULT response too short: %d" % len(payload))
        return cls(*struct.unpack_from("<HBIIB", payload, 0))


ProgressCallback = Callable[[str, int, int], None]


class OTAClient:
    """Synchronous OTA client over one 0x2026 SPP transport."""

    def __init__(self, transport: Transport,
                 pump: Optional[Callable[[float], None]] = None,
                 max_send_data_payload: int = DEFAULT_SEND_DATA_PAYLOAD,
                 packet_interval_s: float = DEFAULT_PACKET_INTERVAL_S) -> None:
        max_allowed = MAX_PACKET_PAYLOAD - SEND_DATA_STRUCT_OVERHEAD
        if max_send_data_payload <= 0 or max_send_data_payload > max_allowed:
            raise ValueError("invalid OTA SEND_DATA payload limit: %d"
                             % max_send_data_payload)
        if packet_interval_s < 0:
            raise ValueError("invalid OTA packet interval: %f"
                             % packet_interval_s)
        self._transport = transport
        self._pump = pump
        self._parser = OTAPacketParser()
        self._max_send_data_payload = max_send_data_payload
        self._packet_interval_s = packet_interval_s
        self._last_packet_time = 0.0
        self._sn = 0

    def open(self) -> None:
        self._transport.open()

    def close(self) -> None:
        self._transport.close()

    def _next_sn(self) -> int:
        self._sn = (self._sn + 1) & 0xFFFF
        if self._sn == 0:
            self._sn = 1
        return self._sn

    def _wait_packet_interval(self) -> None:
        if self._packet_interval_s <= 0 or self._last_packet_time <= 0:
            return
        remaining = self._packet_interval_s - (time.time() - self._last_packet_time)
        if remaining > 0:
            if self._pump is not None:
                self._pump(remaining)
            else:
                time.sleep(remaining)

    def _request(self, opcode: int, payload: bytes, timeout: float = 15.0,
                 expected_sn: Optional[int] = None,
                 throttle: bool = False) -> bytes:
        if throttle:
            self._wait_packet_interval()
        self._transport.write(pack_packet(opcode, payload))
        if throttle:
            self._last_packet_time = time.time()
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._pump is not None:
                self._pump(0.02)
            data = self._transport.read(4096)
            if not data:
                continue
            for packet in self._parser.feed(data):
                if packet.opcode != opcode:
                    continue
                if expected_sn is not None:
                    if len(packet.payload) < 2:
                        continue
                    pkt_sn = struct.unpack_from("<H", packet.payload, 0)[0]
                    if pkt_sn != expected_sn:
                        continue
                    return packet.payload
                return packet.payload
        raise OTATimeoutError("no OTA response for opcode 0x%02X within %.1fs"
                              % (opcode, timeout))

    def _read_response(self, opcode: int, timeout: float,
                       expected_sn_min: Optional[int] = None,
                       expected_sn_max: Optional[int] = None) -> bytes:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._pump is not None:
                self._pump(0.02)
            data = self._transport.read(4096)
            if not data:
                continue
            for packet in self._parser.feed(data):
                if packet.opcode != opcode:
                    continue
                if expected_sn_min is None:
                    return packet.payload
                if len(packet.payload) < 2:
                    continue
                pkt_sn = struct.unpack_from("<H", packet.payload, 0)[0]
                if expected_sn_max is None:
                    if pkt_sn == expected_sn_min:
                        return packet.payload
                elif expected_sn_min <= pkt_sn <= expected_sn_max:
                    return packet.payload
        raise OTATimeoutError("no OTA response for opcode 0x%02X within %.1fs"
                              % (opcode, timeout))

    def _write_send_data_packet(self, sn: int, offset: int, data: bytes) -> None:
        if len(data) > self._max_send_data_payload:
            raise ValueError("SEND_DATA payload exceeds limit: %d > %d"
                             % (len(data), self._max_send_data_payload))
        self._wait_packet_interval()
        payload = (
            struct.pack("<HIH", sn, offset, len(data))
            + data
            + struct.pack("<I", crc32(data))
        )
        self._transport.write(pack_packet(OP_SEND_DATA, payload))
        self._last_packet_time = time.time()

    def get_info(self, instant: bool = False,
                 timeout: float = 15.0) -> OTADeviceInfo:
        sn = self._next_sn()
        payload = struct.pack("<HB", sn, 1 if instant else 0)
        return OTADeviceInfo.parse(
            self._request(OP_GET_INFO, payload, timeout, expected_sn=sn))

    def can_update(self, image: OTAFirmwareImage,
                   timeout: float = 20.0) -> CanUpdateResponse:
        sn = self._next_sn()
        payload = struct.pack("<HH", sn, len(image.header_info)) + image.header_info
        return CanUpdateResponse.parse(
            self._request(OP_CAN_UPDATE, payload, timeout, expected_sn=sn))

    def enter_update(self, timeout: float = 20.0) -> BlockResponse:
        sn = self._next_sn()
        payload = struct.pack("<H", sn)
        return BlockResponse.parse(
            self._request(OP_ENTER_UPDATE, payload, timeout, expected_sn=sn))

    def send_data(self, offset: int, data: bytes,
                  timeout: float = 20.0) -> BlockResponse:
        sn = self._next_sn()
        self._write_send_data_packet(sn, offset, data)
        return BlockResponse.parse(
            self._read_response(OP_SEND_DATA, timeout, expected_sn_min=sn))

    def send_data_block(self, offset: int, data: bytes,
                        timeout: float = 20.0) -> BlockResponse:
        if not data:
            raise ValueError("empty SEND_DATA block")

        pos = 0
        first_sn = last_sn = self._next_sn()
        while pos < len(data):
            chunk = data[pos:pos + self._max_send_data_payload]
            if pos != 0:
                last_sn = self._next_sn()
            self._write_send_data_packet(last_sn, offset + pos, chunk)
            pos += len(chunk)

        return BlockResponse.parse(
            self._read_response(OP_SEND_DATA, timeout,
                                expected_sn_min=first_sn,
                                expected_sn_max=last_sn))

    def verify_data(self, timeout: float = 20.0) -> AsyncResponse:
        sn = self._next_sn()
        payload = struct.pack("<H", sn)
        return AsyncResponse.parse(
            self._request(OP_VERIFY_DATA, payload, timeout, expected_sn=sn))

    def update_result(self, timeout: float = 20.0) -> UpdateResultResponse:
        sn = self._next_sn()
        payload = struct.pack("<H", sn)
        return UpdateResultResponse.parse(
            self._request(OP_UPDATE_RESULT, payload, timeout, expected_sn=sn))

    def upgrade(self, firmware_path: Path, progress: Optional[ProgressCallback] = None,
                poll_interval_s: float = 1.0, poll_timeout_s: float = 90.0,
                block_retries: int = 3) -> UpdateResultResponse:
        image = OTAFirmwareImage.parse(Path(firmware_path).read_bytes())
        if progress:
            progress("info", 0, image.file_len)
        self.get_info()

        if progress:
            progress("can_update", 0, image.file_len)
        can = self.can_update(image)
        if can.result != 0:
            raise OTAStatusError("CAN_UPDATE failed: result=%s reason=%s"
                                 % (can.result_name, can.reason_name))

        block = self.enter_update()
        if block.result != RESULT_OK:
            raise OTAStatusError("ENTER_UPDATE failed: result=%d" % block.result)

        while True:
            while block.offset != 0 or block.length != 0:
                if block.offset + block.length > image.file_len:
                    raise OTAError("device requested invalid block: offset=%d len=%d file_len=%d"
                                   % (block.offset, block.length, image.file_len))
                chunk = image.data[block.offset:block.offset + block.length]
                if len(chunk) != block.length:
                    raise OTAError("short firmware block: offset=%d len=%d have=%d"
                                   % (block.offset, block.length, len(chunk)))
                last_error: Optional[Exception] = None
                for _ in range(block_retries):
                    try:
                        next_block = self.send_data_block(block.offset, chunk)
                        if next_block.result == RESULT_OK:
                            block = next_block
                            if progress:
                                sent = block.offset if block.offset else image.file_len
                                progress("data", min(sent, image.file_len), image.file_len)
                            last_error = None
                            break
                        last_error = OTAStatusError(
                            "SEND_DATA rejected block offset=%d len=%d result=%d"
                            % (block.offset, block.length, next_block.result))
                    except OTATimeoutError as exc:
                        last_error = exc
                if last_error is not None:
                    raise last_error

            self._poll_verify(poll_interval_s, poll_timeout_s)
            result = self._poll_update_result(poll_interval_s, poll_timeout_s)
            if result.offset == 0 and result.length == 0:
                if progress:
                    progress("done", image.file_len, image.file_len)
                return result
            block = BlockResponse(result.sn, RESULT_OK, result.offset, result.length)

    def _poll_verify(self, interval_s: float, timeout_s: float) -> None:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            result = self.verify_data()
            if result.result == ASYNC_OK:
                return
            if result.result == ASYNC_FAIL:
                raise OTAStatusError("VERIFY_DATA failed")
            time.sleep(interval_s)
        raise OTATimeoutError("VERIFY_DATA still in progress after %.1fs" % timeout_s)

    def _poll_update_result(self, interval_s: float,
                            timeout_s: float) -> UpdateResultResponse:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            result = self.update_result()
            if result.result == ASYNC_OK:
                return result
            if result.result == ASYNC_FAIL:
                raise OTAStatusError("UPDATE_RESULT failed")
            time.sleep(interval_s)
        raise OTATimeoutError("UPDATE_RESULT still in progress after %.1fs" % timeout_s)
