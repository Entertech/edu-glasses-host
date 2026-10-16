"""教学 Notebook 的薄包装：直接复用 edu_host.EduSession，不解析 CLI 输出。

请先在仓库根目录运行 ``python -m pip install -e .``。macOS 的单元格须在
内核主线程执行；等待设备时使用 s.wait()/s.events()，让 IOBluetooth 继续收包。
"""
from __future__ import annotations

from pathlib import Path
from typing import Union

from edu_host import (EduSession as _EduSession, EduClientError, KnobEvent,
                      ButtonEvent, AudioStateEvent, ImgStateEvent,
                      LedId, LedMode, LedColor, LedSpeed)

EduSessionError = EduClientError


class EduSession(_EduSession):
    """保留教学用的自动连接、传感器字典与旋钮辅助方法。"""

    def __init__(self, bt: str = "auto", connect_timeout: float = 40.0,
                 out_dir: Union[str, Path] = "captures") -> None:
        super().__init__(bt=bt, out_dir=out_dir)
        self.connect(timeout=connect_timeout)
        ack = self.hello_ack
        self.banner = "connected! proto v%d, firmware %s, caps: %s" % (
            ack.proto_ver, ack.fw_version_str, ", ".join(ack.cap_names))
        print(self.banner)

    def sensors(self, timeout: float = 8.0) -> dict:
        reading = super().sensors(timeout)
        return {"als": reading.als_raw, "battery_temp": reading.battery_temp_c,
                "btcore_temp": reading.btcore_temp_c}

    def events(self, seconds: float) -> list:
        """返回 [(种类, 类型化事件), ...]；旋钮详情直接读取字段。"""
        names = {ButtonEvent: "BUTTON", KnobEvent: "KNOB",
                 AudioStateEvent: "AUDIO_STATE", ImgStateEvent: "IMG_STATE"}
        return [(names.get(type(event), "UNKNOWN_EVT"), event)
                for event in super().events(seconds)]

    @staticmethod
    def knob_delta(detail):
        if isinstance(detail, KnobEvent):
            return detail.direction_name, detail.delta_x
        return None

    def tone(self, name_or_id="click", timeout: float = 8.0):
        return self.play_tone(name_or_id, timeout)

    def led(self, spec: str, timeout: float = 8.0):
        """例如 s.led("inner blink green fast")。"""
        words = spec.upper().split()
        if not 2 <= len(words) <= 4:
            raise ValueError("led: <inner|outer> <off|on|blink|breath> [color] [speed]")
        try:
            led, mode = LedId[words[0]], LedMode[words[1]]
            color, speed = LedColor.WHITE, LedSpeed.NORMAL
            for word in words[2:]:
                if word in LedColor.__members__:
                    color = LedColor[word]
                else:
                    speed = LedSpeed[word]
        except KeyError as exc:
            raise ValueError("unknown LED setting %s" % exc) from None
        return self.set_led(led, mode, color, speed, timeout)
