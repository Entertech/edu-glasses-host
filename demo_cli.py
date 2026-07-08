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
    python demo_cli.py --bt auto                  # macOS: find paired "EDU-*"

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
import time
from pathlib import Path
from typing import Optional

from edu_host import protocol
from edu_host.audio_client import AudioStreamClient
from edu_host.client import EduClient, EduClientError, EduTimeoutError
from edu_host.image_client import ImageClient
from edu_host.protocol import (CommandId, CompletedImage, DeviceInfo, EduEvent,
                               FrameParser, FrameType, HelloAck, SensorData,
                               Status, encode_frame, parse_event)
from edu_host.transport import SerialTransport, list_serial_ports

HELP_TEXT = """\
Commands:
  info                     query device info (fw version, battery, charging)
  sensors                  query sensors (ALS raw, battery temp, btcore temp)
  photo [out.jpg]          take a photo; JPEG is saved when it arrives
  record start [out.wav]   start mic recording
  record stop              stop mic recording and finalize the WAV file
  wait <seconds>           keep the session alive (for piped/scripted use)
  help                     show this help
  quit / exit              leave the demo
Asynchronous device events (buttons, knob, audio/img state) print live.
"""


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
    info = DeviceInfo.parse(data)
    print("firmware version : %s (0x%016X)" % (info.fw_version_str,
                                               info.fw_version))
    print("battery level    : %d%%" % info.battery_level)
    print("charging         : %s" % ("yes" if info.charging else "no"))


def show_sensors(status: int, data: bytes) -> None:
    if status != Status.OK:
        print("failed: status=%s" % protocol.enum_name(Status, status))
        return
    s = SensorData.parse(data)
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


# ---------------------------------------------------------------------------
# Threaded session: serial ports or Bluetooth sockets (Windows / Linux)
# ---------------------------------------------------------------------------

