# Mac 单通道关闭修复与 EDU 回归（2026-10-16）

## 结论与边界

Mac 传输层已改为每条 RFCOMM 通道一个独立进程，保留 `MacRFCOMMChannel`
的 open/read/write/close 接口。每个进程仍使用公开 IOBluetooth 异步打开接口和
主线程 run loop，不使用私有蓝牙方法，不修改 EDU v1 字节、UUID 或通道号。

初轮使用 b67203c6 的 EDU WPK，回归发现快速重连拍照的固件定时器竞态。
追加修复为 eca5981f：只在 CONFIG_LT_EDU_MODE 下保护新预留与近期仍在传输的
会话；公版关闭 EDU 后本文件预处理结果逐字一致。下方保留初轮失败证据。

## 环境与定位证据

- 用户指定的 LTFTDI07 development 开发板，经典地址 `79:71:9A:49:72:26`。
- macOS 27.0、Python 3.13.14、PyObjC 12.2.2、opuslib 3.0.1 与系统 libopus。
- CTRL 6 / AUDIO 5 / IMG 4 / OTA 7，HELLO v1、caps=31。
- 旧 SDK 为 e7142c6499e7ccc22e51237ca4e9f5f916afa407 的原样 archive。

修复前，正常打开 CTRL→AUDIO→IMG 后调用 IMG 原生 `closeChannel()`，返回 0，
但板端 HCI 帧 53 显示 `DISC Channel=6`，随后 info 超时。三个原生对象指针、
getChannelID 和 channelID 均不同且正确；getObjectID 相同，但关闭实现实际传递
channelID，所以没有把 ObjectID 相同认定为根因。

独立 Objective-C 程序也复现错关，排除 Python 回调代码为唯一原因。
IOBluetooth → CoreBluetooth 的原生调用链传入正确 channelID；实际错关发生在
该进程共享的系统蓝牙路由中。具体 bluetoothd 内部实现未修改，也未认定为所有
macOS 版本共有。将每条通道分给独立进程后，同一固件、同一打开顺序下单通道
关闭正确，HCI 与板端 SPP 状态、持续成功的 CTRL info 相互印证。

## 实现决定与失败处理

- SDK 通过标准库私有 Pipe 转发原始字节，协议解析和用户回调仍在调用者主线程。
- 子进程从当前 Python 和导入路径启动，兼容无 `__main__` guard 的普通脚本与
  wheel 导入；不使用 multiprocessing spawn 重新执行用户脚本。
- close 等待原生关闭和进程退出，重复 close 安全；父进程消失时 Pipe EOF 令
  子进程关闭通道退出。超时或写失败只清理目标进程。
- 首次打开失败仅在同设备尚无其他通道时重建 ACL，避免补开 AUDIO/IMG 影响 CTRL。
- 本轮未新增单元测试；沿用 58 项现有测试，增加的是本机忽略目录中的实机断言探针。

## 单通道验收

正常 SDK 打开顺序为 CTRL→AUDIO→IMG，再按需打开 OTA；没有预先打开待断通道。

| 操作 | 结果 |
|---|---|
| IMG 独立 close/open 两轮、重复 close | CTRL info 连续成功；HCI DISC4 / SABM4 |
| AUDIO 独立 close/open 两轮、重复 close | CTRL info 连续成功；HCI DISC5 / SABM5 |
| OTA 独立 close/open 两轮、重复 close | GET_INFO 成功，CTRL info 连续成功；HCI DISC7 / SABM7 |
| CTRL/AUDIO/IMG 会话关闭 | 分别 DISC6 / DISC5 / DISC4，所有工作进程退出 |

对应 HCI 帧：640/664=DISC4、688/712=DISC5、754/781=DISC7；805/808/811 为
正常会话清理。最初已经建立 L2CAP 时才启动抓包，解析时需要强制 CID 解码：

```bash
tshark -r edu-runtime.cfa -d btl2cap.cid==0x0053,btrfcomm \
  -d btl2cap.cid==0x9b0a,btrfcomm \
  -Y 'btrfcomm.frame_type == 0x43 || btrfcomm.frame_type == 0x2f' \
  -T fields -e frame.number -e frame.time_relative -e _ws.col.Info
```

## 异常恢复

已通过：无 IMG 时的旧 ERROR+03 及重连拍照；IMG 收到数据后断开、拍照 START
后断 CTRL、录音时断 AUDIO、录音时断 CTRL、坏 CRC/非法参数/未知命令后的合法
info，以及 OTA GET_INFO。恢复图片均通过 Pillow JPEG verify，录音为 16 kHz
单声道有效 WAV（1.84 / 1.92 秒）。IMG 中断没有保存残缺 JPEG。

