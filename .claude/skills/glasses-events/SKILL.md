---
name: glasses-events
description: Monitor live button presses, knob rotation, audio-state and image-state events from the EDU glasses. Use when the user wants to react to button/knob input from the glasses or debug why events are not arriving. 监听眼镜按键/旋钮事件、做交互实验、事件收不到时使用。
---

# 监听按键 / 旋钮事件

前置：已按 `glasses-connect` 打通连接。事件是设备主动推送，连接期间随时打印。

## 执行（监听 30 秒）

```bash
# macOS / Linux
printf 'wait 30\nquit\n' | python3 demo_cli.py --bt auto
```

```powershell
# Windows PowerShell
"wait 30","quit" | python demo_cli.py --bt AA:BB:CC:DD:EE:FF
```

运行期间**提示用户操作眼镜**：按 AI 键 / 拍照键 / 媒体键，转动旋钮。

## 输出格式

```
[event] BUTTON CAPTURE SINGLE        <- 按键: AI / CAPTURE / MEDIA + 动作
[event] KNOB LEFT dx=-3 dy=0         <- 旋钮: LEFT / RIGHT + 位移
[event] AUDIO_STATE running source=MIC err=0
[event] IMG_STATE DONE error=OK
```

常见按键动作：SINGLE 单击、DOUBLE 双击、TRIPLE 三击、LONG 长按、
LONG_RELEASE 长按抬起、PRESS 按下、RELEASE 抬起（完整 24 项见
`docs/PROTOCOL.md` §4 的取值表）。

## 行为边界（学生常问）

- 事件是**旁路转发**：耳机类本地行为仍然生效（例如媒体键还是会控制音量/播放）。
- 拍照键**不会**本地拍照——拍照只能由 host 发命令触发（见 `glasses-photo`）。
- 拍照键"三击后长按 5 秒"是配对手势，会触发配对模式（伴随提示音），
  监听实验时避免这个组合。

## 故障排查

| 症状 | 处置 |
|---|---|
| 完全无事件 | 确认 `connected!` 已出现；按键需要真实的物理按压 |
| 只有 AUDIO/IMG_STATE，无按键事件 | 用户没按键，或按的是不转发的组合；让用户单击 AI 键测试 |
| 旋钮方向反直觉 | 协议里 RIGHT=1、LEFT=2，host 已按名字打印，按名字为准 |
