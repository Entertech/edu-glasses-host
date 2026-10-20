# EDU SPP 协议规格（教育版固件）

面向学生 host 开发的完整线协议说明。
除非特别说明，所有多字节字段均为**小端（LE）**。

## 1. SPP 服务

先在操作系统层完成经典蓝牙配对（设备名 `EDU-Glasses-xxxx`），然后按服务连接：

| 服务 | SPP UUID (16-bit) | 方向 | 内容 |
|---|---|---|---|
| EDU-CTRL | `0x2028` | 双向 | 命令/响应/事件/传感器 |
| EDU-AUDIO | `0x2024` | 设备→host | OPUS 音频流（recordsv 包格式） |
| EDU-IMG | `0x2025` | 设备→host | 拍照 JPEG（原生 air-img 子帧流） |
| OTA | `0x2026` | 双向 | 固件升级（现有 OTA 协议） |

耳机功能（A2DP 音乐/HFP 通话/AVRCP 控制）走操作系统蓝牙音频，无需本协议。
EDU-CTRL 为单 host 通道：已有 host 连接时，第二台设备的连接会被立即断开。

## 2. EDU-CTRL 帧格式

```
| 0xA5 | 0x5A | ver(1)=0x01 | type(1) | seq(1) | len(2 LE) | payload(len) | crc16(2 LE) |
```

- 单帧总长 ≤ 990 字节（payload ≤ 981）。
- `crc16` 覆盖 `ver` 到 payload 末尾（不含同步字节与 CRC 本身）。
- CRC 校验失败或 len 非法时接收方丢弃并重新搜索同步字。

### CRC16 算法（CRC-16/CCITT-FALSE，多项式 0x1021，初值 0xFFFF）

```python
def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc = ((crc >> 8) | (crc << 8)) & 0xFFFF
        crc ^= b
        crc ^= (crc & 0xFF) >> 4
        crc ^= (crc << 12) & 0xFFFF
        crc ^= ((crc & 0xFF) << 5) & 0xFFFF
    return crc
```

### 帧类型

| type | 名称 | 方向 | payload |
|---|---|---|---|
| 0x01 | HELLO | host→设备 | `host_ver(1)` |
| 0x02 | HELLO_ACK | 设备→host | `proto_ver(1)=1, fw_version(8 LE), caps(2 LE)` |
| 0x10 | CMD | host→设备 | `cmd_id(1) + args` |
| 0x11 | RSP | 设备→host | `cmd_id(1) + status(1) + data`；seq 回显 CMD 的 seq |
| 0x20 | EVT | 设备→host | `evt_id(1) + data` |

图片不走本通道（见 §5）。caps 位：bit0 音频流、bit1 拍照、bit2 传感器、bit3 输入事件、bit4 控制（重启/LED/提示音）；bit5..7 扩展见 §3.1。

### status 码

`0x00` OK ｜ `0x01` BUSY ｜ `0x02` INVALID ｜ `0x03` NOT_READY ｜ `0xFF` ERROR

## 3. 命令

| cmd_id | 命令 | args | RSP data |
|---|---|---|---|
| 0x01 | TAKE_PHOTO | 无 | 无（status=OK 表示已受理；图片经 EDU-IMG 0x2025 通道异步到达，过程状态见 IMG_STATE 事件；status=ERROR 时 data[0]=错误码） |
| 0x02 | AUDIO_START | 无 | 无（开始推流后收到 AUDIO_STATE{running}） |
| 0x03 | AUDIO_STOP | 无 | 无 |
| 0x04 | GET_SENSORS | 无 | `als_raw(2 LE), battery_temp(1, int8 ℃), btcore_temp(2 LE, int16 ℃)` |
| 0x05 | GET_DEVICE_INFO | 无 | `fw_version(8 LE), battery_level(1, %), charging(1)` |
| 0x06 | REBOOT | 无 | 无（status=OK 后约 0.5 s 设备重启，蓝牙断开属预期） |
| 0x07 | SET_LED | `led_id(1), mode(1), color(1), speed(1)` | 无 |
| 0x08 | PLAY_TONE | `tone_event(1)` | 无 |

说明：
- `als_raw` 为 STK3A8X 光敏原始 16-bit 计数值，**非 lux**；数值越大环境越亮。
- `battery_temp` 为电池 NTC 温度；`btcore_temp` 为蓝牙 SoC 结温。设备没有独立环境温度计。
- TAKE_PHOTO 在 ISP 睡眠时会自动唤醒并缓存执行（可能有数秒延迟）；忙碌时返回 BUSY。
- GET_SENSORS 的 RSP 偶尔可能延迟约 200 ms（光敏传感器重新使能后需等一个积分周期）。
  host 请求超时建议 ≥2 s。

