---
name: glasses-record
description: Record microphone audio from the EDU glasses to a WAV file (OPUS stream decoded on the host). Use when the user wants to record audio from the glasses or recording produces no/empty output. 用眼镜录音、录音文件为空或没有 WAV 输出时使用。
---

# 录音到 WAV

前置：已按 `glasses-connect` 打通连接。WAV 输出需要 opuslib + 本机 libopus：

- macOS：`brew install opus && pip install opuslib`；运行时若报找不到 libopus，
  先 `export DYLD_LIBRARY_PATH=/opt/homebrew/lib`。
- Windows：下载 64 位 `opus.dll` 放到 `python.exe` 旁或 `PATH`，再 `pip install opuslib`。
- Linux：`apt install libopus0`（或发行版等价包）+ `pip install opuslib`。

缺 opuslib 时录音仍进行，但线程会话降级保存 `.opusraw`（原始帧，可事后解码），
macOS 会话则输出空 WAV 并打印 warning —— 都不算连接故障。

## 执行（录 N 秒就 wait N）

```bash
# macOS / Linux：录 10 秒
printf 'record start out.wav\nwait 10\nrecord stop\nquit\n' | python3 demo_cli.py --bt auto
```

```powershell
# Windows PowerShell
"record start out.wav","wait 10","record stop","quit" | python demo_cli.py --bt AA:BB:CC:DD:EE:FF
```

## 成功判定

```
recording -> out.wav
[event] AUDIO_STATE running source=MIC err=0
stopped. NN packages, NNN frames (~10.0 s) ... -> out.wav
```

验证 WAV 时长：

```bash
python3 -c "import wave,sys;w=wave.open(sys.argv[1]);print(round(w.getnframes()/w.getframerate(),1),'s')" out.wav
```

音频参数固定：16 kHz、单声道、16-bit PCM（OPUS 20ms 帧解码而来）。

## 故障排查

| 症状 | 处置 |
|---|---|
| `stopped. 0 packages` | 音频通道没数据 → 确认用 `--bt`（自动建立三通道）；串口模式必须给 `--audio-port` 且端口正确 |
| WAV 时长 0 但 packages > 0 | opuslib/libopus 没装好（见上方依赖），原始数据没丢 |
| `AUDIO_STATE` 显示 `source=CALL` | 正在通话，流自动切到通话音频，属预期行为 |
| 录音中途停止 | 看 `[event] AUDIO_STATE` 的 err 码；蓝牙断开会自动停流 |
| frames 有丢失（lost > 0） | 蓝牙带宽紧张（如同时播 A2DP 音乐）→ 缩短距离或停掉音乐 |
