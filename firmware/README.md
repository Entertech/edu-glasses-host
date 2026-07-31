# 教育版眼镜固件

本目录保存与当前教育版 host 协议配套的、可按源码提交追溯的 WQ 烧录包。

## 当前产物

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