def run_threaded_session(ctrl_t, audio_t, img_t, out_dir: str) -> int:
    client = EduClient(ctrl_t)
    client.add_event_listener(print_event)

    audio: Optional[AudioStreamClient] = None
    if audio_t is not None:
        audio = AudioStreamClient(audio_t)

    image: Optional[ImageClient] = None
    if img_t is not None:
        image = ImageClient(img_t, output_dir=out_dir)
        image.add_image_listener(print_image)

    try:
        if image is not None:
            image.start()
        client.start()
        ack = client.hello()
    except EduTimeoutError as exc:
        print("handshake failed: %s" % exc)
        print("hint: is this really the CTRL channel/port?")
        client.close()
        return 1
    except Exception as exc:
        print("failed to connect: %s" % exc)
        return 1

    print("connected! proto v%d, firmware %s, caps: %s"
          % (ack.proto_ver, ack.fw_version_str, ", ".join(ack.cap_names)))
    print(HELP_TEXT)

    try:
        while True:
            try:
                line = input("edu> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not line:
                continue
            try:
                args = shlex.split(line)
            except ValueError as exc:
                print("parse error: %s" % exc)
                continue
            cmd = args[0].lower()
            try:
                if cmd in ("quit", "exit", "q"):
                    break
                elif cmd == "help":
                    print(HELP_TEXT)
                elif cmd == "info":
                    rsp = client.request(CommandId.GET_DEVICE_INFO)
                    show_info(rsp.status, rsp.data)
                elif cmd == "sensors":
                    rsp = client.request(CommandId.GET_SENSORS)
                    show_sensors(rsp.status, rsp.data)
                elif cmd == "photo":
                    if image is None:
                        print("no image channel: reconnect with --bt or "
                              "--img-port to receive photos.")
                        continue
                    if len(args) > 1:
                        image.set_next_photo_path(Path(args[1]))
                    rsp = client.take_photo()
                    show_photo_rsp(rsp.status, rsp.data)
                elif cmd == "record" and len(args) >= 2 and args[1] == "start":
                    if audio is None:
                        print("no audio channel: reconnect with --bt or "
                              "--audio-port to record.")
                        continue
                    if audio.is_running:
                        print("recording already running")
                        continue
                    wav = Path(args[2]) if len(args) > 2 else \
                        Path(out_dir) / "record.wav"
                    actual = audio.start(wav)
                    rsp = client.audio_start()
                    if rsp.status != Status.OK:
                        audio.stop()
                        print("AUDIO_START failed: status=%s"
                              % protocol.enum_name(Status, rsp.status))
                        continue
                    print("recording -> %s" % actual)
                elif cmd == "record" and len(args) >= 2 and args[1] == "stop":
                    if audio is None or not audio.is_running:
                        print("no recording in progress.")
                        continue
                    client.audio_stop()
                    stats = audio.stop()
                    print("stopped. %d packages, %d frames (~%.1f s), "
                          "%d lost, %d decode errors -> %s"
                          % (stats.packages, stats.frames, stats.seconds,
                             stats.lost_packages, stats.decode_errors,
                             stats.output_path))
                elif cmd in ("wait", "sleep"):
                    try:
                        secs = float(args[1]) if len(args) > 1 else 1.0
                    except ValueError:
                        print("usage: wait <seconds>")
                        continue
                    time.sleep(min(max(secs, 0.0), 3600.0))
                else:
                    print("unknown command: %r (try 'help')" % line)
            except EduTimeoutError as exc:
                print("timeout: %s" % exc)
            except EduClientError as exc:
                print("error: %s" % exc)
    finally:
        if audio is not None and audio.is_running:
            try:
                client.audio_stop()
            except EduClientError:
                pass
            audio.stop()
        if image is not None:
            image.close()
        client.close()
    return 0


# ---------------------------------------------------------------------------
# macOS session: IOBluetooth delivers delegate callbacks only while the MAIN
# thread's run loop is pumped, so the REPL polls stdin with select() between
# pumps instead of blocking in input().
# ---------------------------------------------------------------------------

def run_mac_session(bt_addr: str, out_dir: str) -> int:
    try:
        from edu_host import mac_bt
    except ImportError:
        print("macOS Bluetooth support needs pyobjc:\n"
              "  pip install pyobjc-core pyobjc-framework-IOBluetooth")
        return 1
    import datetime
    import select
    from edu_host.audio_client import RecordStreamParser
    from edu_host.protocol import AirImgStreamParser, ImageReassembler

    dev = mac_bt.find_device(None if bt_addr == "auto" else bt_addr)
    if dev is None:
        print("device not found. Pair the glasses first (System Settings > "
              "Bluetooth); with --bt auto the name must start with 'EDU-'.")
        return 1
    print("device: %s (%s), connected=%s"
          % (dev.name(), dev.addressString(), bool(dev.isConnected())))
    if not dev.isConnected():
        dev.openConnection()
        mac_bt.pump(2.0)

    print("querying SDP for service channels ...")
    chmap = mac_bt.sdp_channels(
        dev, [mac_bt.UUID_CTRL, mac_bt.UUID_AUDIO, mac_bt.UUID_IMG])
    if mac_bt.UUID_CTRL not in chmap:
        print("EDU-CTRL service (0x2028) not found — is this the education "
              "firmware?")
        return 1
    print("channels: ctrl=%s audio=%s img=%s"
          % (chmap.get(mac_bt.UUID_CTRL), chmap.get(mac_bt.UUID_AUDIO),
             chmap.get(mac_bt.UUID_IMG)))

    ctrl = mac_bt.MacRFCOMMChannel(dev, chmap[mac_bt.UUID_CTRL], "ctrl")
    ctrl.open()
    audio = img = None
    if mac_bt.UUID_AUDIO in chmap:
        audio = mac_bt.MacRFCOMMChannel(dev, chmap[mac_bt.UUID_AUDIO], "audio")
        audio.open()
    if mac_bt.UUID_IMG in chmap:
        img = mac_bt.MacRFCOMMChannel(dev, chmap[mac_bt.UUID_IMG], "img")
        img.open()

    frames = FrameParser()
    pending = {}          # seq -> Frame (RSP/HELLO_ACK)
    seq_counter = [0]

    audio_parser = RecordStreamParser()
    wav_state = {"file": None, "decoder": None, "path": None,
                 "packages": 0, "frames": 0}
    img_parser = AirImgStreamParser()
    reassembler = ImageReassembler()
    next_photo_path = [None]

    def poll(duration=0.05):
        """Pump the run loop and process every channel's RX buffer."""
        mac_bt.pump(duration)
        data = ctrl.read()
        if data:
            for fr in frames.feed(data):
                if fr.type == FrameType.EVT:
                    print_event(parse_event(fr.payload))
                elif fr.type in (FrameType.RSP, FrameType.HELLO_ACK):
                    pending[fr.seq] = fr
        if audio is not None:
            adata = audio.read()
            if adata and wav_state["file"] is not None:
                for pkg in audio_parser.feed(adata):
                    wav_state["packages"] += 1
                    for f in pkg.frames:
                        wav_state["frames"] += 1
                        if wav_state["decoder"] is not None:
                            try:
                                pcm = wav_state["decoder"].decode(bytes(f), 320)
                                wav_state["file"].writeframes(pcm)
                            except Exception:
                                pass
        if img is not None:
            idata = img.read()
            if idata:
                for sub in img_parser.feed(idata):
                    got = reassembler.feed_subframe(sub)
                    if got is not None:
                        path = next_photo_path[0]
                        next_photo_path[0] = None
                        if path is None:
                            stamp = datetime.datetime.now().strftime(
                                "%Y%m%d_%H%M%S")
                            path = Path(out_dir) / ("photo_%s_g%d%s" % (
                                stamp, got.group_id,
                                got.suggested_extension))
                        path = Path(path)
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(got.data)
                        print_image(path, got)

    def transact(ftype, payload, timeout=6.0):
        seq_counter[0] = (seq_counter[0] + 1) & 0xFF
        s = seq_counter[0]
        ctrl.write(encode_frame(ftype, s, payload))
        end = time.time() + timeout
        while time.time() < end:
            poll()
            if s in pending:
                return pending.pop(s)
        raise EduTimeoutError("no answer within %.1fs" % timeout)

    def request(cmd_id, timeout=6.0):
        fr = transact(FrameType.CMD, bytes([cmd_id]), timeout)
        return fr.payload[1], bytes(fr.payload[2:])

    # HELLO handshake
    fr = transact(FrameType.HELLO, b"\x01")
    ack = HelloAck.parse(fr.payload)
    print("connected! proto v%d, firmware %s, caps: %s"
          % (ack.proto_ver, ack.fw_version_str, ", ".join(ack.cap_names)))
    print(HELP_TEXT)

    def start_wav(path: Path) -> Path:
        import wave
        if path.suffix.lower() != ".wav":
            path = path.with_suffix(".wav")
        path.parent.mkdir(parents=True, exist_ok=True)
        w = wave.open(str(path), "wb")
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        decoder = None
        try:
            import opuslib
            decoder = opuslib.Decoder(16000, 1)
        except Exception:
            print("warning: opuslib/libopus unavailable — WAV will be empty. "
                  "brew install opus && pip install opuslib "
                  "(and export DYLD_LIBRARY_PATH=/opt/homebrew/lib)")
        wav_state.update(file=w, decoder=decoder, path=path,
                         packages=0, frames=0)
        return path

    def stop_wav():
        if wav_state["file"] is not None:
            wav_state["file"].close()
        print("stopped. %d packages, %d frames (~%.1f s) -> %s"
              % (wav_state["packages"], wav_state["frames"],
                 wav_state["frames"] * 0.02, wav_state["path"]))
        wav_state.update(file=None, decoder=None)

    print("edu> ", end="", flush=True)
    try:
        while True:
            poll()
            ready, _, _ = select.select([sys.stdin], [], [], 0)
            if not ready:
                continue
            line = sys.stdin.readline()
            if line == "":
                break
            line = line.strip()
            if line:
                try:
                    args = shlex.split(line)
                    cmd = args[0].lower()
                    if cmd in ("quit", "exit", "q"):
                        break
                    elif cmd == "help":
                        print(HELP_TEXT)
                    elif cmd == "info":
                        show_info(*request(CommandId.GET_DEVICE_INFO))
                    elif cmd == "sensors":
                        show_sensors(*request(CommandId.GET_SENSORS))
                    elif cmd == "photo":
                        if img is None:
                            print("image channel unavailable.")
                        else:
                            if len(args) > 1:
                                next_photo_path[0] = Path(args[1])
                            show_photo_rsp(*request(CommandId.TAKE_PHOTO))
                    elif cmd == "record" and len(args) >= 2 \
                            and args[1] == "start":
                        if audio is None:
                            print("audio channel unavailable.")
                        elif wav_state["file"] is not None:
                            print("recording already running")
                        else:
                            wav = Path(args[2]) if len(args) > 2 else \
                                Path(out_dir) / "record.wav"
                            actual = start_wav(wav)
                            status, _ = request(CommandId.AUDIO_START)
                            if status != Status.OK:
                                stop_wav()
                                print("AUDIO_START failed: status=%s"
                                      % protocol.enum_name(Status, status))
                            else:
                                print("recording -> %s" % actual)
                    elif cmd == "record" and len(args) >= 2 \
                            and args[1] == "stop":
                        if wav_state["file"] is None:
                            print("no recording in progress.")
                        else:
                            request(CommandId.AUDIO_STOP)
                            stop_wav()
                    elif cmd in ("wait", "sleep"):
                        try:
                            secs = float(args[1]) if len(args) > 1 else 1.0
                        except ValueError:
                            print("usage: wait <seconds>")
                            secs = 0.0
                        end = time.time() + min(max(secs, 0.0), 3600.0)
                        while time.time() < end:
                            poll()
                    else:
                        print("unknown command: %r (try 'help')" % line)
                except EduTimeoutError as exc:
                    print("timeout: %s" % exc)
                except (EduClientError, ValueError) as exc:
                    print("error: %s" % exc)
            print("edu> ", end="", flush=True)
    except KeyboardInterrupt:
        print()
    finally:
        if wav_state["file"] is not None:
            try:
                request(CommandId.AUDIO_STOP, timeout=3.0)
            except Exception:
                pass
            stop_wav()
        for ch in (img, audio, ctrl):
            if ch is not None:
                ch.close()
    return 0


# ---------------------------------------------------------------------------
# Entry point / platform dispatch
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Looktech education-firmware host demo",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--bt", metavar="ADDR",
                        help="connect via Bluetooth RFCOMM to this device "
                             "address (AA:BB:CC:DD:EE:FF); on macOS 'auto' "
                             "finds a paired device named EDU-*")
    parser.add_argument("--ctrl-channel", type=int, default=6,
                        help="RFCOMM channel of EDU-CTRL (Windows/Linux --bt)")
    parser.add_argument("--audio-channel", type=int, default=5,
                        help="RFCOMM channel of EDU-AUDIO (Windows/Linux --bt)")
    parser.add_argument("--img-channel", type=int, default=4,
                        help="RFCOMM channel of EDU-IMG (Windows/Linux --bt)")
    parser.add_argument("--list", action="store_true",
                        help="list candidate serial ports and exit")
    parser.add_argument("--ctrl-port",
                        help="EDU-CTRL serial port (fallback, SPP UUID 0x2028)")
    parser.add_argument("--audio-port",
                        help="EDU-AUDIO serial port (SPP UUID 0x2024)")
    parser.add_argument("--img-port",
                        help="EDU-IMG serial port (SPP UUID 0x2025)")
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

    if args.bt:
        if sys.platform == "darwin":
            return run_mac_session(args.bt, args.out_dir)
        from edu_host.bt_socket import (SocketRFCOMMTransport,
                                        bt_socket_supported)
        if not bt_socket_supported():
            print("this Python has no Bluetooth socket support; use the "
                  "serial-port options instead (see README).")
            return 1
        if args.bt == "auto":
            print("'--bt auto' is macOS-only; pass the device address "
                  "(shown in your OS Bluetooth settings).")
            return 1
        return run_threaded_session(
            SocketRFCOMMTransport(args.bt, args.ctrl_channel, name="ctrl"),
            SocketRFCOMMTransport(args.bt, args.audio_channel, name="audio"),
            SocketRFCOMMTransport(args.bt, args.img_channel, name="img"),
            args.out_dir)

    if not args.ctrl_port:
        parser.error("connect with --bt <addr> (recommended) or "
                     "--ctrl-port <port> (serial fallback); "
                     "--list shows serial candidates")

    audio_t = SerialTransport(args.audio_port) if args.audio_port else None
    img_t = SerialTransport(args.img_port) if args.img_port else None
    return run_threaded_session(SerialTransport(args.ctrl_port),
                                audio_t, img_t, args.out_dir)


if __name__ == "__main__":
    sys.exit(main())
