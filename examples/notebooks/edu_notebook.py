"""Jupyter 笔记本用的眼镜会话辅助：经 subprocess 驱动 demo_cli。

为什么不直接 import edu_host 连蓝牙？因为 macOS 的 IOBluetooth 要求主线程
run loop、Windows 走标准库 socket——demo_cli 内部已经把平台差异都处理好了。
笔记本里通过子进程的 stdin/stdout 管道驱动它，代码在三个平台上完全一样，
蓝牙权限也归属到启动 Jupyter 的终端。

用法::

    from edu_notebook import EduSession
    s = EduSession()              # macOS 自动找 EDU-*；其他平台传 bt="AA:BB:.."
    s.sensors()                   # -> {"als": 126, "battery_temp": -8, ...}
    s.photo("shot.jpg")           # 拍照并等 JPEG 落盘，返回绝对路径
    s.record("voice.wav", 5)      # 录 5 秒音
    s.events(10)                  # 收 10 秒事件（旋钮/按键...）
    s.close()
"""

from __future__ import annotations

import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

_EVENT_RE = re.compile(r"\[event\] (\w+) (.*)")
_KNOB_RE = re.compile(r"(LEFT|RIGHT) dx=(-?\d+) dy=(-?\d+)")


class EduSessionError(RuntimeError):
    pass


class EduSession:
    """一个到眼镜的 demo_cli 子进程会话。"""

    def __init__(self, bt: str = "auto", connect_timeout: float = 40.0,
                 out_dir: str | Path = "captures"):
        self.out_dir = Path(out_dir).resolve()
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._proc = subprocess.Popen(
            [sys.executable, "-u", str(REPO_ROOT / "demo_cli.py"),
             "--bt", bt, "--out-dir", str(self.out_dir)],
            cwd=str(REPO_ROOT), text=True, bufsize=1,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT)
        self._lines: "queue.Queue[str]" = queue.Queue()
        self._reader = threading.Thread(target=self._pump_stdout, daemon=True)
        self._reader.start()
        banner = self.wait_for(lambda l: l.startswith("connected!")
                               or "failed" in l or "not found" in l,
                               connect_timeout)
        if not banner.startswith("connected!"):
            self.close()
            raise EduSessionError("连接失败：%s（先在系统蓝牙里配对并连接眼镜）"
                                  % banner)
        self.banner = banner
        print(banner)

    # -- 底层管道 ---------------------------------------------------------

    def _pump_stdout(self) -> None:
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            # REPL 提示符 "edu> " 不带换行，会前缀在回复行上（可能叠加多个），
            # 异步事件还带 \r —— 统一清理，方便上层用 startswith 匹配。
            text = line.rstrip("\n").replace("\r", "")
            while text.startswith("edu> "):
                text = text[len("edu> "):]
            self._lines.put(text)

    def send(self, command: str) -> None:
        if self._proc.poll() is not None:
            raise EduSessionError("会话已退出")
        assert self._proc.stdin is not None
        self._proc.stdin.write(command + "\n")
        self._proc.stdin.flush()

    def wait_for(self, predicate, timeout: float, collect=None) -> str:
        """逐行读输出直到 predicate(line) 为真；collect 收集途中所有行。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                line = self._lines.get(timeout=0.2)
            except queue.Empty:
                continue
            if collect is not None:
                collect.append(line)
            if predicate(line):
                return line
        raise EduSessionError("等待输出超时（%.0fs）" % timeout)

    # -- 命令封装 ---------------------------------------------------------

    def sensors(self, timeout: float = 8.0) -> dict:
        """读一次传感器，返回 {"als", "battery_temp", "btcore_temp"}。"""
        self.send("sensors")
        result: dict = {}

        def feed(line: str) -> bool:
            m = re.search(r"ALS \(raw counts\) : (\d+)", line)
            if m:
                result["als"] = int(m.group(1))
            m = re.search(r"battery temp\s+: (-?\d+) degC", line)
            if m:
                result["battery_temp"] = int(m.group(1))
            m = re.search(r"BT core temp\s+: (-?\d+) degC", line)
            if m:
                result["btcore_temp"] = int(m.group(1))
            return len(result) >= 3

        self.wait_for(feed, timeout)
        return result

    def photo(self, filename: str | Path, timeout: float = 30.0) -> Path:
        """拍一张照，阻塞到 JPEG 落盘，返回绝对路径。"""
        path = (self.out_dir / filename).resolve()
        self.send("photo %s" % path)
        self.wait_for(lambda l: "[photo] saved" in l, timeout)
        return path

    def record(self, filename: str | Path, seconds: float,
               timeout: float = 20.0) -> Path:
        """录 *seconds* 秒音频到 WAV，返回绝对路径。"""
        path = (self.out_dir / filename).resolve()
        self.send("record start %s" % path)
        self.wait_for(lambda l: l.startswith("recording ->"), timeout)
        time.sleep(seconds)
        self.send("record stop")
        self.wait_for(lambda l: l.startswith("stopped."), timeout)
        return path

    def events(self, seconds: float) -> list:
        """收集 *seconds* 秒内的设备事件，返回 [(种类, 详情文本), ...]。"""
        found: list = []
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                line = self._lines.get(timeout=0.2)
            except queue.Empty:
                continue
            m = _EVENT_RE.search(line)
            if m:
                found.append((m.group(1), m.group(2)))
        return found

    @staticmethod
    def knob_delta(detail: str):
        """解析 KNOB 事件详情，返回 (方向, dx) 或 None。"""
        m = _KNOB_RE.search(detail)
        if not m:
            return None
        return m.group(1), int(m.group(2))

    def tone(self, name_or_id="click", timeout: float = 8.0) -> None:
        self.send("tone %s" % name_or_id)
        self.wait_for(lambda l: l.startswith("tone:"), timeout)

    def led(self, spec: str, timeout: float = 8.0) -> None:
        """如 s.led("inner blink green fast")。"""
        self.send("led %s" % spec)
        self.wait_for(lambda l: l.startswith("led:"), timeout)

    def close(self) -> None:
        try:
            if self._proc.poll() is None:
                self.send("quit")
                self._proc.wait(timeout=10)
        except Exception:
            self._proc.kill()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
