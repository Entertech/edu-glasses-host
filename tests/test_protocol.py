"""Pure-Python unit tests for the edu_host protocol stack.

Run from the edu_host/ directory with either:

    python -m unittest discover -s tests -v
    python -m pytest tests -v

No hardware, pyserial or opuslib required.
"""

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))

from edu_host.crc16 import crc16
from edu_host import protocol
from edu_host.protocol import (AIR_IMG_BODY, AIR_IMG_DATA_TYPE_IMAGE,
                               AIR_IMG_HEAD, AIR_IMG_TAIL, FORMAT_JPEG,
                               AirImgStreamParser, FrameParser, FrameType,
                               HelloAck, ImageReassembler, SensorData,
                               DeviceInfo, encode_frame, parse_event,
                               version_to_string)
from edu_host.audio_client import (PKG_HDR, PKG_LEN_EXTRA, PKG_TAG,
                                   RecordStreamParser)


class TestCrc16(unittest.TestCase):
    """The firmware CRC is CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF)."""

    def test_empty(self):
        self.assertEqual(crc16(b""), 0xFFFF)

    def test_single_zero_byte_hand_computed(self):
        # Hand trace of the firmware loop for one 0x00 byte:
        #   crc = 0xFFFF -> swap -> 0xFFFF -> ^0x00 -> 0xFFFF
        #   ^ (0xFF >> 4 = 0x0F)      -> 0xFFF0
        #   ^ (0xFFF0 << 12 = 0x0000) -> 0xFFF0
        #   ^ (0xF0 << 5 = 0x1E00)    -> 0xE1F0
        self.assertEqual(crc16(b"\x00"), 0xE1F0)

    def test_known_ccitt_false_vectors(self):
        self.assertEqual(crc16(b"A"), 0xB915)
        self.assertEqual(crc16(b"123456789"), 0x29B1)

    def test_hello_frame_body(self):
        # ver=1 type=HELLO seq=0 len=1 payload=[0x01]
        body = bytes([1, 0x01, 0x00, 0x01, 0x00, 0x01])
        self.assertEqual(crc16(body), 0xC6F0)


class TestFrameCodec(unittest.TestCase):
    def test_encode_hello_golden_bytes(self):
        frame = encode_frame(FrameType.HELLO, 0, b"\x01")
        #        sync     ver  type seq  len(LE)  payload  crc(LE)
        expected = bytes([0xA5, 0x5A, 0x01, 0x01, 0x00, 0x01, 0x00, 0x01,
                          0xF0, 0xC6])
        self.assertEqual(frame, expected)

    def test_roundtrip_all_types(self):
        parser = FrameParser()
        for ftype in (FrameType.HELLO, FrameType.HELLO_ACK, FrameType.CMD,
                      FrameType.RSP, FrameType.EVT):
            payload = bytes(range(ftype % 7 + 1))
            frames = parser.feed(encode_frame(ftype, 0x42, payload))
            self.assertEqual(len(frames), 1)
            self.assertEqual(frames[0].type, ftype)
            self.assertEqual(frames[0].seq, 0x42)
            self.assertEqual(frames[0].payload, payload)

    def test_empty_payload(self):
        frames = FrameParser().feed(encode_frame(FrameType.CMD, 7, b""))
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].payload, b"")

    def test_max_payload(self):
        payload = bytes(i & 0xFF for i in range(protocol.MAX_PAYLOAD))
        frames = FrameParser().feed(encode_frame(FrameType.EVT, 1, payload))
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].payload, payload)

    def test_oversized_payload_rejected(self):
        with self.assertRaises(ValueError):
            encode_frame(FrameType.EVT, 0, b"x" * (protocol.MAX_PAYLOAD + 1))


