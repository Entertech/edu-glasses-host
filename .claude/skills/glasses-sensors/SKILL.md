---
name: glasses-sensors
description: Read the EDU glasses sensors (ambient light ALS, battery temperature, BT-core temperature) and device info (firmware version, battery, charging). Use when the user asks for sensor values or device status. 查眼镜传感器（光敏/温度）或设备信息（电量/固件版本）时使用。
---

# 读传感器与设备信息

前置：已按 `glasses-connect` 打通连接。

## 执行

```bash
# macOS / Linux
printf 'info\nsensors\nquit\n' | python3 demo_cli.py --bt auto
```

```powershell
# Windows PowerShell
"info","sensors","quit" | python demo_cli.py --bt AA:BB:CC:DD:EE:FF
```

## 成功判定与字段解读

```
firmware version : 0.1.1+609 (0x...)
battery level    : 82%
charging         : no
ALS (raw counts) : 517   (raw ADC counts, not lux)
battery temp     : 28 degC
BT core temp     : 41 degC
```

- **ALS 是原始 16-bit 计数值，不是 lux**：数值越大环境越亮。适合做相对比较
  （遮挡传感器→数值下降；打光→上升），不适合报绝对照度。
- `battery temp` 是电池 NTC 温度，`BT core temp` 是蓝牙 SoC 结温——
  设备没有独立环境温度计，别把它们当室温。
- 传感器查询的响应可能延迟约 0.2 秒（光敏传感器与相机电源域联动，固件会先
  重新使能再采样）。

## 故障排查

| 症状 | 处置 |
|---|---|
| ALS 恒为 0 | 传感器随相机域断电且缓存为空 → 先拍一张照（唤醒相机域）再查；或升级到修复后的固件 |
| ALS 数值不随光照变化 | 确认没有遮挡物粘在传感器窗口上；连续查询间隔 ≥1 秒 |
| 温度看起来偏高 | BT core 结温本来就高于环境温度 10–20 ℃，属正常 |
| RSP ERROR | 温度子系统未就绪（开机极早期）→ 稍后重试 |