### 初轮失败与追加修复：预留被旧清理定时器取消

两次整组运行均观察到：上一张图成功后关闭会话，约 4 秒后新建拍照预留，
上一张图的 5 秒清理定时器到期，新预留以 group=0/result=11 结束，用户收到
IMG_STATE ERROR。该期间 HCI 没有通道断开，CTRL 仍可用；单独运行 BUSY 用例
成功，随后拍照也成功。不能将整组回归标记为全绿。

板端时序：3108843.5 ms 上一张结束，3112927.6 ms 新预留，3113842.8 ms
新预留失败；第二次为 3165501.3→3169691.5→3170500.8 ms，同样约 4999 ms。
源码中 `lt_air_img_port_reserve_transfer_internal` 不撤销旧 cleanup timer，
`cleanup_timer_callback` 无条件 reset 会清掉新预留，证据指向这一共享模块竞态。
追加修复只在 EDU 编译路径中处理该清理回调：active 且 reserved，或距最近一次
发送不足 5000 ms 时，重新启动 cleanup timer；空闲或停滞超时仍走原 reset 和
固定频率资源释放。检查最近发送时间也覆盖了旧 callback 已排队、新数据已开始
发送的情况，不改协议，也不在 SDK 自动重发有副作用的拍照命令。

临时 C 断言直接提取生产回调，覆盖预留、近期发送、停滞、取消后空闲和 32 位
时钟回绕；同时验证 pro 预处理输出等于修复前。EDU 完整构建成功，退出 0。
构建环境为 Darwin/arm64、自动选择 latest-arm64、host-sync。

## 原始证据与未测项

本机固件仓库 `.tmp/mac-single-channel-close-20261016/` 保存完整文本、bin、HCI、
最小 Python/Objective-C 探针、异常恢复脚本和 JPEG/WAV。该目录已忽略，不发布原始
硬件记录。`baseline-close-img.log` / `native-probe.log` 是修复前证据，
`isolated-close-probe.log` 是独立关闭证据；两份 `recovery-probe*.log` 的失败均保留。

未测其他 macOS 版本、Windows/Linux、冻结可执行程序、实体按键/旋钮、灯效听感、
长时间功耗与 OTA 断电；只升级 BT，不更新 ISP/WiFi。进程隔离增加 Python 工作
进程与内存开销：常规会话 3 个，升级期间最多 4 个。

## 追加固件修复后的实测

- eca5981f EDU WPK SHA-256：
  `e8c07601fdb9156e103c060be40c256d945407ca3ee12bbd878dea70458b3374`。
- 烧录预览后执行，development、保留 KV；job
  `a6a51af5a95545e881863f5cae8a92c7`，退出 0，`burn success`，56.98 秒。
- EDU / pro 完整构建都退出 0。pro 配置未改，生产 C 文件在 EDU 关闭时的
  预处理输出与修复前相同；本轮未重新给 Samsung 烧 pro 或重复手机 App 回归。
- 原有八项异常用例全通过：`recovery-fixed-firmware.log`，未使用预开待断
  通道的绕行。恢复 JPEG 为 27,403 / 27,715 / 27,732 B，720×960；录音
  1.84 / 1.92 秒，16 kHz mono。BUSY 用例第一张与后续照片均完成。
- wheel 导入后，在同一会话中相隔 4 秒拍四张：27,399 / 27,385 / 27,429 /
  28,418 B，全部 JPEG verify 通过。日志三次 `defer EDU cleanup reserved:1
  idle:5000/5001`，之后照片完成，直接覆盖原先的 5 秒失败窗口。
- `lifecycle-probe.log`：关闭 IMG/AUDIO/OTA 后 CLI 状态分别为 1/0/0、
  0/1/0、1/1/0，CTRL info 均成功。CTRL 关闭后 AUDIO/IMG 保持 1/1，
  重新 HELLO 成功；打开未注册通道失败而 CTRL 保留。
- 强制结束 AUDIO 工作进程，检测到退出，CTRL 仍成功，重开后有效 WAV；
  主程序 `os._exit` 后工作进程收到 EOF，板端 SPP 全部归零。

新 OTA 外层包 1,836,046 B，SHA-256
`fa055f68daae735f43f585eb7ff890718e52657da905355dabc44b4262e41888`，
Product ID / 整包和 BT 版本不改。所有包 CRC 与旧、新 SDK 的格式保持兼容。

