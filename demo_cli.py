#!/usr/bin/env python3
"""Interactive demo CLI for the Looktech glasses education firmware.

Demonstrates all five host-visible features:

1. ``info``                 — device info (firmware version, battery, charging)
2. ``sensors``              — ALS raw counts + battery/BT-core temperatures
3. ``photo [out.jpg]``      — take a photo; the JPEG arrives asynchronously
4. ``record start/stop``    — mic OPUS stream -> growing WAV file
5. live events              — button / knob / audio-state / img-state prints

Two ways to connect:

**Bluetooth direct (recommended, all platforms)** — pair the glasses in the
OS first, then::

    python demo_cli.py --bt AA:BB:CC:DD:EE:FF     # Windows / Linux / macOS
    python demo_cli.py --bt auto                  # find paired "EDU-*" glasses

On Windows/Linux this uses the standard-library Bluetooth socket (no extra
dependencies); on macOS it drives IOBluetooth (needs
``pip install pyobjc-core pyobjc-framework-IOBluetooth`` and the one-time
Bluetooth permission prompt for your terminal app).

**Virtual serial ports (fallback)** — if your OS exposes the SPP services as
COM ports (mainly Windows)::

    python demo_cli.py --ctrl-port COM5 [--audio-port COM6] [--img-port COM7]

**Scripted / agent-driven usage** — the REPL reads stdin, so commands can be
piped in. Use ``wait <seconds>`` to keep the session alive while
asynchronous results (photo JPEG, audio stream) arrive::

    printf 'sensors\\nphoto out.jpg\\nwait 25\\nquit\\n' | \\
        python demo_cli.py --bt auto

See AGENTS.md for per-task recipes and the exact success markers to check.

The headset function (music/calls, A2DP/HFP) is used through the OS
Bluetooth audio device directly and is NOT part of this demo.
"""

from __future__ import annotations

import argparse
import logging
import shlex
import sys
from pathlib import Path

from edu_host import protocol
from edu_host import EduSession, EduClientError, EduStatusError, EduTimeoutError
from edu_host.ota_client import OTAError
from edu_host.protocol import (CompletedImage, DeviceInfo, EduEvent, LedColor,
                               LedId, LedMode, LedSpeed, SensorData, Status, Tone)
from edu_host.transport import list_serial_ports

HELP_TEXT = """\
Commands:
  info                     query device info (fw version, battery, charging)
  sensors                  query sensors (ALS raw, battery temp, btcore temp)
  photo [out.jpg]          take a photo; JPEG is saved when it arrives
  record start [out.wav]   start mic recording
  record stop              stop mic recording and finalize the WAV file
  ota <firmware.bin>       upgrade firmware over OTA SPP 0x2026
  reboot                   reboot the glasses (~0.5s after the reply)
  led <inner|outer> <off|on|blink|breath> [color] [speed]
  tone <name|id|list>      play a built-in prompt tone
  wait <seconds>           keep the session alive (for piped/scripted use)
  help                     show this help
  quit / exit              leave the demo
Asynchronous device events (buttons, knob, audio/img state) print live.
"""


def split_command(line: str):
    """按 shell 规则分词，但保留 Windows 反斜杠路径。

    ``shlex.split`` 的 POSIX 模式会把 ``C:\\Users\\x.jpg`` 的反斜杠当转义
    符吃掉；这里用非 POSIX 模式分词后手工剥除成对引号。
    """
    tokens = shlex.split(line, posix=False)
    return [t[1:-1] if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'" else t
            for t in tokens]


def print_event(event: EduEvent) -> None:
    print("\r[event] %s" % event)


def print_image(path: Path, image: CompletedImage) -> None:
    print("\r[photo] saved %s (%d bytes, group %d)"
          % (path, len(image.data), image.group_id))


# ---------------------------------------------------------------------------
# Shared REPL output helpers
# ---------------------------------------------------------------------------

def show_info(status: int, data: bytes) -> None:
    if status != Status.OK:
        print("failed: status=%s" % protocol.enum_name(Status, status))
        return
    print_info(DeviceInfo.parse(data))


def print_info(info: DeviceInfo) -> None:
    print("firmware version : %s (0x%016X)" % (info.fw_version_str,
                                               info.fw_version))
    print("battery level    : %d%%" % info.battery_level)
    print("charging         : %s" % ("yes" if info.charging else "no"))


def show_sensors(status: int, data: bytes) -> None:
    if status != Status.OK:
        print("failed: status=%s" % protocol.enum_name(Status, status))
        return
    print_sensors(SensorData.parse(data))


def print_sensors(s: SensorData) -> None:
    print("ALS (raw counts) : %d   (raw ADC counts, not lux)" % s.als_raw)
    print("battery temp     : %d degC" % s.battery_temp_c)
    print("BT core temp     : %d degC" % s.btcore_temp_c)


def show_photo_rsp(status: int, data: bytes) -> None:
    if status == Status.OK:
        print("photo triggered — the JPEG will be saved when it arrives.")
    elif status == Status.BUSY:
        print("device is busy taking another photo, try again later.")
    else:
        print("photo request failed: status=%s data=%s"
              % (protocol.enum_name(Status, status), data.hex()))


