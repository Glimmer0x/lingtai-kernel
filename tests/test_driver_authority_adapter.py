"""Production-shaped tests for the POSIX Driver authority adapter."""
from __future__ import annotations

import array
import json
import os
import socket
import struct
import threading
import time
import traceback
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from lingtai.adapters.acp.driver_authority import (
    DriverAuthorityAdapter,
    DriverChildEndpointLease,
    DriverAuthorityEndpointBindingMismatch,
    EndpointBindingMismatchAuthorityAdapter,
    DriverAuthorityTransportError,
    UnavailableDriverAuthorityAdapter,
    authority_adapter_from_environment,
    consume_posix_child_endpoint_lease,
)
from lingtai.kernel.provider_admission import (
    DerivedLaunchCapability,
    ProviderAdmissionState,
    ProviderAdmittedLLMService,
    ProviderAdmissionError,
    ProviderCallClass,
    RootProviderAdmission,
    begin_derived_provider_admission,
    bind_provider_admission,
    clear_provider_admission,
    require_derived_launch_admission,
)


_RESPONSE_CALL_IDS: dict[int, str] = {}


def _recv_frame(sock: socket.socket) -> dict:
    header = sock.recv(4)
    assert len(header) == 4
    size = struct.unpack("!I", header)[0]
    payload = bytearray()
    while len(payload) < size:
        payload.extend(sock.recv(size - len(payload)))
    value = json.loads(bytes(payload).decode("utf-8"))
    if isinstance(value.get("call_id"), str):
        _RESPONSE_CALL_IDS[sock.fileno()] = value["call_id"]
    return value


def _send_frame(sock: socket.socket, payload: dict, *, fd: int | None = None) -> None:
    if "state" in payload and "call_id" not in payload:
        payload = {**payload, "call_id": _RESPONSE_CALL_IDS[sock.fileno()]}
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    frame = struct.pack("!I", len(encoded)) + encoded
    if fd is None:
        sock.sendall(frame)
        return
    rights = array.array("i", [fd])
    sent = sock.sendmsg([frame], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, rights)])
    if sent < len(frame):
        sock.sendall(frame[sent:])


def _server_thread(server: socket.socket, handler):
    error: list[BaseException] = []

    def run():
        try:
            handler(server)
        except BaseException as exc:  # test server must surface failures
            error.append(exc)
        finally:
            server.close()

    thread = threading.Thread(target=run)
    thread.start()
    return thread, error


def test_truncated_ancillary_data_closes_every_delivered_descriptor(monkeypatch):
    """A kernel may install SCM_RIGHTS before reporting ``MSG_CTRUNC``."""
    payload = b'{"version":1}'
    frame = struct.pack("!I", len(payload)) + payload
    delivered_fd = 731
    fake_socket = SimpleNamespace(
        recvmsg=lambda *_args: (
            frame,
            [
                (
                    socket.SOL_SOCKET,
                    socket.SCM_RIGHTS,
                    array.array("i", [delivered_fd]).tobytes(),
                )
            ],
            socket.MSG_CTRUNC,
            None,
        )
    )
    adapter = object.__new__(DriverAuthorityAdapter)
    adapter._socket = fake_socket
    adapter._buffer = bytearray()
    closed: list[int] = []
    monkeypatch.setattr(os, "close", closed.append)

    with pytest.raises(
        DriverAuthorityTransportError, match="ancillary data was truncated"
    ):
        adapter._recv_frame()

    assert closed == [delivered_fd]


def test_denied_child_endpoint_is_closed_without_erasing_driver_reason(monkeypatch):
    adapter = object.__new__(DriverAuthorityAdapter)
    closed: list[int] = []
    monkeypatch.setattr(os, "close", closed.append)

    decision = adapter._derived_decision(
        {"version": 1, "state": "denied", "reason_code": "policy_denied", "audit_id": "audit-1"},
        731,
    )

    assert closed == [731]
    assert decision.state is ProviderAdmissionState.DENIED
    assert decision.reason_code == "policy_denied"
    assert decision.audit_id == "audit-1"


