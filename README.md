# edu-glasses-host — Looktech 教育版眼镜 Python SDK 与 Demo

Looktech 眼镜**教育版固件**的上位机演示程序，通过四条经典蓝牙 SPP 服务与眼镜通信。

## EDU 集成版本

本 README 对应 `feat/edu-sdk-integration` 的 **0.2.0 验证候选**，配套固件为
[Looktech-Glasses-Device / feat/edu-main-integration](https://github.com/Entertech/Looktech-Glasses-Device/tree/feat/edu-main-integration)。
固件从 main `813ee9999eaefcdb830053d2faec65f0e2bff2c5` 迁入旧 `feat/edu-spp`
的 EDU v1 能力，保留教学功能、重启、LED、提示音和 OTA；当前修复固件源提交为
`eca5981f`，SDK 核心功能提交为 `4c972e2`。尚未合入两仓库 main，也未发布正式 SDK/固件。

SDK 新增统一 `EduSession`，CLI 和 Notebook 直接复用它；保留原有客户端与 transport API。
Mac 每条原生通道使用独立进程主 run loop，避免关闭 IMG/AUDIO/OTA 时误断 CTRL；
本地 OTA 包先校验再开通道。固件复用 main 图片 route/reservation/ACK 与录音资源管理，
并在 EDU 门控内修复 5 秒旧清理回调取消新拍照预留的问题。

**公版与 EDU 是两种构建固件。** 公版默认关闭 `CONFIG_LT_EDU_MODE`，原 BLE、
App 绑定、业务鉴权和 RPC 路径保留；EDU 通过系统经典蓝牙配对后直连 PC SPP，
不广播 BLE、不注册 App GATT/iAP2 业务入口，不能直接作为公版 App 固件使用。
两种固件保留经典 A2DP/HFP/AVRCP。详细隔离和构建说明见
[固件 README](https://github.com/Entertech/Looktech-Glasses-Device/blob/feat/edu-main-integration/README.md)。

HELLO/caps 用于版本与功能发现，不提供业务鉴权或学生/维护者权限分级。当前开放
8 条白名单命令及独立 OTA；未新增 IMU、WiFi/P2P、媒体库、LTAU 或通用 App RPC 开放。

配套的可追溯固件位于 [`firmware/`](firmware/README.md)：保留旧 `feat/edu-spp` 的 WPK，
新增基于 main 的 `stereo-edu` 集成候选 WPK 和可供 SDK 使用的 Looktech OTA 外层 `.bin`。
清单记录源码提交、构建参数、大小与 SHA-256。WPK 用于 WQ 烧录工具；SDK/CLI 的
`ota` 命令必须使用 Looktech 外层 `.bin`，不能直接使用 WPK 或 `wqota` BT 模块内包。

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
  6/5/4/7（如固件变更可用 `--ctrl-channel` 等覆盖）。
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
git clone --branch feat/edu-sdk-integration https://github.com/Entertech/edu-glasses-host.git
cd edu-glasses-host
python3 -m pip install -r requirements.txt
python3 -m pip install -e .
```

## Python SDK

`edu_host.EduSession` 是普通 Python 程序、CLI 和 Notebook 共用的会话入口。
安装本包无必选运行依赖；Windows/Linux 蓝牙直连使用标准库。macOS 可安装
`python3 -m pip install -e '.[macos]'`，串口或 WAV 解码分别可选 `.[serial]`、
`.[audio]`；WAV 解码还需系统 libopus。安装后也可运行 `edu-glasses --bt auto`。

```python
from edu_host import EduSession, KnobEvent, LedId, LedMode, LedColor, Tone

with EduSession(bt="auto", out_dir="captures") as glasses:
    print(glasses.capabilities)             # HELLO_ACK 中的固件能力
    print(glasses.info().fw_version_str)
    reading = glasses.sensors()
    print(reading.als_raw, reading.battery_temp_c, reading.btcore_temp_c)
    jpeg = glasses.photo("lesson.jpg", timeout=30)  # 完整 JPEG 已落盘才返回
    audio = glasses.record("lesson.wav", seconds=5)
    print(jpeg, audio)                       # 缺解码器时 audio 为 .opusraw
    for event in glasses.events(10):         # 返回类型化事件，无需解析打印文本
        if isinstance(event, KnobEvent):
            print(event.direction_name, event.delta_x, event.delta_y)
    if glasses.supports("CONTROL"):
        glasses.set_led(LedId.INNER, LedMode.ON, LedColor.GREEN)
        glasses.play_tone(Tone.CLICK)
```

构造函数不连接；`with` 会自动 `connect()`/`close()`，也可显式调用这两个方法。
`bt` 支持 `"auto"` 和显式蓝牙地址。串口后备示例：
`EduSession(ctrl_port="COM5", audio_port="COM6", img_port="COM7", ota_port="COM8")`。
Windows/Linux 通道可通过 `ctrl_channel`、`audio_channel`、`img_channel`、
`ota_channel` 覆盖（默认 6/5/4/7）；macOS 通过 SDP 查询。

其他会话操作：

| API | 行为 |
|---|---|
| `trigger_photo(path)` / `wait_photo(timeout=30)` | 分开触发与等待；ACK、IMG_STATE DONE 都不代表图片已落盘 |
| `record_start(path)` / `record_stop()` | 返回实际路径 / `AudioStats`（包、帧、丢包、解码错误、实际路径、`decoded_to_wav`、`frames_written`） |
| `add_event_listener(callback)` / `add_image_listener(callback)` | 类型化事件 / `(path, CompletedImage)` 回调 |
| `wait(seconds)` / `poll(seconds=0.05)` | 保持接收并分发回调；`poll` 也返回本次收到的事件 |
| `reboot()` / `set_led(...)` / `play_tone(...)` | 8 条现有控制命令中的重启、LED、提示音；非 OK 抛异常 |
| `ota("firmware.bin", progress=callback)` | 复用现有 OTA 客户端；回调参数 `(stage, done, total)`，返回 `UpdateResultResponse` |

录音保留固件原有 MIC/CALL 自动切换，用 `AudioStateEvent.source_name` 观察来源，
SDK 不强制指定通话来源。无 opuslib/libopus 时保存原始帧 `.opusraw`，不会制造
空 WAV；没有写入任何有效帧时 `record_stop()` 报错。图片接收同样以实际写盘为准。

**macOS 主线程约束**：蓝牙 `connect()`、请求、等待和关闭都必须在进程主线程
执行。每条原生 RFCOMM 通道由一个独立的 Python 子进程持有，在该子进程的主线程
泵动 IOBluetooth run loop；主进程通过私有管道收发字节，在 `wait()` / `events()` /
`poll()` 中解析并分发回调。这样避免 macOS 27 同进程多通道 `closeChannel()` 误断
其他通道。空闲或录音期间仍应调用这些方法，让 SDK 及时消费数据。
Mac 在握手前打开 CTRL/AUDIO/IMG，录音结束保留音频连接、会话关闭时统一关闭；
Windows/Linux socket 与串口继续使用接收线程和原连接顺序。SDK 方法按顺序调用；监听回调在
调用者线程分发，回调应简短，且不要在回调内重入设备请求。

异常可从 `edu_host` 导入：`EduUnsupportedError` 表示旧固件缺能力位或缺通道；
`EduTimeoutError` 表示响应或图片等待超时；`EduStatusError` 保留设备返回的
`cmd_id/status/data`（BUSY、INVALID 等）；它们都继承 `EduClientError`。
连接失败也可能抛 `OSError` 或 `AmbiguousGlassesError`（多台设备需指定地址）；
参数错误抛 `ValueError`。OTA 保留独立的 `OTAError`、
`OTAStatusError`、`OTATimeoutError`。超时不表示设备未执行命令，SDK 不自动重发拍照等操作。
OTA 前须结束录音并等待拍照完成；升级期间拒绝其他设备请求。
本地升级包在建立 OTA 通道前先校验，坏包不会打断当前控制会话。底层
`MacRFCOMMChannel.close()/open()` 可独立关闭、重开目标通道；重复关闭安全。
应用退出时使用 `EduSession.close()` 释放完整会话，SDK 会等待并回收各通道进程。
只有尚无同设备通道打开时，首次打开失败才重建 ACL 重试，避免打断已有连接。
此实现需要可启动子进程的普通 Python 环境；单文件冻结的可执行程序尚未验证。

## 存储照片、录像与 WiFi 原件导出

这组接口需要支持 MEDIA_CATALOG 的 EDU BT，复用公版 ISP 的 ID/元数据及 LAN 能力，
无需修改或烧录 ISP。`media_capabilities()` 查询真实能力；只导出有真实 ID 的照片、视频
及可确认登记的伴随文件。原 `photo()`/`record()` 仍为教学小图/麦克风音频。

拍摄调用返回公版控制状态，不承诺本次唯一媒体 ID 或文件已发布。随后从媒体列表选择
真实条目；暂未列出时可重新查询，SDK 不猜最近文件、不自动重拍。

```python
import json
from pathlib import Path
from edu_host import EduSession, WifiSecurity

# 本地凭据文件由使用者提供；不要提交到仓库。
credentials = json.loads(Path('wifi.json').read_text(encoding='utf-8'))
with EduSession(bt='auto') as glasses:
    photo = glasses.capture_saved_photo()  # 公版 DONE 控制状态，不是媒体身份
    print(photo.operation_id, photo.state)
    glasses.video_start()                 # 等待公版 RECORDING 状态
    glasses.wait(5)
    video = glasses.video_stop()          # 等待公版 DONE；可用 video_status() 查询
    with glasses.media_import(credentials['ssid'], credentials['password'],
                              WifiSecurity[credentials.get('security', 'WPA2')]) as media:
        items = media.list()             # 从真实 ID 目录选择
        for result in media.download_all('captures'):
            print(result.media.media_id, result.main_success, result.complete, result.errors)
        # 单项：media.download(items[0], 'captures')
        # 显式删除独立调用：media.delete(items[0])
```

`wifi.json` 内容为 `{"ssid":"目标网络","security":"WPA2","password":"本地密码"}`，
权限建议仅当前用户可读。CLI 只接受文件路径，避免密码进入命令行和 REPL 输出；SDK
不保存凭据。PC 与眼镜处于同一可达 LAN 即可，PC 可用有线网络，无需互联网。

CLI 同步等待公版拍摄控制状态，文件是否可导出以真实 ID 列表为准。下面命令默认保留全部原件：

```bash
printf 'photo-save\nvideo start\nwait 5\nvideo stop\nmedia open /absolute/path/wifi.json\nmedia list\nmedia download all /absolute/path/captures\nmedia close\nquit\n' | python3 demo_cli.py --bt auto
```

其他命令：`wifi caps|scan|status|disconnect`、`wifi connect <wifi.json>`、`media caps`、
`media download <id> [directory]`、`media delete <id>`、`video status`。
Notebook 见 [`05_wifi_media_export.ipynb`](examples/notebooks/05_wifi_media_export.ipynb)。

`CaptureError.result` 区分失败和结果未知；`CaptureTimeoutError.operation_id` 可继续用于
`media_status()`，不自动重拍。下载逐项报告：主文件成功而gyro缺失/失败或公版legacy
目录无法确认伴随关系时，保留MP4，`main_success=True, complete=False`并列出问题。
长度校验不代表hash校验，无Range续传；每文件最多3次整文件尝试，普通项失败批量继续。
默认不覆盖已有文件，不自动删源。未索引文件不会出现在可操作集合中。

media_import 在交互空档保活约30秒，退出释放所属 HTTP/STA。CTRL失效/取消中止整个会话，
新连接不继承旧录像或导出。LAN 沿用公版可读、可删边界。正常停止等待远端确认；后端
失联时保留未知状态和必要资源，避免冲突拍摄。macOS 长 HTTP I/O 由工作线程处理，调用
主线程持续泵动蓝牙；所有 SDK 方法仍应顺序调用。

## 兼容范围与实机回归（2026-10-16）

协议仍为 EDU v1：`A5 5A` 同步字、版本/seq/LE 长度/CRC16、单帧 990 B 上限，
4 条 SPP UUID/默认通道、8 条命令、4 类事件及音频/图片/OTA 格式保持不变。
8 条命令覆盖拍照、开始/停止录音、传感器、信息、重启、LED、提示音；事件为
BUTTON、KNOB、AUDIO_STATE、IMG_STATE。完整契约见 [PROTOCOL.md](docs/PROTOCOL.md)。
功能按 HELLO_ACK caps 开放；设备没有声明的能力明确报错。

| 组合 / 使用方式 | 兼容与验收边界 |
|---|---|
| SDK 0.2.0 + main EDU `eca5981f` | Mac SDK、CLI、JPEG、WAV、LED/提示音、异常恢复、完整 OTA 与升级后重连通过 |
| 原样旧 SDK `e7142c6` + main EDU | 最终 Mac demo 的 v1 握手、info/sensors、拍照、录音、LED/提示音通过；旧解析器可解析新 OTA 包；首轮已测旧 OTA GET_INFO、坏头拒绝及 REBOOT，未用旧 SDK 完整传输整包 OTA |
| SDK 0.2.0 + 旧 `feat/edu-spp` 固件 | 保留 v1 协议与能力协商，属于兼容设计；本轮未回烧旧固件复测 |
| 原有 Python 接口 | EduClient、AudioStreamClient、ImageClient、transport API 保留；旧 SDK 原文件未反向修改，需要 Mac 独立通道关闭修复时应升级本 SDK |
| 公版 pro 固件 | 不提供 EDU v1 服务，应使用公版 App 的 BLE/绑定/鉴权流程 |
| Windows/Linux/串口 | 保留原传输路径与参数；本轮未做对应实机验收 |

实测环境：LTFTDI07 7036AX **development 开发板**、macOS 27.0、Python 3.13.14、
PyObjC 12.2.2、opuslib 3.0.1 与系统 libopus。SDK 核心提交 `4c972e2`、固件
`eca5981f`；版本字段沿用既有值，请按源提交及 [固件 SHA-256 清单](firmware/README.md) 区分产物。

| 验收项目 | 实测结果 |
|---|---|
| 最终新旧 demo | info/sensors、JPEG、OPUS→WAV、LED/提示音通过；新 JPEG 27,335 B/WAV 2.00 s，旧 JPEG 27,464 B/WAV 2.08 s；均无解码错误 |
| 八项异常恢复 | 缺 IMG、拍照 BUSY、图传断开、拍照时 CTRL 断开、录音时 AUDIO/CTRL 断开、坏 CRC/非法请求、OTA 查询全部通过；无残缺 JPEG，恢复后音频有效 |
| Mac 单通道关闭 | 正常打开顺序下 DISC4/5/7 与 IMG/AUDIO/OTA 对应，CTRL 连续可用；关闭/重开、重复关闭、无效通道补开、工作进程退出及父进程 EOF 清理通过 |
| 连续拍照修复 | 初轮失败已追加固件修复；同会话间隔 4 秒拍四张，JPEG 均校验成功；三次日志确认在旧 5 秒回调到期时保护了新预留 |
| 新包 OTA | 设备拒绝坏头、录音忙时拒绝；首个 16 KiB 后断链续传；1,836,046 B 约 216 s，校验成功并实际重启，结果 0/reboot=1；仅升级 BT |
| 升级后三轮同实例 | 最终 wheel 三轮 connect→info→photo→record→close，3 张 720×960 JPEG、3 份 16 kHz mono/1.84 s 有效 WAV |
| 公版隔离 | 首轮 Samsung SM-A566B 原绑定回连、BLE 鉴权、14 项 RPC、公版拍照/缩略图通过；最后一轮修复后 EDU/pro 双构建及公版预处理等价通过，未重复手机 App 回归 |
| 软件与清理 | 原有 58 项测试、py_compile、wheel 源码一致及独立导入通过；板端 AUDIO/IMG/OTA 全关闭，图传固定频率资源和通道进程已释放，串口空闲 |

JPEG 均通过独立校验，WAV 检查有效非零 PCM；LED/提示音确认的是响应和执行日志。
原始失败与修复后的证据均保留，细节见 [Mac 回归报告](docs/MAC_REGRESSION_20261016.md) 和
[首轮公版/EDU 报告](https://github.com/Entertech/Looktech-Glasses-Device/blob/feat/edu-main-integration/docs/test/edu-integration-hardware-20261016.md)。
原始 HCI/日志和 JPEG/WAV 只保存在本机忽略目录，未随分支上传。

**尚未实测**：首次绑定/解绑、纯 origin/main 烧录 A/B、整机、其他 macOS 版本、
Windows/Linux 蓝牙、实体按键/旋钮、MIC/CALL 切换、灯效听感、功耗/长稳、OTA 断电或
低电量、ISP/WiFi 升级。Mac 默认会话有 3 个通道工作进程，OTA 时最多 4 个；
冻结可执行程序尚未验证。

---

## 1. 环境准备 — macOS

### 1.1 配对眼镜

1. 让眼镜进入配对模式。
2. 系统设置 → 蓝牙 → 连接眼镜。

### 1.2 查找串口（仅串口后备方式需要；推荐直接用 `--bt`）

macOS 优先使用 `--bt` 的 IOBluetooth 路径，不保证系统创建虚拟串口。只有系统或外部适配器
实际提供串口时才使用后备路径。列出候选：

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

  笔记本经 `examples/notebooks/edu_notebook.py` 的薄包装直接调用 SDK，
  不启动 CLI 子进程、不解析人类可读输出。先在仓库根目录安装 `pip install -e .`；
  macOS 仍需主线程执行单元格。教学包装保留 `s.sensors()` 字典与 `knob_delta()`，
  `events()` 的详情为类型化事件，`record()` 返回实际 WAV 或 `.opusraw` 路径。

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
