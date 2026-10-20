# Looktech EDU 眼镜 Python SDK 使用说明

本文面向需要在 PC 程序中调用眼镜能力的开发者，按当前 `feat/edu-sdk-integration`
分支的 SDK 0.2.0 验证候选编写，更新于 2026-10-20。推荐从统一入口
`edu_host.EduSession` 接入；CLI 和 Notebook 也使用这一入口。

## 阅读导航

- [快速开始](#快速开始)：安装、配对、运行第一个程序。
- [连接与能力发现](#连接与能力发现)：平台差异、能力检查、线程约束。
- [信息与传感器](#信息与传感器)、[照片与录像](#照片与录像)、[麦克风录音](#麦克风录音)。
- [事件监听与自定义](#事件监听与自定义)：按键、旋钮及状态事件。
- [WiFi 与媒体导出](#wifi-与媒体导出)：原件下载、结果判定、显式删除。
- [设备控制与升级](#设备控制与升级)、[错误处理](#错误处理)。
- [API 速查](#api-速查)、[CLI 与 Notebook](#cli-与-notebook)、[验收范围与已知边界](#验收范围与已知边界)。

## 快速开始

### 1. 准备设备

需要已烧录 **EDU 固件**的眼镜；公版 pro 固件不提供 EDU SPP 服务。先在操作系统
蓝牙设置中配对 `EDU-Glasses-xxxx`，再运行 SDK。无需手机 App 或公版 App 绑定。
HELLO 用于协商版本和能力，不提供额外用户鉴权。

基础教学能力兼容旧 EDU v1。存储拍照、录像、WiFi 和媒体导出需要当前 EDU 功能固件
（固件源提交 `51a1d390`）及支持公版 ID/BASE/LAN 能力的 ISP。仓库
[`firmware/`](../firmware/README.md) 保留的历史产物不能代替这些新能力检查。

### 2. 安装 SDK

要求 Python 3.9+。当前从集成分支源码安装，尚未发布到 PyPI：

```bash
git clone --branch feat/edu-sdk-integration https://github.com/Entertech/edu-glasses-host.git
cd edu-glasses-host
python3 -m venv .venv
```

macOS/Linux 激活环境：`source .venv/bin/activate`；Windows PowerShell：
`.\.venv\Scripts\Activate.ps1`。激活后按平台安装：

```bash
# Windows / Linux：蓝牙直连使用 Python 标准库
python -m pip install -e .

# macOS：需要 IOBluetooth 绑定，使用这一条
python -m pip install -e '.[macos]'
```

| 可选功能 | 安装方式 | 说明 |
|---|---|---|
| OPUS 转 WAV | `python -m pip install -e '.[audio]'` | 还需系统 libopus；macOS 可用 `brew install opus`，Windows 需可加载的 64 位 `opus.dll` |
| 虚拟串口后备连接 | `python -m pip install -e '.[serial]'` | 仅使用 `ctrl_port` 等参数时需要 |
| 多项可选依赖 | `python -m pip install -e '.[macos,audio]'` | 可组合安装，不改变调用方式 |

macOS 首次运行需允许终端或 Python 宿主访问蓝牙；Windows 建议使用 python.org 的
CPython。若当前 Python 没有蓝牙 socket 支持，可改用虚拟串口后备连接。

### 3. 第一个程序

保存为 `quickstart.py`，在已安装 SDK 的环境运行 `python quickstart.py`：

```python
from edu_host import EduSession

with EduSession(bt="auto") as glasses:
    print("能力：", glasses.capabilities)
    info = glasses.info()
    print("固件：", info.fw_version_str)
    print("电量：", info.battery_level, "充电：", info.charging)
    if glasses.supports("SENSORS"):
        print("传感器：", glasses.sensors())
```

`bt="auto"` 选择已配对的 EDU 设备，多台设备有歧义时会报错。应用中连接固定设备时，
改为 `bt="AA:BB:CC:DD:EE:FF"`，地址从系统蓝牙设置取得。

## 连接与能力发现

`EduSession(...)` 只构造对象，`with` 自动连接并在退出时关闭。需要较长连接等待时，
可显式管理：

```python
from edu_host import EduSession

glasses = EduSession(bt="auto", out_dir="captures")
try:
    glasses.connect(timeout=40)
    print(glasses.hello_ack.proto_ver, glasses.capabilities)
finally:
    glasses.close()
```

一副眼镜只允许一个 CTRL host；运行自己的程序前应关闭占用连接的 CLI/Notebook。
`close()` 会清理所属媒体上下文、尝试停止录像/录音并关闭通道；清理可能等待设备确认，
失联时不能据此宣称远端资源已释放。重连后的会话不接管旧操作。

### 能力检查

先建立连接，再用 `supports("能力名")` 或 `capabilities` 判断。HELLO 能力与实际 ISP
能力是两层检查；新固件能力位齐全仍需 `media_capabilities()` 确认后端支持。

| HELLO 能力 | 对应调用 |
|---|---|
| `PHOTO` | `photo()`、`trigger_photo()`、`wait_photo()`，还需 IMG 通道 |
| `AUDIO_STREAM` | `record()`、`record_start()`、`record_stop()`，还需 AUDIO 通道 |
| `SENSORS` | `sensors()` |
| `INPUT_EVENTS` | 按键/旋钮事件 |
| `CONTROL` | `set_led()`、`play_tone()`、`reboot()` |
| `WIFI` | `wifi_capabilities()`、`wifi_scan()`、配网和状态查询 |
| `SAVED_PHOTO` + `MEDIA_CATALOG` | `capture_saved_photo()` |
| `VIDEO` + `MEDIA_CATALOG` | `video_start()`、`video_stop()`、`video_status()` |
| `MEDIA_CATALOG` + `WIFI` | `media_import()`；真实媒体能力由 ISP 查询确认 |

OTA 通过独立服务发现，没有专门的 HELLO OTA 能力位。能力或必要通道缺失时 SDK
抛出 `EduUnsupportedError`，不要通过固件版本显示字符串推断所有能力。

### 平台、线程与持续收包

- macOS 的连接、请求、`poll()`、等待和关闭都在**进程主线程**调用；SDK 自行管理
  原生蓝牙通道。Windows/Linux 默认 RFCOMM 通道为 CTRL=6、AUDIO=5、IMG=4、OTA=7；
  macOS 通过 SDP 查询。通常不需要修改通道参数。
- 一个会话内顺序调用 SDK。空闲、录音或等事件时使用 `glasses.wait(seconds)` 或
  `glasses.poll(0.05)`，避免用 `time.sleep()` 或阻塞式 `input()` 长时间停住收包。
- `EduSession` 的事件/图片回调在调用者线程分发。回调只做记录或排队，不在回调中
  发设备请求；GUI/其他线程将请求排队，由 SDK 所在线程执行。
- SDK 已处理长 HTTP 下载期间的蓝牙轮询，应用不需要自行将媒体下载移到另一个
  SDK 调用线程。

虚拟串口后备可用
`EduSession(ctrl_port="COM5", audio_port="COM6", img_port="COM7", ota_port="COM8")`。
这些应是各 SPP 服务对应的蓝牙虚拟串口，不是整机烧录/日志 USB 串口。

## 信息与传感器

```python
from edu_host import EduSession

with EduSession(bt="auto") as glasses:
    info = glasses.info()
    print(info.fw_version_str, info.battery_level, info.charging)
    if glasses.supports("SENSORS"):
        data = glasses.sensors()
        print(data.als_raw, data.battery_temp_c, data.btcore_temp_c)
```

`battery_level` 为百分比；`als_raw` 是光敏原始计数，**不是 lux**。
`battery_temp_c` 和 `btcore_temp_c` 分别是电池温度和蓝牙芯片结温，单位 ℃，
不能当作环境温度。`info()`/`sensors()` 默认请求超时均为 5 秒。

## 照片与录像

### 先选择所需接口

| 目的 | 调用 | 传输/保存位置 | 返回成功的含义 |
|---|---|---|---|
| 教学图片分析、小图回传 | `photo()` | JPEG 经 IMG SPP 传到 PC | 完整 JPEG 已写入 PC 文件 |
| 保存原片 | `capture_saved_photo()` | 原片保存在眼镜，随后 WiFi 导出 | 公版拍照控制状态 DONE |
| 录制视频 | `video_start()` / `video_stop()` | MP4 保存在眼镜，随后 WiFi 导出 | 公版 RECORDING / DONE 控制状态 |

`photo()` 不等于保存原片；麦克风 `record()` 也不等于录像。拍摄灯效由固件公共
能力管理，不需要额外调用 `set_led()` 模拟。

### 教学 JPEG 回传

```python
from edu_host import EduSession

with EduSession(bt="auto", out_dir="captures") as glasses:
    path = glasses.photo("lesson.jpg", timeout=30)
    print("已落盘：", path)
```

返回 `pathlib.Path`。相对文件名相对会话 `out_dir`，绝对文件名按绝对路径保存。
传入固定文件名可能覆盖该文件，重复采集应使用不同名称或让 SDK 自动命名。
异步拆分调用为 `trigger_photo(filename)` 后 `wait_photo(timeout=30)`；ACK 或
`ImgStateEvent` 的 DONE 不能替代完整 JPEG 落盘判定。

### 保存原片与录像

```python
from edu_host import EduSession, EduUnsupportedError

with EduSession(bt="auto") as glasses:
    required = ("SAVED_PHOTO", "VIDEO", "MEDIA_CATALOG")
    if not all(glasses.supports(name) for name in required):
        raise EduUnsupportedError("当前固件不支持存储拍照/录像")
    print("实际媒体能力：", glasses.media_capabilities())
    photo = glasses.capture_saved_photo(timeout=45)
    print("照片控制结果：", photo.operation_id, photo.state.name)

    video = glasses.video_start(timeout=20)
    try:
        glasses.wait(5)
    finally:
        stopped = glasses.video_stop(video.operation_id, timeout=45)
        print("视频控制结果：", stopped.state.name)
```

返回 `CaptureResult(operation_id, kind, state, error)`，`kind` 为 1 照片、2 视频。
`operation_id` 仅用于当前 CTRL owner 的控制状态查询，**不是媒体 ID**；同种媒体只
保留最近一个操作状态。`media_status(photo.operation_id)` 查询照片或视频，
`video_status(video.operation_id)` 查询视频；省略视频 ID 时使用本会话最近的录像操作。

`CaptureState` 包含 STARTING、RECORDING、STOPPING、DONE、FAILED、UNKNOWN。
公版 DONE/RECORDING 不保证原件已发布、首帧已写入，也不会精确返回本次拍摄的媒体 ID。
导出时从真实媒体列表选择；暂未出现时重新查询，不能按“最新文件”或最大 ID 猜测归属。
UNKNOWN/超时不代表没有拍摄，SDK 不自动重拍；状态处理见[错误处理](#错误处理)。

## 麦克风录音

```python
from edu_host import EduSession

with EduSession(bt="auto", out_dir="captures") as glasses:
    actual_path = glasses.record_start("lesson.wav")
    try:
        glasses.wait(5)
    finally:
        stats = glasses.record_stop()
    print(actual_path, stats.output_path, stats.seconds)
    print(stats.decoded_to_wav, stats.frames_written, stats.lost_packages)
```

一次性调用为 `glasses.record("lesson.wav", seconds=5)`，返回实际文件路径。
音频为 16 kHz 单声道；缺少 opuslib/libopus 时保存 `.opusraw`，以实际返回路径为准，
不要只根据传入的 `.wav` 后缀判断格式。没有有效帧时 `record_stop()` 会报错。
`AudioStateEvent.source_name` 表示 MIC/CALL，是否切换或暂停沿用固件行为。
`is_recording` 指麦克风推流状态；录像状态使用 `video_status()`。

## 事件监听与自定义

`EduSession` 只分发事件，不自动把按键绑定到拍摄。应用可以自行决定每个事件对应的
业务动作，但不能改变物理按键已经包含的固件本地音量/通话/配对行为。

| 类型 | 主要字段 | 用途 |
|---|---|---|
| `ButtonEvent` | `btn`、`action`、`btn_name`、`action_name` | AI、CAPTURE、MEDIA 键的动作 |
| `KnobEvent` | `direction_name`、`delta_x`、`delta_y` | 旋钮/滑动输入 |
| `AudioStateEvent` | `running`、`source_name`、`err` | 音频运行、来源和错误 |
| `ImgStateEvent` | `capture_evt_name`、`error` | 教学图传状态，不能替代完整文件结果 |

短按会出现 PRESS、RELEASE、SHORT、SINGLE；需要单击语义时只处理 SINGLE，避免
SHORT/SINGLE 重复触发。长按还会有 REPEAT、LONG_RELEASE。枚举 `ButtonId`、
`KeyAction` 从 `edu_host.protocol` 导入，完整动作见[协议事件表](PROTOCOL.md#4-事件evt)。

下面的示例将右侧单击转换为应用请求，由回调外的主循环处理。示例只打印业务请求，
开发者可在标记处接入自己的功能：

```python
from queue import Empty, Queue
from edu_host import ButtonEvent, EduSession, KnobEvent
from edu_host.protocol import ButtonId, KeyAction

requests = Queue()

def on_event(event):
    if isinstance(event, ButtonEvent):
        if event.btn == ButtonId.CAPTURE and event.action == KeyAction.SINGLE:
            requests.put("right_single")
    elif isinstance(event, KnobEvent):
        requests.put(("knob", event.direction_name, event.delta_x))

try:
    with EduSession(bt="auto") as glasses:
        glasses.add_event_listener(on_event)
        while glasses.is_connected:
            glasses.poll(0.05)
            try:
                request = requests.get_nowait()
            except Empty:
                continue
            print("处理应用请求：", request)  # 在此处顺序调用需要的 SDK 方法
except KeyboardInterrupt:
    pass
```

一次性收集可用 `glasses.events(10)`，它等待 10 秒后返回事件列表，不是流式生成器。
图片回调为 `add_image_listener(callback)`，参数 `(path, CompletedImage)`，完整图片已落盘
后触发。以上约束针对 `EduSession`；直接使用旧底层 `EduClient` 时线程模型不同。

参考 CLI 已提供完整拍摄映射：右侧 SINGLE 保存照片、LONG 开录像、录像中再次 PRESS
停止，并处理去重及配对窗口。复用时参照 [`CaptureButtons`](../demo_cli.py)，不要把
同步拍摄请求直接放进事件回调。demo 关闭或 SPP 断开后，EDU 不会在本地自动拍摄。

## WiFi 与媒体导出

### 网络与凭据

SPP 负责配网、控制和查询真实媒体身份，JPEG/MP4 原件通过 WiFi LAN HTTP 下载。
PC 与眼镜应处于互通的局域网，PC 可用有线网络，不需要手机 App 或互联网。
实际频段及安全类型以硬件和 `wifi_capabilities()` / `wifi_scan()` 结果为准。

本地创建 `wifi.json`，填写实际网络信息，不提交到版本库：

```json
{
  "ssid": "YOUR_WIFI_SSID",
  "security": "WPA2",
  "password": "YOUR_WIFI_PASSWORD"
}
```

`security` 取 `WifiSecurity` 枚举名称：OPEN、WEP、WEP_SHARED、WPA、WPA2、WPA3，
实际可用值由设备返回；开放网络使用 OPEN 和空密码。SSID 为 1–32 个 UTF-8 字节、
密码最多 64 字节，均不能含 NUL，安全类型和密钥还需后端校验。不要打印完整凭据。

### 列出并下载原件

```python
import json
from pathlib import Path
from edu_host import EduSession, WifiSecurity

credentials = json.loads(Path("wifi.json").read_text(encoding="utf-8"))
security = WifiSecurity[credentials["security"].upper()]

def on_progress(media_id, filename, received, total):
    print(media_id, filename, received, "/", total)

with EduSession(bt="auto") as glasses:
    print("实际媒体能力：", glasses.media_capabilities())
    with glasses.media_import(credentials["ssid"], credentials["password"], security) as media:
        items = media.list()
        for item in items:
            print(item.media_id, item.kind, item.file.name, item.file.size)
        # 批量导出本次列表中的全部已索引媒体；不会自动删除设备原件
        results = media.download_all("exports", progress=on_progress)
        for result in results:
            print(result.media.media_id, result.main_success, result.complete)
            print("文件：", result.files, "问题：", result.errors)
```

`media_import()` 创建上下文，进入 `with` 时才执行配网、启动服务并查询目录。
同一会话只允许一个媒体上下文；拍照/录像与导入应顺序执行，先停止录像再导出。
上下文有效时 SDK 在空闲约 30 秒后发 HTTP 活动保活，退出或 CTRL 失效时清理所属
HTTP/STA；停止未确认时设备可能暂时保持 BUSY。不要另外启动重复配网或保活循环。

`media.list()` 返回 `tuple[MediaItem, ...]`，只包含真实 ID 的照片/视频；没有 ID 的
文件不会列出，也不允许路径回退。媒体身份按 `catalog_id + media_id` 区分，
`revision` 用于检查描述变化；不要跨目录或跨会话盲用缓存条目。列表不是原子快照。

单项下载使用 `media.download(item, "exports")`，也支持当前目录中的整数
`media_id`。传入 `MediaItem` 可以检查所选描述是否变化。相对导出目录相对进程当前
工作目录，独立于 `EduSession.out_dir`。选择集合应由业务决定，不能从操作 ID 推算媒体 ID。

### 结果、重试和取消

| 结果 | 正确处理 |
|---|---|
| `main_success=True, complete=True` | 主文件和可确认所需伴随文件均成功，使用 `files` 中路径 |
| `main_success=True, complete=False` | 主文件可用；伴随数据缺失、下载失败或无法确认关系，读取 `errors` |
| `main_success=False` | 主文件未成功；本项失败，不能当成导出完成 |

视频导出的是设备 MP4 原件及可确认登记的 gyro 等伴随文件，不包含 App 后处理或
防抖成片。公版 HTTP 列表退为 legacy 时仍可通过 SPP 列出真实媒体 ID，但可能无法
确认视频伴随关系；此时保留可用 MP4 并报告 `complete=False`，不猜同名伴随文件。

SDK 校验 HTTP 状态、Content-Length、实际字节数，并在下载前后重核媒体描述；
通过临时文件提交，默认不覆盖已有文件。每个文件最多尝试 3 次，失败从头下载，
不支持 Range 续传或设备内容哈希校验；不能将本地计算哈希当成端到端身份校验。
已成功导出过同名文件时，换一个导出目录或由应用明确处理已有文件。

`download_all()` 固定调用时的选择集合，普通单项失败后继续并逐项返回结果；
CTRL 失效、取消、目录/所属会话失效会抛出会话级错误并终止，已经提交的文件保留。
进度回调参数为 `(media_id, filename, received, total)`，在调用者线程分发，
重试时 `received` 会重新从头累计，不要在其中重入 SDK。

需要取消时调用 `media.cancel()`，随后下载抛 `MediaCancelled` 并结束所属会话；
也可在进度回调中设置取消。取消后的上下文不能继续使用，应退出 `with` 再重新建立。

### 显式删除

下载默认保留原件。只有应用明确决定删除时才调用 `media.delete(item)` 或
`media.delete(media_id)`。下面仅定义函数，不在导出示例中自动调用：

```python
from edu_host import MediaImport, MediaItem

def delete_selected(media: MediaImport, item: MediaItem):
    result = media.delete(item)
    print(result.media_id, result.deleted, result.already_absent)
    return result
```

删除沿用公版按 ID 删除及登记伴随文件的范围，不保证事务原子性；失败需重新核实，
不能因列表里消失就断言整组文件已删除。`already_absent=True` 表示实际删除端点返回
不存在。SDK 不提供无 ID、音频或任意路径删除。LAN 服务继承公版可读、可删边界，
没有额外 PC token，部署时应选择允许这一访问范围的网络。

### 单独配网和诊断

仅诊断网络时，可顺序使用 `wifi_capabilities()`、`wifi_scan(timeout=30)`、
`wifi_connect(ssid, password, security, timeout=70)`、`wifi_status()`、
`wifi_disconnect()`。`wifi_connect()` 返回 `WifiStatus`，等待 CONNECTED/SERVING；
单独 CONNECTED 不代表 HTTP 已启动。导出优先使用 `media_import()` 管理完整生命周期。
`wifi_disconnect()` 表示停止请求已受理，实际终态用 `wifi_status()` 确认。

## 设备控制与升级

### LED、提示音、重启

```python
from edu_host import EduSession, LedColor, LedId, LedMode, LedSpeed, Tone

with EduSession(bt="auto") as glasses:
    glasses.set_led(LedId.INNER, LedMode.BLINK, LedColor.GREEN, LedSpeed.NORMAL)
    glasses.play_tone(Tone.CLICK)
    glasses.wait(1)
    glasses.set_led(LedId.INNER, LedMode.OFF)
    # 需要重启时单独调用 glasses.reboot()；受理后约 0.5 秒断开
```

外灯不支持颜色选择。手动 LED 是尽力设置，配对/拍摄等业务可覆盖它；OFF 将灯交回
固件自动管理。拍照/录像正常灯效应直接由拍摄能力驱动。提示音用 `Tone` 枚举或
`play_tone("click")`，设备不接受的编号会返回错误。

### OTA

`glasses.ota(package_path, progress=callback)` 使用独立 OTA SPP 服务。升级输入必须是
固件维护者提供、与设备匹配的 **Looktech OTA 外层 `.bin`**，不是 `.wpk` 或 BT 内包。
先停止录像/录音、等待拍照完成并退出媒体导入，再升级；升级期间不调用其他设备能力。

```python
from edu_host import EduSession

def upgrade(glasses: EduSession, package_path):
    def progress(stage, done, total):
        print(stage, done, total)
    result = glasses.ota(package_path, progress=progress)
    print(result)
    return result
```

升级包先在本地校验，再开 OTA 通道；返回 `UpdateResultResponse`。升级完成可能重启
并断开连接，待完整启动后重新连接检查能力与版本。`ota()` 没有通用 `timeout` 参数；
通常保留默认分块大小和间隔。不要将历史基础固件包当作当前扩展能力的升级包。

## 错误处理

| 异常 | 可读取的信息 | 应用处理 |
|---|---|---|
| `EduUnsupportedError` | 缺少能力或通道 | 提示匹配固件/通道，不重复发送同一请求 |
| `EduStatusError` | `cmd_id`、`status`、`data` | 用 `edu_host.protocol.Status` 区分 BUSY/INVALID/NOT_READY/ERROR；待条件恢复后由业务决定重试 |
| `CaptureTimeoutError` | `operation_id` | 保留操作 ID 查询，不能自动重拍或重复开录像 |
| `CaptureError` | `result`，含 UNKNOWN/FAILED | 根据真实状态处理；UNKNOWN 不等于已经停止 |
| `EduTimeoutError` | 请求或图片等待超时 | 可能已执行；先查询或核实，不盲重发 |
| `WifiError` | `code` | 核实网络、安全类型及后端错误，完整码表见协议 |
| `MediaError` | 单项操作问题 | 检查结果/描述；已成功文件保留 |
| `MediaSessionError` / `MediaCancelled` | 所属会话失效或取消 | 结束上下文，明确重新建立后再操作 |
| `AmbiguousGlassesError` | 多设备歧义 | 指定蓝牙地址 |
| `OSError` / `ValueError` | 连接/本地文件问题、无效参数 | 检查系统状态、路径、输入 |
| `OTAError` 及其子类 | 独立 OTA 错误 | 单独处理，不能只捕获 `EduClientError` |

异常均可从 `edu_host` 导入；`CaptureTimeoutError` 继承 `EduTimeoutError`，
`MediaCancelled` 继承 `MediaSessionError`，后者继承 `MediaError`，这些异常最终继承
`EduClientError`。因此先捕获具体异常，再捕获通用异常。

保留拍照超时的操作 ID，例如：

```python
from edu_host import CaptureError, CaptureTimeoutError, EduClientError, EduSession

with EduSession(bt="auto") as glasses:
    try:
        result = glasses.capture_saved_photo()
        print(result)
    except CaptureTimeoutError as exc:
        print("结果未知，保留 operation_id：", exc.operation_id)
        # 后续在同一有效 CTRL 会话查询 glasses.media_status(exc.operation_id)
    except CaptureError as exc:
        print("真实拍摄状态：", exc.result.state.name, exc.result.error)
    except (EduClientError, OSError) as exc:
        print("本次请求失败：", exc)
```

实际应用还应在连接这一层处理错误。设备返回 BUSY 时无需绕过共享准入；先完成或
停止当前业务。记录错误可启用标准库 `logging`，不要记录网络密码或完整配网帧。

## API 速查

下表只列公共接入接口；不建议直接依赖 `_request`、`_client` 等私有实现。所有方法
顺序调用；未标明类型的详细字段见上文及对应数据类。

| 入口 | 返回 / 作用 |
|---|---|
| `EduSession(bt="auto", *, out_dir="captures", ...)` | 创建会话，构造不连接；串口/通道参数见连接章节 |
| `connect(timeout=6)` / `close()` | 返回当前会话 / 关闭所属资源 |
| `is_connected` / `hello_ack` | 连接状态 / `HelloAck`，关闭后 ack 为 None |
| `capabilities` / `supports(name_or_bits)` | 能力名称元组 / bool，需已连接 |
| `info(timeout=5)` / `sensors(timeout=5)` | `DeviceInfo` / `SensorData` |
| `photo(filename=None, timeout=30)` | `Path`，完整教学 JPEG 已写入 PC |
| `trigger_photo(filename=None, timeout=5)` / `wait_photo(timeout=30)` | 受理 `Response` / 完整图片 `Path` |
| `capture_saved_photo(timeout=45)` | `CaptureResult`，原片保存的公版控制状态 |
| `media_status(operation)` | `CaptureResult`，同 owner 最近操作的当前状态 |
| `video_start(timeout=20)` | `CaptureResult`，等待 RECORDING 或实际终态 |
| `video_stop(operation=None, timeout=45)` / `video_status(operation=None)` | `CaptureResult`；省略 ID 使用最近录像操作 |
| `record(filename, seconds, timeout=5)` | 实际音频文件 `Path` |
| `record_start(filename="record.wav", timeout=5)` / `record_stop(timeout=5)` | 实际路径 / `AudioStats` |
| `is_recording` | 麦克风推流状态，不代表视频录像 |
| `add_event_listener(callback)` / `add_image_listener(callback)` | 注册类型化回调 |
| `poll(seconds=0.05)` / `wait(seconds)` / `events(seconds)` | 本次事件列表 / 持续收包 / 时间窗口事件列表 |
| `wifi_capabilities()` / `wifi_scan(timeout=30)` | `WifiCapabilities` / `tuple[WifiNetwork, ...]` |
| `wifi_connect(ssid, password="", security=WifiSecurity.WPA2, timeout=70)` | `WifiStatus`，已入网 |
| `wifi_status()` / `wifi_disconnect()` | `WifiStatus` / 请求停止，实际终态需查询 |
| `media_capabilities()` | `MediaCapabilities(schema_version, catalog_id, features)`，查询真实 ISP |
| `media_import(ssid, password="", security=WifiSecurity.WPA2)` | `MediaImport`，使用上下文管理 |
| `media.list()` | `tuple[MediaItem, ...]` |
| `media.download(media, directory="captures", progress=None)` | 单项 `DownloadResult`；media 为 ID 或 `MediaItem` |
| `media.download_all(directory="captures", progress=None)` | `tuple[DownloadResult, ...]` |
| `media.delete(media)` | `DeleteResult`，显式设备删除 |
| `media.cancel()` / `media.close()` | 取消在途下载 / 结束导入并请求清理 |
| `set_led(led, mode, color=LedColor.WHITE, speed=LedSpeed.NORMAL, timeout=5)` | 控制 `Response` |
| `play_tone(tone=Tone.CLICK, timeout=5)` / `reboot(timeout=5)` | 控制 `Response` |
| `ota(filename, progress=None, chunk_size=512, packet_interval_ms=10)` | `UpdateResultResponse` |

已有自定义传输实现可用 `EduSession.from_transports(ctrl, audio=None, image=None,
ota=None, out_dir="captures")`；普通接入优先使用蓝牙地址或串口参数。

## CLI 与 Notebook

安装后可运行 `edu-glasses --bt auto`，或在源码目录运行
`python demo_cli.py --bt auto`。CLI 用于体验和诊断，应用开发直接调用 SDK，不解析 CLI
打印文本。输入 `help` 查看命令；完整右侧按键映射见 [README](../README.md#cli-右侧按键拍摄)。

| CLI 命令 | SDK 对应 |
|---|---|
| `info` / `sensors` | `info()` / `sensors()` |
| `photo [out.jpg]` | 教学 JPEG 回传 |
| `photo-save` | `capture_saved_photo()` |
| `video start\|stop\|status` | 录像控制和查询 |
| `record start [out.wav]` / `record stop` | 麦克风录音 |
| `wifi caps\|scan\|status\|disconnect` / `wifi connect <wifi.json>` | WiFi 诊断和入网 |
| `media caps` / `media open <wifi.json>` / `media list` | 真实媒体能力和导入上下文 |
| `media download <id\|all> [directory]` / `media delete <id>` / `media close` | 下载、显式删除、退出 |
| `led ...` / `tone ...` / `reboot` / `ota <firmware.bin>` | 对应控制接口 |

教学 Notebook 位于 [`examples/notebooks/`](../examples/notebooks/)，包含图片分析、
录音分析、实时传感器、旋钮事件及 [`05_wifi_media_export.ipynb`](../examples/notebooks/05_wifi_media_export.ipynb)。
`edu_notebook.EduSession` 为教学薄包装：构造时自动连接，`sensors()` 返回字典、
`events()` 返回带种类的二元组列表；普通应用优先用本文 `edu_host.EduSession`，避免
混用两种返回值约定。Notebook 也应按顺序执行，结束后调用 `close()`。

## 验收范围与已知边界

当前 SDK 功能基线为 `6f147e5`，BT 功能基线 `51a1d390`，ISP 保持公版。协议仍为
EDU v1，使用新增能力位发现存储拍摄和 LAN 扩展；旧固件缺少扩展时应明确拒绝。
这些是功能分支验证候选，尚未合并两仓库 main 或形成正式发布版本。

- 2026-10-20 macOS + semi 实机已验证存储照片、录像启停、真实 ID/元数据、JPEG/MP4
  及登记 gyro 导出、显式删除、下载 TCP 中断重试和取消；按键拍照/录像及灯效由用户确认。
  CTRL 断连后底层录像清理与新 owner 隔离已有实测。
- 基础教学 JPEG、录音、传感器、LED/提示音及历史 OTA 证据见
  [2026-10-16 回归报告](MAC_REGRESSION_20261016.md)；不能将历史 OTA 或 TCP 中断测试
  外推为当前固件完整 OTA/断电、无线掉线或系统保护矩阵全部通过。
- Windows/Linux、配对保护、录像自动结束、启动中停止，以及通话/低电/充电/OTA
  冲突的完整矩阵尚未覆盖；这些验证按当前决策暂缓，不在本轮文档任务中补做。
- 已知问题：存储照片 DONE 后立即调用教学小图，曾触发公版 ISP `0x92` 并导致
  TIMEOUT/后续 BUSY；当前尚未修复。不要将混合快速连续调用视为已支持，也不保证
  用固定延迟即可规避。

完整线协议与状态码见 [PROTOCOL.md](PROTOCOL.md)；固件设计及设备验收记录见
[固件规格第 14 节](https://github.com/Entertech/Looktech-Glasses-Device/blob/feat/edu-main-integration/docs/plans/stereo-edu-spp-firmware.md)。