def test_derived_decision_is_the_only_owner_of_a_denied_child_descriptor(monkeypatch):
    """The caller must not double-close a descriptor already released below."""
    adapter = object.__new__(DriverAuthorityAdapter)
    adapter._identity = SimpleNamespace(role="root", launch_id="root-1")
    adapter._lock = threading.Lock()
    adapter._exchange_locked = lambda *_args, **_kwargs: (
        {"version": 1, "state": "denied", "reason_code": "policy_denied", "audit_id": "audit-1"},
        731,
    )
    closed: list[int] = []
    monkeypatch.setattr(os, "close", closed.append)

    decision = adapter.authorize_derived_launch(
        RootProviderAdmission("turn-1", "puffo-v0.full-tool-acp-ingress.v1"),
        DerivedLaunchCapability.AVATAR,
    )

    assert closed == [731]
    assert decision.state is ProviderAdmissionState.DENIED
    assert decision.reason_code == "policy_denied"


def test_granted_endpoint_wrapper_owns_cleanup_after_descriptor_adoption(monkeypatch):
    """A stale raw fd must not be closed after ``socket(fileno=...)`` adopts it."""
    adapter = object.__new__(DriverAuthorityAdapter)
    endpoint = SimpleNamespace(
        close=lambda: closed_wrappers.append(True),
        family=socket.AF_UNIX,
        type=socket.SOCK_STREAM,
        getpeername=lambda: "driver",
        fileno=lambda: 731,
    )
    closed_wrappers: list[bool] = []
    raw_closes: list[int] = []
    monkeypatch.setattr(socket, "socket", lambda *, fileno: endpoint)
    monkeypatch.setattr(os, "set_inheritable", lambda *_args: (_ for _ in ()).throw(OSError("bad fd")))
    monkeypatch.setattr(os, "close", raw_closes.append)

    with pytest.raises(DriverAuthorityTransportError, match="child endpoint is invalid"):
        adapter._derived_decision(
            {"version": 1, "state": "granted", "reason_code": "allowed", "audit_id": "audit-1"},
            731,
        )

    assert closed_wrappers == [True]
    assert raw_closes == []


def test_unconnected_unix_endpoint_is_explicitly_closed_by_decision_parser(monkeypatch):
    """An unconnected child descriptor cannot become a Driver lease."""
    from lingtai.adapters.acp import driver_authority as authority_module

    adapter = object.__new__(DriverAuthorityAdapter)
    unconnected = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    close_stacks = []
    real_socket = authority_module.socket.socket

    class _CloseRecordingSocket(real_socket):
        def close(self):
            close_stacks.append(traceback.extract_stack())
            return super().close()

    monkeypatch.setattr(authority_module.socket, "socket", _CloseRecordingSocket)
    try:
        with pytest.raises(DriverAuthorityTransportError, match="child endpoint is invalid"):
            adapter._derived_decision(
                {"version": 1, "state": "granted", "reason_code": "allowed", "audit_id": "audit-1"},
                unconnected.detach(),
            )
    finally:
        # ``detach`` transfers ownership to the parser; this only keeps the
        # test robust if construction failed before the parser adopted it.
        try:
            unconnected.close()
        except OSError:
            pass

    assert any(
        frame.name == "_derived_decision"
        for stack in close_stacks
        for frame in stack
    ), "the parser must explicitly close the endpoint, not defer to __del__"


def _fd_is_open(fd: int) -> bool:
    try:
        os.fstat(fd)
    except OSError:
        return False
    return True


