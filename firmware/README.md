# 教育版眼镜固件

本目录保留旧 EDU v1 固件，并新增基于最新 main 的集成候选。SDK 0.2.0 兼容两者。
新候选本轮只编译、校验与 fake transport 验证，尚未烧录验收。

## 当前 main 集成候选

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
真机配对、拍照、录音、功耗与 OTA 后重连尚未验收。

OTA 输入必须是表中带 Looktech 外层头的 `.bin`，不能直接传 `.wpk` 或 `wqota` BT 内包。
外层版本与源码配置一致，不代表已经发布新版本。

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
