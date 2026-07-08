---
name: glasses-protocol-dev
description: Develop a custom host implementation or extend this library against the EDU glasses SPP wire protocol (frames, CRC, audio packages, air-img). Use when the user wants to write their own client (any language), add features to edu_host, or debug protocol-level bytes. 自己写 host、扩展本库、或做协议字节级调试时使用。
---

# 协议二次开发指南

## 事实来源与分层

1. **线协议唯一事实来源：`docs/PROTOCOL.md`** —— 帧格式、CRC、命令/事件表、
   音频包、图片子帧全部在此。文档与代码矛盾时以实际设备行为为准并向维护者反馈。
2. 参考实现：`edu_host/` 包。协议层（`protocol.py`、`crc16.py`、
   `audio_client.py` 的解析部分）是**纯 stdlib**，可直接移植/对拍。

## 关键不变量（改代码前必读）

- 线协议常量（同步字 `A5 5A`、帧类型、cmd/evt id、UUID、通道号、990 字节上限、
  CRC-16/CCITT-FALSE）由固件决定，host 侧**不可单方面更改**。
- `edu_host/protocol.py` 与 `crc16.py` 保持零第三方依赖，让单测不需要硬件。
- macOS 蓝牙（`mac_bt.py`）两条铁律：IOBluetooth 回调只在**主线程 run loop**
  泵动时投递（async open + `pump()`，勿用 sync open / 后台线程）；首次 open 可能
  `kIOReturnError`，按现有 ACL 重建逻辑重试。
- 新增 REPL 命令要同时改 `demo_cli.py` 的两个会话分支（threaded + mac）、
  `HELP_TEXT`、README，并保持管道可脚本化（不引入交互确认）。

## 无硬件验证闭环

```bash
python3 -m unittest discover -s tests -v     # 35+ 用例，全绿才算过
python3 -m py_compile demo_cli.py edu_host/*.py
```

`tests/test_protocol.py` 就是可执行的协议规格：写其他语言实现时，把里面的
用例字节序列当对拍向量。生成任意帧的期望字节：

```bash
python3 -c "
from edu_host.protocol import encode_frame, FrameType
print(encode_frame(FrameType.CMD, 1, bytes([0x04])).hex())   # GET_SENSORS
"
```

CRC 对拍向量：

```bash
python3 -c "from edu_host.crc16 import crc16; print(hex(crc16(bytes.fromhex('0110010100'))))"
```

## 真机调试技巧

- 字节级抓流：直接连通道后把原始字节存文件再离线分析——`FrameParser`/
  `AirImgStreamParser`/`RecordStreamParser`（见 `edu_host/`）都支持喂任意分片。
- 帧解析失败先查三件事：CRC 范围（`ver..payload`，不含同步字和 CRC 本身）、
  len 字段小端、990 上限。
- 图片流丢帧：按 `seq` 连续性判断，断号即丢弃整张等下一个 HEAD（协议无重传）。
- 设备侧固件不可改（学生无固件源码）；需要新命令/事件时联系固件维护者对齐
  proto_ver 与 caps 位。

## 扩展本库的验收标准

改动后必须：单测全绿 + 在真机跑通至少一条对应功能链路（连接/拍照/录音），
并同步更新 README 与（协议变化时）`docs/PROTOCOL.md`。
