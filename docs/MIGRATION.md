# SDK 发行与迁移

## 0.6.0：Looktech Glasses 全量更名（2026-10-28）

开发阶段统一采用新名称，不保留旧模块、类型、命令或发行包的兼容入口。

| 对象 | 新名称 |
|---|---|
| SDK 仓库 / PyPI 项目 | `Entertech/looktech-glasses-sdk` / `looktech-glasses-sdk` |
| Python 模块 | `looktech_glasses_sdk` |
| 公开类型 | `GlassesSession`、`GlassesClient`、`GlassesClientError`、`GlassesStatusError`、`GlassesTimeoutError`、`GlassesUnsupportedError`、`GlassesEvent` |
| 捕获来源 | `CaptureSource.SDK`，协议数值仍为 4 |
| Demo 仓库 / 发行名 | `Entertech/looktech-glasses-demo` / `looktech-glasses-demo`，版本 0.4.0 |
| CLI / Notebook | `looktech-glasses` / `glasses_notebook.py` |

SDK 0.6.0 为新 PyPI 项目的候选版本，发布前使用构建的本地 wheel；Demo 固定依赖同一版本。
先完成新项目的 Trusted Publisher 配置、构建和发行，再切换 Demo 默认分支的依赖。
仓库与包描述统一面向开发者，当前说明使用“开发者固件”“交互式 Notebook”和“SPP JPEG 小图”。
源码包目录、Cython 扩展、类型声明、动态子进程导入、版本门禁和既有检查同时迁移。

原始蓝牙设备前缀 `EDU-`、服务 UUID、CRC、帧格式、能力位与命令编号仍与现有固件一致。
当前固件获取仍需联系我们通过 OTA 协助，不新增 App 升级入口。历史固件文件、配置名及验收记录保留真实身份。
仅修改软件命名，不改变设备生命周期、超时、错误、采集、存储和删除语义。构建与发布见 [RELEASING.md](RELEASING.md)。

以下保留旧版本原始迁移记录，不作为 0.6.0 的安装指引或兼容承诺。


## 0.5.0：二进制发行（2026-10-26）

SDK 实现与 demo 分仓维护；当前 SDK 仓库暂时保持公开，demo 和文档位于 `Entertech/edu-glasses-demo`。
将原 Git commit 依赖替换为 `edu-glasses-host==0.5.0`，macOS 使用 `[macos]`。
已发布到 PyPI，安装无需源码仓库权限。仅提供标准 CPython 的平台 wheel，
保留 `edu_host` 导入、`EduSession`、全部原有低层 API 和 extras；wheel 含 `.pyi` 类型声明，
不含实现 `.py`、生成的 C 或 sdist。完整平台和维护步骤见 [RELEASING.md](RELEASING.md)。
Cython 兼容处理将一处字节切片解包改为等价 `struct.unpack_from`，线协议和完成语义不变。

以下是历史版本的拆分记录，Git 安装方式不再作为外部发行入口。

## SDK与Demo拆分（0.3.0，2026-10-23）

此前0.2.0在同一个仓库和安装包内包含SDK、CLI与教学示例。0.3.0拆分为：

| 仓库 | 内容 |
|---|---|
| [edu-glasses-host](https://github.com/Entertech/edu-glasses-host/tree/feat/edu-sdk-integration) | `edu_host`包、SDK使用说明、协议、SDK既有检查 |
| [edu-glasses-demo](https://github.com/Entertech/edu-glasses-demo) | `demo_cli.py`、5本Notebook、耳机示例、CLI既有检查及操作指引 |

应用的`from edu_host import EduSession`及现有SDK接口不变。SDK版本升为0.3.0，
当时仍为验证候选且未发布 PyPI；当前安装方式见[SDK使用说明](SDK_GUIDE.md)。

## 使用自己的项目

安装SDK的Git依赖或wheel即可，不需要克隆demo。Windows/Linux使用标准库蓝牙socket，
macOS选择`[macos]`；`[audio]`与`[serial]`按需安装。生产项目建议固定完整commit SHA。

## 使用原来的CLI/Notebook

```bash
git clone https://github.com/Entertech/edu-glasses-demo.git
cd edu-glasses-demo
python -m pip install -e .
edu-glasses --bt auto
```

`edu-glasses`命令由demo安装包提供，SDK 0.3.0不再附带`demo_cli`模块或控制台命令。
demo会自动安装固定commit的SDK及CLI原有可选依赖；录音解码仍需系统libopus。
原`python demo_cli.py ...`命令在demo仓库根目录继续可用。
Notebook安装 `python -m pip install -e '.[notebooks]'` 后在`examples/notebooks/`运行Jupyter。

不再从SDK仓库运行`demo_cli.py`或`examples/`。旧版本可从Git历史取回，
无需在SDK内保留第二份demo。CLI原有3项路径解析检查迁入demo，其余55项留在SDK，未新增单元测试。

## 验证边界

拆分验收检查SDK wheel不含demo模块/入口、SDK单独安装后导入、demo依赖SDK wheel后启动、
既有检查和Notebook代码的语法/导入。硬件协议和收发实现保持原样，本次不重烧固件或重跑实机矩阵。

## 0.4.0：原生输入

新增 DEVICE_CAPTURE_STATE、NATIVE_INPUT 能力及只读状态 API/事件；旧公开接口保留。
收到 NATIVE_INPUT 时，移除原始 CAPTURE 事件到 SDK 拍照/录像的自动映射。
录音请求事件是 PC 业务意图，需要应用准备接收后调用原录音方法；不会自动开麦。
先升级 PC 程序再升级原生输入固件。普通 CLI/Notebook 调用及旧固件能力回退保持兼容。