SET_LED 取值：`led_id` 0=内部 RGB / 1=外侧指示灯（外侧不支持颜色）；`mode`
0=off / 1=on / 2=blink / 3=breath（off 同时把灯交还固件自动控制）；`color`
0=红 1=绿 2=蓝 3=橙 4=紫 5=白；`speed` 0=慢 1=中 2=快（仅 blink/breath）。
注意：固件的业务状态（配对/拍照/录音等指示）随时可能收回 LED——手动设置是
**尽力而为**，被覆盖后重发命令即可。

PLAY_TONE 的 `tone_event` 为设备内置提示音编号，常用值：0 开机、2 进入配对、
3 蓝牙已连接、11 拍照咔嚓（capturing）、12 拍照完成、27 开始录音、28 停止
录音、29 短促点击（click）。无效编号返回 INVALID。完整可用值 0–29。


### 3.1 存储拍摄与 LAN 导出扩展

此扩展保留 v1、11B HELLO_ACK、990B 帧和旧命令。caps 新增 bit5 WIFI、bit6
SAVED_PHOTO、bit7 VIDEO；这些位表示 BT 入口存在，使用前仍查询真实 ISP 能力。
原 TAKE_PHOTO 返回教学小图，AUDIO_START/STOP 仍为音频推流。

| cmd_id | 命令 | args | RSP data（外层 status=OK） |
|---|---|---|---|
| 0x20 | WIFI_EXECUTE | `operation u8 + operationArgs` | `operation u8 + kind u8 + outcome` |
| 0x21 | SAVED_PHOTO | 无 | `operationId u32`，仅表示受理 |
| 0x22 | VIDEO_START | 无 | `operationId u32`，仅表示受理 |
| 0x23 | VIDEO_STOP | `operationId u32` | `operationId u32`，仅表示停止受理 |
| 0x24 | MEDIA_STATUS | `operationId u32` | `operationId u32, kind u8, state u8, error u8, catalogId u64, mediaId u64, revision u32`（27B） |
| 0x25 | MEDIA_CAPS | 无 | `schemaVersion u8=1, catalogId u64, features u32`（13B） |
| 0x26 | MEDIA_DESCRIPTOR | `operationId u32` | `operationId u32, revision u32, size u64, nameLength u16, pathLength u16, name UTF-8, path UTF-8` |

所有多字节字段均 LE。operationId 由共享能力生成，不等于 EDU seq，仅当前 CTRL
owner 可查询/停止。MEDIA_STATUS 的 kind 为 1 照片、2 视频；state 为 1 STARTING、
2 RECORDING、3 STOPPING、4 PUBLISHED、5 SAVED_UNPUBLISHED、6 FAILED、7 UNKNOWN。
PUBLISHED 必须 error=0，且 catalogId/mediaId/revision 均非零；其他状态不提供可导出
身份。UNKNOWN 表示完成结果未知，不能据此认定未保存或资源已释放。迟到的真实发布
仍可被查询；设备不自动重拍。后端失联且未证明停止时继续阻止冲突启动。

MEDIA_DESCRIPTOR 只接受本 owner 已 PUBLISHED 的操作，重新确认 catalog 后查实际
元数据。SDK 的存储拍摄等待方法在 PUBLISHED 后取得描述才返回；描述失败单独报错，
不重拍。描述中的 revision 可能因缩略图更新而晚于发布通知。
MEDIA_CAPS 的 features 继承 ISP bit0..6；bit7 表示精确操作发布结果及结果查询，
bit8 表示独立已索引 HTTP 目录。旧 ISP 缺相关位时明确不支持，不能根据 WiFi v3 推断。
当前通过 MEDIA_STATUS 查询状态，旧 IMG_STATE 继续只服务教学小图。

WIFI_EXECUTE 操作及参数：

| operation | 含义 | operationArgs |
|---|---|---|
| 2 | CAPS | 无 |
| 3 | SCAN | `offset u32`，首请求 0 |
| 7 | CONNECT | `security u8, ssidLength u8, passwordLength u8, ssid, password` |
| 8 | START_MEDIA | 无 |
| 9 | STATUS | 无 |
| 10 | DISCONNECT | 无 |

SSID 为 1..32 个 UTF-8 字节，密码最多64字节，均不含 NUL；不记录原始配网帧。
security：0 不支持、1 OPEN、2 WEP、3 WEP_SHARED、4 WPA、5 WPA2、6 WPA3。
CAPS 返回真实支持的位图；OPEN 无密码，WEP/WEP_SHARED 长度为5/10/13/26，WPA
类由后端继续校验。kind 与 outcome：

