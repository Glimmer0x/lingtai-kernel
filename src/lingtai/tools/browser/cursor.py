"""Opaque HMAC cursors and bounded lossless block pagination."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass

from .extractor import Block

MIN_MAX_CHARS = 1
MAX_MAX_CHARS = 100_000


class CursorError(Exception):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.message = error_code


@dataclass(frozen=True, slots=True)
class CursorPayload:
    snapshot_id: str
    extract_mode: str
    next_index: int
    next_char_offset: int = 0


class CursorCodec:
    """Process-local signer; refresh/reconstruction naturally invalidates it."""

    def __init__(self, secret: bytes | None = None) -> None:
        self._secret = secret if secret is not None else os.urandom(32)
        if not isinstance(self._secret, bytes) or len(self._secret) < 16:
            raise ValueError("cursor secret must be at least 16 bytes")

    def encode(self, payload: CursorPayload) -> str:
        if payload.next_index < 0 or payload.next_char_offset < 0:
            raise ValueError("cursor offsets must be non-negative")
        body = json.dumps(
            {
                "extract_mode": payload.extract_mode,
                "next_char_offset": payload.next_char_offset,
                "next_index": payload.next_index,
                "snapshot_id": payload.snapshot_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        tag = hmac.new(self._secret, body, hashlib.sha256).digest()
        return ".".join(
            base64.urlsafe_b64encode(part).decode("ascii").rstrip("=") for part in (body, tag)
        )

    def decode(self, cursor: object) -> CursorPayload:
        try:
            if not isinstance(cursor, str) or len(cursor) > 4096:
                raise ValueError
            body_text, tag_text = cursor.split(".", 1)
            if not body_text or not tag_text:
                raise ValueError
            body = _decode_part(body_text)
            tag = _decode_part(tag_text)
        except Exception:
            raise CursorError("CURSOR_MALFORMED") from None
        expected = hmac.new(self._secret, body, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise CursorError("CURSOR_INVALID")
        try:
            obj = json.loads(body.decode("utf-8"))
            snapshot_id = obj["snapshot_id"]
            mode = obj["extract_mode"]
            index = obj["next_index"]
            offset = obj.get("next_char_offset", 0)
            if (
                not isinstance(snapshot_id, str)
                or not isinstance(mode, str)
                or isinstance(index, bool)
                or not isinstance(index, int)
                or isinstance(offset, bool)
                or not isinstance(offset, int)
                or index < 0
                or offset < 0
            ):
                raise ValueError
            return CursorPayload(snapshot_id, mode, index, offset)
        except Exception:
            raise CursorError("CURSOR_MALFORMED") from None


def _decode_part(value: str) -> bytes:
    if any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for char in value):
        raise ValueError
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def validate_max_chars(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return "max_chars must be an integer"
    if value < MIN_MAX_CHARS:
        return "max_chars is below the minimum"
    if value > MAX_MAX_CHARS:
        return "max_chars is above the maximum"
    return None


@dataclass(frozen=True, slots=True)
class PageResult:
    blocks: list[Block]
    next_index: int
    next_char_offset: int
    has_more: bool


def _fragment(block: Block, offset: int, text: str) -> Block:
    return Block(f"{block.id}#{offset}", block.kind, text)


def paginate_blocks(
    blocks: list[Block], *, start_index: int, max_chars: int, start_char_offset: int = 0
) -> PageResult:
    """Paginate without emitting an empty page or exceeding ``max_chars``."""
    page: list[Block] = []
    total = 0
    index = start_index
    offset = start_char_offset
    while index < len(blocks):
        block = blocks[index]
        remaining = block.text[offset:]
        if not remaining:
            index += 1
            offset = 0
            continue
        if not page and len(remaining) > max_chars:
            page.append(_fragment(block, offset, remaining[:max_chars]))
            return PageResult(page, index, offset + max_chars, True)
        if page and total + len(remaining) > max_chars:
            break
        page.append(block if offset == 0 else _fragment(block, offset, remaining))
        total += len(remaining)
        index += 1
        offset = 0
        if total >= max_chars:
            break
    return PageResult(page, index, offset, index < len(blocks))