class TestFrameParserResync(unittest.TestCase):
    def test_garbage_around_frames(self):
        parser = FrameParser()
        good = encode_frame(FrameType.EVT, 3, b"\x01\x00\x06")
        stream = b"\x00\xA5\xFF junk" + good + b"\x5A\xA5" + good
        frames = parser.feed(stream)
        self.assertEqual(len(frames), 2)
        for f in frames:
            self.assertEqual(f.payload, b"\x01\x00\x06")

    def test_byte_by_byte_feed(self):
        parser = FrameParser()
        good = encode_frame(FrameType.RSP, 9, b"\x05\x00" + b"\xAB" * 10)
        collected = []
        for i in range(len(good)):
            collected += parser.feed(good[i:i + 1])
        self.assertEqual(len(collected), 1)
        self.assertEqual(collected[0].seq, 9)

    def test_corrupted_crc_then_good_frame(self):
        parser = FrameParser()
        bad = bytearray(encode_frame(FrameType.EVT, 1, b"\x02\x01\x05\x00\x00\x00"))
        bad[-1] ^= 0xFF  # corrupt CRC
        good = encode_frame(FrameType.EVT, 2, b"\x03\x01\x00\x00")
        frames = parser.feed(bytes(bad) + good)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].seq, 2)

    def test_bad_length_field_resync(self):
        parser = FrameParser()
        # sync + insane length; firmware skips 2 bytes and rescans
        junk = bytes([0xA5, 0x5A, 0x01, 0x10, 0x00, 0xFF, 0xFF])
        good = encode_frame(FrameType.HELLO_ACK, 0,
                            struct.pack("<BQH", 1, 0x0001020300040005, 0x000F))
        frames = parser.feed(junk + good)
        self.assertEqual(len(frames), 1)
        ack = HelloAck.parse(frames[0].payload)
        self.assertEqual(ack.fw_version_str, "1.2.3-4+5")
        self.assertEqual(sorted(ack.cap_names),
                         ["AUDIO_STREAM", "INPUT_EVENTS", "PHOTO", "SENSORS"])

    def test_sync_inside_payload_no_confusion(self):
        # payload containing the sync pattern must not derail the parser
        parser = FrameParser()
        payload = b"\xA5\x5A\xA5\x5A\x00\x01"
        f1 = encode_frame(FrameType.EVT, 0, payload)
        f2 = encode_frame(FrameType.EVT, 1, payload)
        frames = parser.feed(f1 + f2)
        self.assertEqual([f.seq for f in frames], [0, 1])
        self.assertEqual(frames[0].payload, payload)


class TestPayloadParsing(unittest.TestCase):
    def test_sensor_data_negative_temps(self):
        # als=0x0123, battery=-5 degC, btcore=-300 -> i16
        data = struct.pack("<Hbh", 0x0123, -5, -300)
        s = SensorData.parse(data)
        self.assertEqual(s.als_raw, 0x0123)
        self.assertEqual(s.battery_temp_c, -5)
        self.assertEqual(s.btcore_temp_c, -300)

    def test_device_info(self):
        data = struct.pack("<QBB", 0x0001020300000005, 87, 1)
        info = DeviceInfo.parse(data)
        self.assertEqual(info.fw_version_str, "1.2.3+5")
        self.assertEqual(info.battery_level, 87)
        self.assertTrue(info.charging)

    def test_version_string_variants(self):
        self.assertEqual(version_to_string(0x0001020300040005), "1.2.3-4+5")
        self.assertEqual(version_to_string(0x0001020300000005), "1.2.3+5")
        self.assertEqual(version_to_string(0x0001020300040000), "1.2.3-4")
        self.assertEqual(version_to_string(0x0001020300000000), "1.2.3")

    def test_button_event(self):
        evt = parse_event(bytes([0x01, 1, 7]))
        self.assertEqual(evt.btn_name, "CAPTURE")
        self.assertEqual(evt.action_name, "LONG")

    def test_knob_event_numeric_order(self):
        # firmware: RIGHT=1, LEFT=2 (order swapped vs intuition!)
        evt = parse_event(bytes([0x02]) + struct.pack("<Bhh", 2, -10, 300))
        self.assertEqual(evt.direction_name, "LEFT")
        self.assertEqual(evt.delta_x, -10)
        self.assertEqual(evt.delta_y, 300)

    def test_audio_state_event(self):
        evt = parse_event(bytes([0x03, 1, 1, 0]))
        self.assertTrue(evt.running)
        self.assertEqual(evt.source_name, "CALL")

    def test_img_state_event(self):
        evt = parse_event(bytes([0x04, 1, 0]))
        self.assertEqual(evt.capture_evt_name, "DONE")

    def test_unknown_event_kept_raw(self):
        evt = parse_event(bytes([0x7F, 1, 2, 3]))
        self.assertEqual(evt.evt_id, 0x7F)
        self.assertEqual(evt.data, b"\x01\x02\x03")


