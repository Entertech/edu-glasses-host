# 教育版眼镜固件

本目录保留旧 EDU v1 固件和 2026-10-16 的 main 集成候选。SDK 0.2.0 保留其基础能力接口。
2026-10-16 已在 LTFTDI07 开发板完成 pro / edu 烧录、Samsung 公版 App 回归、
新旧 SDK 的 EDU v1 功能和拍照/录音断链恢复、BT 单模块 OTA 错误拒绝与断点续传验收。

## 当前功能适配（2026-10-20）

存储拍照、录像和 WiFi 原件导出需 `feat/edu-main-integration` 当前功能固件
（源提交 `51a1d390`）及支持公版 ID/BASE/LAN 能力的 ISP；ISP 不需要 EDU 定制改动。
本目录下列历史产物不包含这些扩展，不能据此判断新 SDK 功能不可用。请从固件维护者
取得与硬件匹配的当前产物，并在连接后核对 `glasses.capabilities` 和
`glasses.media_capabilities()`。接入方式见 [SDK 使用说明](../docs/SDK_GUIDE.md)。

## 2026-10-16 EDU v1 修复候选 eca5981f（历史）

基于同一 main 的 `feat/edu-main-integration`，提交 `eca5981f` 在 EDU 门控内修复
旧图传 cleanup timer 取消下一张照片预留的竞态，公版预处理输出保持不变。
SDK 同时修复 macOS 27 独立关闭多条 RFCOMM 通道的路由串线。详细范围与实机
记录见 [Mac 回归报告](../docs/MAC_REGRESSION_20261016.md)。

| 用途 | 文件 | 大小 | SHA-256 |
|---|---|---:|---|
| WQ 工具烧录 | [EDU WPK](looktech-edu-stereo-edu-7036AX-1.2.3.4-eca5981f.wpk) | 2,307,324 B | `e8c07601fdb9156e103c060be40c256d945407ca3ee12bbd878dea70458b3374` |
| SDK / CLI SPP OTA | [Looktech OTA 外层包](looktech-edu-stereo-edu-7036AX-1.2.3.4-eca5981f-ota.bin) | 1,836,046 B | `fa055f68daae735f43f585eb7ff890718e52657da905355dabc44b4262e41888` |

Product ID、整包/BT 版本、BT 单模块范围均沿用下方配置；pack/inspect 各 CRC
均通过。本候选已烧录开发板，默认参数下首块断链后续传约 216 秒，校验重启
成功；之后同 SDK 实例三轮 JPEG/WAV 和新旧 CLI 回归通过。版本字符串未增加，
识别本修复应使用源提交和文件 SHA-256。

## 首轮 main 集成候选（历史）

- 固件工程/芯片：`stereo-edu` / `7036AX`。
- 源仓库：`Entertech/Looktech-Glasses-Device`。
- main 基线：`813ee9999eaefcdb830053d2faec65f0e2bff2c5`。
- 源分支/提交：`feat/edu-main-integration` / `b67203c6df8fd26de76221cc1d0b0b9512b3ec57`（本地提交，尚未推送）。
- 构建日期：2026-10-16，Darwin/arm64，wqdocker latest-arm64，host-sync。
- 构建版本：`1.2.3.4`；`CONFIG_LT_EDU_MODE=y`，原 `defconfig.pro` 未改。
- 整包版本：`0x0001010109290001`（1.1.1-929+1），BT 版本：`0x0000010109290001`（0.1.1-929+1），沿用源码配置。

| 用途 | 文件 | 大小 | SHA-256 |
|---|---|---:|---|
| WQ 工具烧录 | [EDU WPK](looktech-edu-stereo-edu-7036AX-1.2.3.4-b67203c6.wpk) | 2,307,235 B | `7234405403a7a939fedb8579361ee5193bda0d5e595b929f7ac2805905af8345` |
| SDK / CLI 的 SPP OTA | [Looktech OTA 外层包](looktech-edu-stereo-edu-7036AX-1.2.3.4-b67203c6-ota.bin) | 1,835,990 B | `bb98f56600a9017253df18566965236ba35cd09357472d81c92b128f97828558` |

