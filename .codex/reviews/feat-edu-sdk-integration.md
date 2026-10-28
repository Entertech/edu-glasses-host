# Code Review Ledger

> 本文保留更名前的历史接口与验收身份；源码链接固定至更名前提交，当前入口见 [SDK 使用说明](../../docs/SDK_GUIDE.md)。

- 审查目标：EDU v1 Python SDK 统一会话、CLI/Notebook 与固件交付
- 分支：feat/edu-sdk-integration
- Base：e7142c6499e7ccc22e51237ca4e9f5f916afa407
- Code Head：本分支 0.2.0 集成提交
- 审查轮次：初审 + 已修问题闭环
- 最近验证：58 项已有测试、py_compile、wheel 源码一致与实机导入、HCI 独立关闭/重开、工作进程退出与 EOF、EDU eca5981f 真机恢复与 OTA

| ID | 严重级别 | 状态 | 代码位置 | 问题描述 | 影响 | 修复建议 | 验证方式 | 备注 |
|---|---|---|---|---|---|---|---|---|
| R001 | Major | Fixed | [session.py:122](https://github.com/Entertech/looktech-glasses-sdk/blob/a94821a39f9218eae627887727d63e2e35d45909/edu_host/session.py#L122) | 直接统一为一个打开顺序会破坏旧平台连接时序 | Windows/Linux 默认路径可能连错或 Mac 重建 ACL 后破坏已握手 CTRL | 线程模式 IMG→CTRL→HELLO，Mac CTRL→AUDIO→IMG→HELLO | 平台 fake 与连接顺序断言通过 | 无新增单元测试文件 |
| R002 | Major | Fixed | [session.py:339](https://github.com/Entertech/looktech-glasses-sdk/blob/a94821a39f9218eae627887727d63e2e35d45909/edu_host/session.py#L339) | Mac 每次录音重新开通道可能触发 ACL 重建 | 一次录音可能打断控制连接 | Mac 录音间保留物理 AUDIO，close 才关闭，open 幂等 | 主线程 fake、启停/重复录音与旧 API 检查通过 | 无新增单元测试文件 |
| R003 | Major | Fixed | [session.py:297](https://github.com/Entertech/looktech-glasses-sdk/blob/a94821a39f9218eae627887727d63e2e35d45909/edu_host/session.py#L297) | 拍照 ACK 超时后若清空 pending 与路径会误认操作未执行 | 晚到 JPEG 丢失目标路径，自动重拍会产生重复操作 | ACK 超时保留 pending 与文件名，不自动重发 | 晚到 JPEG 断言通过 | 无新增单元测试文件 |
| R004 | Major | Fixed | [session.py:405](https://github.com/Entertech/looktech-glasses-sdk/blob/a94821a39f9218eae627887727d63e2e35d45909/edu_host/session.py#L405) | 会话层允许 OTA 与录音或拍照同时请求 | 资源竞争或升级中执行其他设备操作 | OTA 前拒绝 pending photo/recording，升级期间拒绝 CTRL 请求 | fake OTA 互斥与 close 清理通过 | 无新增单元测试文件 |
| R005 | Major | Fixed | [README.md:27](https://github.com/Entertech/looktech-glasses-sdk/blob/a94821a39f9218eae627887727d63e2e35d45909/firmware/README.md#L27) | wqota 生成 BT 内包，不能直接当 Looktech 外层 OTA 包 | SDK 拒绝文件，升级流程无法启动 | 外层按 type=1 打包，记录 Product ID/版本/CRC；保留 SDK 校验 | 真实外包解析/CRC、3,586 包 fake 完整传输通过 | 无新增单元测试文件 |

原有协议常量、UUID、低层 API 与已有测试保留。初次编译阶段未运行真实 IOBluetooth/Windows/Linux 蓝牙、串口或 OTA；Python 3.9 只做语法检查，实际运行 Python 3.13。

## 2026-10-16 实机问题闭环

| ID | 严重级别 | 状态 | 代码位置 | 问题描述 | 影响 | 修复建议 | 验证方式 | 备注 |
|---|---|---|---|---|---|---|---|---|
| R006 | Major | Fixed | [session.py:440](https://github.com/Entertech/looktech-glasses-sdk/blob/a94821a39f9218eae627887727d63e2e35d45909/edu_host/session.py#L440)、[mac_bt.py:175](https://github.com/Entertech/looktech-glasses-sdk/blob/a94821a39f9218eae627887727d63e2e35d45909/edu_host/mac_bt.py#L175) | Mac 异步关闭未完成便释放引用，反向关闭可留下 AUDIO 物理连接 | 同进程重连时补开通道重建 ACL，造成 CTRL 超时或 closed | Mac 按 CTRL→AUDIO→IMG 关闭，每通道泵动回调等待关闭，上限 1 秒 | 断链恢复 8 项通过；OTA 后同 EduSession 实例两轮连接/拍照/录音成功 | Windows/Linux 关闭顺序保留 |
| R007 | Major | Fixed | [session.py:414](https://github.com/Entertech/looktech-glasses-sdk/blob/a94821a39f9218eae627887727d63e2e35d45909/edu_host/session.py#L414) | 本地 OTA 文件校验发生在开通道后 | 坏头拒绝仍会触发 Mac 通道关闭，影响正在使用的 CTRL | 开 OTA 通道前复用 OTAFirmwareImage.parse 预校验 | 修复前 info 超时；修复后同会话 ValueError→info→完整 JPEG 通过 | OTA 传输代码不改，未绕过设备 CRC |
| R008 | Major | Fixed | [mac_bt.py:179](https://github.com/Entertech/looktech-glasses-sdk/blob/a94821a39f9218eae627887727d63e2e35d45909/edu_host/mac_bt.py#L179) | macOS 27 同进程多 RFCOMM 关闭可路由到其他通道，原生 Objective-C 同样复现 | 独立关闭 IMG/AUDIO/OTA 会破坏 CTRL；SDK OTA 结束后可能无法继续使用 | 每条原生通道由独立进程主 run loop 持有，私有 Pipe 透传字节，关闭等待回收；已有其他通道时禁止 ACL 重建 | 正常打开顺序两轮独立关闭/重开/重复关闭；HCI DISC4/5/7 与持续成功的 info | 不改 v1 或公开 SDK API；系统内部具体缺陷未修改；其他 macOS 版本待验证 |

最新验证：58 项原有测试、py_compile、Mac 实机新旧 SDK 拍照/录音/控制、坏 CRC/非法请求、通道断连恢复；BT OTA 坏头/忙时拒绝、16 KiB 后断开续传、全量校验重启，以及升级后两轮同实例回归均通过。Windows/Linux/首次绑定/OTA 断电未测。未新增单元测试文件。

2026-10-16 Mac 单通道关闭复核：原生复现、进程隔离与 HCI 已闭环。快速重连拍照另有固件清理定时器竞态，已追加 eca5981f 修复，双构建、烧录后八项恢复和 5 秒窗口四张图验收通过；见 [本轮回归](../../docs/MAC_REGRESSION_20261016.md)。

最终闭环：eca5981f 新 OTA 外包断开首块后续传、设备校验/重启通过；最终 wheel
同实例三轮 JPEG/WAV、新旧 CLI 全流程通过；工作进程意外退出、父进程 EOF、
无效通道补开均未误断 CTRL。日志和串口已释放；无新增未闭环的 Critical/Major。
保留跨 macOS 版本、Windows/Linux、冻结程序、旧 SDK 整包 OTA 和断电等实测边界。


## 2026-10-20 semi 新对端闭环

- 审查目标：共用能力固件 semi 实机连接与 EDU 兼容；修复前 Head f705838。
- 最近验证：58 项已有测试；正式 SDK 恢复 8/8、owner/控制/重启探针、新旧 CLI 联调。设备 84:9D:4B:5A:67:29，USB 串口 312400。

| ID | 严重级别 | 状态 | 代码位置 | 问题描述 | 影响 | 修复建议 | 验证方式 | 备注 |
|---|---|---|---|---|---|---|---|---|
| R009 | Major | Fixed | [mac_bt.py:308](https://github.com/Entertech/looktech-glasses-sdk/blob/a94821a39f9218eae627887727d63e2e35d45909/edu_host/mac_bt.py#L308) | 新对端在 worker 中直接 open RFCOMM，未得到完成回调 | HELLO 前即失败，全部业务不可用 | worker 自己查询 SDP 后再 open，复用现有 helper | 原版两次失败；native/隔离探针对照；正式 SDK 8/8 恢复、能力/owner/重启及新旧 CLI 通过；已有 58/58 测试 | 不改固件或线协议，详见 MAC 回归文档的 2026-10-20 补充 |

保留此前 R001–R008 的审查记录。新增问题在本轮首次配对此 semi 时发现，是 R008 进程隔离路径缺少本进程 SDP 初始化的实机补充，不重新开启已经闭环的其他问题。
