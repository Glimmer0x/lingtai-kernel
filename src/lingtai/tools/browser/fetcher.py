"""Bounded redirect-following orchestration for Browser Core."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Mapping

from . import netpolicy
from .port import BrowserPort, TransportError, TransportResponse

DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_MAX_REDIRECTS = 5
DEFAULT_MAX_CONNECTIONS = 6
DEFAULT_TIMEOUT_S = 15.0


class FetchError(Exception):
    """Sanitized, stage-tagged failure from a bounded fetch."""

    def __init__(self, stage: str, error_code: str, *, retryable: bool = False, http_status: int | None = None) -> None:
        super().__init__(error_code)
        self.stage = stage
        self.error_code = error_code
        self.message = error_code
        self.retryable = retryable
        self.http_status = http_status


@dataclass(frozen=True, slots=True)
class FetchLimits:
    max_bytes: int = DEFAULT_MAX_BYTES
    max_redirects: int = DEFAULT_MAX_REDIRECTS
    max_connections: int = DEFAULT_MAX_CONNECTIONS
    timeout_s: float = DEFAULT_TIMEOUT_S


@dataclass(frozen=True, slots=True)
class FetchResult:
    requested_url: str
    final_url: str
    http_status: int
    headers: dict[str, str]
    body: bytes
    redirect_chain: list[str]
    fetch_ms: int


def _header(headers: Mapping[str, str], name: str) -> str | None:
    wanted = name.lower()
    for key, value in headers.items():
        if str(key).lower() == wanted:
            return str(value)
    return None


def fetch(port: BrowserPort, url: str, *, limits: FetchLimits, resolver=None) -> FetchResult:
    """Perform static GETs, validating DNS and redirects before every hop."""
    if limits.max_bytes < 1 or limits.max_redirects < 0 or limits.max_connections < 1 or not math.isfinite(limits.timeout_s) or limits.timeout_s <= 0:
        raise FetchError("policy", "INVALID_FETCH_LIMITS")
    requested_url = url
    current_url = url
    redirects: list[str] = []
    start = time.monotonic()
    deadline = start + limits.timeout_s
    connections = 0
    resolve = resolver or port.resolve

    for hop in range(limits.max_redirects + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise FetchError("connect", "FETCH_TIMEOUT", retryable=True)
        try:
            parsed = netpolicy._parse(current_url)
            # Resolution is part of the same end-to-end deadline as connect,
            # redirect, and body-read time.  The Port owns how it enforces the
            # bounded wait; Core only supplies the remaining budget.
            resolved = netpolicy.resolve_and_check(current_url, resolve, timeout_s=remaining)
        except TransportError as exc:
            raise FetchError(exc.stage, exc.error_code, retryable=exc.retryable) from None
        except netpolicy.PolicyViolation as exc:
            raise FetchError("policy", exc.error_code) from None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise FetchError("connect", "FETCH_TIMEOUT", retryable=True)
        if connections >= limits.max_connections:
            raise FetchError("policy", "TOO_MANY_CONNECTIONS")
        connections += 1
        try:
            response: TransportResponse = port.request(
                current_url,
                resolved=resolved,
                max_bytes=limits.max_bytes,
                timeout_s=remaining,
            )
        except FetchError:
            raise
        except Exception as exc:
            stage = getattr(exc, "stage", "connect")
            code = getattr(exc, "error_code", "TRANSPORT_FAILED")
            retryable = bool(getattr(exc, "retryable", True))
            raise FetchError(str(stage), str(code), retryable=retryable) from None

        status = int(response.status)
        if 300 <= status < 400:
            location = _header(response.headers, "location")
            if not location:
                raise FetchError("http", "REDIRECT_MISSING_LOCATION", http_status=status)
            if hop >= limits.max_redirects:
                raise FetchError("policy", "TOO_MANY_REDIRECTS", http_status=status)
            try:
                next_url = netpolicy.resolved_url(current_url, location)
            except netpolicy.PolicyViolation as exc:
                raise FetchError("policy", exc.error_code, http_status=status) from None
            redirects.append(current_url)
            current_url = next_url
            continue

        if status < 200 or status >= 300:
            raise FetchError(
                "http",
                "HTTP_STATUS",
                retryable=status == 429 or status >= 500,
                http_status=status,
            )
        if response.truncated or len(response.body) > limits.max_bytes:
            raise FetchError("fetch", "BODY_TOO_LARGE", http_status=status)
        return FetchResult(
            requested_url=requested_url,
            final_url=current_url,
            http_status=status,
            headers=dict(response.headers),
            body=response.body[: limits.max_bytes],
            redirect_chain=redirects,
            fetch_ms=max(0, int((time.monotonic() - start) * 1000)),
        )
    raise FetchError("policy", "TOO_MANY_REDIRECTS")
