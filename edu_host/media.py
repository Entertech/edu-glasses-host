"""ID-scoped LAN export. The CTRL connection owns every HTTP operation."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import http.client
import ipaddress
import json
import logging
import os
from pathlib import Path, PurePosixPath
import queue
import socket
import tempfile
import threading
import time
from typing import Callable, Optional, Tuple, TYPE_CHECKING, Union
from urllib.parse import quote, unquote, urlsplit

from .client import EduClientError
from .wifi import WifiClient, WifiSecurity

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .session import EduSession


class MediaError(EduClientError):
    """One media operation failed; already downloaded files are retained."""


class MediaSessionError(MediaError):
    """The owner, catalog or LAN session is no longer usable."""


class MediaCancelled(MediaSessionError):
    pass


@dataclass(frozen=True)
class MediaFile:
    name: str
    path: str
    size: int


@dataclass(frozen=True)
class MediaItem:
    catalog_id: int
    media_id: int
    revision: int
    kind: str
    file: MediaFile
    companions: Tuple[MediaFile, ...] = ()
    motion_required: bool = False


@dataclass(frozen=True)
class DownloadResult:
    media: MediaItem
    files: Tuple[Path, ...]
    errors: Tuple[str, ...]

    @property
    def main_success(self) -> bool:
        return bool(self.files)

    @property
    def complete(self) -> bool:
        return self.main_success and not self.errors


@dataclass(frozen=True)
class DeleteResult:
    media_id: int
    deleted: bool
    already_absent: bool


def _integer(value, name: str, maximum: int = (1 << 64) - 1, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise MediaSessionError("invalid %s in media catalog" % name)
    return value


def _media_file(value) -> MediaFile:
    if not isinstance(value, dict):
        raise MediaSessionError("invalid media descriptor")
    name, path = value.get('name'), value.get('path')
    if not isinstance(name, str) or not name or name in ('.', '..') or any(c in name for c in '/\\:\x00'):
        raise MediaSessionError("unsafe media filename")
    if not isinstance(path, str) or len(path) > 1024 or any(c in path for c in '\r\n\x00\\'):
        raise MediaSessionError("unsafe media path")
    parsed = urlsplit(path)
    decoded = unquote(path)
    parts = PurePosixPath(decoded).parts
    if (parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or
            not decoded.startswith('/customer/bt_res/') or '..' in parts or
            any(c in decoded for c in '\r\n\x00\\')):
        raise MediaSessionError("media path is outside the device media root")
    if len(parts) != 5 or parts[3] not in ('image', 'video', 'audio', 'gsensor'):
        raise MediaSessionError("media path is not a direct media file")
    return MediaFile(name, path, _integer(value.get('size'), 'size'))


def parse_catalog(data: bytes, catalog_id: int) -> Tuple[MediaItem, ...]:
    try:
        document = json.loads(data)
        if not isinstance(document, dict) or _integer(document.get('catalogId'), 'catalogId', minimum=1) != catalog_id:
            raise MediaSessionError("media catalog identity changed")
        companions = {}
        for entry in document.get('gsensor', []):
            parent = _integer(entry.get('parentMediaId'), 'parentMediaId', minimum=1)
            revision = _integer(entry.get('metadataRevision'), 'metadataRevision', (1 << 32) - 1, 1)
            companions.setdefault((parent, revision), []).append(_media_file(entry))
        items, seen = [], set()
        for key, kind in (('image', 'photo'), ('video', 'video')):
            entries = document.get(key)
            if not isinstance(entries, list):
                raise MediaSessionError("indexed media catalog is required")
            for entry in entries:
                if not isinstance(entry, dict):
                    raise MediaSessionError("invalid media catalog entry")
                if entry.get('id') is None:
                    continue
                media_id = _integer(entry['id'], 'id', minimum=1)
                if media_id in seen:
                    raise MediaSessionError("duplicate media identity")
                seen.add(media_id)
                revision = _integer(entry.get('metadataRevision'), 'metadataRevision', (1 << 32) - 1, 1)
                motion = entry.get('motionRequired', False)
                if type(motion) is not bool:
                    raise MediaSessionError("invalid motionRequired")
                items.append(MediaItem(catalog_id, media_id, revision, kind, _media_file(entry),
                                       tuple(companions.get((media_id, revision), ())), motion))
        return tuple(items)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise MediaSessionError("malformed indexed media catalog") from exc


class MediaImport:
    """One sequential LAN context. Progress callbacks run on the SDK caller's thread."""

    def __init__(self, session: EduSession, ssid: str, password: str = '',
                 security: WifiSecurity = WifiSecurity.WPA2) -> None:
        self.session = session
        self._ssid, self._password, self._security = ssid, password, security
        self._owner = None
        self._endpoint = None
        self._cancelled = threading.Event()
        self._closed = False
        self._request_lock = threading.Lock()
        self._socket_lock = threading.Lock()
        self._socket = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='edu-media')
        self._heartbeat = None
        self._heartbeat_error = None
        self._last_activity = time.monotonic()
        self._progress = queue.Queue()
        self._known_items = {}

    def __repr__(self) -> str:
        return '<MediaImport closed=%s>' % self._closed

    def _check_owner(self) -> None:
        if self._cancelled.is_set():
            raise MediaCancelled("media import cancelled")
        if self._closed or not self.session.is_connected or self.session._client is not self._owner:
            raise MediaSessionError("CTRL owner disconnected or changed")
        if self._heartbeat_error is not None:
            raise MediaSessionError("media keepalive failed") from self._heartbeat_error

    def __enter__(self) -> MediaImport:
        if self._closed or self._owner is not None or self.session._media_import is not None:
            raise MediaSessionError("a media import context is already active or closed")
        self.session._require_connected()
        self._owner = self.session._client
        self.session._media_import = self
        try:
            from .capture import INDEXED_HTTP
            from .session import EduUnsupportedError
            if not self.session.media_capabilities().features & INDEXED_HTTP:
                raise EduUnsupportedError('ISP needs the explicit indexed media HTTP catalog')
            wifi = WifiClient(self.session)
            wifi.connect(self._ssid, self._password, self._security)
            status = wifi.start_media()
            address = ipaddress.IPv4Address(status.ipv4)
            if address.is_unspecified or address.is_loopback or address.is_multicast:
                raise MediaSessionError("invalid LAN endpoint")
            self._endpoint = (str(address), status.port, status.catalog_id)
            self.list()
            self._heartbeat = threading.Thread(target=self._keepalive, name='edu-media-keepalive', daemon=True)
            self._heartbeat.start()
            return self
        except BaseException:
            self._close_after_error()
            raise
        finally:
            self._password = ''

    def __exit__(self, *exc) -> None:
        if exc and exc[0] is not None:
            self._close_after_error()
        else:
            self.close()

    def _close_after_error(self) -> None:
        try:
            self.close()
        except Exception:
            log.exception("LAN cleanup failed; device retains pending release")

    def cancel(self) -> None:
        self._cancelled.set()
        with self._socket_lock:
            if self._socket is not None:
                try:
                    self._socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass  # The worker may already have closed this exact socket.

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._password = ''
        self.cancel()
        self._executor.shutdown(wait=False, cancel_futures=True)
        try:
            if self.session.is_connected and self.session._client is self._owner:
                WifiClient(self.session).disconnect()
        finally:
            if self.session._media_import is self:
                self.session._media_import = None

    def _keepalive(self) -> None:
        while not self._cancelled.wait(1.0):
            if time.monotonic() - self._last_activity < 30.0:
                continue
            if not self._request_lock.acquire(blocking=False):
                continue
            try:
                self._check_owner()
                data = self._http('GET', '/media/catalog')
                parse_catalog(data, self._endpoint[2])
            except Exception as exc:
                self._heartbeat_error = exc
                return
            finally:
                self._request_lock.release()

    def _http(self, method: str, path: str, consume=None, allow_absent: bool = False):
        self._check_owner()
        connection = http.client.HTTPConnection(self._endpoint[0], self._endpoint[1], timeout=10.0)
        try:
            connection.connect()
            with self._socket_lock:
                self._socket = connection.sock
            self._check_owner()
            connection.request(method, quote(path, safe='/?='), headers={'Connection': 'close'})
            response = connection.getresponse()
            if allow_absent and response.status == 404:
                return False
            if response.status == 404 and path == '/media/catalog':
                raise MediaSessionError("ISP does not support the indexed catalog endpoint")
            if response.status != 200:
                raise MediaError("HTTP %s failed with status %d" % (method, response.status))
            if consume is not None:
                result = consume(response)
            else:
                result = response.read(16 * 1024 * 1024 + 1)
                if len(result) > 16 * 1024 * 1024:
                    raise MediaSessionError("media catalog response is too large")
            self._last_activity = time.monotonic()
            return result
        finally:
            with self._socket_lock:
                self._socket = None
            connection.close()

    def _run(self, operation, progress=None):
        self._check_owner()
        def serialized():
            with self._request_lock:
                return operation()
        future = self._executor.submit(serialized)
        try:
            while not future.done():
                self.session.poll(0.05)
                self._check_owner()
                self._drain_progress(progress)
            self._drain_progress(progress)
            self._check_owner()
            return future.result()
        except MediaSessionError:
            self._close_after_error()
            raise
        except MediaError:
            raise
        except BaseException:
            self.cancel()
            self._close_after_error()
            raise

    def _drain_progress(self, callback) -> None:
        while True:
            try:
                value = self._progress.get_nowait()
            except queue.Empty:
                return
            if callback is not None:
                callback(*value)

    def list(self) -> Tuple[MediaItem, ...]:
        def fetch():
            items = parse_catalog(self._http('GET', '/media/catalog'), self._endpoint[2])
            self._known_items.update((item.media_id, item) for item in items)
            return items
        return self._run(fetch)

    def _resolve(self, media) -> MediaItem:
        if isinstance(media, int) and not isinstance(media, bool):
            media_id = media
        else:
            if media.catalog_id != self._endpoint[2]:
                raise MediaSessionError("selected media belongs to another catalog")
            media_id = media.media_id
        for item in parse_catalog(self._http('GET', '/media/catalog'), self._endpoint[2]):
            if item.media_id == media_id:
                if isinstance(media, MediaItem) and item != media:
                    raise MediaError("selected media descriptor changed; list again")
                return item
        raise MediaError("selected media ID is no longer available")

    def _download_file(self, item: MediaItem, file: MediaFile, directory: Path) -> Path:
        target = directory / file.name
        if target.resolve().parent != directory or target.exists():
            raise MediaError("output already exists or is outside the destination: %s" % file.name)
        for attempt in range(3):
            self._check_owner()
            fd, temporary = tempfile.mkstemp(prefix='.%d-' % item.media_id, suffix='.part', dir=directory)
            try:
                with os.fdopen(fd, 'wb') as output:
                    def consume(response):
                        length = response.getheader('Content-Length')
                        if length is None or not length.isascii() or not length.isdigit() or int(length) != file.size:
                            raise MediaError("HTTP length does not match the selected media")
                        received = 0
                        while True:
                            self._check_owner()
                            chunk = response.read(64 * 1024)
                            if not chunk:
                                break
                            received += len(chunk)
                            if received > file.size:
                                raise MediaError("HTTP body exceeds selected media size")
                            output.write(chunk)
                            self._last_activity = time.monotonic()
                            self._progress.put((item.media_id, file.name, received, file.size))
                        if received != file.size:
                            raise MediaError("incomplete media body")
                        output.flush()
                        os.fsync(output.fileno())
                    self._http('GET', file.path, consume)
                self._check_owner()
                current = self._resolve(item)
                if current != item:
                    raise MediaError("media descriptor changed during download")
                os.link(temporary, target)
                return target
            except MediaSessionError:
                raise
            except (OSError, http.client.HTTPException, MediaError) as exc:
                if attempt == 2 or isinstance(exc, FileExistsError):
                    raise MediaError("download failed: %s: %s" % (file.name, exc)) from exc
            finally:
                os.unlink(temporary)
        raise MediaError("download retries exhausted")

    def download(self, media, directory: Union[str, Path] = 'captures',
                 progress: Optional[Callable[[int, str, int, int], None]] = None) -> DownloadResult:
        destination = Path(directory).resolve()
        destination.mkdir(parents=True, exist_ok=True)
        def transfer():
            item = self._resolve(media)
            files, errors = [], []
            try:
                files.append(self._download_file(item, item.file, destination))
            except MediaSessionError:
                raise
            except MediaError as exc:
                return DownloadResult(item, (), (str(exc),))
            for companion in item.companions:
                try:
                    files.append(self._download_file(item, companion, destination))
                except MediaSessionError:
                    raise
                except MediaError as exc:
                    errors.append(str(exc))
            if item.motion_required and not item.companions:
                errors.append('registered motion data is missing')
            return DownloadResult(item, tuple(files), tuple(errors))
        return self._run(transfer, progress)

    def download_all(self, directory: Union[str, Path] = 'captures', progress=None) -> Tuple[DownloadResult, ...]:
        selected = self.list()
        results = []
        for item in selected:
            try:
                results.append(self.download(item, directory, progress))
            except MediaSessionError:
                raise
            except MediaError as exc:
                results.append(DownloadResult(item, (), (str(exc),)))
        return tuple(results)

    def delete(self, media) -> DeleteResult:
        def remove():
            if isinstance(media, int) and not isinstance(media, bool):
                media_id = _integer(media, 'media ID', minimum=1)
            else:
                if media.catalog_id != self._endpoint[2]:
                    raise MediaSessionError("selected media belongs to another catalog")
                media_id = _integer(media.media_id, 'media ID', minimum=1)
            items = parse_catalog(self._http('GET', '/media/catalog'), self._endpoint[2])
            selected = next((item for item in items if item.media_id == media_id), None)
            if selected is None:
                if media_id not in self._known_items:
                    raise MediaError('media ID is not an indexed photo or video in this catalog')
            else:
                if isinstance(media, MediaItem) and selected != media:
                    raise MediaError('selected media descriptor changed; list again')
                self._known_items[media_id] = selected
            deleted = self._http('DELETE', '/media?id=%d' % media_id, allow_absent=True) is not False
            return DeleteResult(media_id, deleted, not deleted)
        return self._run(remove)
