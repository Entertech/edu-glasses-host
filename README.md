# edu-glasses-host — Looktech 教育版眼镜 Python 上位机 Demo

Looktech 眼镜**教育版固件**的上位机演示程序，通过四条经典蓝牙 SPP 服务与眼镜通信：

| 服务      | SPP UUID | RFCOMM 通道 | 用途                                   |
|-----------|----------|-------------|----------------------------------------|
| EDU-CTRL  | `0x2028` | 6           | 命令 / 响应 / 事件                     |
| EDU-AUDIO | `0x2024` | 5           | 连续 OPUS 麦克风音频流                 |
| EDU-IMG   | `0x2025` | 4           | 照片（JPEG）帧，原生 air-img 子帧流    |
| OTA       | `0x2026` | 7           | 固件升级                               |

**推荐连接方式：`--bt` 蓝牙直连**，Windows / Linux / macOS 全平台一条命令，
无需配置任何串口（macOS 会自动走 IOBluetooth 专用路径）：

```bash
# 先在系统蓝牙里配对眼镜（EDU-Glasses-xxxx），然后：
python3 demo_cli.py --bt AA:BB:CC:DD:EE:FF     # 全平台（地址见系统蓝牙设置）
python3 demo_cli.py --bt auto                  # 全平台：自动找已配对的 EDU-* 设备
```

平台差异（自动处理，无需关心）：
- **Windows / Linux**：Python 标准库蓝牙 socket，零额外依赖；`auto` **优先
  当前已连接**的 EDU-* 设备（Linux 用 `bluetoothctl`，macOS 用 IOBluetooth
  连接状态）。Windows 注册表无连接状态：只有一台 EDU-* 配对时自动选，多台
  时会要求你用 `--bt <地址>` 指定（避免选到离线的那台）。RFCOMM 通道号默认
  6/5/4（如固件变更可用 `--ctrl-channel` 等覆盖）。
- **macOS**：CPython 无蓝牙 socket 且系统不给 SPP 建串口，demo 自动改走
  IOBluetooth（SDP 动态查通道）。需要 `pip install pyobjc-core
  pyobjc-framework-IOBluetooth`；在 Terminal 里首次运行会弹一次蓝牙授权。

下面的"虚拟串口"方式仅作为后备（主要用于 Windows COM 口习惯用户）。

演示的功能：设备信息、传感器查询（光敏 / 温度）、拍照回传、麦克风录音存
WAV、按键 / 旋钮 / 状态事件实时打印、OTA 固件升级。

> **耳机功能**（音乐播放和通话，A2DP/HFP）走操作系统的标准蓝牙音频设备，
> *不在*本 demo 范围内——在系统里把眼镜选为音频输出/输入即可。

环境要求：Python **3.9+**、`pyserial`（仅串口后备路径需要），以及可选的
`opuslib` + 本机 libopus（录音输出 WAV 用）。

```bash
git clone https://github.com/Entertech/edu-glasses-host.git
cd edu-glasses-host
python3 -m pip install -r requirements.txt
```

---

## 1. 环境准备 — macOS

### 1.1 配对眼镜

1. 让眼镜进入配对模式。
2. 系统设置 → 蓝牙 → 连接眼镜。

### 1.2 查找串口（仅串口后备方式需要；推荐直接用 `--bt`）

配对后 macOS 会为设备的**每个 SPP 服务**各建一个 `/dev/cu.*` 虚拟串口
（连接后可能要等几秒）。列出候选：

```bash
python3 demo_cli.py --list
# 或: ls /dev/cu.*
```

会看到若干设备相关条目，例如：

```
/dev/cu.LooktechGlasses        <- 某个 SPP 通道
/dev/cu.LooktechGlasses-1      <- 另一个 SPP 通道
/dev/cu.LooktechGlasses-2      <- 另一个 SPP 通道
```

### 1.3 区分三个串口

几个服务共用设备名，光看端口名分不出谁是谁，要靠行为判断：

- **CTRL** 口会应答 HELLO 握手（另外两个永远不会）；
- **AUDIO** 口在录音时吐 `0x52` 开头的数据包；
- **IMG** 口在 `photo` 命令后吐 air-img 帧。

逐个把端口当 `--ctrl-port` 试，凡是打印 `handshake failed` 就换下一个；
剩下两个分给 `--audio-port` / `--img-port`（如果猜反了，`record` 收不到
音频、`photo` 存不下来——对调重试即可）：

```bash
python3 demo_cli.py --ctrl-port /dev/cu.LooktechGlasses-1 \
                    --audio-port /dev/cu.LooktechGlasses \
                    --img-port /dev/cu.LooktechGlasses-2
```

### 1.4 OPUS 解码（录音输出 WAV 用）

