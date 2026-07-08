---
name: glasses-connect
description: Connect to the EDU glasses over Bluetooth SPP and verify the handshake; diagnose pairing, channel, permission and dependency problems. Use when the user wants to connect to the glasses, the demo cannot find the device, the handshake fails, or Bluetooth errors/crashes occur. 连接教育版眼镜/连不上/握手失败/蓝牙报错时使用。
---

# 连接眼镜并验证握手

## 前置条件（先核对，缺一不可）

1. 眼镜已开机。开机后自动可发现约 2 分钟；手动进入配对：**拍照键三击后按住 5 秒**（有提示音）。
2. 已在**操作系统蓝牙设置**中配对（设备名 `EDU-Glasses-xxxx`）。
3. 依赖就绪：
   - Windows / Linux：无额外依赖（Windows 需 python.org 官方 Python，内置蓝牙 socket）。
   - macOS：`pip install pyobjc-core pyobjc-framework-IOBluetooth`。

## 连接验证（一条命令）

蓝牙地址在系统蓝牙设置里可见；**不要猜地址，问用户要**。macOS 可用 `auto`。

```bash
# macOS / Linux
printf 'info\nquit\n' | python3 demo_cli.py --bt auto            # macOS
printf 'info\nquit\n' | python3 demo_cli.py --bt AA:BB:CC:DD:EE:FF
```

```powershell
# Windows PowerShell
"info","quit" | python demo_cli.py --bt AA:BB:CC:DD:EE:FF
```

**成功标志**（stdout）：`connected! proto v1, firmware ...` 且随后打印
`firmware version : ...`。看到即连接链路完全打通。

## 故障排查表

| 症状 | 处置 |
|---|---|
| `device not found`（mac auto） | 未配对或名字不以 `EDU-` 开头 → 系统设置里配对；或改用 `--bt <地址>` |
| `handshake failed` | 连到了错误通道/设备 → 核对地址；Windows/Linux 尝试 `--ctrl-channel 6`（默认）附近的值 |
| macOS 进程直接崩溃（SIGABRT，无 Python 异常） | 终端 App 缺蓝牙权限 → 系统设置 → 隐私与安全性 → 蓝牙 → 勾选正在使用的终端（Terminal/iTerm/IDE），**重开终端再试** |
| macOS `ImportError: objc` | `pip install pyobjc-core pyobjc-framework-IOBluetooth` |
| macOS `RFCOMM open failed` 反复出现 | 系统蓝牙开关关/开一次；仍失败则在蓝牙设置中忽略设备后重新配对 |
| Windows 报无 `AF_BTH` | 使用 python.org 官方 Python；或走串口后备（见 README §2） |
| 一直连不上且设备曾被另一台电脑用过 | EDU-CTRL 是单 host 通道：先在那台电脑断开，再连 |

## 通道说明（排障时参考）

| 服务 | UUID | RFCOMM 通道（Win/Linux 默认） |
|---|---|---|
| EDU-CTRL（命令/事件） | 0x2028 | 6 |
| EDU-AUDIO（OPUS 音频流） | 0x2024 | 5 |
| EDU-IMG（照片 JPEG） | 0x2025 | 4 |

macOS 走 SDP 动态查询，不需要通道号。Windows/Linux 通道号由固件注册顺序决定，
稳定不变；异常时可用 `--ctrl-channel/--audio-channel/--img-channel` 覆盖。