LED_IDS = {"inner": LedId.INNER, "outer": LedId.OUTER}
LED_MODES = {"off": LedMode.OFF, "on": LedMode.ON,
             "blink": LedMode.BLINK, "breath": LedMode.BREATH}
LED_COLORS = {c.name.lower(): c for c in LedColor}
LED_SPEEDS = {s.name.lower(): s for s in LedSpeed}
LED_USAGE = "usage: led <inner|outer> <off|on|blink|breath> [color] [speed]"


def parse_led_args(args):
    """Parse the REPL 'led' command; returns ((id,mode,color,speed), error)."""
    if len(args) < 3:
        return None, LED_USAGE
    led = LED_IDS.get(args[1].lower())
    mode = LED_MODES.get(args[2].lower())
    if led is None or mode is None:
        return None, LED_USAGE
    color, speed = LedColor.WHITE, LedSpeed.NORMAL
    for extra in args[3:5]:
        word = extra.lower()
        if word in LED_COLORS:
            color = LED_COLORS[word]
        elif word in LED_SPEEDS:
            speed = LED_SPEEDS[word]
        else:
            return None, "unknown color/speed %r; colors: %s; speeds: %s" % (
                extra, "/".join(LED_COLORS), "/".join(LED_SPEEDS))
    return (led, mode, color, speed), None


def parse_tone_arg(word: str):
    """Tone name or numeric id -> int, or None if unknown."""
    if word.isdigit():
        value = int(word)
        return value if value <= 0xFF else None
    try:
        return Tone[word.upper()]
    except KeyError:
        return None


def print_tone_list() -> None:
    print(", ".join("%s=%d" % (t.name.lower(), t.value) for t in Tone))


def print_ota_progress(stage: str, done: int, total: int) -> None:
    if stage == "data" and total:
        print("\r[ota] data %d/%d bytes (%.1f%%)"
              % (done, total, done * 100.0 / total))
    else:
        print("\r[ota] %s" % stage)


def run_session(session: EduSession, ota_chunk_size: int = 512,
                ota_packet_interval_ms: float = 10.0) -> int:
    """One REPL for every transport; only stdin is read on a worker thread."""
    import queue
    import threading

    session.add_event_listener(print_event)
    session.add_image_listener(print_image)
    try:
        session.connect()
    except EduTimeoutError as exc:
        print("handshake failed: %s" % exc)
        print("hint: is this really the CTRL channel/port?")
        return 1
    except Exception as exc:
        print("failed to connect: %s" % exc)
        return 1
    ack = session.hello_ack
    print("connected! proto v%d, firmware %s, caps: %s"
          % (ack.proto_ver, ack.fw_version_str, ", ".join(ack.cap_names)))
    print(HELP_TEXT)

    lines = queue.Queue()

    def read_stdin():
        try:
            for line in sys.stdin:
                lines.put(line)
        finally:
            lines.put(None)

    threading.Thread(target=read_stdin, name="edu-cli-stdin", daemon=True).start()
    print("edu> ", end="", flush=True)
    try:
        while True:
            session.poll(0.05)
            try:
                line = lines.get_nowait()
            except queue.Empty:
                continue
            if line is None:
                break
            line = line.strip()
            if not line:
                continue
            try:
                args = split_command(line)
                cmd = args[0].lower()
                if cmd in ("quit", "exit", "q"):
                    break
                elif cmd == "help":
                    print(HELP_TEXT)
                elif cmd == "info":
                    print_info(session.info())
                elif cmd == "sensors":
                    print_sensors(session.sensors())
                elif cmd == "photo":
                    # CLI filenames retain their historical cwd-relative meaning.
                    filename = Path(args[1]).resolve() if len(args) > 1 else None
                    try:
                        rsp = session.trigger_photo(filename)
                        show_photo_rsp(rsp.status, rsp.data)
                    except EduStatusError as exc:
                        show_photo_rsp(exc.status, exc.data)
                elif cmd == "record" and len(args) >= 2 and args[1] == "start":
                    filename = Path(args[2]).resolve() if len(args) > 2 else "record.wav"
                    print("recording -> %s" % session.record_start(filename))
                elif cmd == "record" and len(args) >= 2 and args[1] == "stop":
                    if not session.is_recording:
                        print("no recording in progress.")
                    else:
                        stats = session.record_stop()
                        print("stopped. %d packages, %d frames (~%.1f s), "
                              "%d lost, %d decode errors -> %s"
                              % (stats.packages, stats.frames, stats.seconds,
                                 stats.lost_packages, stats.decode_errors, stats.output_path))
                elif cmd == "ota":
                    if len(args) < 2:
                        print("usage: ota <firmware.bin>")
                    else:
                        result = session.ota(args[1], progress=print_ota_progress,
                                             chunk_size=ota_chunk_size,
                                             packet_interval_ms=ota_packet_interval_ms)
                        print("[ota] complete, reboot=%d" % result.reboot)
                elif cmd == "reboot":
                    rsp = session.reboot()
                    print("reboot: status=%s (device restarts in ~0.5s)"
                          % protocol.enum_name(Status, rsp.status))
                elif cmd == "led":
                    parsed, err = parse_led_args(args)
                    if err:
                        print(err)
                    else:
                        rsp = session.set_led(*parsed)
                        print("led: status=%s" % protocol.enum_name(Status, rsp.status))
                elif cmd == "tone":
                    if len(args) < 2 or args[1].lower() == "list":
                        print_tone_list()
                    else:
                        tone = parse_tone_arg(args[1])
                        if tone is None:
                            print("unknown tone %r (try 'tone list')" % args[1])
                        else:
                            rsp = session.play_tone(tone)
                            print("tone: status=%s" % protocol.enum_name(Status, rsp.status))
                elif cmd in ("wait", "sleep"):
                    try:
                        seconds = float(args[1]) if len(args) > 1 else 1.0
                    except ValueError:
                        print("usage: wait <seconds>")
                        seconds = 0.0
                    session.wait(min(max(seconds, 0.0), 3600.0))
                else:
                    print("unknown command: %r (try 'help')" % line)
            except EduTimeoutError as exc:
                print("timeout: %s" % exc)
            except OTAError as exc:
                print("ota error: %s" % exc)
            except (EduClientError, ValueError, OSError) as exc:
                print("error: %s" % exc)
            print("edu> ", end="", flush=True)
    except KeyboardInterrupt:
        print()
    except OSError as exc:
        print("connection lost: %s" % exc)
        return 1
    finally:
        session.close()
    return 0


