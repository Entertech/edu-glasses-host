# AGENTS.md — edu-glasses-host

给 coding agent（Claude Code / Codex / Cursor 等）的仓库操作指南。
人类读者请从 [README.md](README.md) 开始。

## 这个仓库是什么

Looktech **教育版眼镜**的 Python 上位机：通过经典蓝牙 SPP 与眼镜通信，演示
5 个能力 —— 设备信息、传感器查询、拍照回传、麦克风录音（OPUS→WAV）、
按键/旋钮事件。协议的**唯一事实来源**是 [docs/PROTOCOL.md](docs/PROTOCOL.md)；
`edu_host/` 包和 `tests/` 是它的参考实现与可执行规格。

`.claude/skills/` 下有按任务拆好的 skill（连接排障、拍照、录音、传感器、
事件监听、协议二次开发），Claude Code 打开本仓库即自动可用。

## 环境与安装

- Python **3.9+**。
- **Windows / Linux + `--bt`**：零额外依赖（标准库蓝牙 socket）。Windows 需
  python.org 官方构建（内置 `AF_BTH`）。
- **macOS + `--bt`**：`pip install pyobjc-core pyobjc-framework-IOBluetooth`。
- 录音出 WAV（可选）：`pip install opuslib` + 本机 libopus——macOS
  `brew install opus`（运行时可能需要 `export DYLD_LIBRARY_PATH=/opt/homebrew/lib`）；
  Windows 需将 64 位 `opus.dll` 放到 `python.exe` 旁或 `PATH`。缺 opuslib 时
  录音降级（见 README §4），不算错误。
- 串口后备路径才需要 `pyserial`。

## 连接设备（前置条件）

1. 眼镜开机后自动可发现（约 2 分钟窗口）；或拍照键三击后按住 5 秒手动进入配对。
2. 先在**操作系统蓝牙设置**里配对眼镜（设备名 `EDU-Glasses-xxxx`）。
3. 蓝牙地址（`AA:BB:CC:DD:EE:FF`）在系统蓝牙设置里可见。**不要猜地址**——
   问用户要，或在 macOS 上用 `--bt auto`（按 `EDU-` 名称前缀自动找）。

```bash
python3 demo_cli.py --bt AA:BB:CC:DD:EE:FF   # 全平台
python3 demo_cli.py --bt auto                # 仅 macOS
```

Windows/Linux 的 RFCOMM 通道号默认 ctrl=6 / audio=5 / img=4，固件侧注册顺序
固定所以通常不用动；连不上时可用 `--ctrl-channel` 等覆盖。macOS 走 SDP 动态
查询，无需通道号。

## Agent 非交互调用模式（关键）

demo 是一个读 stdin 的 REPL，所以**用管道喂命令**即可脚本化。拍照/录音的结果
是异步到达的，必须用 `wait <seconds>` 保活会话等结果落盘，再 `quit`：

```bash
# macOS / Linux
printf 'info\nsensors\nquit\n' | python3 demo_cli.py --bt auto
printf 'photo out.jpg\nwait 25\nquit\n' | python3 demo_cli.py --bt auto
printf 'record start out.wav\nwait 10\nrecord stop\nquit\n' | python3 demo_cli.py --bt auto
```

```powershell
# Windows PowerShell（数组逐元素成行）
"info","sensors","quit" | python demo_cli.py --bt AA:BB:CC:DD:EE:FF
"photo out.jpg","wait 25","quit" | python demo_cli.py --bt AA:BB:CC:DD:EE:FF
```

### 成功判定标志（grep 输出）

| 任务 | 成功标志（stdout 行） |
|---|---|
| 连接/握手 | `connected! proto v1, firmware ...` |
| 设备信息 | `firmware version : ...` / `battery level    : ...` |
| 传感器 | `ALS (raw counts) : ...` |
| 拍照 | `[photo] saved <path> (<N> bytes, group <G>)` |
| 录音 | `stopped. <N> packages, <M> frames (~<S> s) ...` |
| 事件 | `[event] BUTTON ...` / `[event] KNOB ...` |

握手失败：Windows/Linux 输出 `handshake failed`；macOS 输出 `device not found`
（未配对）、`EDU-CTRL service (0x2028) not found`（非教育固件）或直接异常退出。
进程退出码 0 仅代表会话正常退出，**具体任务成败要看上面的标志行**。

### 时长建议

- 拍照：`wait 25`（ISP 冷启动最多 ~10 s + 传输数秒；`[photo] saved` 行出现即可）。
- 录音：录 N 秒就 `wait N`，`record stop` 会自动结算。
- 事件监听：`wait 30` 左右，期间提示用户按键/转旋钮。

