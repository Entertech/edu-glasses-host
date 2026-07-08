#!/usr/bin/env python3
"""耳机（A2DP / HFP）演示：把眼镜当蓝牙音频设备来放音和录音。

眼镜的耳机功能走操作系统的标准蓝牙音频协议，不经过 EDU SPP 协议：

* **A2DP**（高音质单向）：给眼镜放音乐/提示音；
* **HFP**（通话档双向）：用眼镜的麦克风。一旦打开眼镜麦克风，蓝牙链路
  会切到 HFP，此时播放音质也会降到通话档——这不是 bug，是蓝牙经典音频
  的协议特性，松开麦克风后恢复 A2DP。

本脚本用 `sounddevice`（PortAudio）**按名字指定设备**收放音频，不改系统
默认输出，演示完全自包含::

    python3 examples/headset_demo.py list                 # 列出眼镜音频设备
    python3 examples/headset_demo.py play                 # A2DP 放一段琶音
    python3 examples/headset_demo.py record -o voice.wav  # HFP 录 5 秒麦克风
    python3 examples/headset_demo.py loopback             # 录进来立刻放出去

依赖：``pip install sounddevice``（wheel 自带 PortAudio）。macOS 首次录音
会弹终端的麦克风权限授权。
"""

from __future__ import annotations

import argparse
import array
import math
import sys
import time
import wave

try:
    import sounddevice as sd
except ImportError:
    print("需要 sounddevice：python3 -m pip install sounddevice")
    sys.exit(1)

DEFAULT_NAME_SUBSTRING = "EDU-"


def find_devices(name_sub: str):
    """按名字子串找眼镜的输入/输出设备，返回 (inputs, outputs)。"""
    ins, outs = [], []
    for idx, dev in enumerate(sd.query_devices()):
        if name_sub.lower() not in dev["name"].lower():
            continue
        if dev["max_input_channels"] > 0:
            ins.append((idx, dev))
        if dev["max_output_channels"] > 0:
            outs.append((idx, dev))
    return ins, outs


def cmd_list(args) -> int:
    ins, outs = find_devices(args.device)
    if not ins and not outs:
        print("没有找到名字含 %r 的音频设备。" % args.device)
        print("请确认：眼镜已在系统蓝牙里连接（不只是已配对）。")
        return 1
    for idx, dev in outs:
        print("[输出/A2DP] #%d  %s  (%d ch, %.0f Hz)"
              % (idx, dev["name"], dev["max_output_channels"],
                 dev["default_samplerate"]))
    for idx, dev in ins:
        print("[输入/HFP ] #%d  %s  (%d ch, %.0f Hz)"
              % (idx, dev["name"], dev["max_input_channels"],
                 dev["default_samplerate"]))
    return 0


def synth_arpeggio(seconds: float, samplerate: int) -> bytes:
    """生成一段 A 大调琶音（16-bit 立体声），带淡入淡出防爆音。"""
    notes = [440.00, 554.37, 659.25, 880.00]
    pcm = array.array("h")
    per_note = max(1, int(samplerate * seconds / len(notes)))
    ramp = max(1, samplerate // 100)  # 10 ms 淡入/淡出
    for freq in notes:
        for i in range(per_note):
            env = min(1.0, i / ramp, (per_note - i) / ramp)
            v = int(12000 * env * math.sin(2 * math.pi * freq * i / samplerate))
            pcm.append(v)  # left
            pcm.append(v)  # right
    return pcm.tobytes()


def cmd_play(args) -> int:
    _, outs = find_devices(args.device)
    if not outs:
        print("找不到眼镜的输出设备（先在系统蓝牙里连接眼镜）。")
        return 1
    idx, dev = outs[0]
    rate = int(dev["default_samplerate"]) or 44100
    print("A2DP 播放 %.1f 秒 -> #%d %s (%d Hz)"
          % (args.seconds, idx, dev["name"], rate))
    data = synth_arpeggio(args.seconds, rate)
    with sd.RawOutputStream(samplerate=rate, channels=2, dtype="int16",
                            device=idx) as stream:
        stream.write(data)
    print("播放完成。")
    return 0


def cmd_record(args) -> int:
    ins, _ = find_devices(args.device)
    if not ins:
        print("找不到眼镜的输入设备。注意：部分系统只有把眼镜设为通话设备"
              "后才暴露 HFP 麦克风。")
        return 1
    idx, dev = ins[0]
    rate = int(dev["default_samplerate"]) or 16000
    print("HFP 录音 %.1f 秒 <- #%d %s (%d Hz)…（此时链路切 HFP 属正常）"
          % (args.seconds, idx, dev["name"], rate))
    frames = bytearray()
    with sd.RawInputStream(samplerate=rate, channels=1, dtype="int16",
                           device=idx) as stream:
        deadline = time.time() + args.seconds
        while time.time() < deadline:
            chunk, _overflow = stream.read(rate // 10)
            frames += bytes(chunk)
    with wave.open(args.out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    print("已保存 %s（%d 字节，%.1f 秒 @ %d Hz）"
          % (args.out, len(frames), len(frames) / 2 / rate, rate))
    return 0


def cmd_loopback(args) -> int:
    ins, outs = find_devices(args.device)
    if not ins or not outs:
        print("回环需要眼镜同时暴露输入和输出设备。")
        return 1
    in_idx, in_dev = ins[0]
    out_idx, _ = outs[0]
    rate = int(in_dev["default_samplerate"]) or 16000
    print("回环 %.1f 秒：#%d -> #%d（%d Hz，对着眼镜说话，会从眼镜里放出来）"
          % (args.seconds, in_idx, out_idx, rate))
    with sd.RawInputStream(samplerate=rate, channels=1, dtype="int16",
                           device=in_idx) as mic, \
         sd.RawOutputStream(samplerate=rate, channels=1, dtype="int16",
                            device=out_idx) as spk:
        deadline = time.time() + args.seconds
        while time.time() < deadline:
            chunk, _overflow = mic.read(rate // 10)
            spk.write(bytes(chunk))
    print("回环结束。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="EDU 眼镜耳机（A2DP/HFP）演示",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--device", default=DEFAULT_NAME_SUBSTRING,
                        help="音频设备名子串（按名字匹配眼镜）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="列出匹配的音频设备")
    p = sub.add_parser("play", help="A2DP 播放测试音")
    p.add_argument("--seconds", type=float, default=4.0)
    p = sub.add_parser("record", help="HFP 录制眼镜麦克风到 WAV")
    p.add_argument("--seconds", type=float, default=5.0)
    p.add_argument("-o", "--out", default="headset_record.wav")
    p = sub.add_parser("loopback", help="麦克风 -> 扬声器实时回环")
    p.add_argument("--seconds", type=float, default=8.0)
    args = parser.parse_args()

    return {"list": cmd_list, "play": cmd_play,
            "record": cmd_record, "loopback": cmd_loopback}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