def test_root_driver_adapter_receives_one_child_endpoint_lease_and_consumes_once():
    client, server = socket.socketpair()
    child_client, child_driver = socket.socketpair()

    def handler(sock):
        assert _recv_frame(sock) == {"version": 1, "op": "hello"}
        _send_frame(sock, {"version": 1, "role": "root", "launch_id": "root-1", "capability": None})
        request = _recv_frame(sock)
        assert {key: request[key] for key in request if key != "call_id"} == {
            "version": 1,
            "op": "authorize_derived_launch",
            "launch_id": "root-1",
            "capability": "avatar",
        }
        assert isinstance(request["call_id"], str) and request["call_id"]
        _send_frame(
            sock,
            {
                "version": 1,
                "state": "granted",
                "reason_code": "allowed",
                "audit_id": "audit-1",
                "admission_id": "admission-1",
            },
            fd=child_client.fileno(),
        )
        child_client.close()

    thread, errors = _server_thread(server, handler)
    adapter = DriverAuthorityAdapter(client)
    root = RootProviderAdmission("turn-1", "puffo-v0.full-tool-acp-ingress.v1")
    token = bind_provider_admission(root)
    try:
        decision = require_derived_launch_admission(adapter, DerivedLaunchCapability.AVATAR)
    finally:
        clear_provider_admission(token)
    thread.join(timeout=2)

    assert errors == []
    assert decision.state is ProviderAdmissionState.GRANTED
    assert decision.audit_id == "audit-1"
    assert decision.admission_id == "admission-1"
    assert decision.child_endpoint_lease is not None
    inherited_fd = consume_posix_child_endpoint_lease(decision.child_endpoint_lease)
    try:
        assert os.get_inheritable(inherited_fd) is False
        with pytest.raises(DriverAuthorityTransportError, match="already consumed"):
            consume_posix_child_endpoint_lease(decision.child_endpoint_lease)
    finally:
        os.close(inherited_fd)
        child_driver.close()


def test_child_endpoint_lease_remains_explicitly_closeable_after_detach_failure():
    """A failed handoff must not mark an open endpoint as consumed."""
    endpoint = SimpleNamespace(
        detach=MagicMock(side_effect=OSError("detach failed")),
        close=MagicMock(),
    )
    lease = DriverChildEndpointLease(endpoint)

    with pytest.raises(DriverAuthorityTransportError, match="lease unavailable"):
        consume_posix_child_endpoint_lease(lease)

    lease.close()
    endpoint.close.assert_called_once_with()


def test_denied_launch_reply_closes_an_unexpected_received_fd(tmp_path):
    """A malicious/buggy denied decision cannot leak an SCM_RIGHTS descriptor."""
    client, server = socket.socketpair()
    payload_path = tmp_path / "received-fd-payload"
    payload_path.write_text("unique")
    sent_fd = os.open(payload_path, os.O_RDONLY)
    sent_identity = os.fstat(sent_fd)

    def handler(sock):
        assert _recv_frame(sock) == {"version": 1, "op": "hello"}
        _send_frame(sock, {"version": 1, "role": "root", "launch_id": "root-1", "capability": None})
        _recv_frame(sock)
        _send_frame(
            sock,
            {"version": 1, "state": "denied", "reason_code": "denied"},
            fd=sent_fd,
        )

    thread, errors = _server_thread(server, handler)
    adapter = DriverAuthorityAdapter(client)
    root = RootProviderAdmission("turn-denied-fd", "puffo-v0.test")
    token = bind_provider_admission(root)
    try:
        decision = adapter.authorize_derived_launch(root, DerivedLaunchCapability.AVATAR)
    finally:
        clear_provider_admission(token)
        adapter.close()
        os.close(sent_fd)
    thread.join(timeout=2)
    leaked = {
        fd
        for fd in range(3, 128)
        if fd != sent_fd
        and _fd_is_open(fd)
        and (stat := os.fstat(fd)).st_dev == sent_identity.st_dev
        and stat.st_ino == sent_identity.st_ino
    }
    for fd in leaked:
        os.close(fd)

    assert errors == []
    assert decision.state is ProviderAdmissionState.INDETERMINATE
    assert leaked == set()


