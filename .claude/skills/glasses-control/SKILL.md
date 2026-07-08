---
name: glasses-control
description: Control the EDU glasses device — reboot it, drive the inner RGB / outer indicator LEDs, or play built-in prompt tones. Use when the user asks to restart the glasses, light up / blink the LEDs, or make the glasses beep. 重启眼镜、控制 LED 灯效、播放提示音时使用。
---

# 设备控制：重启 / LED / 提示音

前置：已按 `glasses-connect` 打通连接。这些命令需要固件 caps 含 `CONTROL`
（`connected!` 行里可见）；老固件返回 INVALID。

## LED 控制

```bash
# 内部 RGB：绿色快闪
printf 'led inner blink green fast\nwait 3\nled inner off\nquit\n' | python3 demo_cli.py --bt auto
# 外侧指示灯：常亮 2 秒后关
printf 'led outer on\nwait 2\nled outer off\nquit\n' | python3 demo_cli.py --bt auto
```

语法：`led <inner|outer> <off|on|blink|breath> [color] [speed]`
- 颜色（仅 inner）：red / green / blue / orange / purple / white（默认 white）
- 速度（仅 blink/breath）：slow / normal / fast（默认 normal）
- **`off` 同时把灯交还固件自动控制**；固件业务状态（配对/拍照指示等）随时
  可能收回灯——手动设置是尽力而为，被覆盖后重发即可。

成功标志：`led: status=OK`（灯效需人眼确认，agent 应提示用户观察）。

## 提示音

```bash
printf 'tone list\nquit\n' | python3 demo_cli.py --bt auto     # 列出可用名字
printf 'tone click\ntone 12\nquit\n' | python3 demo_cli.py --bt auto
```

常用：`click`（短促）、`photo_captured`（快门）、`power_on`、
`bluetooth_connected`、`audio_recording_started/stopped`。也接受 0–29 数字。
成功标志：`tone: status=OK`（声音从眼镜扬声器播出，提示用户听）。

## 重启

```bash
printf 'reboot\nquit\n' | python3 demo_cli.py --bt auto
# 约 30-40 秒后设备重启完成并自动回连，可再连验证：
printf 'info\nquit\n' | python3 demo_cli.py --bt auto
```

成功标志：`reboot: status=OK` → 连接断开（预期）→ 重连后 `info` 正常。

## 故障排查

| 症状 | 处置 |
|---|---|
| status=INVALID | 参数拼写错误（看用法行），或固件太旧没有 CONTROL 能力 |
| LED 设置了但很快变回去 | 固件业务状态收回了灯（如正在配对/拍照）——预期行为 |
| tone 无声 | 确认音量、眼镜未在通话中；`tone list` 核对名字 |
| reboot 后连不上 | 等足 40 秒；仍不行按 `glasses-connect` 排障 |