## 无硬件时的验证

单元测试不需要眼镜、不需要蓝牙、不需要任何第三方依赖：

```bash
python3 -m unittest discover -s tests -v    # 35 tests，应全绿
python3 -m py_compile demo_cli.py edu_host/*.py
```

任何代码改动后必须跑通全部单测。涉及连接/收发行为的改动，还应在真机上按
上面的管道 recipe 做一次冒烟（至少 `info` + `photo` 或 `record`）。

## 代码结构

| 文件 | 职责 |
|---|---|
| `edu_host/protocol.py` | 帧编解码、枚举、air-img 切帧/JPEG 重组（**纯 stdlib**） |
| `edu_host/crc16.py` | CRC-16/CCITT-FALSE |
| `edu_host/client.py` | EduClient：握手、请求/响应配对、事件分发（线程版） |
| `edu_host/audio_client.py` | 0x52 音频包解析 + OPUS→WAV |
| `edu_host/image_client.py` | EDU-IMG 接收线程 → JPEG 落盘 |
| `edu_host/transport.py` | Transport 抽象 + 串口实现（pyserial 懒加载） |
| `edu_host/bt_socket.py` | Windows/Linux 标准库 RFCOMM socket |
| `edu_host/mac_bt.py` | macOS IOBluetooth（**主线程 run loop 模型**） |
| `demo_cli.py` | 交互/管道 REPL；平台分发（darwin → mac 会话，其余 → 线程会话） |

## 修改守则（不变量）

1. **线协议常量不可单方面改**（同步字、帧类型、cmd/evt id、CRC 算法、UUID、
   通道号、990 字节上限）：它们必须与眼镜固件一致。协议疑义以
   `docs/PROTOCOL.md` 为准；文档与代码不符时先向维护者确认，不要"顺手修正"。
2. **`edu_host/protocol.py` 与 `crc16.py` 保持纯 stdlib**，可无依赖单测。
3. **macOS 路径的两条铁律**（改 `mac_bt.py` / mac 会话前必读其模块 docstring）：
   IOBluetooth 回调只在**主线程** run loop 泵动时投递（必须 async open +
   `pump()`，不能用 sync open、不能搬到后台线程）；首次 open 可能
   `kIOReturnError`，按现有 ACL 重建逻辑重试。
4. 线程会话（Windows/Linux/串口）里不要引入 pyobjc；mac 会话里不要引入
   阻塞式 `input()`（会停掉 run loop）。
5. 新增 REPL 命令要同时改两个会话分支 + `HELP_TEXT` + README + 本文件的
   recipe 表，并保持管道可用（无交互确认）。

## 常见故障排查

| 症状 | 处置 |
|---|---|
| `device not found`（mac auto） | 未配对，或设备名不以 `EDU-` 开头 → 系统设置里配对；或改用 `--bt <地址>` |
| `handshake failed` | 连到了别的通道/设备 → 核对地址；Windows/Linux 试 `--ctrl-channel` 覆盖 |
| mac 进程直接崩溃（SIGABRT） | 终端 App 无蓝牙权限 → 系统设置 → 隐私与安全性 → 蓝牙，勾选你的终端（Terminal/iTerm/IDE），然后**重开终端** |
| mac `ImportError: ... objc` | `pip install pyobjc-core pyobjc-framework-IOBluetooth` |
| mac `RFCOMM open failed` 反复出现 | 系统蓝牙开关关一下再开，或忘记设备重新配对 |
| Windows 无 `AF_BTH` | 换 python.org 官方 Python；或走串口后备（README §2） |
| 录音只出 `.opusraw` / 空 WAV | libopus 未装好（见"环境与安装"），原始帧仍可事后解码 |
| `photo` 一直不落盘 | 看 `[event] IMG_STATE` 行：`ERROR/REMOTE_ERROR` 是相机侧失败，重拍；完全无事件则检查 img 通道 |
| 眼镜连着别的 host | EDU-CTRL 单 host：先断开占用方 |

## 学生二次开发指引

- 用其他语言写自己的 host：照 `docs/PROTOCOL.md` 实现；用
  `python3 -c "from edu_host.crc16 import crc16; print(hex(crc16(bytes.fromhex('0110010100'))))"`
  之类生成 CRC 对拍向量；`tests/test_protocol.py` 里有现成的帧级测试样例可移植。
- 用 Python 扩展：直接 import `edu_host` 包（见上表），不要复制粘贴协议常量。
- 固件在眼镜端，本仓库改不了设备行为；需要新命令/事件时先与固件维护者对齐
  协议版本与 caps 位。