def run_threaded_session(ctrl_t, audio_t, img_t, ota_t, out_dir: str,
                         ota_chunk_size: int = 512,
                         ota_packet_interval_ms: float = 10.0) -> int:
    return run_session(EduSession.from_transports(ctrl_t, audio_t, img_t, ota_t,
                                                 out_dir=out_dir),
                       ota_chunk_size, ota_packet_interval_ms)


def run_mac_session(bt_addr: str, out_dir: str, ota_chunk_size: int = 512,
                    ota_packet_interval_ms: float = 10.0) -> int:
    return run_session(EduSession(bt=bt_addr, out_dir=out_dir),
                       ota_chunk_size, ota_packet_interval_ms)


# ---------------------------------------------------------------------------
# Entry point / platform dispatch
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Looktech education-firmware host demo",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--bt", metavar="ADDR",
                        help="connect via Bluetooth RFCOMM to this device "
                             "address (AA:BB:CC:DD:EE:FF); 'auto' finds a "
                             "paired device named EDU-* (all platforms)")
    parser.add_argument("--ctrl-channel", type=int, default=6,
                        help="RFCOMM channel of EDU-CTRL (Windows/Linux --bt)")
    parser.add_argument("--audio-channel", type=int, default=5,
                        help="RFCOMM channel of EDU-AUDIO (Windows/Linux --bt)")
    parser.add_argument("--img-channel", type=int, default=4,
                        help="RFCOMM channel of EDU-IMG (Windows/Linux --bt)")
    parser.add_argument("--ota-channel", type=int, default=7,
                        help="RFCOMM channel of OTA 0x2026 (Windows/Linux --bt)")
    parser.add_argument("--ota-chunk-size", type=int, default=512,
                        help="max firmware payload bytes per OTA SEND_DATA packet")
    parser.add_argument("--ota-packet-interval-ms", type=float, default=10.0,
                        help="minimum interval between OTA SEND_DATA packets")
    parser.add_argument("--list", action="store_true",
                        help="list candidate serial ports and exit")
    parser.add_argument("--ctrl-port",
                        help="EDU-CTRL serial port (fallback, SPP UUID 0x2028)")
    parser.add_argument("--audio-port",
                        help="EDU-AUDIO serial port (SPP UUID 0x2024)")
    parser.add_argument("--img-port",
                        help="EDU-IMG serial port (SPP UUID 0x2025)")
    parser.add_argument("--ota-port",
                        help="OTA serial port (SPP UUID 0x2026)")
    parser.add_argument("--out-dir", default="captures",
                        help="directory for saved photos/recordings")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s")

    if args.list:
        ports = list_serial_ports()
        if not ports:
            print("no serial ports found.")
        for p in ports:
            print(p)
        return 0

    if not args.bt and not args.ctrl_port:
        parser.error("connect with --bt <addr> (recommended) or "
                     "--ctrl-port <port> (serial fallback); "
                     "--list shows serial candidates")
    session = EduSession(bt=args.bt,
                         ctrl_port=None if args.bt else args.ctrl_port,
                         audio_port=args.audio_port, img_port=args.img_port,
                         ota_port=args.ota_port, ctrl_channel=args.ctrl_channel,
                         audio_channel=args.audio_channel, img_channel=args.img_channel,
                         ota_channel=args.ota_channel, out_dir=args.out_dir)
    return run_session(session, args.ota_chunk_size, args.ota_packet_interval_ms)


if __name__ == "__main__":
    sys.exit(main())
