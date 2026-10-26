# Looktech EDU 眼镜 Python SDK

通过经典蓝牙 SPP 调用 EDU 眼镜的设备信息、传感器、拍照、录像、麦克风、事件、
设备控制、OTA 和 WiFi 媒体导出能力。统一从 `edu_host.EduSession` 接入。

- [外部开发者指南](https://github.com/Entertech/edu-glasses-demo/blob/main/docs/SDK_GUIDE.md)
- [API 参考](https://github.com/Entertech/edu-glasses-demo/blob/main/docs/API_REFERENCE.md)
- [公开 Demo、CLI 和 Notebook](https://github.com/Entertech/edu-glasses-demo)

## 安装

0.5.0 改用 Cython 二进制 wheel 分发。首次 PyPI 发布完成后，在自己的项目安装：

```bash
python -m pip install --only-binary=edu-glasses-host "edu-glasses-host==0.5.0"
# macOS 使用这一条
python -m pip install --only-binary=edu-glasses-host "edu-glasses-host[macos]==0.5.0"
```

支持标准 CPython 3.9–3.14：Windows x64、macOS 11+ Intel/Apple Silicon、Linux glibc 2.17+ x64/ARM64。
各 Python 版本和依赖可能提高系统最低版本，以实际 wheel 和安装器要求为准。
PyPy、free-threaded Python、Windows ARM64、32 位和 Alpine/musl 暂未提供 wheel。
外部开发者无需 SDK 仓库权限、Git 或编译器；发行包包含二进制扩展、类型声明与包元数据。
`audio`、`serial`、`macos` extras 按需组合，例如 `[macos,audio]`。
WAV 解码另需系统 libopus；缺少时录音保留 `.opusraw`。

## 第一个程序

先安装 EDU 固件，在系统蓝牙设置配对眼镜，然后：

```python
from edu_host import EduSession

with EduSession(bt="auto") as glasses:
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