def make_head(group, fmt=FORMAT_JPEG, seq=0):
    return bytes([AIR_IMG_HEAD, AIR_IMG_DATA_TYPE_IMAGE, group]) + \
        struct.pack("<I", seq) + bytes([fmt])


def make_body(group, seq, data):
    return bytes([AIR_IMG_BODY, AIR_IMG_DATA_TYPE_IMAGE, group]) + \
        struct.pack("<I", seq) + struct.pack("<H", len(data)) + data


def make_tail(group, seq):
    # The on-wire tail is exactly 7 bytes — no data_length / end_marker.
    return bytes([AIR_IMG_TAIL, AIR_IMG_DATA_TYPE_IMAGE, group]) + \
        struct.pack("<I", seq)


class TestAirImgStreamParser(unittest.TestCase):
    """The 0x2025 channel is a raw byte stream: sub-frames may split/merge."""

    def _stream(self, group=3, chunk=32):
        jpeg = b"\xFF\xD8" + b"stream-data" * 30 + b"\xFF\xD9"
        chunks = [jpeg[i:i + chunk] for i in range(0, len(jpeg), chunk)]
        frames = [make_head(group)]
        frames += [make_body(group, 1 + i, c) for i, c in enumerate(chunks)]
        frames.append(make_tail(group, 1 + len(chunks)))
        return b"".join(frames), len(frames)

    def test_single_feed(self):
        raw, n = self._stream()
        subs = AirImgStreamParser().feed(raw)
        self.assertEqual(len(subs), n)
        self.assertEqual(subs[0].frame_type, AIR_IMG_HEAD)
        self.assertEqual(subs[-1].frame_type, AIR_IMG_TAIL)

    def test_awkward_read_boundaries(self):
        raw, n = self._stream()
        parser = AirImgStreamParser()
        subs = []
        for i in range(0, len(raw), 5):
            subs += parser.feed(raw[i:i + 5])
        self.assertEqual(len(subs), n)

    def test_resync_on_garbage_prefix(self):
        raw, n = self._stream()
        subs = AirImgStreamParser().feed(b"\x00\xFF\x01\x99" + raw)
        self.assertEqual(len(subs), n)

    def test_end_to_end_with_reassembler(self):
        raw, _ = self._stream(group=7)
        parser = AirImgStreamParser()
        r = ImageReassembler()
        image = None
        for i in range(0, len(raw), 11):
            for sub in parser.feed(raw[i:i + 11]):
                got = r.feed_subframe(sub)
                if got is not None:
                    image = got
        self.assertIsNotNone(image)
        self.assertEqual(image.group_id, 7)
        self.assertTrue(image.data.startswith(b"\xFF\xD8"))
        self.assertTrue(image.data.endswith(b"\xFF\xD9"))


