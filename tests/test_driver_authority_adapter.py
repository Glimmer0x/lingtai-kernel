"""Isolated protocol tests for the Driver authority client."""
from __future__ import annotations

import array
import json
import os
import select
import socket
import struct
import threading
import time
from unittest.mock import patch

from lingtai.adapters.acp.driver_authority import (
    DriverAuthorityClient,
    DriverAuthorityTransportError,
)
from lingtai.kernel.provider_admission import (
    DerivedLaunchCapability,
    ProviderAdmissionState,
    ProviderCallClass,
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
    decision = client.authorize_provider_call(RootProviderAdmission("turn", "v1"), ProviderCallClass.ROOT)
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


def test_malformed_derived_decision_closes_received_endpoint_and_fails_closed():
    peer, driver_end = socket.socketpair()

    def handler(sock):
        _hello(sock)
        request = _recv(sock)
        _send(sock, {
            "version": 1, "call_id": request["call_id"], "state": "granted",
            "reason_code": "",  # invalid decision field
        }, fd=driver_end.fileno())
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


def test_detach_failure_leaves_lease_closable():
    endpoint, peer = socket.socketpair()
    from lingtai.adapters.acp.driver_authority import DriverChildEndpointLease

    lease = DriverChildEndpointLease(endpoint)
    with patch.object(socket.socket, "detach", side_effect=OSError("injected detach failure")):
        try:
            lease.consume_for_posix_spawn()
        except DriverAuthorityTransportError:
            pass
        else:
            raise AssertionError("detach failure did not surface")

    lease.close()
    ready, _, _ = select.select([peer], [], [], 0.2)
    assert ready == [peer]
    assert peer.recv(1) == b""
    peer.close()


def test_truncated_ancillary_data_closes_every_delivered_descriptor():
    from lingtai.adapters.acp import driver_authority as authority_module

    frame = struct.pack("!I", len(b'{"version":1}')) + b'{"version":1}'
    delivered_fd = 731
    client = object.__new__(DriverAuthorityClient)
    client._socket = type("FakeSocket", (), {
        "recvmsg": lambda _self, *_args: (frame, [(
            socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [delivered_fd]).tobytes(),
        )], socket.MSG_CTRUNC, None),
    })()
    client._buffer = bytearray()
    with patch.object(authority_module.os, "close") as close:
        try:
            client._recv_frame()
        except DriverAuthorityTransportError as exc:
            assert "ancillary data was truncated" in str(exc)
        else:
            raise AssertionError("truncated ancillary data was accepted")
    close.assert_called_once_with(delivered_fd)


def test_denied_child_endpoint_is_closed_without_erasing_driver_reason():
    peer, driver_end = socket.socketpair()

    def handler(sock):
        _hello(sock)
        request = _recv(sock)
        _send(sock, {
            "version": 1, "call_id": request["call_id"], "state": "denied",
            "reason_code": "policy_denied", "audit_id": "audit-1",
        }, fd=driver_end.fileno())
        driver_end.close()

    endpoint, thread, errors = _server(handler)
    client = DriverAuthorityClient(endpoint)
    decision = client.request_derived_launch(RootProviderAdmission("turn", "v1"), DerivedLaunchCapability.AVATAR)
    thread.join(2)
    assert not errors
    assert decision.state is ProviderAdmissionState.DENIED
    assert decision.reason_code == "policy_denied"
    assert decision.audit_id == "audit-1"
    assert peer.recv(1) == b""
    peer.close()


def test_unconnected_unix_endpoint_is_closed_by_the_grant_parser():
    endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    fd = endpoint.detach()
    try:
        DriverAuthorityClient._checked_endpoint(fd)
    except DriverAuthorityTransportError:
        pass
    else:
        raise AssertionError("unconnected endpoint became a grant")
    try:
        os.fstat(fd)
    except OSError:
        pass
    else:
        os.close(fd)
        raise AssertionError("rejected endpoint descriptor leaked")


def test_grant_parser_closes_its_socket_wrapper_after_descriptor_adoption():
    endpoint, peer = socket.socketpair()
    fd = endpoint.detach()
    with patch.object(os, "set_inheritable", side_effect=OSError("injected inheritable failure")):
        try:
            DriverAuthorityClient._checked_endpoint(fd)
        except DriverAuthorityTransportError:
            pass
        else:
            raise AssertionError("invalid adopted endpoint became a grant")
    assert peer.recv(1) == b""
    peer.close()


def test_derived_endpoint_cannot_mint_a_second_child_even_with_a_socket():
    def handler(sock):
        _hello(sock, role="derived", capability="daemon")

    endpoint, thread, errors = _server(handler)
    client = DriverAuthorityClient(endpoint)
    decision = client.request_derived_launch(RootProviderAdmission("turn", "v1"), DerivedLaunchCapability.DAEMON)
    client.close()
    thread.join(2)
    assert not errors
    assert decision.state is ProviderAdmissionState.DENIED
    assert decision.reason_code == "nested_derived_launch_denied"


