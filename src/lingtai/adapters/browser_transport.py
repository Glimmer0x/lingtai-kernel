"""Production static HTTP(S) Adapter for the browser Core Port.

The adapter is intentionally outside ``lingtai.tools.browser`` Core.  It dials
the exact vetted IP supplied by Core, keeps the original hostname for Host/SNI,
never follows redirects, and does not consult proxy environment variables.
"""
from __future__ import annotations

import http.client
import socket
import ssl
from urllib.parse import urlsplit

from lingtai.tools.browser.port import ResolvedTarget, TransportError, TransportResponse


class VettedHttpTransport:
    """One-shot pinned HTTP(S) transport with bounded response reads."""

    user_agent = "lingtai-browser/1.0 (static-read-only)"

    def resolve(self, hostname: str) -> tuple[str, ...]:
        try:
            infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
        except (OSError, ValueError):
            raise TransportError("dns", "DNS_RESOLUTION_FAILED", retryable=True) from None
        addresses = tuple(sorted({str(info[4][0]) for info in infos if info[4]}))
        if not addresses:
            raise TransportError("dns", "DNS_RESOLUTION_FAILED", retryable=True)
        return addresses

    def request(
        self,
        url: str,
        *,
        resolved: ResolvedTarget,
        max_bytes: int,
        timeout_s: float,
    ) -> TransportResponse:
        try:
            parts = urlsplit(url)
            if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
                raise ValueError
            path = parts.path or "/"
            if parts.query:
                path += "?" + parts.query
            host_header = _host_header(parts.hostname, resolved.port, parts.scheme.lower())
        except (TypeError, ValueError):
            raise TransportError("connect", "MALFORMED_URL") from None
        if not resolved.ip_addresses:
            raise TransportError("connect", "NO_RESOLVED_ADDRESS")
        if max_bytes < 1 or timeout_s <= 0:
            raise TransportError("connect", "INVALID_REQUEST_LIMITS")

        pinned_ip = resolved.ip_addresses[0]
        http_cls, https_cls = _make_pinned_connection_classes(pinned_ip)
        connection: http.client.HTTPConnection | http.client.HTTPSConnection
        try:
            if parts.scheme.lower() == "https":
                context = ssl.create_default_context()
                connection = https_cls(parts.hostname, resolved.port, context=context, timeout=timeout_s)
            else:
                connection = http_cls(parts.hostname, resolved.port, timeout=timeout_s)
            connection.request(
                "GET",
                path,
                headers={
                    "Host": host_header,
                    "User-Agent": self.user_agent,
                    "Accept": "text/html, text/plain;q=0.9",
                    "Connection": "close",
                },
            )
            response = connection.getresponse()
            body = response.read(max_bytes + 1)
            truncated = len(body) > max_bytes
            headers = {str(key): str(value) for key, value in response.getheaders()}
            return TransportResponse(response.status, headers, body[:max_bytes], truncated, url)
        except TransportError:
            raise
        except (socket.timeout, TimeoutError):
            raise TransportError("connect", "READ_TIMEOUT", retryable=True) from None
        except (ssl.SSLError, OSError, http.client.HTTPException):
            raise TransportError("connect", "TRANSPORT_FAILED", retryable=True) from None
        finally:
            try:
                connection.close()
            except (UnboundLocalError, OSError):
                pass


def _host_header(hostname: str, port: int, scheme: str) -> str:
    host = f"[{hostname}]" if ":" in hostname and not hostname.startswith("[") else hostname
    default_port = 443 if scheme == "https" else 80
    return host if port == default_port else f"{host}:{port}"


def _make_pinned_connection_classes(pinned_ip: str):
    """Create connection classes that never perform a second hostname lookup."""

    def create_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None):
        _, port = address
        return socket.create_connection((pinned_ip, port), timeout, source_address)

    class PinnedHTTPConnection(http.client.HTTPConnection):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._create_connection = create_connection

    class PinnedHTTPSConnection(http.client.HTTPSConnection):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._create_connection = create_connection

    return PinnedHTTPConnection, PinnedHTTPSConnection


BrowserTransport = VettedHttpTransport
