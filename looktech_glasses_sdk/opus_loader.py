"""定位 libopus 并创建 OPUS 解码器（跨平台，免环境变量）。

macOS 上 Homebrew 的 `/opt/homebrew/lib`（Apple Silicon）和
`/usr/local/lib`（Intel）不在 `ctypes.util.find_library` 的默认搜索路径里，
导致 `import opuslib` 找不到 libopus——历史上要靠
`DYLD_LIBRARY_PATH=/opt/homebrew/lib` 环境变量，学生极易踩坑且症状是
**录出来的 WAV 是空的**。本模块在 import opuslib 前给 `find_library`
打补丁，把已知安装路径兜住，让 `pip install opuslib && brew install opus`
之后开箱即用。
"""

from __future__ import annotations

import ctypes.util
import os

_KNOWN_OPUS_PATHS = (
    "/opt/homebrew/lib/libopus.dylib",   # macOS Apple Silicon (Homebrew)
    "/opt/homebrew/lib/libopus.0.dylib",
    "/usr/local/lib/libopus.dylib",      # macOS Intel (Homebrew)
    "/usr/local/lib/libopus.0.dylib",
)

_patched = False


def _patch_find_library() -> None:
    global _patched
    if _patched:
        return
    _patched = True
    original = ctypes.util.find_library

    def find_library(name):
        found = original(name)
        if found is None and name == "opus":
            for candidate in _KNOWN_OPUS_PATHS:
                if os.path.exists(candidate):
                    return candidate
        return found

    ctypes.util.find_library = find_library


def create_decoder(sample_rate: int, channels: int):
    """返回 opuslib.Decoder；opuslib/libopus 不可用时抛 ImportError/OSError。"""
    _patch_find_library()
    import opuslib  # noqa: import after patch so libopus can be located
    return opuslib.Decoder(sample_rate, channels)
