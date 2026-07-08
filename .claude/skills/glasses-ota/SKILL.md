---
name: glasses-ota
description: Upgrade the EDU glasses firmware over the OTA SPP channel (0x2026) using a firmware package provided by the maintainers, and verify the new version after reboot. Use when the user asks to flash/upgrade the glasses firmware over Bluetooth or an OTA transfer fails. 给眼镜 OTA 升级固件、升级失败排查时使用。
---

# OTA 升级固件

前置：已按 `glasses-connect` 打通连接；**升级包（`.bin`）由固件维护方提供**——
它是带固件头/模块头/CRC 的专用格式，不是任意固件文件。设备电量须 ≥20%。

## 执行

```bash
# macOS / Linux（ota 命令同步阻塞直到完成，无需 wait）
printf 'info\nota /path/to/firmware.bin\nquit\n' | python3 demo_cli.py --bt auto
```

```powershell
# Windows PowerShell
"info","ota C:\path\firmware.bin","quit" | python demo_cli.py --bt AA:BB:CC:DD:EE:FF
```

~1.8 MB 的包约一分钟传完。完成后设备**约 2 秒自动重启**（蓝牙断开属预期）。

## 成功判定

```
[ota] can_update
[ota] data .../... bytes (100.0%)
[ota] done
[ota] complete, reboot=1
```

重启后（约 30 秒）再连一次核对版本已变为包版本：

```bash
printf 'info\nquit\n' | python3 demo_cli.py --bt auto
# firmware version : <新版本>
```

## 传输参数（默认值已真机验证，勿轻易调大）

- `--ota-chunk-size 512`：单 SEND_DATA 数据段大小（设备侧单包上限 ~4KB）；
- `--ota-packet-interval-ms 10.0`：子包间隔（约 51 KB/s）；
- `--ota-channel 7`：Windows/Linux 的 OTA RFCOMM 通道（macOS 走 SDP 自动发现）。

## 故障排查

| 症状 | 处置 |
|---|---|
| `CAN_UPDATE failed: result=BATTERY_LOW` | 充电到 ≥20% 再试 |
| `CAN_UPDATE failed: result=BUSY reason=...` | 设备正在通话/拍照/录音等，停掉对应业务再试 |
| `firmware header CRC mismatch`（本地就报错） | 升级包损坏或不是本机型的包 → 找维护方重取 |
| 传输中途超时 | 蓝牙断链 → 12 秒内重连重跑 `ota` 会自动断点续传；超时则从头再来 |
| 完成后连不上 | 等 30 秒再试（重启+回连需要时间）；仍不行则重启系统蓝牙 |
| 升级后版本没变 | 看是否有 `complete, reboot=1`；无 reboot=1 说明流程未走完，重跑 |
