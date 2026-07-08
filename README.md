# edu-glasses-host — Looktech 教育版眼镜 Python 上位机 Demo

Host-side demo for the Looktech glasses **education firmware**. It talks to
the glasses over three Classic-Bluetooth SPP services:

| Service   | SPP UUID | RFCOMM ch | Purpose                                        |
|-----------|----------|-----------|------------------------------------------------|
| EDU-CTRL  | `0x2028` | 6         | commands / responses / events                  |
| EDU-AUDIO | `0x2024` | 5         | continuous OPUS mic-audio stream               |
| EDU-IMG   | `0x2025` | 4         | photo (JPEG) frames, native air-img sub-frames |

**推荐连接方式：`--bt` 蓝牙直连**，Windows / Linux / macOS 全平台一条命令，
无需配置任何串口（macOS 会自动走 IOBluetooth 专用路径）：

```bash
# 先在系统蓝牙里配对眼镜（EDU-Glasses-xxxx），然后：
python3 demo_cli.py --bt AA:BB:CC:DD:EE:FF     # 全平台（地址见系统蓝牙设置）
python3 demo_cli.py --bt auto                  # 仅 macOS：自动找 EDU-* 设备
```

平台差异（自动处理，无需关心）：
- **Windows / Linux**：Python 标准库蓝牙 socket，零额外依赖；RFCOMM 通道号
  默认 6/5/4（如固件变更可用 `--ctrl-channel` 等覆盖）。
- **macOS**：CPython 无蓝牙 socket 且系统不给 SPP 建串口，demo 自动改走
  IOBluetooth（SDP 动态查通道）。需要 `pip install pyobjc-core
  pyobjc-framework-IOBluetooth`；在 Terminal 里首次运行会弹一次蓝牙授权。

下面的"虚拟串口"方式仅作为后备（主要用于 Windows COM 口习惯用户）。

Features demonstrated: device info, sensor query (ALS / temperatures),
photo capture, mic recording to WAV, and live button / knob / state events.

> The **headset** function (music playback and phone calls, A2DP/HFP) works
> through the operating system's normal Bluetooth audio device — it is *not*
> part of this demo. Just select the glasses as your audio output/input.

Requirements: Python **3.9+**, `pyserial`, and (optionally, for WAV output)
`opuslib` + the native libopus library.

```bash
git clone https://github.com/Entertech/edu-glasses-host.git
cd edu-glasses-host
python3 -m pip install -r requirements.txt
```

---

## 1. Setup — macOS

### 1.1 Pair the glasses

1. Put the glasses in pairing mode.
2. System Settings → Bluetooth → connect to the glasses.

### 1.2 Find the serial ports

After pairing, macOS automatically creates one `/dev/cu.*` virtual serial
port **per SPP service** of the device (this may take a few seconds after
connecting). List candidates:

```bash
python3 demo_cli.py --list
# or: ls /dev/cu.*
```

You should see several device-related entries, e.g.:

```
/dev/cu.LooktechGlasses        <- one SPP channel
/dev/cu.LooktechGlasses-1      <- another SPP channel
/dev/cu.LooktechGlasses-2      <- another SPP channel
```

### 1.3 Tell the three ports apart

The services share the device name, so the port names alone don't say which
is which. Use behavior:

- the **CTRL** port answers the HELLO handshake (the other two never do);
- the **AUDIO** port emits `0x52`-tagged packages while recording;
- the **IMG** port emits air-img frames right after a `photo` command.

Try ports one by one as `--ctrl-port`; whenever the demo prints
`handshake failed`, move on to the next. Then assign the remaining two to
`--audio-port` / `--img-port` (if you guess them swapped, `record` produces
no audio and `photo` never saves — swap and retry):

```bash
python3 demo_cli.py --ctrl-port /dev/cu.LooktechGlasses-1 \
                    --audio-port /dev/cu.LooktechGlasses \
                    --img-port /dev/cu.LooktechGlasses-2
```

### 1.4 OPUS decoding (for WAV output)

