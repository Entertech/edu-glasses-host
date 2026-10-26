# AGENTS.md — edu-glasses-host

本仓库维护可独立安装的`edu_host` SDK、既有检查、[通信协议](docs/PROTOCOL.md)和
[SDK使用说明](docs/SDK_GUIDE.md)。CLI、Notebook与设备操作技能在
[edu-glasses-demo](https://github.com/Entertech/edu-glasses-demo)维护；需要操作demo时阅读该仓库AGENTS.md。

## 修改与验收

1. SDK功能放在`edu_host/`并经`EduSession`统一暴露。既有低层API与`from edu_host import ...`保持兼容。
2. 协议变更先与固件对齐，更新`docs/PROTOCOL.md`；公开API、安装方式变化同步更新SDK使用说明。
3. Python 3.9+；SDK基础安装无必选依赖，`macos`、`serial`、`audio`按需安装。入口与版本在`pyproject.toml`，`edu_host.__version__`同步。
4. 检查SDK wheel只包含`edu_host`，不包含demo模块或控制台入口。demo只安装SDK，不导入邻接源码树。
5. 在SDK仓库执行既有检查：

```bash
python -m unittest discover -s tests -v
python -m compileall -q edu_host
python -m pip wheel --no-deps . -w dist
```

涉及收发行为的修改，按对应能力进行实机验证并记录实际覆盖范围；离线检查不能充当实机通过。
构建和拆分不需要自动连接设备。打包或发布时读取[发布流程](docs/RELEASING.md)，
SDK/demo拆分的迁移合同见[迁移说明](docs/MIGRATION.md)。

## 协议与运行约束

- `docs/PROTOCOL.md`是协议事实来源。同步字、CRC、UUID、通道号、命令与事件编号、990字节限制随固件对齐，host不可单方面更改。
- `protocol.py`、`crc16.py`保持纯stdlib；macOS依赖延迟导入，Windows/Linux路径独立使用标准库socket。
- macOS连接、请求、等待和关闭都在进程主线程顺序执行；每条原生RFCOMM通道由独立子进程的主run loop收发。
  等待使用`wait()/poll()/events()`，事件回调应简短，设备请求排队到主循环。
- 仅在该设备尚无其他通道打开时才允许重建ACL重试，避免误断已有连接。
- 请求超时不代表设备未执行；拍照/录像等操作不得自动重发。按owner和生命周期处理连接、操作与LAN退出。
- 与通话/充电/低电/OTA的冲突沿用设备保护规则，记录真实错误，不能用固定延时或跳过检查声称问题已修复。

需要扩展线协议或对拍字节时阅读`.claude/skills/glasses-protocol-dev/SKILL.md`。
