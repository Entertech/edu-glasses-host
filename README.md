# Looktech EDU 眼镜 Python SDK

通过经典蓝牙SPP调用EDU眼镜的设备信息、传感器、拍照、录像、麦克风、按键事件、
设备控制、OTA和WiFi媒体导出能力。应用统一从 `edu_host.EduSession` 接入。

- [SDK使用说明与API速查](docs/SDK_GUIDE.md)
- [EDU通信协议](docs/PROTOCOL.md)
- [独立Demo仓库](https://github.com/Entertech/edu-glasses-demo)：CLI、按键拍摄、Notebook和耳机示例
- [0.3.0拆分迁移说明](docs/MIGRATION.md)

## 在自己的项目中安装

Python 3.9+。SDK可通过pip从Git安装，无需复制SDK源码或下载demo。
当前0.3.0是功能分支候选，尚未发布到PyPI；`pip install edu-glasses-host`不能作为当前版本的安装方式。
Git安装需要本机有Git，源码见 `feat/edu-sdk-integration`，尚未合并main。

```bash
python -m venv .venv
# macOS/Linux：source .venv/bin/activate
# Windows PowerShell：.\.venv\Scripts\Activate.ps1

# Windows/Linux，标准库蓝牙socket，无必选运行依赖
python -m pip install "edu-glasses-host @ git+https://github.com/Entertech/edu-glasses-host.git@feat/edu-sdk-integration"

# macOS，需要IOBluetooth绑定，使用这一条
python -m pip install "edu-glasses-host[macos] @ git+https://github.com/Entertech/edu-glasses-host.git@feat/edu-sdk-integration"
```

可选extras：`audio`安装OPUS解码依赖，`serial`安装串口依赖，`macos,audio`等可组合。
WAV解码还需要系统libopus；缺失时录音保留`.opusraw`，详见SDK使用说明。
离线分发可由维护者构建wheel：`python -m pip wheel --no-deps . -w dist`，再安装该`.whl`。
业务项目的`requirements.txt`可写入上面的`edu-glasses-host @ git+https://...`依赖，
建议把分支名替换为验收过的完整commit SHA，保证环境可复现。

## 第一个程序

先在系统蓝牙设置配对已烧录EDU固件的眼镜，再运行：

```python
from edu_host import EduSession

with EduSession(bt="auto") as glasses:
    print(glasses.capabilities)
    print(glasses.info())
    if glasses.supports("SENSORS"):
        print(glasses.sensors())
```

多台设备配对时使用明确地址 `EduSession(bt="AA:BB:CC:DD:EE:FF")`。
macOS的连接、请求、等待和关闭在主线程顺序执行；等待时用`wait()`或`poll()`保持收包。
回调应简短，设备请求排队到主循环处理。退出时通过`with`或`close()`释放连接。

录像配置示例：

```python
from edu_host import EduSession

with EduSession(bt="auto") as glasses:
    print(glasses.get_video_config())
    glasses.set_video_config(resolution="1080p", orientation="portrait", max_duration_s=60)
```

完整的存储拍摄→WiFi原件导出、事件自定义和错误处理，
见[SDK使用说明](docs/SDK_GUIDE.md)。新能力按HELLO/caps检查，旧固件缺能力时明确报错。
SDK调用不需要运行demo，安装SDK也不会注册`edu-glasses`演示命令。

## SDK开发与验证

```bash
git clone --branch feat/edu-sdk-integration https://github.com/Entertech/edu-glasses-host.git
cd edu-glasses-host
python -m pip install -e .
python -m unittest discover -s tests -v
```

SDK源码、既有检查、协议和API文档在本仓库维护。CLI和教学示例在demo仓库维护；
原`edu-glasses --bt auto`命令改由demo安装提供，迁移步骤见[迁移说明](docs/MIGRATION.md)。

## 固件与验收边界

EDU需专用固件，使用系统蓝牙配对后直连SPP；不走公版App绑定认证。
HELLO用于能力发现，不提供额外权限分级。WiFi导出沿用公版ISP的ID媒体目录和LAN服务。
[配套固件源码](https://github.com/Entertech/Looktech-Glasses-Device/tree/feat/edu-main-integration)
与[历史固件产物说明](firmware/README.md)分别维护，历史WPK不代表具备全部新能力。

已有实机结果和已知问题见[验收范围](docs/SDK_GUIDE.md#验收范围与已知边界)。
仓库拆分只调整打包和示例归属，不改变设备协议或SDK调用行为。