def test_malformed_granted_launch_reply_closes_its_received_fd_once(monkeypatch, tmp_path):
    """A rejected grant frame must not leave its SCM_RIGHTS capability live."""
    client, server = socket.socketpair()
    payload_path = tmp_path / "received-malformed-fd-payload"
    payload_path.write_text("unique")
    sent_fd = os.open(payload_path, os.O_RDONLY)
    sent_identity = os.fstat(sent_fd)
    from lingtai.adapters.acp import driver_authority as authority_module

    close_calls = []
    original_close = authority_module.os.close

    def tracking_close(fd):
        close_calls.append(fd)
        original_close(fd)

    monkeypatch.setattr(authority_module.os, "close", tracking_close)

    def handler(sock):
        assert _recv_frame(sock) == {"version": 1, "op": "hello"}
        _send_frame(sock, {"version": 1, "role": "root", "launch_id": "root-malformed", "capability": None})
        _recv_frame(sock)
        # Missing audit_id makes the frame malformed after its fd has arrived.
        _send_frame(
            sock,
            {"version": 1, "state": "granted", "reason_code": "allowed"},
            fd=sent_fd,
        )

    thread, errors = _server_thread(server, handler)
    adapter = DriverAuthorityAdapter(client)
    root = RootProviderAdmission("turn-malformed-fd", "puffo-v0.test")
    try:
        decision = adapter.authorize_derived_launch(root, DerivedLaunchCapability.AVATAR)
        assert close_calls and len(close_calls) == 1
        assert close_calls[0] != sent_fd
        assert not _fd_is_open(close_calls[0])
    finally:
        adapter.close()
        original_close(sent_fd)
    thread.join(timeout=2)
    leaked = {
        fd
        for fd in range(3, 128)
        if fd != sent_fd
        and _fd_is_open(fd)
        and (stat := os.fstat(fd)).st_dev == sent_identity.st_dev
        and stat.st_ino == sent_identity.st_ino
    }
    for fd in leaked:
        os.close(fd)

    assert errors == []
    assert decision.state is ProviderAdmissionState.INDETERMINATE
    assert leaked == set()


def test_granted_launch_rejects_non_unix_stream_child_endpoint_before_spawn():
    """Only connected AF_UNIX stream endpoints may become child leases."""
    client, server = socket.socketpair()
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_identity = os.fstat(udp.fileno())

    def handler(sock):
        assert _recv_frame(sock) == {"version": 1, "op": "hello"}
        _send_frame(sock, {"version": 1, "role": "root", "launch_id": "root-1", "capability": None})
        _recv_frame(sock)
        _send_frame(
            sock,
            {"version": 1, "state": "granted", "reason_code": "allowed"},
            fd=udp.fileno(),
        )

    thread, errors = _server_thread(server, handler)
    adapter = DriverAuthorityAdapter(client)
    root = RootProviderAdmission("turn-invalid-child-fd", "puffo-v0.test")
    token = bind_provider_admission(root)
    try:
        decision = adapter.authorize_derived_launch(root, DerivedLaunchCapability.AVATAR)
    finally:
        clear_provider_admission(token)
        adapter.close()
        udp.close()
    thread.join(timeout=2)
    leaked = {
        fd
        for fd in range(3, 128)
        if _fd_is_open(fd)
        and (stat := os.fstat(fd)).st_dev == udp_identity.st_dev
        and stat.st_ino == udp_identity.st_ino
    }
    for fd in leaked:
        os.close(fd)

    assert errors == []
    assert decision.state is ProviderAdmissionState.INDETERMINATE
    assert decision.child_endpoint_lease is None
    assert leaked == set()


