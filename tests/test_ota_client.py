"""Unit tests for the OTA SPP host client."""

import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))

from edu_host.ota_client import (ASYNC_OK, OP_CAN_UPDATE, OP_ENTER_UPDATE,
                                 OP_GET_INFO, OP_SEND_DATA, OP_UPDATE_RESULT,
                                 OP_VERIFY_DATA, OTAClient, OTAFirmwareImage,
                                 OTAPacketParser, PACKET_APPENDIX,
                                 PACKET_PREFIX, RESULT_OK, crc32,
                                 pack_packet)


def build_test_firmware(module_len=37):
    module = bytes((i * 7 + 3) & 0xFF for i in range(module_len))
    header_info_len = 32 + 32 + 8
    file_len = header_info_len + len(module)

    fw_header = bytearray(32)
    struct.pack_into("<QQI", fw_header, 0, 0x1122334455667788,
                     0x0001020300040005, file_len)
    fw_header[20] = 1

    module_header = bytearray(32)
    module_header[0] = 1
    struct.pack_into("<I", module_header, 1, header_info_len)
    struct.pack_into("<I", module_header, 5, len(module))
    struct.pack_into("<Q", module_header, 9, 0x0001020300000006)
    struct.pack_into("<I", module_header, 17, crc32(module))

    prefix = bytes(fw_header) + bytes(module_header)
    content_crc = crc32(module)
    header_crc = crc32(prefix + struct.pack("<I", content_crc))
    return prefix + struct.pack("<II", content_crc, header_crc) + module, module


class TestOTAPacketCodec(unittest.TestCase):
    def test_pack_packet_golden_shape(self):
        pkt = pack_packet(OP_GET_INFO, b"\x34\x12")
        self.assertEqual(struct.unpack_from("<I", pkt, 0)[0], PACKET_PREFIX)
        self.assertEqual(pkt[4], OP_GET_INFO)
        self.assertEqual(struct.unpack_from("<H", pkt, 5)[0], 2)
        self.assertEqual(pkt[7:9], b"\x34\x12")
        self.assertEqual(struct.unpack_from("<I", pkt, len(pkt) - 4)[0],
                         PACKET_APPENDIX)

    def test_parser_resync_and_split_reads(self):
        raw = b"\x00bad" + pack_packet(OP_CAN_UPDATE, b"abc")
        parser = OTAPacketParser()
        packets = []
        for i in range(len(raw)):
            packets += parser.feed(raw[i:i + 1])
        self.assertEqual(len(packets), 1)
        self.assertEqual(packets[0].opcode, OP_CAN_UPDATE)
        self.assertEqual(packets[0].payload, b"abc")


class TestOTAFirmwareImage(unittest.TestCase):
    def test_parse_valid_firmware_header(self):
        fw, module = build_test_firmware()
        image = OTAFirmwareImage.parse(fw)
        self.assertEqual(image.product_id, 0x1122334455667788)
        self.assertEqual(image.version, 0x0001020300040005)
        self.assertEqual(image.file_len, len(fw))
        self.assertEqual(len(image.modules), 1)
        self.assertEqual(image.modules[0].module_type, 1)
        self.assertEqual(image.modules[0].start_offset, len(image.header_info))
        self.assertEqual(image.modules[0].length, len(module))

    def test_rejects_bad_header_crc(self):
        fw, _ = build_test_firmware()
        bad = bytearray(fw)
        bad[10] ^= 0x01
        with self.assertRaises(ValueError):
            OTAFirmwareImage.parse(bytes(bad))