在固件仓库根目录构建：

```bash
./.agents/skills/wq-build-verify/scripts/wq_build_verify.sh --variant edu --chip 7036AX
```

OTA 分两层：先按固件 CI `.github/actions/wq-build/action.yml` 的 `wqota encoding` 参数生成 BT 模块内包；
再用 Looktech 整包工具加 32 B firmware header、32 B BT module header 和 8 B CRC。
本产物仅包含 type=1 的 Bluetooth 模块，Product ID `0x201` 沿用固件仓库现有 OTA 示例。
它不更新 ISP / WiFi，也未宣称这些模块已经验证兼容。

本次外层使用 build-firmware-bundle 的本地 `pack_firmware.py`：

```bash
python3 <pack_firmware.py路径> pack --product-id 0x201 \
  --version 0x0001010109290001 \
  --bluetooth stereo-edu-7036AX-1.2.3.4-ota.bin \
  --bluetooth-version 0x0000010109290001 \
  --output looktech-edu-stereo-edu-7036AX-1.2.3.4-b67203c6-ota.bin
```

pack/inspect 的头部、内容、模块 CRC 全部通过；SDK 对真实外包完成解析，并通过现有 fake transport
完整传输 3,586 包（每包 ≤512 B，payload 与原文件一致）。WPK 通过现有 tone/flash layout 检查。
本轮已实测：720×960 JPEG、新旧 SDK 16 kHz mono WAV、LED/提示音命令、
拍照/录音断链恢复。OTA 在接收首个 16 KiB 后断开、重连续传成功，最终设备
`OTA image verify OK`、`result=0,reboot=1`；重启后两轮拍照/录音和同 SDK 实例重连通过。
功耗、首次绑定、实体按键/旋钮、Windows/Linux 蓝牙和 OTA 断电未测。

OTA 输入必须是表中带 Looktech 外层头的 `.bin`，不能直接传 `.wpk` 或 `wqota` BT 内包。
外层版本与源码配置一致，不代表已经发布新版本。保留 KV 串口烧录后设备可能仍显示
原有更高整包版本（本板为 4.0.1）；本 OTA 完成后整包版本按外层更新为 1.1.1-929+1。
Mac 默认参数本轮续传到完成约 259 秒，升级后等待完整启动再重新连接。
原始版本值是 `0x0001010109290001`；新旧 SDK 的十进制显示为 `1.1.1-2345+1`，
固件使用十六进制 pre-release 显示 `1.1.1-929+1`，二者为同一个版本。

## 保留的旧版产物

- 文件：`looktech-edu-stereo-pro-7036AX-1.2.3.4-97b5ce6b.wpk`
- 固件工程：`stereo-pro`
- 芯片：`7036AX`
- 构建版本：`1.2.3.4`
- 源仓库：`Entertech/Looktech-Glasses-Device`
- 源分支：`feat/edu-spp`
- 源提交：[`97b5ce6b8aa10fe99732b09f1aa736ad1ac6d2c8`](https://github.com/Entertech/Looktech-Glasses-Device/commit/97b5ce6b8aa10fe99732b09f1aa736ad1ac6d2c8)
- 源提交时间：`2026-07-08T23:51:38+08:00`
- 构建时间：`2026-07-31`（Asia/Shanghai）
- SHA-256：`83fe7004afffe97c65615d2ec928d0e725308e01d3fec49822f9b434d6f8a0bc`

构建命令：

```bash
./.agents/skills/wq-build-verify/scripts/wq_build_verify.sh \
  --project stereo \
  --chip 7036AX \
  --repo <feat-edu-spp-worktree>
```

构建日志判定为 `Build successful.`，且命令退出码为 `0`。

此 `.wpk` 是 WQ 烧录工具使用的整机烧录包，不是 `demo_cli.py` 的 SPP OTA 输入。
本次交付未执行实机烧录或 host 功能回归；烧录后仍需按根目录 README 的步骤验证
`info`、传感器、拍照、录音及按键/旋钮事件。