def test_derived_endpoint_asks_driver_to_audit_and_deny_a_second_child():
    client, server = socket.socketpair()

    def handler(sock):
        sock.settimeout(0.5)
        assert _recv_frame(sock) == {"version": 1, "op": "hello"}
        _send_frame(
            sock,
            {
                "version": 1,
                "role": "derived",
                "launch_id": "child-1",
                "capability": "daemon",
            },
        )
        request = _recv_frame(sock)
        assert {key: request[key] for key in request if key != "call_id"} == {
            "version": 1,
            "op": "authorize_derived_launch",
            "launch_id": "child-1",
            "capability": "daemon",
        }
        assert isinstance(request["call_id"], str) and request["call_id"]
        _send_frame(
            sock,
            {
                "version": 1,
                "state": "denied",
                "reason_code": "nested_derived_launch_denied",
                "audit_id": "audit-nested-1",
            },
        )

    thread, errors = _server_thread(server, handler)
    adapter = DriverAuthorityAdapter(client)
    root = RootProviderAdmission("turn-1", "puffo-v0.full-tool-acp-ingress.v1")
    child = begin_derived_provider_admission(root, ProviderCallClass.DAEMON)
    token = bind_provider_admission(child)
    try:
        with pytest.raises(Exception, match="nested_derived_launch_denied") as raised:
            require_derived_launch_admission(adapter, DerivedLaunchCapability.DAEMON)
    finally:
        clear_provider_admission(token)
    thread.join(timeout=2)
    assert errors == []
    assert raised.value.decision.audit_id == "audit-nested-1"


def test_timeout_invalidates_endpoint_so_a_late_grant_cannot_admit_next_call():
    """A response belongs to its request, never to the next wait on a socket."""

    client, server = socket.socketpair()

    def handler(sock):
        assert _recv_frame(sock) == {"version": 1, "op": "hello"}
        _send_frame(
            sock,
            {"version": 1, "role": "root", "launch_id": "root-timeout", "capability": None},
        )
        first = _recv_frame(sock)
        assert first["op"] == "authorize_provider_call"
        # First wait expires at 20ms; the second is then waiting when this
        # delayed first response arrives at 30ms.
        time.sleep(0.03)
        try:
            _send_frame(
                sock,
                {
                    "version": 1,
                    "state": "granted",
                    "reason_code": "allowed",
                    "audit_id": "audit-late-first",
                },
            )
            # Before the fix, the second request is already queued and this
            # stale grant is consumed as its response.  A fixed client has
            # invalidated the endpoint, so EOF/OSError is expected here.
            _recv_frame(sock)
        except (BrokenPipeError, ConnectionResetError, EOFError, OSError):
            pass

    thread, errors = _server_thread(server, handler)
    adapter = DriverAuthorityAdapter(client, timeout=0.02)
    root = RootProviderAdmission("turn-timeout", "puffo-v0.test")
    first = adapter.authorize_provider_call(root, ProviderCallClass.ROOT)
    second = adapter.authorize_provider_call(root, ProviderCallClass.ROOT)
    adapter.close()
    thread.join(timeout=2)

    assert errors == []
    assert first.state is ProviderAdmissionState.INDETERMINATE
    assert second.state is ProviderAdmissionState.INDETERMINATE
    assert second.audit_id is None


@pytest.mark.parametrize("state", ("granted", "denied"))
def test_driver_decision_without_audit_id_is_indeterminate(state):
    """Every Driver decision must have a stable audit correlation id."""

    client, server = socket.socketpair()

    def handler(sock):
        assert _recv_frame(sock) == {"version": 1, "op": "hello"}
        _send_frame(
            sock,
            {"version": 1, "role": "root", "launch_id": "root-audit", "capability": None},
        )
        request = _recv_frame(sock)
        assert request["op"] == "authorize_provider_call"
        _send_frame(
            sock,
            {"version": 1, "state": state, "reason_code": "test-decision"},
        )

    thread, errors = _server_thread(server, handler)
    adapter = DriverAuthorityAdapter(client)
    root = RootProviderAdmission("turn-audit", "puffo-v0.test")
    decision = adapter.authorize_provider_call(root, ProviderCallClass.ROOT)
    adapter.close()
    thread.join(timeout=2)

    assert errors == []
    assert decision.state is ProviderAdmissionState.INDETERMINATE
    assert decision.reason_code == "derived_admission_port_unconnected"