| kind | outcome |
|---|---|
| 0 CAPS | `version u32, securityMask u8`（bitN 对应 security=N） |
| 1 SCAN | `complete u8, nextOffset u32, hasMore u8, count u8`；接 count 项，每项 `ssidLength u8, ssid, channel u32, rssi i32, security u8`，count≤5 |
| 2 STATUS | `stage u8, failure u8, catalogId u64, port u16, ipv4[16], ssidLength u8, ssid, security u8`；ipv4 为 NUL 填充数值 IPv4 |
| 3 DONE | 无；CONNECT/START_MEDIA/DISCONNECT 的受理结果 |
| 4 ERROR | `error u8` |

CONNECT/START_MEDIA 的 DONE 不是入网/服务就绪。继续 STATUS，stage 为0 IDLE、1
SCANNING、2 CONNECTING、3 DHCP、5 CONNECTED、6 SERVING、7 STOPPING、8 FAILED。
仅 SERVING 且实际 IPv4、port、非零 catalogId 齐备时开始 HTTP。STOPPING 保留 owner，
直到真实停止确认。外层 OK 仅表示 WiFi 结果已映射，kind4 或 stage8 仍为业务失败。
WiFi error：1 unsupported、2 invalid、3 busy、4 scan、5 auth、6 connection、7 DHCP、
8 storage、10 not-found、11 stale、12 HTTP、13 timeout、14 cancelled、15 protected。

### 3.2 HTTP 与媒体身份

`GET /media/catalog` 返回真实 DB 已索引目录（`catalogId`、`image`、`video`、`gsensor`
等）；主条目含 `id`、`metadataRevision`、`name`、`path`、整数 `size`。该入口不因未索引
文件降级；不支持/DB失败明确报错。原公版 `GET /` 保持原行为。

SDK 只接受照片/视频的真实 ID。gyro 按 `parentMediaId` 与 `metadataRevision` 关联；
`motionRequired=true` 而 gyro 未登记或缺失时保留 MP4 并报告不完整。下载使用经验证的
`/customer/bt_res/{image,video,gsensor}/文件名` 描述，整文件 GET 200，无 Range 续传或
内容哈希保证。长度匹配后原子提交本地文件；默认不覆盖、不删除设备原件。每文件最多
3次整文件尝试，批量固定选择并逐项返回；CTRL失效或取消终止整个会话。

`DELETE /media?id=<真实ID>` 是独立显式动作，包含后端登记的关联文件。200 为成功、
404 为已不存在、其他错误如实报告，部分删除不保证事务原子性。SDK 不开放路径删除，
也不允许使用音频或无 ID 文件。LAN 继承公版可读可删边界，不增加 PC 令牌。

media_import 上下文在交互空档约30秒请求目录保活；状态轮询不续 HTTP 活动。关闭上下文
或 CTRL 丢失后清理所属 HTTP/STA，停止未确认前保留 hold，新连接不继承旧意图。

## 4. 事件（EVT）

| evt_id | 事件 | data |
|---|---|---|
| 0x01 | BUTTON | `btn(1): 0=AI 1=CAPTURE 2=MEDIA; action(1): 见下方 action 取值表` |
| 0x02 | KNOB | `dir(1): 1=RIGHT 2=LEFT; delta_x(2 LE, int16); delta_y(2 LE, int16)` |
| 0x03 | AUDIO_STATE | `state(1): 0=stopped 1=running; source(1): 0=mic 1=call; err(1)` |
| 0x04 | IMG_STATE | `capture_evt(1): 0=START 1=DONE 2=ERROR 3=REMOTE_ERROR 4=CANCEL; error(1)` |

`action` 完整取值表：

| 值 | 含义 | 值 | 含义 |
|---|---|---|---|
| 0 | 单击 | 12 | 超超长按抬起 |
| 1 | 双击 | 13 | 连按（repeat） |
| 2 | 三击 | 14 | 按下 |
| 3 | 四击 | 15 | 抬起 |
| 4 | 五击 | 16 | 单击后长按 |
| 5 | 六击 | 17 | 双击后长按 |
| 6 | 短按 | 18 | 三击后长按 |
| 7 | 长按 | 19 | 单击后超长按 |
| 8 | 长按抬起 | 20 | 双击后超长按 |
| 9 | 超长按 | 21 | 三击后超长按 |
| 10 | 超长按抬起 | 22 | 上滑 |
| 11 | 超超长按 | 23 | 下滑 |

按键本地行为（音量/媒体/通话控制）保留，事件为旁路转发；拍照键不再本地拍照。

## 5. 图片传输（EDU-IMG 通道，UUID 0x2025）

