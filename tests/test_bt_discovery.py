"""bt_discovery 纯解析函数的单测（无需硬件/平台）。"""

import unittest

from edu_host.bt_discovery import (DEFAULT_NAME_PREFIX, _format_address,
                                   decode_registry_name,
                                   parse_bluetoothctl_devices, pick_by_prefix)


class TestFormatAddress(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(_format_address("8caab5112233"), "8C:AA:B5:11:22:33")

    def test_uppercase_input(self):
        self.assertEqual(_format_address("8CAAB5112233"), "8C:AA:B5:11:22:33")

    def test_rejects_bad_length_and_nonhex(self):
        self.assertIsNone(_format_address("849d4baa0d"))
        self.assertIsNone(_format_address("zz9d4baa0d05"))
        self.assertIsNone(_format_address("LocalServices"))  # 注册表杂项子键


class TestRegistryName(unittest.TestCase):
    def test_null_terminated(self):
        self.assertEqual(decode_registry_name(b"EDU-Glasses-0001\x00"),
                         "EDU-Glasses-0001")

    def test_plain(self):
        self.assertEqual(decode_registry_name(b"EDU-Glasses-0001"),
                         "EDU-Glasses-0001")

    def test_invalid_utf8_does_not_raise(self):
        self.assertTrue(decode_registry_name(b"\xff\xfeX"))


class TestBluetoothctlParse(unittest.TestCase):
    OUTPUT = """\
Device 8C:AA:B5:11:22:33 EDU-Glasses-0001
Device 11:22:33:44:55:66 Keyboard K380
not a device line
Device AA:BB:CC:DD:EE:FF Name With Spaces
"""

    def test_parse(self):
        devices = parse_bluetoothctl_devices(self.OUTPUT)
        self.assertEqual(devices[0], ("8C:AA:B5:11:22:33", "EDU-Glasses-0001"))
        self.assertEqual(devices[2], ("AA:BB:CC:DD:EE:FF", "Name With Spaces"))
        self.assertEqual(len(devices), 3)

    def test_pick_by_prefix(self):
        devices = parse_bluetoothctl_devices(self.OUTPUT)
        picked = pick_by_prefix(devices, DEFAULT_NAME_PREFIX)
        self.assertEqual(picked, ("8C:AA:B5:11:22:33", "EDU-Glasses-0001"))

    def test_pick_none(self):
        self.assertIsNone(pick_by_prefix([("11:22:33:44:55:66", "Mouse")],
                                         DEFAULT_NAME_PREFIX))

    def test_empty_output(self):
        self.assertEqual(parse_bluetoothctl_devices(""), [])


if __name__ == "__main__":
    unittest.main()
