# SDK与Demo拆分（0.3.0，2026-10-23）

此前0.2.0在同一个仓库和安装包内包含SDK、CLI与教学示例。0.3.0拆分为：

| 仓库 | 内容 |
|---|---|
| [edu-glasses-host](https://github.com/Entertech/edu-glasses-host/tree/feat/edu-sdk-integration) | `edu_host`包、SDK使用说明、协议、SDK既有检查 |
| [edu-glasses-demo](https://github.com/Entertech/edu-glasses-demo) | `demo_cli.py`、5本Notebook、耳机示例、CLI既有检查及操作指引 |

应用的`from edu_host import EduSession`及现有SDK接口不变。SDK版本升为0.3.0，
仍为验证候选。安装方式见[SDK使用说明](SDK_GUIDE.md#2-安装-sdk)；尚未发布PyPI。

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
