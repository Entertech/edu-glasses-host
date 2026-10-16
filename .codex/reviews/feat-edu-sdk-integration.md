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

原有协议常量、UUID、低层 API 与已有测试保留。初次编译阶段未运行真实 IOBluetooth/Windows/Linux 蓝牙、串口或 OTA；Python 3.9 只做语法检查，实际运行 Python 3.13。

## 2026-10-16 实机问题闭环

| ID | 严重级别 | 状态 | 代码位置 | 问题描述 | 影响 | 修复建议 | 验证方式 | 备注 |
|---|---|---|---|---|---|---|---|---|
| R006 | Major | Fixed | [session.py:440](/Volumes/SanDisk-CaseSensitive/code/sdk/edu-glasses-host/edu_host/session.py:440)、[mac_bt.py:175](/Volumes/SanDisk-CaseSensitive/code/sdk/edu-glasses-host/edu_host/mac_bt.py:175) | Mac 异步关闭未完成便释放引用，反向关闭可留下 AUDIO 物理连接 | 同进程重连时补开通道重建 ACL，造成 CTRL 超时或 closed | Mac 按 CTRL→AUDIO→IMG 关闭，每通道泵动回调等待关闭，上限 1 秒 | 断链恢复 8 项通过；OTA 后同 EduSession 实例两轮连接/拍照/录音成功 | Windows/Linux 关闭顺序保留 |
| R007 | Major | Fixed | [session.py:414](/Volumes/SanDisk-CaseSensitive/code/sdk/edu-glasses-host/edu_host/session.py:414) | 本地 OTA 文件校验发生在开通道后 | 坏头拒绝仍会触发 Mac 通道关闭，影响正在使用的 CTRL | 开 OTA 通道前复用 OTAFirmwareImage.parse 预校验 | 修复前 info 超时；修复后同会话 ValueError→info→完整 JPEG 通过 | OTA 传输代码不改，未绕过设备 CRC |
| R008 | Minor | Follow-up | [mac_bt.py:175](/Volumes/SanDisk-CaseSensitive/code/sdk/edu-glasses-host/edu_host/mac_bt.py:175) | 本机 macOS 27.0 低层单独关闭非首个 RFCOMM 通道可能实际关闭其他通道 | 自行操作低层 channel 的程序不能假定其他链路仍在线 | 教学程序使用完整 EduSession.close/connect；继续跨 macOS 版本核对 IOBluetooth 行为 | HCI DISC 与板端 SPP 状态交叉验证；完整会话恢复路径已通过 | 不改变协议或兼容层 API；不把底层部分通道关闭算可靠公开能力 |

最新验证：58 项原有测试、py_compile、Mac 实机新旧 SDK 拍照/录音/控制、坏 CRC/非法请求、通道断连恢复；BT OTA 坏头/忙时拒绝、16 KiB 后断开续传、全量校验重启，以及升级后两轮同实例回归均通过。Windows/Linux/首次绑定/OTA 断电未测。未新增单元测试文件。
