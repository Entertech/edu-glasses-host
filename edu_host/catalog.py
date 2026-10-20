"""Typed bridge to the public ISP ID and BASE metadata queries over EDU SPP."""
from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import TYPE_CHECKING, Tuple

from . import protocol
from .client import EduClientError, EduStatusError, EduTimeoutError
from .media import MediaError, MediaItem, MediaSessionError, _integer, _media_file

if TYPE_CHECKING:
    from .session import EduSession


@dataclass(frozen=True)
class MediaCapabilities:
    schema_version: int
    catalog_id: int
    features: int


class CatalogClient:
    def __init__(self, session: EduSession) -> None:
        self.session = session

    def _request(self, command, args=b''):
        owner = self.session._client
        try:
            self.session._require(protocol.CAP_MEDIA_CATALOG)
            return self.session._request(command, args, timeout=35.0).data
        except EduStatusError as exc:
            # These public backend errors invalidate a selected catalog or owner.
            if exc.data and exc.data[0] in (0x60, 0x68, 0x6e, 0x73, 0x74):
                raise MediaSessionError('media catalog unavailable (code %d)' % exc.data[0]) from exc
            raise MediaError('media query failed (code %s)' % (exc.data.hex() or 'unknown')) from exc
        except (EduTimeoutError, OSError) as exc:
            raise MediaSessionError('media control query timed out or lost transport') from exc
        except EduClientError as exc:
            if not self.session.is_connected or self.session._client is not owner:
                raise MediaSessionError('media CTRL owner disconnected or changed') from exc
            raise

    def capabilities(self) -> MediaCapabilities:
        data = self._request(protocol.CommandId.MEDIA_CAPS)
        if len(data) != 13:
            raise MediaSessionError('invalid media capabilities response')
        version, catalog, features = struct.unpack('<BQI', data)
        if version != 1 or not catalog or features & 0x11 != 0x11:
            from .session import EduUnsupportedError
            raise EduUnsupportedError('ISP needs the public ID catalog and BASE metadata queries')
        return MediaCapabilities(version, catalog, features)

    def check(self, catalog_id: int) -> None:
        if self.capabilities().catalog_id != catalog_id:
            raise MediaSessionError('media catalog identity changed')

    def item(self, catalog_id: int, media_id: int) -> MediaItem:
        _integer(catalog_id, 'catalog ID', minimum=1)
        _integer(media_id, 'media ID', minimum=1)
        data = self._request(protocol.CommandId.MEDIA_DESCRIPTOR, struct.pack('<QQ', catalog_id, media_id))
        if len(data) < 33:
            raise MediaSessionError('truncated media descriptor')
        catalog, identity, revision, kind, size, names, paths = struct.unpack_from('<QQIBQHH', data)
        if catalog != catalog_id or identity != media_id or not revision or kind not in (1, 2) or len(data) != 33 + names + paths:
            raise MediaSessionError('invalid media descriptor identity or size')
        try:
            file = _media_file({'name': data[33:33 + names].decode('utf-8'),
                                'path': data[33 + names:].decode('utf-8'), 'size': size})
        except UnicodeError as exc:
            raise MediaSessionError('invalid UTF-8 in media descriptor') from exc
        return MediaItem(catalog, identity, revision, 'photo' if kind == 1 else 'video', file,
                         companions_known=kind == 1)

    def list(self, catalog_id: int) -> Tuple[MediaItem, ...]:
        self.check(catalog_id)
        cursor, seen, items = 0, set(), []
        while True:
            data = self._request(protocol.CommandId.MEDIA_IDS, struct.pack('<QQ', catalog_id, cursor))
            if len(data) < 26:
                raise MediaSessionError('truncated media ID page')
            catalog, revision, next_cursor, more, count = struct.unpack_from('<QQQBB', data)
            if catalog != catalog_id or more > 1 or count > 16 or len(data) != 26 + count * 8:
                raise MediaSessionError('invalid media ID page')
            identities = struct.unpack_from('<%dQ' % count, data, 26)
            for identity in identities:
                if not identity or identity in seen:
                    raise MediaSessionError('invalid or duplicate media ID')
                seen.add(identity)
                try:
                    items.append(self.item(catalog_id, identity))
                except MediaError as exc:
                    if isinstance(exc, MediaSessionError) or not isinstance(exc.__cause__, EduStatusError) or exc.__cause__.data not in (b'\x62', b'\x63'):
                        raise
                    # A concurrent public deletion may remove an ID between these two queries.
            if not more:
                break
            if not count or next_cursor <= cursor:
                raise MediaSessionError('media ID cursor did not advance')
            cursor = next_cursor
        self.check(catalog_id)
        return tuple(items)
