"""Production browser Adapter pinning tests; all traffic is loopback-only."""
from __future__ import annotations

import socket
import threading
import time

import pytest

import lingtai.adapters.browser_transport as browser_transport
from lingtai.adapters.browser_transport import VettedHttpTransport
from lingtai.tools.browser.port import ResolvedTarget, TransportError


def test_production_transport_pins_vetted_ip_and_ignores_proxy(monkeypatch):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    seen: dict[str, str] = {}

    def serve_once():
        connection, _ = listener.accept()
        with connection:
            request = b""
            while b"\r\n\r\n" not in request:
                chunk = connection.recv(4096)
                if not chunk:
                    break
                request += chunk
            seen["request"] = request.decode("iso-8859-1")
            connection.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n"
                b"Content-Length: 5\r\nConnection: close\r\n\r\nhello"
            )

    thread = threading.Thread(target=serve_once)
    thread.start()
    original_create_connection = socket.create_connection
    dialed: list[tuple[str, int]] = []

    def recorded_create_connection(address, timeout=None, source_address=None):
        dialed.append(address)
        return original_create_connection(address, timeout, source_address)

    monkeypatch.setattr(socket, "create_connection", recorded_create_connection)
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    try:
        response = VettedHttpTransport().request(
            f"http://public.example:{port}/page",
            resolved=ResolvedTarget("public.example", port, "http", ("127.0.0.1",)),
            max_bytes=100,
            timeout_s=2.0,
        )
    finally:
        listener.close()
        thread.join(timeout=2.0)

    assert response.status == 200
    assert response.body == b"hello"
    assert dialed == [("127.0.0.1", port)]
    assert "Host: public.example:" + str(port) in seen["request"]
    assert "GET /page HTTP/1.1" in seen["request"]


def test_production_transport_maps_socket_timeout(monkeypatch):
    def timeout(*args, **kwargs):
        raise socket.timeout()

    monkeypatch.setattr(socket, "create_connection", timeout)
    with pytest.raises(TransportError) as raised:
        VettedHttpTransport().request(
            "http://public.example/page",
            resolved=ResolvedTarget("public.example", 80, "http", ("198.51.100.8",)),
            max_bytes=100,
            timeout_s=1.0,
        )
    assert raised.value.error_code == "READ_TIMEOUT"
    assert raised.value.retryable is True


def test_production_transport_truncates_body_at_adapter_limit(monkeypatch):
    class FakeResponse:
        status = 200

        def getheaders(self):
            return [("Content-Type", "text/plain")]

        def read(self, limit):
            assert limit == 6
            return b"abcdef"

    class FakeConnection:
        def __init__(self, *args, **kwargs):
            self.response = FakeResponse()

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return self.response

        def close(self):
            pass

    monkeypatch.setattr(browser_transport, "_make_pinned_connection_classes", lambda ip: (FakeConnection, FakeConnection))
    response = VettedHttpTransport().request(
        "http://public.example/page",
        resolved=ResolvedTarget("public.example", 80, "http", ("198.51.100.8",)),
        max_bytes=5,
        timeout_s=1.0,
    )
    assert response.body == b"abcde"
    assert response.truncated is True


def test_production_transport_keeps_https_hostname_for_sni(monkeypatch):
    seen: dict[str, object] = {}

    class FakeResponse:
        status = 200

        def getheaders(self):
            return []

        def read(self, limit):
            return b"ok"

    class FakeHTTPSConnection:
        def __init__(self, hostname, port, **kwargs):
            seen["hostname"] = hostname
            seen["port"] = port
            self.response = FakeResponse()

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return self.response

        def close(self):
            pass

    class FakeHTTPConnection(FakeHTTPSConnection):
        pass

    monkeypatch.setattr(
        browser_transport,
        "_make_pinned_connection_classes",
        lambda ip: (FakeHTTPConnection, FakeHTTPSConnection),
    )
    response = VettedHttpTransport().request(
        "https://public.example/page",
        resolved=ResolvedTarget("public.example", 443, "https", ("198.51.100.8",)),
        max_bytes=10,
        timeout_s=1.0,
    )
    assert response.body == b"ok"
    assert seen == {"hostname": "public.example", "port": 443}


def test_request_rejects_no_resolved_address():
    with pytest.raises(TransportError) as raised:
        VettedHttpTransport().request(
            "http://public.example/page",
            resolved=ResolvedTarget("public.example", 80, "http", ()),
            max_bytes=1,
            timeout_s=1.0,
        )
    assert raised.value.error_code == "NO_RESOLVED_ADDRESS"


def test_resolve_maps_dns_failure_and_empty_answers(monkeypatch):
    def fail(*args, **kwargs):
        raise socket.gaierror("no answer")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    with pytest.raises(TransportError) as raised:
        VettedHttpTransport().resolve("public.example", timeout_s=1.0)
    assert raised.value.error_code == "DNS_RESOLUTION_FAILED"
    assert raised.value.retryable is True

    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [])
    with pytest.raises(TransportError) as raised:
        VettedHttpTransport().resolve("public.example", timeout_s=1.0)
    assert raised.value.error_code == "DNS_RESOLUTION_FAILED"


def test_resolve_times_out_without_spawning_a_second_lookup(monkeypatch):
    release = threading.Event()
    started = threading.Event()

    def stuck(*args, **kwargs):
        started.set()
        release.wait(2.0)
        return []

    monkeypatch.setattr(socket, "getaddrinfo", stuck)
    transport = VettedHttpTransport()
    first_worker = None
    try:
        with pytest.raises(TransportError) as first:
            transport.resolve("public.example", timeout_s=0.01)
        assert first.value.error_code == "DNS_RESOLUTION_TIMEOUT"
        assert started.wait(0.2)
        first_job = transport._resolver_job
        assert first_job is not None and first_job.thread is not None
        first_worker = first_job.thread
        with pytest.raises(TransportError) as second:
            transport.resolve("another.example", timeout_s=0.01)
        assert second.value.error_code == "DNS_RESOLUTION_TIMEOUT"
        assert first_worker.is_alive()
    finally:
        release.set()
        if first_worker is not None:
            deadline = time.monotonic() + 1.0
            while first_worker.is_alive() and time.monotonic() < deadline:
                first_worker.join(timeout=max(0.0, deadline - time.monotonic()))
            assert not first_worker.is_alive()

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
    )
    addresses = transport.resolve("public.example", timeout_s=1.0)
    second_job = transport._resolver_job
    assert second_job is not None and second_job.thread is not None
    assert second_job.thread is not first_worker
    assert not second_job.thread.is_alive()
    assert addresses == ("93.184.216.34",)