TAKE_PHOTO 受理后，缩略图 JPEG 在独立的 EDU-IMG 通道以**裸字节流**下发：
无外层封装、无 CRC（完整性依赖 RFCOMM），由定长头子帧组成：

```
HEAD (8B):  0x01 | data_type(1)=0x01 | group_id(1) | seq(4 LE)=0 | format(1)=0x01(JPEG)
BODY (9B+): 0x02 | data_type(1)=0x01 | group_id(1) | seq(4 LE)   | data_len(2 LE) | data
TAIL (7B):  0x03 | data_type(1)=0x01 | group_id(1) | seq(4 LE)
```

- 同一张图 group_id 相同；HEAD 的 seq=0，BODY 的 seq 从 1 递增，TAIL 的 seq = 最后一个
  BODY seq + 1。
- 子帧可能跨读取分片：host 需按帧类型定长（HEAD 8B / TAIL 7B）与 BODY 的 data_len
  做缓冲切帧。
- host 重组：收到 HEAD 开新缓冲；按 seq 连续性校验拼接 BODY；收到 TAIL 校验后落盘。
  发现丢帧/断号直接丢弃整张图并重新拍照（无应用层重传）。

## 6. 音频流（EDU-AUDIO 通道，UUID 0x2024）

连接 0x2024 后，经 EDU-CTRL 发送 AUDIO_START 即开始收流。包格式（`recordsv` 包）：

```
| tag(1)=0x52 | cmd(1) | len(2 LE) | sn(2 LE) | sections(1)=8 | sub_id(1) |
| 8 × [ frame_len(1) | 帧 blob ] |
```


每个帧 blob 本身带 8 字节封装头（dcore 编码器输出格式）：

```
| payload_len(4 大端) | encoder_final_range(4 大端) | OPUS 包(payload_len 字节) |
```

**解码前必须剥掉这 8 字节**，只把 OPUS 包（CELT-WB，20 ms/帧）喂给解码器
（本库 `extract_opus_packet()` 已处理）。若整帧直接解码，长度头首字节 0x00
会被误读为 SILK-10ms 的 TOC，"成功"解出**半时长的噪声**——症状是录 N 秒只得
N/2 秒且内容不可辨。

- `len` = 全部 sections 字节数 + 4；`sn` 为包序号（丢包检测）；`sub_id` 为业务位图。
- OPUS：16 kHz、单声道、约 16 kbps、20 ms/帧（一包 8 帧 = 160 ms）。
- 解码：libopus（`opuslib` 等绑定），采样率 16000、声道 1、每帧 320 样本。
- HFP 通话期间流可能自动切为通话音频或暂停，以 AUDIO_STATE 事件为准；
  host 断开 EDU-CTRL 时设备自动停流。

## 7. 配对与连接

- 教育版设备永远处于"未绑定"状态，**每次开机约 5 秒后自动进入配对模式**（可发现，
  2 分钟窗口）；配对窗口结束不会自动关机。
- 手动进入配对：**拍照键三击，随后按住 5 秒** → 提示音，经典蓝牙配对模式（2 分钟窗口，
  新连接或超时后退出）。
- 无任何鉴权握手：SPP 连接建立即可通信（HELLO/HELLO_ACK 仅用于版本与能力协商）。

## 8. Host 参考实现

本仓库即参考实现：`edu_host/` Python 包（蓝牙 socket / IOBluetooth / 串口三种
transport、协议编解码、音频解码存 wav、图片重组存 jpg、OTA SPP 升级）+
`demo_cli.py` 交互式 demo + `tests/` 单元测试。环境配置见仓库根 README。
SDK 入口为 `edu_host.EduSession`；CLI 和 Notebook 复用它，不另行编码线协议。
实现沿用 `EduClient`、音频解析/sink、图片重组/写盘和 OTA 客户端；macOS 由
主线程轮询同一套解析器，底层每条原生通道在独立子进程的主线程接收，再经私有管道
交给解析器，规避 macOS 27 同进程多通道关闭路由串线；close 等待回收子进程，
重建 ACL 仅允许发生在同设备没有其他已打开通道时。其余 transport 使用接收线程。
这些字节转发不引入新的蓝牙协议或公开 SDK 参数。能力检查读取 HELLO_ACK
的 caps，旧固件未声明的能力明确报错；拍照以完整文件落盘为完成条件，录音缺
解码器时保存 `.opusraw`，不能将空 WAV 视为录制成功。这些是 host 实现决策，
不改变本规格的协议、设备能力与固件产物版本。
升级命令：`ota <firmware.bin>`（升级包由固件维护方提供）；macOS `--bt auto`
路径通过 SDP 查找 0x2026，Windows/Linux `--bt` 默认 OTA RFCOMM channel 为 7，
可用 `--ota-channel` 覆盖。
