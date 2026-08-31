"""Isolated protocol tests for the Driver authority client."""
from __future__ import annotations

import array
import json
import os
import socket
import struct
import threading

from lingtai.adapters.acp.driver_authority import (
    DriverAuthorityClient,
    DriverAuthorityTransportError,
)
from lingtai.kernel.provider_admission import (
    DerivedLaunchCapability,
    ProviderAdmissionState,
    RootProviderAdmission,
)


def _recv(sock):
    size = struct.unpack("!I", sock.recv(4))[0]
    body = bytearray()
    while len(body) < size:
        body.extend(sock.recv(size - len(body)))
    return json.loads(body.decode("utf-8"))


def _send(sock, payload, *, fd=None):
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    frame = struct.pack("!I", len(encoded)) + encoded
    if fd is None:
        sock.sendall(frame)
    else:
        sock.sendmsg([frame], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [fd]))])


def _server(handler):
    client, server = socket.socketpair()
    errors = []
    def run():
        try:
            handler(server)
        except BaseException as exc:  # retained for the caller assertion
            errors.append(exc)
        finally:
            server.close()
    thread = threading.Thread(target=run)
    thread.start()
    return client, thread, errors


def _hello(sock, *, role="root", capability=None):
    request = _recv(sock)
    assert request["op"] == "hello"
    assert isinstance(request["call_id"], str) and request["call_id"]
    _send(sock, {"version": 1, "call_id": request["call_id"], "role": role, "launch_id": "launch-1", "capability": capability})


def test_hello_and_provider_request_are_correlated():
    def handler(sock):
        _hello(sock)
        request = _recv(sock)
        assert request["op"] == "authorize_provider_call"
        assert request["capability"] == "root"
        _send(sock, {"version": 1, "call_id": request["call_id"], "state": "granted", "reason_code": "allowed"})
    endpoint, thread, errors = _server(handler)
    client = DriverAuthorityClient(endpoint)
    decision = client.authorize_provider_call(RootProviderAdmission("turn", "v1"), __import__("lingtai.kernel.provider_admission", fromlist=["ProviderCallClass"]).ProviderCallClass.ROOT)
    thread.join(2)
    assert not errors
    assert decision.state is ProviderAdmissionState.GRANTED


def test_mismatched_call_id_closes_received_endpoint_and_fails_closed():
    peer, driver_end = socket.socketpair()
    def handler(sock):
        _hello(sock)
        request = _recv(sock)
        _send(sock, {"version": 1, "call_id": "stale", "state": "granted", "reason_code": "allowed"}, fd=driver_end.fileno())
        driver_end.close()
    endpoint, thread, errors = _server(handler)
    client = DriverAuthorityClient(endpoint)
    decision = client.request_derived_launch(RootProviderAdmission("turn", "v1"), DerivedLaunchCapability.DAEMON)
    thread.join(2)
    assert not errors
    assert decision.state is ProviderAdmissionState.INDETERMINATE
    assert peer.recv(1) == b""
    peer.close()


def test_granted_launch_has_one_linear_inheritable_false_lease():
    child, driver_end = socket.socketpair()
    def handler(sock):
        _hello(sock)
        request = _recv(sock)
        _send(sock, {"version": 1, "call_id": request["call_id"], "state": "granted", "reason_code": "allowed", "audit_id": "audit-1"}, fd=driver_end.fileno())
        driver_end.close()
    endpoint, thread, errors = _server(handler)
    client = DriverAuthorityClient(endpoint)
    grant = client.request_derived_launch(RootProviderAdmission("turn", "v1"), DerivedLaunchCapability.AVATAR)
    thread.join(2)
    assert not errors and grant.state is ProviderAdmissionState.GRANTED
    fd = grant.child_endpoint_lease.consume_for_posix_spawn()
    try:
        assert os.get_inheritable(fd) is False
    finally:
        os.close(fd); child.close()
    try:
        grant.child_endpoint_lease.consume_for_posix_spawn()
    except DriverAuthorityTransportError:
        pass
    else:
        raise AssertionError("lease was reusable")