class TestImageReassembly(unittest.TestCase):
    JPEG = b"\xFF\xD8" + b"image-data" * 20 + b"\xFF\xD9"

    def _frames(self, group=1, chunk=32):
        chunks = [self.JPEG[i:i + chunk] for i in range(0, len(self.JPEG), chunk)]
        frames = [make_head(group)]
        for i, c in enumerate(chunks):
            frames.append(make_body(group, 1 + i, c))
        frames.append(make_tail(group, 1 + len(chunks)))
        return frames

    def test_happy_path(self):
        r = ImageReassembler()
        result = None
        for frame in self._frames():
            result = r.feed(frame)
        self.assertIsNotNone(result)
        self.assertEqual(result.data, self.JPEG)
        self.assertEqual(result.group_id, 1)
        self.assertEqual(result.img_format, FORMAT_JPEG)
        self.assertEqual(r.images_completed, 1)
        self.assertEqual(r.images_dropped, 0)

    def test_lost_body_detected_and_dropped(self):
        r = ImageReassembler()
        frames = self._frames()
        del frames[2]  # drop one BODY -> sequence gap
        results = [r.feed(f) for f in frames]
        self.assertTrue(all(res is None for res in results))
        self.assertEqual(r.images_completed, 0)
        self.assertEqual(r.images_dropped, 1)
        self.assertIn("frame lost", r.last_error)

    def test_new_head_resets_partial_image(self):
        r = ImageReassembler()
        partial = self._frames(group=1)[:3]      # HEAD + 2 BODYs, no TAIL
        for f in partial:
            self.assertIsNone(r.feed(f))
        result = None
        for f in self._frames(group=2):          # full second image
            result = r.feed(f)
        self.assertIsNotNone(result)
        self.assertEqual(result.group_id, 2)
        self.assertEqual(result.data, self.JPEG)
        self.assertEqual(r.images_dropped, 1)

    def test_tail_after_broken_stream_ignored(self):
        r = ImageReassembler()
        self.assertIsNone(r.feed(make_tail(1, 5)))  # tail without head
        self.assertEqual(r.images_completed, 0)


def make_package(sn=8, sections=8, cmd=2, reserved=0, frame_size=40):
    frames = [bytes([(sn + i) & 0xFF]) * frame_size for i in range(sections)]
    section_area = b"".join(bytes([len(f)]) + f for f in frames)
    hdr = PKG_HDR.pack(PKG_TAG, cmd, len(section_area) + PKG_LEN_EXTRA, sn,
                       sections, reserved)
    return hdr + section_area, frames


class TestRecordStreamParser(unittest.TestCase):
    def test_single_package(self):
        raw, frames = make_package()
        pkgs = RecordStreamParser().feed(raw)
        self.assertEqual(len(pkgs), 1)
        self.assertEqual(pkgs[0].sn, 8)
        self.assertEqual(pkgs[0].sections, 8)
        self.assertEqual(pkgs[0].frames, frames)

    def test_partial_reads(self):
        raw, frames = make_package(sn=16)
        parser = RecordStreamParser()
        pkgs = []
        for i in range(0, len(raw), 7):  # awkward chunk size on purpose
            pkgs += parser.feed(raw[i:i + 7])
        self.assertEqual(len(pkgs), 1)
        self.assertEqual(pkgs[0].frames, frames)

    def test_resync_on_junk(self):
        raw, frames = make_package(sn=24)
        junk = b"\x52\x00\xFF\xFF" + b"\x99" * 5  # fake tag + garbage
        pkgs = RecordStreamParser().feed(junk + raw)
        self.assertEqual(len(pkgs), 1)
        self.assertEqual(pkgs[0].sn, 24)

    def test_tag_byte_inside_frame_data(self):
        # 0x52 appearing inside audio data must not break parsing
        raw1, _ = make_package(sn=8, frame_size=0x52)
        raw2, _ = make_package(sn=16, frame_size=0x52)
        parser = RecordStreamParser()
        pkgs = parser.feed(raw1 + raw2)
        self.assertEqual([p.sn for p in pkgs], [8, 16])

    def test_len_field_consistency_enforced(self):
        raw, _ = make_package()
        bad = bytearray(raw)
        bad[2] += 1  # header len no longer matches the section walk
        parser = RecordStreamParser()
        pkgs = parser.feed(bytes(bad))
        # depending on trailing bytes the bad package may simply be skipped;
        # a following good package must still be found
        pkgs += parser.feed(raw)
        self.assertEqual(pkgs[-1].sn, 8)
        self.assertEqual(len(pkgs[-1].frames), 8)


if __name__ == "__main__":
    unittest.main()
