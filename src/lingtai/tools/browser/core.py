"""Static browse use case: policy, fetch, extraction, refs, cursors and state."""
from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, replace
from typing import Any, Mapping

from . import netpolicy
from .cursor import CursorCodec, CursorError, CursorPayload, paginate_blocks, validate_max_chars
from .extractor import extract_html, extract_plain_text
from .fetcher import FetchError, FetchLimits, fetch
from .port import BrowserPort
from .refstore import RefStore
from .snapshots import InMemorySnapshotStore, LinkItem, Snapshot

DEFAULT_MAX_CHARS = 12_000
MAX_RETURNED_LINKS = 256
MAX_LINK_TEXT_CHARS = 512
MAX_LINK_URL_CHARS = 2_048
MAX_RETURNED_LINK_CHARS = 24_000
LINKS_TRUNCATED_WARNING = "LINKS_TRUNCATED"


class BrowserFailure(Exception):
    """Typed failure whose serialized form is safe for model-facing output."""

    def __init__(
        self,
        stage: str,
        error_code: str,
        *,
        retryable: bool = False,
        http_status: int | None = None,
        snapshot_id: str | None = None,
    ) -> None:
        super().__init__(error_code)
        self.stage = stage
        self.error_code = error_code
        self.retryable = retryable
        self.http_status = http_status
        self.snapshot_id = snapshot_id

    def to_dict(self, request_id: str) -> dict[str, Any]:
        message = _MESSAGES.get(self.error_code, "The browser request failed safely.")
        if self.error_code == "HTTP_STATUS" and self.http_status is not None:
            message = f"The page returned HTTP status {self.http_status}."
        recommended = "Retry once if the destination is expected to be temporary." if self.retryable else "Check the URL and stop if the failure persists."
        if self.stage == "policy":
            recommended = "Use a public, direct HTTP(S) URL; do not retry an unsafe destination."
        result: dict[str, Any] = {
            "status": "failed",
            "request_id": request_id,
            "stage": self.stage,
            "error_code": self.error_code,
            "message": message,
            "retryable": self.retryable,
            "recommended_action": recommended,
            "partial": False,
        }
        if self.snapshot_id is not None:
            result["snapshot_id"] = self.snapshot_id
        return result


_MESSAGES = {
    "MALFORMED_URL": "The URL is malformed.",
    "MALFORMED_REDIRECT": "The redirect destination is malformed.",
    "SCHEME_NOT_ALLOWED": "Only public HTTP(S) URLs are supported.",
    "URL_USERINFO_FORBIDDEN": "URLs containing credentials are not supported.",
    "NO_HOSTNAME": "The URL has no hostname.",
    "LOOPBACK_BLOCKED": "The destination is not a public address.",
    "PRIVATE_ADDRESS_BLOCKED": "The destination is not a public address.",
    "LINK_LOCAL_BLOCKED": "The destination is not a public address.",
    "CLOUD_METADATA_BLOCKED": "The destination is not a public address.",
    "CGNAT_ADDRESS_BLOCKED": "The destination is not a public address.",
    "SIX_TO_FOUR_RELAY_BLOCKED": "The destination is not a public address.",
    "RESERVED_ADDRESS_BLOCKED": "The destination is not a public address.",
    "UNSPECIFIED_ADDRESS_BLOCKED": "The destination is not a public address.",
    "MULTICAST_BLOCKED": "The destination is not a public address.",
    "UNPARSEABLE_IP": "The destination address is invalid.",
    "DNS_RESOLUTION_FAILED": "The public destination could not be resolved.",
    "DNS_RESOLUTION_TIMEOUT": "The public destination DNS lookup exceeded the fetch deadline.",
    "REDIRECT_MISSING_LOCATION": "The server returned a redirect without a destination.",
    "TOO_MANY_REDIRECTS": "The redirect limit was reached.",
    "TOO_MANY_CONNECTIONS": "The connection limit was reached.",
    "FETCH_TIMEOUT": "The fetch deadline was reached.",
    "BODY_TOO_LARGE": "The response exceeded the bounded download limit.",
    "HTTP_STATUS": "The destination did not return a successful page.",
    "CONTENT_TYPE_UNSUPPORTED": "Only HTML and plain text pages are supported.",
    "NO_TEXT_BLOCKS": "The page contained no static text blocks.",
    "CURSOR_MALFORMED": "The continuation cursor is malformed.",
    "CURSOR_INVALID": "The continuation cursor failed integrity validation.",
    "CURSOR_SNAPSHOT_NOT_FOUND": "The continuation snapshot has expired or was evicted.",
    "CURSOR_SNAPSHOT_MISMATCH": "The continuation cursor belongs to another snapshot.",
    "CURSOR_EXTRACT_MODE_MISMATCH": "The continuation cursor belongs to another extract mode.",
    "CURSOR_OUT_OF_RANGE": "The continuation cursor is no longer valid.",
    "REF_NOT_FOUND": "The link reference is stale or belongs to another Agent.",
    "INVALID_TARGET": "Provide exactly one direct URL or link reference.",
    "INVALID_MAX_CHARS": "max_chars must be an integer between 1 and 100000.",
    "INVALID_EXTRACT": "Only article extraction is supported.",
    "UNSUPPORTED_ACTION": "Only browse and manual actions are supported.",
    "TRANSPORT_FAILED": "The public page could not be fetched.",
    "INTERNAL_ERROR": "The browser request failed safely.",
}