class FakeOTATransport:
    def __init__(self, firmware: bytes, device_block_len: int = 11) -> None:
        self._parser = OTAPacketParser()
        self._rx = bytearray()
        self._open = False
        self._firmware = OTAFirmwareImage.parse(firmware)
        self._device_block_len = device_block_len
        self._target_offset = 0
        self.received = bytearray()
        self.send_chunks = []

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    def read(self, max_bytes=4096) -> bytes:
        if not self._rx:
            return b""
        n = min(max_bytes, len(self._rx), 7)
        out = bytes(self._rx[:n])
        del self._rx[:n]
        return out

    def write(self, data: bytes) -> None:
        for pkt in self._parser.feed(data):
            self._handle(pkt.opcode, pkt.payload)

    @property
    def is_open(self) -> bool:
        return self._open

    def _queue(self, opcode: int, payload: bytes) -> None:
        self._rx.extend(pack_packet(opcode, payload))

    def _handle(self, opcode: int, payload: bytes) -> None:
        sn = struct.unpack_from("<H", payload, 0)[0]
        if opcode == OP_GET_INFO:
            self._queue(opcode, struct.pack("<HQQBB", sn, 1, 2, 88, 1)
                        + struct.pack("<BQ", 1, 2))
        elif opcode == OP_CAN_UPDATE:
            self._queue(opcode, struct.pack("<HBB", sn, 0, 0))
        elif opcode == OP_ENTER_UPDATE:
            first_len = min(self._device_block_len,
                            self._firmware.file_len -
                            len(self._firmware.header_info))
            self._target_offset = len(self._firmware.header_info) + first_len
            self._queue(opcode, struct.pack("<HBII", sn, RESULT_OK,
                                            len(self._firmware.header_info),
                                            first_len))
        elif opcode == OP_SEND_DATA:
            offset, data_len = struct.unpack_from("<IH", payload, 2)
            block = payload[8:8 + data_len]
            block_crc = struct.unpack_from("<I", payload, 8 + data_len)[0]
            self.assert_crc(block, block_crc)
            self.received.extend(block)
            self.send_chunks.append((offset, data_len))
            next_offset = offset + data_len
            if next_offset < self._target_offset and next_offset < self._firmware.file_len:
                return
            if next_offset >= self._firmware.file_len:
                next_offset = 0
                next_len = 0
            else:
                next_len = min(self._device_block_len,
                               self._firmware.file_len - next_offset)
                self._target_offset = next_offset + next_len
            self._queue(opcode, struct.pack("<HBII", sn, RESULT_OK,
                                            next_offset, next_len))
        elif opcode == OP_VERIFY_DATA:
            self._queue(opcode, struct.pack("<HB", sn, ASYNC_OK))
        elif opcode == OP_UPDATE_RESULT:
            self._queue(opcode, struct.pack("<HBIIB", sn, ASYNC_OK, 0, 0, 1))

    @staticmethod
    def assert_crc(block: bytes, expected: int) -> None:
        if crc32(block) != expected:
            raise AssertionError("bad block crc")


class TestOTAClientUpgrade(unittest.TestCase):
    def test_upgrade_happy_path(self):
        fw, module = build_test_firmware()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "fw.bin"
            path.write_bytes(fw)
            fake = FakeOTATransport(fw)
            client = OTAClient(fake)
            client.open()
            result = client.upgrade(path, poll_interval_s=0.0)
            client.close()
        self.assertEqual(result.reboot, 1)
        self.assertEqual(bytes(fake.received), module)

    def test_upgrade_splits_large_device_blocks(self):
        fw, module = build_test_firmware(module_len=1500)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "fw.bin"
            path.write_bytes(fw)
            fake = FakeOTATransport(fw, device_block_len=1500)
            client = OTAClient(fake, max_send_data_payload=600,
                               packet_interval_s=0.0)
            client.open()
            result = client.upgrade(path, poll_interval_s=0.0)
            client.close()
        self.assertEqual(result.reboot, 1)
        self.assertEqual(bytes(fake.received), module)
        self.assertEqual([size for _, size in fake.send_chunks],
                         [600, 600, 300])
        self.assertTrue(all(size <= 600 for _, size in fake.send_chunks))


if __name__ == "__main__":
    unittest.main()
