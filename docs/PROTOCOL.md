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

图片不走本通道（见 §5）。caps 位：bit0 音频流、bit1 拍照、bit2 传感器、bit3 输入事件、bit4 控制（重启/LED/提示音）。

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
升级命令：`ota <firmware.bin>`（升级包由固件维护方提供）；macOS `--bt auto`
路径通过 SDP 查找 0x2026，Windows/Linux `--bt` 默认 OTA RFCOMM channel 为 7，
可用 `--ota-channel` 覆盖。