@dataclass(frozen=True, slots=True)
class BrowserLimits:
    max_bytes: int = 5 * 1024 * 1024
    max_redirects: int = 5
    max_connections: int = 6
    timeout_s: float = 15.0


class BrowserEngine:
    """One Agent-lifetime, stateless-transport browser engine."""

    def __init__(
        self,
        port: BrowserPort,
        *,
        limits: BrowserLimits | None = None,
        snapshots: InMemorySnapshotStore | None = None,
        refs: RefStore | None = None,
        cursor: CursorCodec | None = None,
    ) -> None:
        self.port = port
        self.limits = limits or BrowserLimits()
        self.snapshots = snapshots if snapshots is not None else InMemorySnapshotStore()
        self.refs = refs if refs is not None else RefStore()
        self.cursor = cursor if cursor is not None else CursorCodec()

    def handle(self, args: Mapping[str, Any] | None) -> dict[str, Any]:
        request_id = uuid.uuid4().hex
        try:
            return self._browse(dict(args or {}), request_id)
        except BrowserFailure as failure:
            return failure.to_dict(request_id)
        except Exception:
            return BrowserFailure("internal", "INTERNAL_ERROR").to_dict(request_id)

    def _browse(self, args: dict[str, Any], request_id: str) -> dict[str, Any]:
        if args.get("action", "browse") != "browse":
            raise BrowserFailure("policy", "UNSUPPORTED_ACTION")
        extract_mode = args.get("extract", "article")
        if extract_mode != "article":
            raise BrowserFailure("policy", "INVALID_EXTRACT")
        max_chars = args.get("max_chars", DEFAULT_MAX_CHARS)
        if validate_max_chars(max_chars) is not None:
            raise BrowserFailure("policy", "INVALID_MAX_CHARS")
        assert isinstance(max_chars, int)
        has_url = args.get("url") is not None
        has_ref = args.get("link_ref") is not None
        if has_url == has_ref:
            raise BrowserFailure("policy", "INVALID_TARGET")
        if not isinstance(args.get("url") if has_url else args.get("link_ref"), str):
            raise BrowserFailure("policy", "INVALID_TARGET")
        target = args["url"] if has_url else self.refs.resolve_link_ref(args["link_ref"])
        if target is None:
            raise BrowserFailure("ref", "REF_NOT_FOUND")
        try:
            target = netpolicy._parse(target).original
        except netpolicy.PolicyViolation as exc:
            raise BrowserFailure("policy", exc.error_code) from None

        raw_cursor = args.get("cursor")
        if raw_cursor is not None:
            return self._continue(target, raw_cursor, max_chars, extract_mode, request_id)
        return self._initial(target, max_chars, extract_mode, request_id)

    def _bounded_links(self, extracted_links) -> tuple[list[LinkItem], bool]:
        """Build links within both the count and aggregate returned-payload caps."""
        links: list[LinkItem] = []
        returned_chars = 0
        truncated = len(extracted_links) > MAX_RETURNED_LINKS
        for extracted_link in extracted_links[:MAX_RETURNED_LINKS]:
            text = extracted_link.text[:MAX_LINK_TEXT_CHARS]
            url = extracted_link.url[:MAX_LINK_URL_CHARS]
            link_chars = len(text) + len(url)
            if returned_chars + link_chars > MAX_RETURNED_LINK_CHARS:
                truncated = True
                break
            # The snapshot retains the full canonical target; only returned
            # fields participate in the aggregate payload budget.  Refs are
            # minted at response time so continuation can repair evicted refs.
            links.append(LinkItem("", text, url, extracted_link.url))
            returned_chars += link_chars
        return links, truncated

    def _initial(self, target: str, max_chars: int, extract_mode: str, request_id: str) -> dict[str, Any]:
        started = time.monotonic()
        try:
            fetched = fetch(
                self.port,
                target,
                limits=FetchLimits(
                    max_bytes=self.limits.max_bytes,
                    max_redirects=self.limits.max_redirects,
                    max_connections=self.limits.max_connections,
                    timeout_s=self.limits.timeout_s,
                ),
            )
        except FetchError as exc:
            raise BrowserFailure(exc.stage, exc.error_code, retryable=exc.retryable, http_status=exc.http_status) from None
        content_type, charset, content_warnings = _content_metadata(fetched.headers)
        extract_started = time.monotonic()
        if content_type in {"text/html", "application/xhtml+xml"}:
            extracted = extract_html(fetched.body, base_url=fetched.final_url, charset=charset)
        elif content_type == "text/plain":
            extracted = extract_plain_text(fetched.body, charset=charset)
        else:
            raise BrowserFailure("extract", "CONTENT_TYPE_UNSUPPORTED", http_status=fetched.http_status)
        extract_ms = max(0, int((time.monotonic() - extract_started) * 1000))
        if not extracted.blocks:
            raise BrowserFailure("extract", "NO_TEXT_BLOCKS", http_status=fetched.http_status)
        links, links_truncated = self._bounded_links(extracted.links)
        warnings = list(content_warnings)
        warnings.extend(item for item in extracted.warnings if item not in warnings)
        if links_truncated and LINKS_TRUNCATED_WARNING not in warnings:
            warnings.append(LINKS_TRUNCATED_WARNING)
        snapshot = self.snapshots.put(
            raw_bytes=fetched.body,
            fetched_url=fetched.requested_url,
            final_url=fetched.final_url,
            http_status=fetched.http_status,
            content_type=content_type,
            extracted=replace(extracted, warnings=warnings),
            links=links,
            extract_mode=extract_mode,
            redirect_chain=fetched.redirect_chain,
        )
        page = paginate_blocks(snapshot.blocks, start_index=0, max_chars=max_chars)
        return self._success(
            snapshot,
            page,
            max_chars,
            request_id,
            timings={
                "fetch": fetched.fetch_ms,
                "extract": extract_ms,
                "total": max(0, int((time.monotonic() - started) * 1000)),
            },
        )

    def _continue(self, target: str, raw_cursor: object, max_chars: int, extract_mode: str, request_id: str) -> dict[str, Any]:
        try:
            payload = self.cursor.decode(raw_cursor)
        except CursorError as exc:
            raise BrowserFailure("cursor", exc.error_code) from None
        snapshot = self.snapshots.get(payload.snapshot_id)
        if snapshot is None:
            raise BrowserFailure("cursor", "CURSOR_SNAPSHOT_NOT_FOUND", snapshot_id=payload.snapshot_id)
        try:
            if payload.extract_mode != extract_mode:
                raise BrowserFailure("cursor", "CURSOR_EXTRACT_MODE_MISMATCH", snapshot_id=snapshot.snapshot_id)
            if not netpolicy.same_target(target, snapshot.requested_url, snapshot.final_url):
                raise BrowserFailure("cursor", "CURSOR_SNAPSHOT_MISMATCH", snapshot_id=snapshot.snapshot_id)
            if payload.next_index >= len(snapshot.blocks):
                raise BrowserFailure("cursor", "CURSOR_OUT_OF_RANGE", snapshot_id=snapshot.snapshot_id)
            if payload.next_char_offset > len(snapshot.blocks[payload.next_index].text):
                raise BrowserFailure("cursor", "CURSOR_OUT_OF_RANGE", snapshot_id=snapshot.snapshot_id)
            page = paginate_blocks(
                snapshot.blocks,
                start_index=payload.next_index,
                max_chars=max_chars,
                start_char_offset=payload.next_char_offset,
            )
        except BrowserFailure:
            raise
        except (IndexError, ValueError):
            raise BrowserFailure("cursor", "CURSOR_OUT_OF_RANGE", snapshot_id=snapshot.snapshot_id) from None
        if not page.blocks and page.has_more:
            raise BrowserFailure("cursor", "CURSOR_OUT_OF_RANGE", snapshot_id=snapshot.snapshot_id)
        return self._success(snapshot, page, max_chars, request_id, timings={})

    def _success(self, snapshot: Snapshot, page, max_chars: int, request_id: str, *, timings: dict[str, int]) -> dict[str, Any]:
        next_cursor = None
        if page.has_more:
            next_cursor = self.cursor.encode(
                CursorPayload(snapshot.snapshot_id, snapshot.extract_mode, page.next_index, page.next_char_offset)
            )
        # A snapshot is immutable, while RefStore is an independently bounded
        # LRU.  Re-mint from each full canonical target for every response so a
        # continuation never emits a ref that was evicted between responses.
        emitted_links = [
            LinkItem(self.refs.add_link_ref(link.target or link.url), link.text, link.url, link.target or link.url)
            for link in snapshot.links
        ]
        return {
            "status": "ok",
            "request_id": request_id,
            "snapshot_id": snapshot.snapshot_id,
            "source_sha256": snapshot.source_sha256,
            "requested_url": snapshot.requested_url,
            "final_url": snapshot.final_url,
            "http_status": snapshot.http_status,
            "content_type": snapshot.content_type,
            "title": snapshot.title[:512],
            "retrieved_at": snapshot.retrieved_at,
            "render_mode": "static",
            "render_reason": "static_http_get",
            "redirect_chain": list(snapshot.redirect_chain),
            "blocks": [{"id": b.id, "kind": b.kind, "text": b.text} for b in page.blocks],
            "links": [{"ref": l.ref, "text": l.text, "url": l.url} for l in emitted_links],
            "partial": page.has_more,
            "returned_chars": sum(len(b.text) for b in page.blocks),
            "next_cursor": next_cursor,
            "timings_ms": dict(timings),
            "warnings": list(snapshot.warnings),
            "untrusted_content": True,
        }


_CHARSET_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,39}$")


def _content_metadata(headers: Mapping[str, str]) -> tuple[str, str | None, list[str]]:
    raw_value = next((str(value) for key, value in headers.items() if str(key).lower() == "content-type"), "text/plain")
    value_truncated = len(raw_value) > 512
    raw_value = raw_value[:512]
    parts = raw_value.split(";", 33)
    media = parts[0].strip().lower() or "text/plain"
    charset: str | None = None
    warnings: list[str] = ["MALFORMED_CHARSET_FALLBACK"] if value_truncated else []
    for parameter in parts[1:]:
        name, separator, value = parameter.strip().partition("=")
        if name.lower() != "charset":
            continue
        if charset is not None:
            warnings.append("MALFORMED_CHARSET_FALLBACK")
            continue
        if not separator:
            warnings.append("MALFORMED_CHARSET_FALLBACK")
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        if not value or not _CHARSET_TOKEN.fullmatch(value):
            warnings.append("MALFORMED_CHARSET_FALLBACK")
        else:
            charset = value
    return media, charset, list(dict.fromkeys(warnings))


def _content_type(headers: Mapping[str, str]) -> str:
    """Return the media type while retaining the historical helper shape."""
    return _content_metadata(headers)[0]
