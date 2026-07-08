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


class TestSplitCommand(unittest.TestCase):
    """demo_cli.split_command 必须保留 Windows 反斜杠路径（shlex posix 会吃掉）。"""

    def setUp(self):
        import importlib
        self.demo_cli = importlib.import_module("demo_cli")

    def test_windows_absolute_path_preserved(self):
        got = self.demo_cli.split_command(r"photo F:\Codes\wintest.jpg")
        self.assertEqual(got, ["photo", r"F:\Codes\wintest.jpg"])

    def test_quoted_path_with_space(self):
        got = self.demo_cli.split_command('photo "C:\\a b\\x.jpg"')
        self.assertEqual(got, ["photo", r"C:\a b\x.jpg"])

    def test_plain_tokens(self):
        self.assertEqual(self.demo_cli.split_command("led inner blink green fast"),
                         ["led", "inner", "blink", "green", "fast"])


class TestAmbiguityAndConnected(unittest.TestCase):
    """已连接优先 + 多台匹配报歧义（bt_discovery 的连接状态过滤）。"""

    def setUp(self):
        import edu_host.bt_discovery as bd
        self.bd = bd

    def test_ambiguous_error_lists_all(self):
        from edu_host.bt_discovery import AmbiguousGlassesError
        matches = [("8C:AA:B5:11:11:11", "EDU-Glasses-0001"),
                   ("8C:AA:B5:66:66:66", "EDU-Glasses-0066")]
        err = AmbiguousGlassesError(matches)
        self.assertIn("EDU-Glasses-0001", str(err))
        self.assertIn("EDU-Glasses-0066", str(err))
        self.assertEqual(err.matches, matches)

    def test_connected_preferred_over_paired(self):
        # Linux 路径：已连接列表命中即返回，不看已配对的其它设备
        bd = self.bd
        orig_plat = bd.sys.platform
        orig_conn = bd._connected_devices_linux
        orig_paired = bd._paired_devices_linux
        try:
            bd.sys.platform = "linux"
            bd._connected_devices_linux = lambda: [
                ("8C:AA:B5:66:66:66", "EDU-Glasses-0066")]
            bd._paired_devices_linux = lambda: [
                ("8C:AA:B5:11:11:11", "EDU-Glasses-0001"),
                ("8C:AA:B5:66:66:66", "EDU-Glasses-0066")]
            got = bd.find_paired_device()
            self.assertEqual(got, ("8C:AA:B5:66:66:66", "EDU-Glasses-0066"))
        finally:
            bd.sys.platform = orig_plat
            bd._connected_devices_linux = orig_conn
            bd._paired_devices_linux = orig_paired

    def test_multiple_paired_none_connected_raises(self):
        from edu_host.bt_discovery import AmbiguousGlassesError
        bd = self.bd
        orig_plat = bd.sys.platform
        orig_conn = bd._connected_devices_linux
        orig_paired = bd._paired_devices_linux
        try:
            bd.sys.platform = "linux"
            bd._connected_devices_linux = lambda: []
            bd._paired_devices_linux = lambda: [
                ("8C:AA:B5:11:11:11", "EDU-Glasses-0001"),
                ("8C:AA:B5:66:66:66", "EDU-Glasses-0066")]
            with self.assertRaises(AmbiguousGlassesError):
                bd.find_paired_device()
        finally:
            bd.sys.platform = orig_plat
            bd._connected_devices_linux = orig_conn
            bd._paired_devices_linux = orig_paired

    def test_single_paired_returned(self):
        bd = self.bd
        orig_plat = bd.sys.platform
        orig_conn = bd._connected_devices_linux
        orig_paired = bd._paired_devices_linux
        try:
            bd.sys.platform = "linux"
            bd._connected_devices_linux = lambda: []
            bd._paired_devices_linux = lambda: [
                ("8C:AA:B5:66:66:66", "EDU-Glasses-0066")]
            self.assertEqual(bd.find_paired_device(),
                             ("8C:AA:B5:66:66:66", "EDU-Glasses-0066"))
        finally:
            bd.sys.platform = orig_plat
            bd._connected_devices_linux = orig_conn
            bd._paired_devices_linux = orig_paired
