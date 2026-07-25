"""Production browser Adapter pinning tests; all traffic is loopback-only."""
from __future__ import annotations

import socket
import threading

import pytest

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
