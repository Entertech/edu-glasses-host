# Looktech Glasses Python SDK

面向开发者的 Looktech 智能眼镜 Python SDK，提供设备控制、拍摄、音频采集、
传感器、事件、OTA 和 Wi-Fi 媒体导出接口。统一从 `looktech_glasses_sdk.GlassesSession` 接入。

- [外部开发者指南](https://github.com/Entertech/looktech-glasses-demo/blob/main/docs/SDK_GUIDE.md)
- [API 参考](https://github.com/Entertech/looktech-glasses-demo/blob/main/docs/API_REFERENCE.md)
- [公开 Demo、CLI 和 Notebook](https://github.com/Entertech/looktech-glasses-demo)

## 安装

> 当前为更名候选版本；新 PyPI 包发布前，请先构建并安装 SDK wheel，再从本仓库安装 Demo。下列 PyPI 命令在新版本发布后使用。

[SDK 0.6.0 发布后可从 PyPI 安装](https://pypi.org/project/looktech-glasses-sdk/0.6.0/)，使用 Cython 二进制 wheel 分发。在自己的项目安装：

```bash
python -m pip install --only-binary=looktech-glasses-sdk "looktech-glasses-sdk==0.6.0"
# macOS 使用这一条
python -m pip install --only-binary=looktech-glasses-sdk "looktech-glasses-sdk[macos]==0.6.0"
```

支持标准 CPython 3.9–3.14：Windows x64、macOS 11+ Intel/Apple Silicon、Linux glibc 2.17+ x64/ARM64。
各 Python 版本和依赖可能提高系统最低版本，以实际 wheel 和安装器要求为准。
PyPy、free-threaded Python、Windows ARM64、32 位和 Alpine/musl 暂未提供 wheel。
外部开发者无需 SDK 仓库权限、Git 或编译器；发行包包含二进制扩展、类型声明与包元数据。
`audio`、`serial`、`macos` extras 按需组合，例如 `[macos,audio]`。
WAV 解码另需系统 libopus；缺少时录音保留 `.opusraw`。

## 第一个程序

先安装开发者固件，在系统蓝牙设置配对眼镜，然后：

```python
from looktech_glasses_sdk import GlassesSession

with GlassesSession(bt="auto") as glasses:
    print(glasses.capabilities)
    print(glasses.info())
    if glasses.supports("SENSORS"):
        print(glasses.sensors())
```

多台设备时指定明确地址。macOS 的连接、请求、等待和关闭在主线程顺序执行；
等待使用 `wait()` 或 `poll()` 保持收包，事件回调只排队，由主循环发送请求。
拍摄、录音和 WiFi 导出完整示例见公开开发者指南。SDK 独立使用，不注册 CLI 命令。

## 内部维护

本仓库维护 SDK 实现、协议与既有检查。公开使用文档在 demo 仓库维护。
构建和手动发布步骤见 [RELEASING.md](docs/RELEASING.md)，兼容变化见 [MIGRATION.md](docs/MIGRATION.md)。
构建仅上传 wheel，禁用 sdist；Cython 增加直接阅读源码的成本，无法保证二进制不可逆向。
