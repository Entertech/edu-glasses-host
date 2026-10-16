# Code Review Ledger

- 审查目标：EDU v1 Python SDK 统一会话、CLI/Notebook 与固件交付
- 分支：feat/edu-sdk-integration
- Base：e7142c6499e7ccc22e51237ca4e9f5f916afa407
- Code Head：本分支 0.2.0 集成提交
- 审查轮次：初审 + 已修问题闭环
- 最近验证：58 项已有测试、py_compile、临时 fake/断言、真实 OTA 外包 fake 传输、wheel 构建/导入

| ID | 严重级别 | 状态 | 代码位置 | 问题描述 | 影响 | 修复建议 | 验证方式 | 备注 |
|---|---|---|---|---|---|---|---|---|
| R001 | Major | Fixed | [session.py:122](/Volumes/SanDisk-CaseSensitive/code/sdk/edu-glasses-host/edu_host/session.py:122) | 直接统一为一个打开顺序会破坏旧平台连接时序 | Windows/Linux 默认路径可能连错或 Mac 重建 ACL 后破坏已握手 CTRL | 线程模式 IMG→CTRL→HELLO，Mac CTRL→AUDIO→IMG→HELLO | 平台 fake 与连接顺序断言通过 | 无新增单元测试文件 |
| R002 | Major | Fixed | [session.py:339](/Volumes/SanDisk-CaseSensitive/code/sdk/edu-glasses-host/edu_host/session.py:339) | Mac 每次录音重新开通道可能触发 ACL 重建 | 一次录音可能打断控制连接 | Mac 录音间保留物理 AUDIO，close 才关闭，open 幂等 | 主线程 fake、启停/重复录音与旧 API 检查通过 | 无新增单元测试文件 |
| R003 | Major | Fixed | [session.py:297](/Volumes/SanDisk-CaseSensitive/code/sdk/edu-glasses-host/edu_host/session.py:297) | 拍照 ACK 超时后若清空 pending 与路径会误认操作未执行 | 晚到 JPEG 丢失目标路径，自动重拍会产生重复操作 | ACK 超时保留 pending 与文件名，不自动重发 | 晚到 JPEG 断言通过 | 无新增单元测试文件 |
| R004 | Major | Fixed | [session.py:405](/Volumes/SanDisk-CaseSensitive/code/sdk/edu-glasses-host/edu_host/session.py:405) | 会话层允许 OTA 与录音或拍照同时请求 | 资源竞争或升级中执行其他设备操作 | OTA 前拒绝 pending photo/recording，升级期间拒绝 CTRL 请求 | fake OTA 互斥与 close 清理通过 | 无新增单元测试文件 |
| R005 | Major | Fixed | [README.md:27](/Volumes/SanDisk-CaseSensitive/code/sdk/edu-glasses-host/firmware/README.md:27) | wqota 生成 BT 内包，不能直接当 Looktech 外层 OTA 包 | SDK 拒绝文件，升级流程无法启动 | 外层按 type=1 打包，记录 Product ID/版本/CRC；保留 SDK 校验 | 真实外包解析/CRC、3,586 包 fake 完整传输通过 | 无新增单元测试文件 |

原有协议常量、UUID、低层 API 与已有测试保留。未运行真实 IOBluetooth/Windows/Linux 蓝牙、串口或 OTA；Python 3.9 只做语法检查，实际运行 Python 3.13。