@pytest.mark.parametrize(
    ("endpoint_capability", "expected_call_class"),
    [
        ("daemon", ProviderCallClass.AVATAR_CHILD),
        ("avatar", ProviderCallClass.DAEMON),
    ],
)
def test_local_child_mode_must_match_the_driver_endpoint_capability(
    endpoint_capability, expected_call_class,
):
    """Composition cannot treat a self-consistent wrong endpoint as authority."""
    client, server = socket.socketpair()

    def handler(sock):
        assert _recv_frame(sock) == {"version": 1, "op": "hello"}
        _send_frame(
            sock,
            {
                "version": 1,
                "role": "derived",
                "launch_id": "child-1",
                "capability": endpoint_capability,
            },
        )

    thread, errors = _server_thread(server, handler)
    adapter = DriverAuthorityAdapter(client)
    with pytest.raises(DriverAuthorityEndpointBindingMismatch):
        adapter.derived_provider_parent(expected_call_class)
    adapter.close()
    thread.join(timeout=2)
    assert errors == []


def test_derived_provider_parent_requires_an_explicit_local_child_mode():
    """A new composition cannot silently skip its endpoint-mode comparison."""
    client, server = socket.socketpair()

    def handler(sock):
        assert _recv_frame(sock) == {"version": 1, "op": "hello"}
        _send_frame(
            sock,
            {
                "version": 1,
                "role": "derived",
                "launch_id": "child-1",
                "capability": "daemon",
            },
        )

    thread, errors = _server_thread(server, handler)
    adapter = DriverAuthorityAdapter(client)
    with pytest.raises(TypeError, match="expected_call_class"):
        adapter.derived_provider_parent()  # type: ignore[call-arg]
    adapter.close()
    thread.join(timeout=2)
    assert errors == []


@pytest.mark.parametrize(
    "call_class", [ProviderCallClass.DAEMON, ProviderCallClass.AVATAR_CHILD]
)
def test_cross_mode_binding_mismatch_rejects_before_inner_provider_io(call_class):
    """Both child compositions use the typed mismatch denial, never generic I/O."""

    class InnerSession:
        interface = object()
        pre_request_hook = None

        def __init__(self):
            self.calls = []

        def send(self, message):
            self.calls.append(message)
            return message

    class InnerService:
        def __init__(self):
            self.session = InnerSession()

        def create_session(self, *_args, **_kwargs):
            return self.session

    adapter = EndpointBindingMismatchAuthorityAdapter()
    inner = InnerService()
    service = ProviderAdmittedLLMService(inner, adapter)
    token = bind_provider_admission(adapter.derived_provider_parent(call_class))
    try:
        with pytest.raises(ProviderAdmissionError, match="endpoint_binding_mismatch"):
            service.create_session("system").send("must-not-reach-provider")
    finally:
        clear_provider_admission(token)
    assert inner.session.calls == []


def test_derived_provider_call_uses_its_own_endpoint_and_driver_known_fields():
    client, server = socket.socketpair()

    def handler(sock):
        assert _recv_frame(sock) == {"version": 1, "op": "hello"}
        _send_frame(
            sock,
            {
                "version": 1,
                "role": "derived",
                "launch_id": "child-1",
                "capability": "daemon",
            },
        )
        request = _recv_frame(sock)
        assert request["version"] == 1
        assert request["op"] == "authorize_provider_call"
        assert request["launch_id"] == "child-1"
        assert request["provider"] == "llm"
        assert request["capability"] == "daemon"
        assert request["call_id"]
        _send_frame(
            sock,
            {
                "version": 1,
                "state": "granted",
                "reason_code": "allowed",
                "audit_id": "audit-provider-1",
                "admission_id": "admission-provider-1",
            },
        )

    thread, errors = _server_thread(server, handler)
    adapter = DriverAuthorityAdapter(client)
    parent = adapter.derived_provider_parent(ProviderCallClass.DAEMON)
    decision = adapter.authorize_provider_call(parent, ProviderCallClass.DAEMON)
    thread.join(timeout=2)

    assert errors == []
    assert decision.state is ProviderAdmissionState.GRANTED
    assert decision.audit_id == "audit-provider-1"
    assert decision.admission_id == "admission-provider-1"


