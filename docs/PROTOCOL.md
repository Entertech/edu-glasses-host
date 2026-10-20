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

保留 v1、11B HELLO_ACK、990B 帧和旧命令。HELLO caps 新增 bit5 WIFI、bit6
SAVED_PHOTO、bit7 VIDEO、bit8 MEDIA_CATALOG。bit8 标识本节的公版 ISP 桥接合同，
新 SDK 在使用下列拍摄/媒体命令前要求它；不与此前未发布的精确发布原型混用。
原 TAKE_PHOTO 为教学小图，AUDIO_START/STOP 为音频推流。ISP 固件、索引及路由不变。

| cmd_id | 命令 | args | RSP data（外层 status=OK） |
|---|---|---|---|
| 0x20 | WIFI_EXECUTE | `operation u8 + operationArgs` | `operation u8 + kind u8 + outcome` |
| 0x21 | SAVED_PHOTO | 无 | `operationId u32`，仅表示受理 |
| 0x22 | VIDEO_START | 无 | `operationId u32`，仅表示受理 |
| 0x23 | VIDEO_STOP | `operationId u32` | `operationId u32`，仅表示停止受理 |
| 0x24 | MEDIA_STATUS | `operationId u32` | `operationId u32, kind u8, state u8, error u8`（7B） |
| 0x25 | MEDIA_CAPS | 无 | `schemaVersion u8=1, catalogId u64, features u32`（13B） |
| 0x26 | MEDIA_DESCRIPTOR | `catalogId u64, mediaId u64` | `catalogId u64, mediaId u64, revision u32, kind u8, size u64, nameLength u16, pathLength u16, name UTF-8, path UTF-8`（33B+字符串） |
| 0x27 | MEDIA_IDS | `catalogId u64, cursor u64` | `catalogId u64, catalogRevision u64, nextCursor u64, hasMore u8, count u8, ids u64[count]`（26B+8N，N≤16） |

多字节字段均 LE。operationId 由共享能力生成，只作 BT 本地控制与 owner 关联，
不发送给 ISP，也不是媒体 ID。仅当前 CTRL owner 可查询/停止其操作；每种媒体保存最近
一个操作状态。MEDIA_STATUS kind 为1照片、2视频；state 为1 STARTING、2 RECORDING、
3 STOPPING、4 DONE、6 FAILED、7 UNKNOWN。DONE/RECORDING 是公版 ISP 控制状态，
**不保证文件发布或首帧写入，也不返回本次唯一媒体 ID**。UNKNOWN/超时不能推断未保存
或资源已释放，不自动重拍。后续通过独立 ID 列表选择媒体，不猜最近文件。

MEDIA_CAPS 继承真实 ISP schema/catalog/features，使用公版 bit0 BATCH_METADATA、
bit4 DB_CATALOG；不要求 ISP bit7/8，不依赖新增 UART 0x2B。ID 分页复用公版0x21，
mask=3、includeDeleted=0，只列照片/视频。描述复用公版0x22的BASE字段，kind 1/2、
revision非零、真实名称/路径/大小。桥接在每个查询前核对实际 CAPS/catalog，保留底层
请求关联、分片、超时和 owner 取消。后端错误为外层ERROR＋1B公版错误码（如0x62不存在、
0x68目录/游标失效），不能把查询失败伪装空列表。页游标是公版offset；列表不承诺原子快照。

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

SDK 主媒体身份只来自SPP的真实ID/BASE查询。公版 HTTP `GET /` 可能因无ID文件退回
legacy目录，不影响SPP索引查询；不新增 `/media/catalog` 路由，不允许路径身份回退。
SDK 开启LAN后固定实际endpoint/catalog，只接受照片/视频ID，下载前后重核描述。

公版BASE没有gyro关系。若 `GET /` 返回已索引JSON，SDK仅在catalog、主ID、revision和
文件描述一致时按 `parentMediaId`/`metadataRevision` 采用已登记伴随文件；若为legacy，
视频 `companions_known=False`，保留可用MP4且 `complete=False`，报告无法确认伴随关系。
不按同名文件推断。已知 `motionRequired=true` 而gyro缺失/下载失败也报告不完整。

文件使用经验证的 `/customer/bt_res/{image,video,gsensor}/文件名`，直连实际数值IPv4，
不使用代理/重定向；整文件GET 200，无Range或内容hash保证。状态、Content-Length和实际
字节数匹配条目大小后提交本地文件；默认不覆盖、不删除设备原件。每文件最多3次整文件
尝试，批量固定选择并逐项返回，CTRL失效或取消终止所属会话。

`DELETE /media?id=<真实ID>` 独立显式发起，范围沿用公版登记关联文件。200成功、404已不存在、
其他错误如实报告，不保证事务原子性。SDK不提供路径删除，不操作音频/无ID文件。
LAN继承公版可读可删边界，不增加PC token。上下文交互空档约30秒GET /保活；关闭或CTRL
失效清理所属HTTP/STA，停止未确认保留hold。macOS所有SPP调用在调用线程，HTTP工作线程
运行期间调用线程继续poll；不会从HTTP线程发蓝牙命令。

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
参考 CLI demo 在 PC 端将 CAPTURE 的 SINGLE 映射到存储拍照、LONG 映射到录像启动，
录像中再次 PRESS 映射到停止；灯效由共享固件拍摄能力处理。这是 demo 行为，不改变
事件协议，普通 SDK/Notebook 的事件监听没有自动拍摄副作用。

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
