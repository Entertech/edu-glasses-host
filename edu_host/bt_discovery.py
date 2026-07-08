"""按名字前缀查找已配对的眼镜（Windows / Linux，零第三方依赖）。

macOS 走 :mod:`edu_host.mac_bt`（IOBluetooth 自带 pairedDevices）；本模块
补齐另外两个平台，让 ``--bt auto`` 三平台可用：

* **Windows**：已配对经典蓝牙设备记录在注册表
  ``HKLM\\SYSTEM\\CurrentControlSet\\Services\\BTHPORT\\Parameters\\Devices``
  之下——子键名是设备地址（12 位十六进制），``Name`` 值是设备名字节串。
  用标准库 ``winreg`` 读取。
* **Linux**：问 BlueZ 的 ``bluetoothctl``（新版 ``devices Paired``，老版
  ``paired-devices``），解析 ``Device AA:BB:CC:DD:EE:FF 名字`` 行。

两者都只能看到**已配对**的设备——auto 不做射频扫描，先在系统蓝牙里配对。
"""

from __future__ import annotations

import subprocess
import sys
from typing import List, Optional, Tuple

DEFAULT_NAME_PREFIX = "EDU-"

#: (address "AA:BB:CC:DD:EE:FF", device name)
PairedDevice = Tuple[str, str]


# -- 纯解析函数（可无平台单测） ------------------------------------------

def _format_address(hex12: str) -> Optional[str]:
    """"8caab5112233" -> "8C:AA:B5:11:22:33"；非 12 位十六进制返回 None。"""
    hex12 = hex12.strip().lower()
    if len(hex12) != 12:
        return None
    try:
        int(hex12, 16)
    except ValueError:
        return None
    return ":".join(hex12[i:i + 2] for i in range(0, 12, 2)).upper()


def decode_registry_name(raw: bytes) -> str:
    """Windows 注册表 Name 值（REG_BINARY 字节串，可能含结尾 NUL）→ 设备名。"""
    return raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")


def parse_bluetoothctl_devices(output: str) -> List[PairedDevice]:
    """解析 ``bluetoothctl devices [Paired]`` 输出的 ``Device <addr> <name>`` 行。"""
    found: List[PairedDevice] = []
    for line in output.splitlines():
        parts = line.strip().split(" ", 2)
        if len(parts) == 3 and parts[0] == "Device":
            addr = _format_address(parts[1].replace(":", ""))
            if addr:
                found.append((addr, parts[2]))
    return found


def pick_by_prefix(devices: List[PairedDevice],
                   name_prefix: str) -> Optional[PairedDevice]:
    for addr, name in devices:
        if name.startswith(name_prefix):
            return addr, name
    return None


# -- 平台封装 --------------------------------------------------------------

def _paired_devices_windows() -> List[PairedDevice]:
    import winreg  # 仅 Windows 存在

    devices: List[PairedDevice] = []
    key_path = r"SYSTEM\CurrentControlSet\Services\BTHPORT\Parameters\Devices"
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path)
    except OSError:
        return devices
    try:
        index = 0
        while True:
            try:
                sub = winreg.EnumKey(root, index)
            except OSError:
                break
            index += 1
            addr = _format_address(sub)
            if addr is None:
                continue
            try:
                with winreg.OpenKey(root, sub) as dev_key:
                    raw, _kind = winreg.QueryValueEx(dev_key, "Name")
            except OSError:
                continue
            if isinstance(raw, str):
                name = raw
            else:
                name = decode_registry_name(bytes(raw))
            if name:
                devices.append((addr, name))
    finally:
        root.Close()
    return devices


def _paired_devices_linux() -> List[PairedDevice]:
    for cmd in (["bluetoothctl", "devices", "Paired"],
                ["bluetoothctl", "paired-devices"]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True,
                                 timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return []
        devices = parse_bluetoothctl_devices(out.stdout)
        if devices or out.returncode == 0:
            return devices
    return []


def find_paired_device(name_prefix: str = DEFAULT_NAME_PREFIX
                       ) -> Optional[PairedDevice]:
    """返回第一个名字以 *name_prefix* 开头的已配对设备 (地址, 名字)。

    仅 Windows / Linux；macOS 请用 :mod:`edu_host.mac_bt`。找不到（或平台
    不支持枚举）返回 None——调用方应提示用户先配对或显式传地址。
    """
    if sys.platform.startswith("win"):
        devices = _paired_devices_windows()
    elif sys.platform.startswith("linux"):
        devices = _paired_devices_linux()
    else:
        return None
    return pick_by_prefix(devices, name_prefix)