def test_driver_reports_endpoint_binding_mismatch_as_a_distinct_denial():
    """Core preserves the Driver's high-signal binding-mismatch decision."""
    client, server = socket.socketpair()

    def handler(sock):
        assert _recv_frame(sock) == {"version": 1, "op": "hello"}
        _send_frame(
            sock,
            {
                "version": 1,
                "role": "derived",
                "launch_id": "child-1",
                "capability": "avatar",
            },
        )
        request = _recv_frame(sock)
        assert request["op"] == "authorize_provider_call"
        _send_frame(
            sock,
            {
                "version": 1,
                "state": "denied",
                "reason_code": "endpoint_binding_mismatch",
                "audit_id": "audit-binding-mismatch",
            },
        )

    thread, errors = _server_thread(server, handler)
    adapter = DriverAuthorityAdapter(client)
    decision = adapter.authorize_provider_call(
        adapter.derived_provider_parent(ProviderCallClass.AVATAR_CHILD),
        ProviderCallClass.AVATAR_CHILD,
    )
    thread.join(timeout=2)

    assert errors == []
    assert decision.state is ProviderAdmissionState.DENIED
    assert decision.reason_code == "endpoint_binding_mismatch"
    assert decision.audit_id == "audit-binding-mismatch"


@pytest.mark.parametrize(
    "payload",
    [
        b"{not-json",
        b'{"version":1,"state":"granted","reason_code":""}',
    ],
)
def test_malformed_driver_provider_reply_fails_closed_before_provider_io(payload):
    client, server = socket.socketpair()

    def handler(sock):
        assert _recv_frame(sock) == {"version": 1, "op": "hello"}
        _send_frame(sock, {"version": 1, "role": "root", "launch_id": "root-1", "capability": None})
        _recv_frame(sock)
        sock.sendall(struct.pack("!I", len(payload)) + payload)

    thread, errors = _server_thread(server, handler)
    adapter = DriverAuthorityAdapter(client)
    parent = RootProviderAdmission("turn-1", "puffo-v0.full-tool-acp-ingress.v1")
    token = bind_provider_admission(parent)
    try:
        decision = adapter.authorize_provider_call(parent, ProviderCallClass.ROOT)
    finally:
        clear_provider_admission(token)
    thread.join(timeout=2)

    assert errors == []
    assert decision.state is ProviderAdmissionState.INDETERMINATE
    assert decision.reason_code == "derived_admission_port_unconnected"


@pytest.mark.parametrize("failure", ["closed", "truncated", "timeout"])
def test_closed_truncated_or_timed_out_driver_reply_is_structured_indeterminate(failure):
    client, server = socket.socketpair()

    def handler(sock):
        assert _recv_frame(sock) == {"version": 1, "op": "hello"}
        _send_frame(sock, {"version": 1, "role": "root", "launch_id": "root-1", "capability": None})
        _recv_frame(sock)
        if failure == "truncated":
            sock.sendall(struct.pack("!I", 12) + b"{}")
        elif failure == "timeout":
            time.sleep(0.05)

    thread, errors = _server_thread(server, handler)
    adapter = DriverAuthorityAdapter(client, timeout=0.01)
    parent = RootProviderAdmission("turn-1", "puffo-v0.full-tool-acp-ingress.v1")
    decision = adapter.authorize_provider_call(parent, ProviderCallClass.ROOT)
    thread.join(timeout=2)

    assert errors == []
    assert decision.state is ProviderAdmissionState.INDETERMINATE
    assert decision.reason_code == "derived_admission_port_unconnected"


