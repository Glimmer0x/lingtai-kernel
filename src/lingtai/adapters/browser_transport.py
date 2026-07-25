"""Production static HTTP(S) Adapter for the browser Core Port.

The adapter is intentionally outside ``lingtai.tools.browser`` Core.  It dials
the exact vetted IP supplied by Core, keeps the original hostname for Host/SNI,
never follows redirects, and does not consult proxy environment variables.
"""
from __future__ import annotations

import http.client
import math
import socket
import ssl
import threading
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from lingtai.tools.browser.port import ResolvedTarget, TransportError, TransportResponse


@dataclass
class _ResolverJob:
    """One bounded-wait DNS operation; the underlying stdlib call may be stuck."""

    event: threading.Event = field(default_factory=threading.Event)
    addresses: tuple[str, ...] = ()
    error: BaseException | None = None
    thread: threading.Thread | None = None


class VettedHttpTransport:
    """One-shot pinned HTTP(S) transport with bounded response reads.

    ``socket.getaddrinfo`` has no portable timeout argument.  A single daemon
    resolver thread lets Core bound the caller's wait without adding a thread
    per request: while one lookup is still stuck, later resolves fail with a
    typed timeout instead of spawning or queueing more work.
    """

    user_agent = "lingtai-browser/1.0 (static-read-only)"

    def __init__(self) -> None:
        self._resolver_lock = threading.Lock()
        self._resolver_job: _ResolverJob | None = None

    def resolve(self, hostname: str, *, timeout_s: float) -> tuple[str, ...]:
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise TransportError("dns", "DNS_RESOLUTION_TIMEOUT", retryable=True)
        with self._resolver_lock:
            previous = self._resolver_job
            if previous is not None:
                if previous.thread is not None and previous.thread.is_alive():
                    raise TransportError("dns", "DNS_RESOLUTION_TIMEOUT", retryable=True)
                self._resolver_job = None
            job = _ResolverJob()
            self._resolver_job = job
            thread = threading.Thread(
                target=self._resolve_worker,
                args=(hostname, job),
                name="lingtai-browser-dns",
                daemon=True,
            )
            job.thread = thread
            thread.start()
        if not job.event.wait(timeout_s):
            # Leave the job installed while its daemon lookup unwinds.  This
            # is the guard that prevents unbounded in-flight resolver growth.
            raise TransportError("dns", "DNS_RESOLUTION_TIMEOUT", retryable=True)
        if job.error is not None:
            raise TransportError("dns", "DNS_RESOLUTION_FAILED", retryable=True) from None
        if not job.addresses:
            raise TransportError("dns", "DNS_RESOLUTION_FAILED", retryable=True)
        return job.addresses

    @staticmethod
    def _resolve_worker(hostname: str, job: _ResolverJob) -> None:
        try:
            infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
            job.addresses = tuple(sorted({str(info[4][0]) for info in infos if info[4]}))
        except Exception as exc:
            # The caller receives only the stable, sanitized DNS error code.
            job.error = exc
        finally:
            job.event.set()

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
        if max_bytes < 1 or not math.isfinite(timeout_s) or timeout_s <= 0:
            raise TransportError("connect", "INVALID_REQUEST_LIMITS")

        pinned_ip = resolved.ip_addresses[0]
        http_cls, https_cls = _make_pinned_connection_classes(pinned_ip)
        connection: http.client.HTTPConnection | http.client.HTTPSConnection
        try:
            if parts.scheme.lower() == "https":
                context = ssl.create_default_context()
                # Keep parts.hostname, rather than the pinned IP, so the
                # stdlib HTTPS connection performs SNI and certificate checks
                # for the public hostname while the socket dials pinned_ip.
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