```bash
brew install opus
python3 -m pip install opuslib
```

缺 `opuslib`/libopus 时录音仍可进行，但保存为 `.opusraw` 而非 WAV
（见 §4"录音输出说明"）。

---

## 2. 环境准备 — Windows

### 2.1 配对眼镜

设置 → 蓝牙和其他设备 → 添加设备 → 配对眼镜。

### 2.2 创建 / 查找 COM 口（仅串口后备方式需要；推荐直接用 `--bt`）

1. 设置 → 蓝牙和其他设备 → 设备 → **更多蓝牙设置**（或控制面板 → 蓝牙设置）。
2. 打开 **COM 端口**标签页。Windows 会为设备的每个 SPP 服务列一个
   **传出（Outgoing）** COM 口；如果没有，点 **添加… → 传出**选中眼镜，
   重复几次让每个服务都有端口。
3. 记下几个 `COMx` 编号（例如 `COM5`、`COM6`、`COM7`）。

```powershell
python demo_cli.py --list
```

### 2.3 区分三个 COM 口

方法同 macOS（§1.3）：只有 CTRL 口会应答 HELLO：

```powershell
python demo_cli.py --ctrl-port COM5 --audio-port COM6 --img-port COM7
```

### 2.4 Windows 上的 OPUS 解码

`opuslib` 需要本机 `opus.dll`（libopus）：