def test_timeout_invalidates_endpoint_so_a_late_grant_cannot_admit_next_call():
    """A response belongs to its request, never to the next socket wait."""

    client, server = socket.socketpair()

    def handler(sock):
        assert _recv_frame(sock) == {"version": 1, "op": "hello"}
        _send_frame(
            sock,
            {"version": 1, "role": "root", "launch_id": "root-timeout", "capability": None},
        )
        first = _recv_frame(sock)
        assert first["op"] == "authorize_provider_call"
        # The first wait expires at 20ms; this late response must not be
        # consumed as a decision for the subsequent request.
        time.sleep(0.03)
        try:
            _send_frame(
                sock,
                {
                    "version": 1,
                    "state": "granted",
                    "reason_code": "allowed",
                    "audit_id": "audit-late-first",
                },
            )
            _recv_frame(sock)
        except (BrokenPipeError, ConnectionResetError, EOFError, OSError):
            pass

    thread, errors = _server_thread(server, handler)
    adapter = DriverAuthorityAdapter(client, timeout=0.02)
    root = RootProviderAdmission("turn-timeout", "puffo-v0.test")
    first = adapter.authorize_provider_call(root, ProviderCallClass.ROOT)
    second = adapter.authorize_provider_call(root, ProviderCallClass.ROOT)
    adapter.close()
    thread.join(timeout=2)

    assert errors == []
    assert first.state is ProviderAdmissionState.INDETERMINATE
    assert second.state is ProviderAdmissionState.INDETERMINATE
    assert second.audit_id is None


def test_mismatched_derived_response_id_closes_a_foreign_child_endpoint():
    """A valid endpoint from another request cannot become this child's lease."""

    client, server = socket.socketpair()
    foreign_client, foreign_driver = socket.socketpair()

    def handler(sock):
        assert _recv_frame(sock) == {"version": 1, "op": "hello"}
        _send_frame(
            sock,
            {"version": 1, "role": "root", "launch_id": "root-mismatch", "capability": None},
        )
        request = _recv_frame(sock)
        assert request["op"] == "authorize_derived_launch"
        _send_frame(
            sock,
            {
                "version": 1,
                "state": "granted",
                "reason_code": "allowed",
                "audit_id": "audit-foreign",
                "call_id": "different-request",
            },
            fd=foreign_client.fileno(),
        )
        foreign_client.close()

    thread, errors = _server_thread(server, handler)
    adapter = DriverAuthorityAdapter(client)
    root = RootProviderAdmission("turn-mismatch", "puffo-v0.test")
    decision = adapter.authorize_derived_launch(root, DerivedLaunchCapability.DAEMON)
    adapter.close()
    thread.join(timeout=2)
    foreign_driver.settimeout(1)
    try:
        assert foreign_driver.recv(1) == b""
    finally:
        foreign_driver.close()

    assert errors == []
    assert decision.state is ProviderAdmissionState.INDETERMINATE
    assert decision.audit_id is None


def test_invalid_fd_locator_never_falls_back_to_a_legacy_adapter(monkeypatch):
    monkeypatch.setenv("LINGTAI_DRIVER_AUTHORITY_FD", "not-an-fd")
    assert isinstance(authority_adapter_from_environment(), UnavailableDriverAuthorityAdapter)


@pytest.mark.parametrize(
    "response",
    [
        {"version": 2, "role": "root", "launch_id": "root-1", "capability": None},
        {"version": 1, "role": "root", "launch_id": "", "capability": None},
    ],
)
def test_bad_driver_handshake_is_not_an_adapter(response):
    client, server = socket.socketpair()

    def handler(sock):
        _recv_frame(sock)
        _send_frame(sock, response)

    thread, errors = _server_thread(server, handler)
    with pytest.raises(DriverAuthorityTransportError):
        DriverAuthorityAdapter(client)
    thread.join(timeout=2)
    assert errors == []
