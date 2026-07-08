"""ImageClient: receiver for the air-img SPP channel (UUID 0x2025).

The firmware returns photos on its native image channel as a raw stream of
air-img sub-frames (no outer framing, no CRC — see protocol.py). This client
runs a background reader that cuts the stream into sub-frames, reassembles
complete JPEGs and saves them under an output directory.

Typical use together with :class:`edu_host.client.EduClient`::

    img = ImageClient(SerialTransport(img_port))
    img.add_image_listener(lambda path, image: print("saved", path))
    img.start()
    ctrl.take_photo()          # EDU-CTRL command; photo arrives here
"""

from __future__ import annotations

import datetime
import logging
import threading
from pathlib import Path
from typing import Callable, List, Optional

from .protocol import AirImgStreamParser, CompletedImage, ImageReassembler
from .transport import Transport

log = logging.getLogger("edu_host.image_client")

ImageCallback = Callable[[Path, CompletedImage], None]


class ImageClient:
    """Host client for the air-img image SPP channel (UUID 0x2025)."""

    def __init__(self, transport: Transport,
                 output_dir: str = "captures") -> None:
        self._transport = transport
        self._parser = AirImgStreamParser()
        self._reassembler = ImageReassembler()
        self._output_dir = Path(output_dir)

        self._image_callbacks: List[ImageCallback] = []
        self._next_photo_path: Optional[Path] = None

        self._reader: Optional[threading.Thread] = None
        self._stop = threading.Event()

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        """Open the transport and start the background reader thread."""
        self._transport.open()
        self._stop.clear()
        self._reader = threading.Thread(target=self._reader_loop,
                                        name="edu-img-reader", daemon=True)
        self._reader.start()

    def close(self) -> None:
        """Stop the reader and close the transport."""
        self._stop.set()
        if self._reader is not None:
            self._reader.join(timeout=2.0)
            self._reader = None
        self._transport.close()
        self._reassembler.reset()

    # -- callbacks / configuration -------------------------------------------

    def add_image_listener(self, callback: ImageCallback) -> None:
        """Register a callback fired after a photo has been saved to disk."""
        self._image_callbacks.append(callback)

    def set_next_photo_path(self, path: Optional[Path]) -> None:
        """Override the filename used for the *next* completed photo."""
        self._next_photo_path = Path(path) if path else None

    # -- internals -----------------------------------------------------------

    def _reader_loop(self) -> None:
        while not self._stop.is_set():
            try:
                data = self._transport.read(4096)
            except Exception as exc:  # port unplugged, BT dropped, ...
                if not self._stop.is_set():
                    log.error("img transport read failed: %s", exc)
                break
            if not data:
                continue
            for sub in self._parser.feed(data):
                before = self._reassembler.last_error
                image = self._reassembler.feed_subframe(sub)
                if self._reassembler.last_error != before:
                    log.warning("image reassembly: %s",
                                self._reassembler.last_error)
                if image is not None:
                    self._deliver(image)

    def _deliver(self, image: CompletedImage) -> None:
        path = self._save_image(image)
        for cb in self._image_callbacks:
            try:
                cb(path, image)
            except Exception:
                log.exception("image callback failed for %s", path)

    def _save_image(self, image: CompletedImage) -> Path:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        if self._next_photo_path is not None:
            path = self._next_photo_path
            self._next_photo_path = None
        else:
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            path = self._output_dir / ("photo_%s_g%d%s" % (
                stamp, image.group_id, image.suggested_extension))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(image.data)
        log.info("saved image: %s (%d bytes)", path, len(image.data))
        return path