1. 下载预编译的 64 位 `opus.dll`（官方 [opus-codec.org](https://opus-codec.org/)
   构建或可信镜像）。
2. 放到 `python.exe` 旁边，**或**放进 `PATH` 里的目录。
3. `pip install opuslib`。

没有它时录音保存为 `.opusraw`（原始帧，之后在任何装有 libopus 的机器上
都能转成 WAV——格式见 §4）。

---

## 3. 使用

```bash
python3 demo_cli.py --bt auto                  # 推荐（macOS；其他平台用 --bt <地址>）
python3 demo_cli.py --ctrl-port <CTRL> [--audio-port <AUDIO>] \
                    [--img-port <IMG>] [--out-dir captures]   # 串口后备
```

启动后 demo 先做 HELLO 握手并打印固件版本与能力位，然后进入一个小 REPL：

| 命令                     | 作用                                                             |
|--------------------------|------------------------------------------------------------------|
| `info`                   | 固件版本、电量 %、充电状态                                       |
| `sensors`                | 光敏**原始计数**（非 lux）、电池温度（℃）、蓝牙芯片结温（℃）    |
| `photo [out.jpg]`        | 拍一张照；JPEG 异步到达后自动保存                                |
| `record start [out.wav]` | 开始麦克风录音                                                   |
| `record stop`            | 停止录音，打印统计（包数/帧数/丢包）                             |
| `ota <firmware.bin>`     | 经 OTA SPP `0x2026` 升级固件（升级包由固件维护方提供）           |
| `reboot`                 | 重启眼镜（回复后约 0.5 秒断开重启）                              |
| `led <inner\|outer> <off\|on\|blink\|breath> [color] [speed]` | 控制内部 RGB / 外侧指示灯 |
| `tone <name\|id\|list>`  | 播放内置提示音（`tone list` 列出可用名字）                       |
| `wait <seconds>`         | 保活会话（主要用于管道/脚本化调用）                              |
| `help` / `quit`          | 帮助 / 退出                                                      |

OTA 按设备请求的块拆成小的 `SEND_DATA` 包发送。默认节奏
`--ota-chunk-size 512 --ota-packet-interval-ms 10.0` 已在 macOS RFCOMM
真机端到端验证（约 1.8 MB 一分钟左右传完；升级成功后设备自动重启）。
调大调快可能压垮主机蓝牙链路。

异步事件随时实时打印，例如：

```
[event] BUTTON CAPTURE SINGLE
[event] KNOB LEFT dx=-3 dy=0
[event] AUDIO_STATE running source=MIC err=0
[event] IMG_STATE DONE error=OK
```

### 脚本化 / AI agent 调用

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
按任务拆好的 skills（连接排障 / 拍照 / 录音 / 传感器 / 事件监听 / OTA 升级 /
设备控制 / 协议开发），Claude Code 打开本仓库即自动可用。

### 教学示例（examples/）

- `examples/headset_demo.py` —— 把眼镜当蓝牙音频设备：A2DP 放音 / HFP 录音 /
  实时回环（`python3 examples/headset_demo.py list|play|record|loopback`）。
- `examples/notebooks/` —— 四本 Jupyter 教学笔记本（依赖
  `pip install jupyter matplotlib pillow`，笔记本目录下启动 `jupyter lab`）：

  | 笔记本 | 内容 |
  |---|---|
  | `01_photo_analysis` | 拍照 → PIL 显示 / RGB 直方图 / 边缘检测 |
  | `02_audio_analysis` | 录音 → 波形图 + 声谱图 |
  | `03_live_sensors` | 光敏 ALS 实时曲线（遮挡传感器看变化） |
  | `04_knob_events` | 旋钮事件累积成表盘指针 |

  笔记本经 `examples/notebooks/edu_notebook.py` 的 `EduSession` 驱动
  `demo_cli` 子进程，三平台代码一致，无需直接操作蓝牙 API。

### 会话示例

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

## 4. 录音输出说明

- WAV 输出：16 kHz、单声道、16-bit PCM，录音过程中增量写入
  （标准库 `wave` 模块）。
- 降级 `.opusraw`（opuslib/libopus 不可用时）：重复的
  `[u8 帧长][OPUS 帧]` 记录。每帧是 20 ms 的 16 kHz 单声道音频，约
  16 kbps。之后可在任何装有 libopus 的机器上解码，例如用
  `opuslib.Decoder(16000, 1).decode(frame, 320)` 写个小脚本。
- 如果正在通话，固件可能把流源从 MIC 切到 CALL——你会看到
  `source=CALL` 的 `AUDIO_STATE` 事件。

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
| 0x01 | 按键        | btn u8 (0 AI / 1 CAPTURE / 2 MEDIA) + action u8（完整取值表见 docs/PROTOCOL.md §4） |
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
接着 sections 个: [frame_len u8][帧 blob]
```


每个帧 blob 本身带 8 字节封装头（dcore 编码器输出格式）：

```
| payload_len(4 大端) | encoder_final_range(4 大端) | OPUS 包(payload_len 字节) |
```

**解码前必须剥掉这 8 字节**，只把 OPUS 包（CELT-WB，20 ms/帧）喂给解码器
（本库 `extract_opus_packet()` 已处理）。若整帧直接解码，长度头首字节 0x00
会被误读为 SILK-10ms 的 TOC，"成功"解出**半时长的噪声**——症状是录 N 秒只得
N/2 秒且内容不可辨。

- `len` = 段区总长 + 4（固件如此填写，段区总长 = `len - 4`）；
- `sn` 按 **帧** 递增，相邻包相差 `sections`（=8），可用于丢包检测；
- OPUS 参数：16 kHz、单声道、约 16 kbps、20 ms/帧（320 samples）。
- 解析需在 0x52 上重新同步并容忍半包（本库 `RecordStreamParser` 已实现）。

---

## 6. 目录结构

```
edu-glasses-host/
├── demo_cli.py            # 交互式 demo REPL（支持管道脚本化）
├── requirements.txt
├── AGENTS.md              # coding agent 操作指南
├── docs/
│   └── PROTOCOL.md        # 完整线协议规格
├── edu_host/              # 可 import 的包
│   ├── crc16.py           # CRC-16/CCITT-FALSE
│   ├── protocol.py        # 帧编解码、枚举、事件、图片重组
│   ├── transport.py       # Transport 抽象 + 串口实现 + --list 辅助
│   ├── bt_socket.py       # Windows/Linux 标准库 RFCOMM socket
│   ├── mac_bt.py          # macOS IOBluetooth RFCOMM 支持
│   ├── client.py          # EduClient：握手、请求/响应、事件
│   ├── image_client.py    # EDU-IMG 接收 → JPEG 落盘
│   ├── audio_client.py    # 音频包解析 + OPUS→WAV
│   └── ota_client.py      # OTA 升级客户端（0x2026）
└── tests/
    ├── test_protocol.py   # 纯 Python 单测（无需硬件）
    └── test_ota_client.py # OTA 协议/流程单测（无需硬件）
```

跑单测：

```bash
python3 -m unittest discover -s tests -v     # 或: python3 -m pytest tests -v
```

## 7. 故障排查

| 症状                                  | 处置                                                                 |
|---------------------------------------|----------------------------------------------------------------------|
| `--list` 列不出设备端口               | 重新配对；macOS 连接后等几秒；Windows 手动添加传出 COM 口（§2.2）。 |
| 连接时 `handshake failed`             | 大概率开的是 AUDIO 口——把端口对调。                                 |
| `record` 存的是 `.opusraw` 不是 `.wav`| 安装 libopus + opuslib（§1.4 / §2.4）。                             |
| 端口被占 / 权限不足                   | 关掉占用端口的其他程序；重连蓝牙。                                   |
| 照片一直不到                          | 确认给了 `--img-port` 且端口正确；看 `IMG_STATE` 事件——`ERROR`/`REMOTE_ERROR` 表示相机侧失败。 |