### 新固件包 OTA 与升级后

新包设备端坏头返回 FIRMWARE_ERROR=2；录音期间返回 BUSY=5 /
RECORDING_AUDIO=5，停止录音后有 44 个有效帧、0 丢包/解码错误。接收首个
16 KiB 后单独断开 OTA，CTRL info 持续成功；重连后串口 `is_resumed=1`、
`last_offset=16402`、`ota_task_resume succeed`。正常按需打开 OTA，没有预开绕行。

完整 1,836,046 B 续传，info→done 约 216 秒，默认 512 B/10 ms；设备
`OTA image verify OK`、结果 0/reboot=1，并实际重启。`ota-fixed-firmware.log`
和 `edu-fixed-runtime.txt/.cfa` 保留完整证据。本轮还用修复前 b67203c6 包跑过
一次相同的完整断链续传并成功，两个阶段的日志分别保存。

升级后从最终 wheel 导入，在同一个 EduSession 实例做三轮
connect→info→photo→record→close：JPEG 27,270 / 27,412 / 27,539 B，
全部 720×960 并验证通过；WAV 每轮 16 kHz mono / 1.84 秒。第二轮失败的
旧日志 `post-ota-wheel.log` 仍保留，对比修复后的 `post-ota-fixed-wheel.log`
与 `SAME_SESSION_RECONNECT_PASS`。

旧 SDK 对新外层包解析通过。最终 wheel 61,655 B，SHA-256
`c9a13e8b98a042288f761f8fef5135e0e2cc038c08a66c42bfdde348899b3853`，
所有 edu_host Python 文件与工作区逐字一致；58 项现有测试及 py_compile 通过。
未重复用旧 SDK 完整传输整包 OTA，其旧 get_info/坏头拒绝在首轮已测。

### 最终新旧 Mac demo 与资源清理

最终 eca5981f 固件上，新 CLI 与 e7142c6 原样旧 CLI 都完成 v1 握手、info、
sensors、JPEG、OPUS→WAV、LED 与提示音，`NEW_AND_LEGACY_DEMO_PASS`。
新 JPEG 27,335 B / WAV 2.00 秒，100 帧，0 丢包、0 解码错误；旧 JPEG
27,464 B / WAV 2.08 秒，104 帧，0 解码错误。五张最终 JPEG 均通过验证，
五份最终 WAV 为有效 PCM，RMS 172.56–300.15，非空、非全零。

最终 CLI `GET_SPP_STATE=00 00 00`；device bitmap=0、ISP sleep=4。
日志确认最后图传的固定频率资源 en=0；未把 keep_active 字节当作功耗测量。
全部本轮通道工作进程退出，日志已停止，lsof 确认 LTFTDI07 无占用。设备保留
eca5981f EDU 固件。输出文件位于忽略目录 `fixed/`，最终媒体检查为
`final-media-validation.json`。本轮没有发布、推送或合并两个本地分支。


## 2026-10-20 semi 新对端回归补充

固件采用共用能力入口的 `1f25d014`，用户选择的目标为 `/dev/cu.usbserial-312400` semi，串口确认蓝牙地址 `84:9D:4B:5A:67:29`。不是本报告前文的开发板。

本次原版 SDK 两次在 worker 内等待 RFCOMM open-complete 超时（status=None），主进程已能查询全部 SDP。native 单进程先查询 SDP 后 HELLO/INFO 成功；隔离探针只补 worker 的 SDP 查询便收到有效 JPEG。最小修复在 `_channel_worker` 内复用 `sdp_channels`，每个 worker 在自己的主线程查询 SDP 后再 open；仍是一通道一进程，公开 API、关闭策略和 EDU v1 不变。

修复后的正式 SDK：恢复检查 8/8；五次传感器查询、LED/tone、旧录音 owner 断连停止、新连接未 start 前不出音频、HELLO 前 INFO、重启后拍照录音全部通过。已有 58 项测试通过，未新增单元测试。原样 `e7142c6` 旧 SDK 与当前 SDK 各自完整 CLI 联调也通过，正常 WAV 为 16 kHz 单声道，JPEG 720×960。

完整架构对账与证据目录见 [固件 semi 实机报告](../../Looktech-Glasses-Device/docs/test/edu-shared-capabilities-semi-20261020.md)。尚未覆盖 Windows/Linux、第二主机、真实 CALL、物理充电/输入及完整 OTA 升级；本次没有更新发布包或替换 SDK 内附旧固件。