```bash
brew install opus
python3 -m pip install opuslib
```

If `opuslib`/libopus is missing, recording still works but saves a
`.opusraw` file instead of WAV (see §4 "record").

---

## 2. Setup — Windows

### 2.1 Pair the glasses

Settings → Bluetooth & devices → Add device → pair the glasses.

### 2.2 Create / find the COM ports

1. Settings → Bluetooth & devices → Devices → **More Bluetooth settings**
   (or Control Panel → Bluetooth Settings).
2. Open the **COM Ports** tab. Windows lists one **Outgoing** COM port per
   SPP service of the device. If none exist, click **Add… → Outgoing** and
   select the glasses; repeat so that all three services get a port.
3. Note the three `COMx` numbers (e.g. `COM5`, `COM6`, `COM7`).

```powershell
python demo_cli.py --list
```

### 2.3 Tell the three ports apart

Same trial method as macOS (§1.3): only the CTRL port answers HELLO:

```powershell
python demo_cli.py --ctrl-port COM5 --audio-port COM6 --img-port COM7
```

### 2.4 OPUS decoding on Windows

`opuslib` needs the native `opus.dll` (libopus):

1. Download a prebuilt 64-bit `opus.dll` (e.g. from the official
   [opus-codec.org](https://opus-codec.org/) builds or a trusted mirror).
2. Place it next to `python.exe` **or** in a directory on `PATH`
   (e.g. `C:\Windows\System32` for 64-bit Python).
3. `pip install opuslib`.

Without it, recordings are saved as `.opusraw` (raw frames, convertible to
WAV later on any machine with libopus — layout documented in §4).

---

## 3. Usage

```bash
python3 demo_cli.py --ctrl-port <CTRL> [--audio-port <AUDIO>] \
                    [--img-port <IMG>] [--out-dir captures]
```

On start the demo performs the HELLO handshake and prints the firmware
version and capability flags, then drops into a small REPL:

| Command                  | What it does                                                         |
|--------------------------|----------------------------------------------------------------------|
| `info`                   | firmware version, battery %, charging state                          |
| `sensors`                | ALS **raw counts** (not lux), battery temp (°C), BT-core temp (°C)   |
| `photo [out.jpg]`        | trigger a photo; the JPEG arrives on `--img-port` and is auto-saved  |
| `record start [out.wav]` | start mic recording (requires `--audio-port`)                        |
| `record stop`            | stop recording, print stats (packages/frames/loss)                   |
| `wait <seconds>`         | keep the session alive (mainly for piped/scripted use)               |
| `help` / `quit`          | help / exit                                                          |

Asynchronous events print live at any time, e.g.:

```
[event] BUTTON CAPTURE SINGLE
[event] KNOB LEFT dx=-3 dy=0
[event] AUDIO_STATE running source=MIC err=0
[event] IMG_STATE DONE error=OK
```

### Scripted / agent-driven usage（脚本化 / AI agent 调用）

REPL 从 stdin 读命令，因此可以直接用管道非交互调用。拍照/录音的结果是异步
到达的，用 `wait <seconds>` 保活会话等结果落盘后再 `quit`：

```bash
# macOS / Linux
printf 'photo out.jpg\nwait 25\nquit\n' | python3 demo_cli.py --bt auto
printf 'record start out.wav\nwait 10\nrecord stop\nquit\n' | python3 demo_cli.py --bt auto
```

```powershell
# Windows PowerShell（数组逐元素成行送入 stdin）
"photo out.jpg","wait 25","quit" | python demo_cli.py --bt AA:BB:CC:DD:EE:FF
```

用 Claude Code / Codex 等 coding agent 操作本仓库时：agent 说明见
[AGENTS.md](AGENTS.md)（含每个任务的成功判定标志），`.claude/skills/` 下有
按任务拆好的 skills（连接排障 / 拍照 / 录音 / 传感器 / 事件监听 / 协议开发），
Claude Code 打开本仓库即自动可用。

### Example session

```
$ python3 demo_cli.py --ctrl-port /dev/cu.LooktechGlasses --audio-port /dev/cu.LooktechGlasses-1 --img-port /dev/cu.LooktechGlasses-2
connected! proto v1, firmware 0.1.1+609, caps: AUDIO_STREAM, PHOTO, SENSORS, INPUT_EVENTS
edu> info
firmware version : 0.1.1+609 (0x0000010100000261)
battery level    : 82%
charging         : no
edu> sensors
ALS (raw counts) : 517   (raw ADC counts, not lux)
battery temp     : 28 degC
BT core temp     : 41 degC
edu> photo
photo triggered (status OK) — waiting for image frames...
[event] IMG_STATE START error=OK
[event] IMG_STATE DONE error=OK
[photo] saved captures/photo_20260707_153000_g1.jpg (48213 bytes, group 1)
edu> record start hello.wav
recording -> hello.wav (Opus 16 kHz mono; file grows while recording)
[event] AUDIO_STATE running source=MIC err=0
edu> record stop
stopped. 250 packages, 2000 frames (~40.0 s), 0 lost package(s), 0 decode error(s)
```

---

## 4. Recording output details

- WAV output: 16 kHz, mono, 16-bit PCM, written incrementally while
  recording (standard `wave` module).
- Fallback `.opusraw` (when opuslib/libopus is unavailable): repeated
  records of `[u8 frame_len][OPUS frame]`. Each frame is 20 ms of 16 kHz
  mono audio at ~16 kbps. Decode later on any machine with libopus, e.g.
  with a small script using `opuslib.Decoder(16000, 1).decode(frame, 320)`.
- If a phone call is active, the firmware may switch the stream source from
  MIC to CALL — you'll see an `AUDIO_STATE` event with `source=CALL`.

---

## 5. 协议速览（Wire Format Quick Reference）

完整协议规格见 [docs/PROTOCOL.md](docs/PROTOCOL.md)，以下为速览。

### 5.1 EDU-CTRL 帧格式（SPP UUID 0x2028）

```
| A5 5A | ver(1)=1 | type(1) | seq(1) | len(2 小端) | payload(len) | crc16(2 小端) |
```

- CRC16 计算范围：`ver..payload`（不含同步字节和 CRC 本身）；
  算法为 CRC-16/CCITT-FALSE（多项式 0x1021，初值 0xFFFF）。
- payload 最大 981 字节（整帧 ≤ 990）。

**帧类型**：

| type | 方向        | 含义                                              |
|------|-------------|---------------------------------------------------|
| 0x01 | 主机→设备   | HELLO，payload = [host_ver u8]                     |
| 0x02 | 设备→主机   | HELLO_ACK：proto_ver u8 + fw_version u64 + caps u16 |
| 0x10 | 主机→设备   | CMD：cmd_id u8 + 参数                              |
| 0x11 | 设备→主机   | RSP：cmd_id u8 + status u8 + 数据（seq 回显 CMD）  |
| 0x20 | 设备→主机   | EVT：evt_id u8 + 数据                              |

（图片不走本通道，见 §5.2。）

**命令**（status: 0 OK / 1 BUSY / 2 INVALID / 3 NOT_READY / 0xFF ERROR）：

| cmd  | 含义            | 响应数据                                                    |
|------|-----------------|-------------------------------------------------------------|
| 0x01 | 拍照            | 无（图片经 0x2025 通道异步到达；失败时附 1 字节错误码）     |
| 0x02 | 开始录音        | 无                                                          |
| 0x03 | 停止录音        | 无                                                          |
| 0x04 | 读传感器        | als_raw u16 (原始计数) + battery_temp i8 + btcore_temp i16 |
| 0x05 | 读设备信息      | fw_version u64 + battery_level u8 (%) + charging u8         |

**事件**：

| evt  | 含义        | 数据                                                          |
|------|-------------|---------------------------------------------------------------|
| 0x01 | 按键        | btn u8 (0 AI / 1 CAPTURE / 2 MEDIA) + action u8 (key_pressed_type_t) |
| 0x02 | 旋钮        | dir u8 (1 RIGHT / 2 LEFT，注意数值顺序) + delta_x i16 + delta_y i16 |
| 0x03 | 录音状态    | state u8 (0 停止/1 运行) + source u8 (0 MIC/1 CALL) + err u8  |
| 0x04 | 拍照状态    | capture_evt u8 (0 START/1 DONE/2 ERROR/3 REMOTE_ERROR/4 CANCEL) + error u8 |

### 5.2 EDU-IMG 图片流（SPP UUID 0x2025）

固件原生 air-img 图片通道：**裸字节流**，无外层封装、无 CRC（完整性依赖
RFCOMM），由 air-img 子帧组成，子帧可能跨读取分片（本库
`AirImgStreamParser` 负责切帧）：

```
HEAD (8B): 01 | 01 | group u8 | seq u32(=0) | format u8 (1=JPEG, 2=HEIF)
BODY (9B+): 02 | 01 | group u8 | seq u32    | data_len u16 | data
TAIL (7B): 03 | 01 | group u8 | seq u32
```

seq 从 HEAD 的 0 开始逐帧 +1；seq 断号说明丢帧，应丢弃整张图，等待下一个
HEAD。TAIL 固定 7 字节，无附加字段。

### 5.3 EDU-AUDIO 流格式（SPP UUID 0x2024）

连续的 recordsv package 流，每包：

```
8 字节包头（小端）:
  tag u8 = 0x52 | cmd u8 (2 左/3 右) | len u16 | sn u16 | sections u8 (=8) | reserved u8
接着 sections 个: [frame_len u8][OPUS 帧]
```

- `len` = 段区总长 + 4（固件如此填写，段区总长 = `len - 4`）；
- `sn` 按 **帧** 递增，相邻包相差 `sections`（=8），可用于丢包检测；
- OPUS 参数：16 kHz、单声道、约 16 kbps、20 ms/帧（320 samples）。
- 解析需在 0x52 上重新同步并容忍半包（本库 `RecordStreamParser` 已实现）。

---

## 6. Library layout

```
edu-glasses-host/
├── demo_cli.py            # interactive demo REPL
├── requirements.txt
├── docs/
│   └── PROTOCOL.md        # full wire-protocol specification
├── edu_host/              # importable package
│   ├── crc16.py           # CRC-16/CCITT-FALSE
│   ├── protocol.py        # frame codec, enums, events, image reassembly
│   ├── transport.py       # Transport ABC + SerialTransport + --list helper
│   ├── bt_socket.py       # Windows/Linux stdlib RFCOMM socket transport
│   ├── mac_bt.py          # macOS IOBluetooth RFCOMM support
│   ├── client.py          # EduClient: handshake, req/rsp, events
│   ├── image_client.py    # EDU-IMG channel receiver -> JPEG files
│   └── audio_client.py    # audio package parser + OPUS→WAV sink
└── tests/
    └── test_protocol.py   # pure-python unit tests (no hardware needed)
```

Run the tests:

```bash
python3 -m unittest discover -s tests -v     # or: python3 -m pytest tests -v
```

## 7. Troubleshooting

| Symptom                              | Fix                                                                 |
|--------------------------------------|----------------------------------------------------------------------|
| `--list` shows no device port        | Re-pair; on macOS wait a few seconds after connecting; on Windows add Outgoing COM ports manually (§2.2). |
| `handshake failed` on connect        | You probably opened the AUDIO port — swap the two ports.            |
| `record` saves `.opusraw` not `.wav` | Install libopus + opuslib (§1.4 / §2.4).                            |
| Port busy / permission denied        | Close other apps using the port; reconnect Bluetooth.               |
| Photo never arrives                  | Check that `--img-port` is given and is the right port; watch `IMG_STATE` events — `ERROR`/`REMOTE_ERROR` means the camera side failed. |