def test_local_child_mode_must_match_driver_endpoint_capability():
    def handler(sock):
        _hello(sock, role="derived", capability="daemon")

    endpoint, thread, errors = _server(handler)
    client = DriverAuthorityClient(endpoint)
    try:
        client.derived_provider_parent(ProviderCallClass.AVATAR_CHILD)
    except DriverAuthorityTransportError:
        pass
    else:
        raise AssertionError("wrong derived endpoint capability was accepted")
    client.close()
    thread.join(2)
    assert not errors


def test_derived_provider_call_uses_its_own_endpoint_and_driver_known_fields():
    def handler(sock):
        _hello(sock, role="derived", capability="daemon")
        request = _recv(sock)
        assert request["op"] == "authorize_provider_call"
        assert request["launch_id"] == "launch-1"
        assert request["provider"] == "llm"
        assert request["capability"] == "daemon"
        _send(sock, {"version": 1, "call_id": request["call_id"], "state": "granted", "reason_code": "allowed"})

    endpoint, thread, errors = _server(handler)
    client = DriverAuthorityClient(endpoint)
    decision = client.authorize_provider_call(client.derived_provider_parent(), ProviderCallClass.DAEMON)
    thread.join(2)
    assert not errors
    assert decision.state is ProviderAdmissionState.GRANTED


def test_malformed_driver_provider_reply_fails_closed_before_provider_io():
    def handler(sock):
        _hello(sock)
        _recv(sock)
        payload = b'{"version":1,"state":"granted","reason_code":""}'
        sock.sendall(struct.pack("!I", len(payload)) + payload)

    endpoint, thread, errors = _server(handler)
    client = DriverAuthorityClient(endpoint)
    decision = client.authorize_provider_call(RootProviderAdmission("turn", "v1"), ProviderCallClass.ROOT)
    thread.join(2)
    assert not errors
    assert decision.state is ProviderAdmissionState.INDETERMINATE


def test_provider_reply_with_an_endpoint_fails_closed_and_closes_it():
    peer, driver_end = socket.socketpair()

    def handler(sock):
        _hello(sock)
        request = _recv(sock)
        _send(sock, {"version": 1, "call_id": request["call_id"], "state": "granted", "reason_code": "allowed"}, fd=driver_end.fileno())
        driver_end.close()

    endpoint, thread, errors = _server(handler)
    client = DriverAuthorityClient(endpoint)
    decision = client.authorize_provider_call(RootProviderAdmission("turn", "v1"), ProviderCallClass.ROOT)
    thread.join(2)
    assert not errors
    assert decision.state is ProviderAdmissionState.INDETERMINATE
    assert peer.recv(1) == b""
    peer.close()


def test_closed_truncated_or_timed_out_driver_reply_is_indeterminate():
    for failure in ("closed", "truncated", "timeout"):
        def handler(sock, failure=failure):
            _hello(sock)
            _recv(sock)
            if failure == "truncated":
                sock.sendall(struct.pack("!I", 12) + b"{}")
            elif failure == "timeout":
                time.sleep(0.05)

        endpoint, thread, errors = _server(handler)
        client = DriverAuthorityClient(endpoint, timeout=0.01)
        decision = client.authorize_provider_call(RootProviderAdmission("turn", "v1"), ProviderCallClass.ROOT)
        thread.join(2)
        assert not errors
        assert decision.state is ProviderAdmissionState.INDETERMINATE


def test_timeout_invalidates_endpoint_so_late_grant_cannot_admit_next_call():
    def handler(sock):
        _hello(sock)
        first = _recv(sock)
        assert first["op"] == "authorize_provider_call"
        time.sleep(0.03)
        try:
            _send(sock, {"version": 1, "call_id": first["call_id"], "state": "granted", "reason_code": "allowed"})
            _recv(sock)
        except OSError:
            pass

    endpoint, thread, errors = _server(handler)
    client = DriverAuthorityClient(endpoint, timeout=0.02)
    parent = RootProviderAdmission("turn", "v1")
    first = client.authorize_provider_call(parent, ProviderCallClass.ROOT)
    second = client.authorize_provider_call(parent, ProviderCallClass.ROOT)
    client.close()
    thread.join(2)
    assert not errors
    assert first.state is ProviderAdmissionState.INDETERMINATE
    assert second.state is ProviderAdmissionState.INDETERMINATE


def test_bad_driver_handshake_is_not_a_client():
    def handler(sock):
        request = _recv(sock)
        _send(sock, {"version": 2, "call_id": request["call_id"], "role": "root", "launch_id": "launch-1", "capability": None})

    endpoint, thread, errors = _server(handler)
    try:
        DriverAuthorityClient(endpoint)
    except DriverAuthorityTransportError:
        pass
    else:
        raise AssertionError("invalid handshake constructed a client")
    thread.join(2)
    assert not errors
