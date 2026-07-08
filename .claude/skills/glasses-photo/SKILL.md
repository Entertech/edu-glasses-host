---
name: glasses-photo
description: Take a photo with the EDU glasses and save/verify the returned JPEG. Use when the user asks to capture a photo from the glasses, or when photos are not arriving / are corrupted. 用眼镜拍照、照片收不到或打不开时使用。
---

# 拍照并验证 JPEG

前置：已按 `glasses-connect` 打通连接。

## 执行

```bash
# macOS / Linux（wait 25 给 ISP 冷启动 + 图传留足时间）
printf 'photo out.jpg\nwait 25\nquit\n' | python3 demo_cli.py --bt auto
```

```powershell
# Windows PowerShell
"photo out.jpg","wait 25","quit" | python demo_cli.py --bt AA:BB:CC:DD:EE:FF
```

不带文件名时照片按时间戳存到 `captures/`（`--out-dir` 可改）。

## 成功判定

stdout 出现：

```
[photo] saved out.jpg (NNNNN bytes, group G)
```

再验证 JPEG 完整性（SOI=ffd8，EOI=ffd9）：

```bash
python3 -c "import sys;d=open(sys.argv[1],'rb').read();print(len(d),d[:2].hex(),d[-2:].hex())" out.jpg
# 期望输出形如: 64240 ffd8 ffd9
```

## 时序与状态事件

- 相机（ISP）睡眠时会自动唤醒，拍照命令被缓存执行，**首拍可能延迟 5–15 秒**，
  这不是故障；`wait 25` 已覆盖。
- 过程事件会实时打印：`[event] IMG_STATE START` → `DONE`。
- 连拍：等上一张 `[photo] saved` 出现后再发下一个 `photo`。

## 故障排查

| 症状 | 处置 |
|---|---|
| RSP BUSY（`device is busy taking another photo`） | 上一拍未完成，等几秒重试 |
| `[event] IMG_STATE ERROR/REMOTE_ERROR` | 相机侧失败 → 重拍一次；连续失败则重启眼镜 |
| `photo triggered` 后完全无下文 | img 通道没建立 → 确认用的是 `--bt`（三通道自动建立）；串口模式必须给 `--img-port` |
| 照片字节数很小或 EOI 缺失 | 传输中断 → 重拍；检查蓝牙距离/干扰 |
| status ERROR + 1 字节错误码 | 3=相机资源被占（等待后重试），2=超时（重拍） |
