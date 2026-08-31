"""POSIX socket transport for the Puffo Driver admission authority.

The Kernel only sees the two typed admission Ports.  This adapter owns the
versioned socket protocol, inherited-fd handling, bounded framing, and the
opaque one-shot child endpoint handoff.  Descriptor numbers and response ids
are locators/audit material, never credentials: authority is the connected
endpoint whose peer is the Driver.
"""
from __future__ import annotations

import array
import json
import os
import socket
import struct
import threading
import uuid
from dataclasses import dataclass
from typing import Any

from lingtai.kernel.provider_admission import (
    DerivedLaunchCapability,
    DerivedLaunchDecision,
    DerivedProviderAdmission,
    ProviderAdmissionParent,
    ProviderAdmissionState,
    ProviderCallAdmissionPort,
    ProviderCallClass,
    ProviderCallDecision,
    RootProviderAdmission,
    begin_derived_provider_admission,
)


DRIVER_AUTHORITY_FD_ENV = "LINGTAI_DRIVER_AUTHORITY_FD"
_PROTOCOL_VERSION = 1
_MAX_FRAME_BYTES = 64 * 1024
_DEFAULT_TIMEOUT_SECONDS = 2.0


class DriverAuthorityTransportError(RuntimeError):
    """A bounded wire/descriptor failure translated to INDETERMINATE."""


class DriverAuthorityEndpointBindingMismatch(DriverAuthorityTransportError):
    """The locally expected child mode disagrees with the Driver endpoint."""


@dataclass(frozen=True, slots=True)
class _EndpointIdentity:
    role: str
    launch_id: str
    capability: str | None


class DriverChildEndpointLease:
    """Adapter-private, one-use ownership of a Driver-created child endpoint.

    Core may carry this object opaquely inside a ``DerivedLaunchDecision`` but
    cannot read its descriptor or reconstruct it from a string.  Only the
    POSIX launch adapters consume it to produce a narrowly allowlisted
    ``pass_fds`` handoff for the immediate child process.
    """

    __slots__ = ("_socket", "_consumed")

    def __init__(self, endpoint: socket.socket) -> None:
        self._socket = endpoint
        self._consumed = False

    def _take_for_posix_spawn(self) -> int:
        if self._consumed:
            raise DriverAuthorityTransportError("child endpoint lease already consumed")
        self._consumed = True
        try:
            return self._socket.detach()
        except OSError as exc:
            raise DriverAuthorityTransportError("child endpoint lease unavailable") from exc

    def close(self) -> None:
        if self._consumed:
            return
        self._consumed = True
        try:
            self._socket.close()
        except OSError:
            pass

    def __del__(self) -> None:
        """Do not retain a descriptor if preparation aborts before spawn."""

        self.close()


def consume_posix_child_endpoint_lease(lease: object) -> int:
    """Consume one adapter lease immediately before a POSIX child spawn.

    This is intentionally adapter-owned.  Core callers pass the opaque object
    through their technology-neutral launch Port and never receive the fd.
    """

    if not isinstance(lease, DriverChildEndpointLease):
        raise DriverAuthorityTransportError("derived launch lease is not Driver-owned")
    return lease._take_for_posix_spawn()


def close_child_endpoint_lease(lease: object | None) -> None:
    """Best-effort close for a grant whose spawn did not consume it."""

    if isinstance(lease, DriverChildEndpointLease):
        lease.close()


class DriverAuthorityAdapter(ProviderCallAdmissionPort):
    """Driver-backed implementation of both provider and derived-launch Ports.

    The constructor performs the v1 handshake while still at the outer
    composition boundary.  A failed handshake is represented by
    :class:`UnavailableDriverAuthorityAdapter`, so Kernel consumers retain
    their structured fail-closed reasons instead of seeing socket exceptions.
    """

    __slots__ = ("_socket", "_identity", "_lock", "_timeout", "_buffer")

    def __init__(self, endpoint: socket.socket, *, timeout: float = _DEFAULT_TIMEOUT_SECONDS):
        if (
            endpoint.family != socket.AF_UNIX
            or (endpoint.type & socket.SOCK_STREAM) != socket.SOCK_STREAM
        ):
            endpoint.close()
            raise DriverAuthorityTransportError("authority endpoint must be an AF_UNIX stream socket")
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
            endpoint.close()
            raise DriverAuthorityTransportError("authority timeout must be positive")
        self._socket = endpoint
        self._timeout = float(timeout)
        self._lock = threading.Lock()
        self._buffer = bytearray()
        try:
            os.set_inheritable(endpoint.fileno(), False)
            endpoint.settimeout(self._timeout)
            response, received_fd = self._exchange_locked({"op": "hello"}, expect_fd=False)
            if received_fd is not None:
                os.close(received_fd)
                raise DriverAuthorityTransportError("hello must not receive a child endpoint")
            self._identity = self._parse_hello(response)
        except Exception:
            try:
                endpoint.close()
            except OSError:
                pass
            raise

    @classmethod
    def from_inherited_fd(cls, fd: int, *, timeout: float = _DEFAULT_TIMEOUT_SECONDS) -> "DriverAuthorityAdapter":
        """Adopt a Driver-passed fd and immediately mark it close-on-exec."""

        if not isinstance(fd, int) or isinstance(fd, bool) or fd < 0:
            raise DriverAuthorityTransportError("authority fd is invalid")
        try:
            endpoint = socket.socket(fileno=fd)
        except OSError as exc:
            raise DriverAuthorityTransportError("authority fd is unavailable") from exc
        return cls(endpoint, timeout=timeout)

    @property
    def endpoint_role(self) -> str:
        return self._identity.role

    @property
    def launch_id(self) -> str:
        return self._identity.launch_id

    def derived_provider_parent(
        self, expected_call_class: ProviderCallClass | None = None
    ) -> DerivedProviderAdmission:
        """Return the local Core context for this Driver-bound child endpoint.

        The resulting object is not a grant: each provider call still crosses
        this adapter and the Driver validates the endpoint's server-side role.
        It simply lets the protocol-neutral Core identify the call as a derived
        daemon/avatar request without serializing lineage into child state.
        """

        if self._identity.role != "derived" or self._identity.capability is None:
            raise DriverAuthorityTransportError("root endpoint cannot become a derived parent")
        capability = DerivedLaunchCapability(self._identity.capability)
        call_class = (
            ProviderCallClass.DAEMON
            if capability is DerivedLaunchCapability.DAEMON
            else ProviderCallClass.AVATAR_CHILD
        )
        if expected_call_class is not None and call_class is not expected_call_class:
            raise DriverAuthorityEndpointBindingMismatch(
                "authority endpoint capability does not match local child mode"
            )
        root = RootProviderAdmission(
            correlation_id=f"driver-launch:{self._identity.launch_id}",
            policy_version="driver-authority.v1",
        )
        return begin_derived_provider_admission(root, call_class)

    def authorize_provider_call(
        self,
        parent: ProviderAdmissionParent,
        call_class: ProviderCallClass,
    ) -> ProviderCallDecision:
        if not isinstance(call_class, ProviderCallClass):
            return ProviderCallDecision(ProviderAdmissionState.INDETERMINATE, "derived_admission_port_unconnected")
        if self._identity.role == "root":
            if not isinstance(parent, RootProviderAdmission) or call_class is not ProviderCallClass.ROOT:
                return ProviderCallDecision(ProviderAdmissionState.DENIED, "provider_parent_endpoint_mismatch")
        elif self._identity.role == "derived":
            if not isinstance(parent, DerivedProviderAdmission) or parent.call_class is not call_class:
                return ProviderCallDecision(ProviderAdmissionState.DENIED, "provider_parent_endpoint_mismatch")
        else:
            return ProviderCallDecision(ProviderAdmissionState.INDETERMINATE, "derived_admission_port_unconnected")
        try:
            response, received_fd = self._exchange(
                {
                    "op": "authorize_provider_call",
                    "call_id": str(uuid.uuid4()),
                    "launch_id": self._identity.launch_id,
                    "provider": "llm",
                    "capability": call_class.value,
                },
                expect_fd=False,
            )
            if received_fd is not None:
                os.close(received_fd)
                raise DriverAuthorityTransportError("provider decision must not return an fd")
            return self._provider_decision(response)
        except DriverAuthorityTransportError:
            return ProviderCallDecision(
                ProviderAdmissionState.INDETERMINATE,
                "derived_admission_port_unconnected",
            )

    def authorize_derived_launch(
        self,
        parent: RootProviderAdmission,
        capability: DerivedLaunchCapability,
    ) -> DerivedLaunchDecision:
        if not isinstance(parent, RootProviderAdmission) or self._identity.role != "root":
            return DerivedLaunchDecision(
                ProviderAdmissionState.DENIED,
                "nested_derived_launch_denied",
            )
        if not isinstance(capability, DerivedLaunchCapability):
            return DerivedLaunchDecision(
                ProviderAdmissionState.INDETERMINATE,
                "derived_launch_admission_port_unconnected",
            )
        try:
            response, received_fd = self._exchange(
                {
                    "op": "authorize_derived_launch",
                    "launch_id": self._identity.launch_id,
                    "capability": capability.value,
                },
                expect_fd=None,
            )
            decision = self._derived_decision(response, received_fd)
            return decision
        except DriverAuthorityTransportError:
            return DerivedLaunchDecision(
                ProviderAdmissionState.INDETERMINATE,
                "derived_launch_admission_port_unconnected",
            )

    def close(self) -> None:
        try:
            self._socket.close()
        except OSError:
            pass

    def _exchange(
        self, request: dict[str, Any], *, expect_fd: bool | None
    ) -> tuple[dict[str, Any], int | None]:
        with self._lock:
            return self._exchange_locked(request, expect_fd=expect_fd)

    def _exchange_locked(
        self, request: dict[str, Any], *, expect_fd: bool | None
    ) -> tuple[dict[str, Any], int | None]:
        payload = {"version": _PROTOCOL_VERSION, **request}
        self._send_frame(payload)
        response, received_fd = self._recv_frame()
        if expect_fd is not None and expect_fd != (received_fd is not None):
            if received_fd is not None:
                os.close(received_fd)
            raise DriverAuthorityTransportError("authority response carried an unexpected endpoint")
        return response, received_fd

    def _send_frame(self, payload: dict[str, Any]) -> None:
        try:
            encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise DriverAuthorityTransportError("authority request is not encodable") from exc
        if len(encoded) > _MAX_FRAME_BYTES:
            raise DriverAuthorityTransportError("authority request exceeds frame bound")
        try:
            self._socket.sendall(struct.pack("!I", len(encoded)) + encoded)
        except (OSError, TimeoutError) as exc:
            raise DriverAuthorityTransportError("authority request transport failed") from exc

    def _recv_frame(self) -> tuple[dict[str, Any], int | None]:
        received_fds: list[int] = []

        def read_exact(count: int) -> bytes:
            while len(self._buffer) < count:
                try:
                    data, ancdata, flags, _ = self._socket.recvmsg(
                        _MAX_FRAME_BYTES + 4,
                        socket.CMSG_SPACE(array.array("i", [0]).itemsize),
                    )
                except (OSError, TimeoutError) as exc:
                    raise DriverAuthorityTransportError("authority response transport failed") from exc
                if not data:
                    raise DriverAuthorityTransportError("authority peer closed")
                for level, kind, raw in ancdata:
                    if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                        items = array.array("i")
                        usable = len(raw) - (len(raw) % items.itemsize)
                        items.frombytes(raw[:usable])
                        received_fds.extend(items.tolist())
                if flags & socket.MSG_CTRUNC:
                    # Linux may install a descriptor even when its ancillary
                    # payload is truncated. Collect it first so the outer
                    # fail-closed cleanup cannot leak it into this process.
                    raise DriverAuthorityTransportError("authority ancillary data was truncated")
                self._buffer.extend(data)
            value = bytes(self._buffer[:count])
            del self._buffer[:count]
            return value

        try:
            frame_size = struct.unpack("!I", read_exact(4))[0]
            if frame_size <= 0 or frame_size > _MAX_FRAME_BYTES:
                raise DriverAuthorityTransportError("authority response frame is out of bounds")
            raw = read_exact(frame_size)
            value = json.loads(raw.decode("utf-8"))
            if not isinstance(value, dict):
                raise DriverAuthorityTransportError("authority response must be an object")
            if len(received_fds) > 1:
                raise DriverAuthorityTransportError("authority response carried too many endpoints")
            return value, received_fds[0] if received_fds else None
        except (UnicodeDecodeError, json.JSONDecodeError, struct.error) as exc:
            for fd in received_fds:
                try:
                    os.close(fd)
                except OSError:
                    pass
            raise DriverAuthorityTransportError("authority response is malformed") from exc
        except Exception:
            for fd in received_fds:
                try:
                    os.close(fd)
                except OSError:
                    pass
            raise

    @staticmethod
    def _nonempty_string(value: object, field: str) -> str:
        if not isinstance(value, str) or not value:
            raise DriverAuthorityTransportError(f"authority response {field} is invalid")
        return value

    def _parse_hello(self, response: dict[str, Any]) -> _EndpointIdentity:
        if response.get("version") != _PROTOCOL_VERSION:
            raise DriverAuthorityTransportError("authority protocol version mismatch")
        role = self._nonempty_string(response.get("role"), "role")
        if role not in {"root", "derived"}:
            raise DriverAuthorityTransportError("authority role is invalid")
        launch_id = self._nonempty_string(response.get("launch_id"), "launch_id")
        capability = response.get("capability")
        if role == "derived":
            capability = self._nonempty_string(capability, "capability")
            if capability not in {item.value for item in DerivedLaunchCapability}:
                raise DriverAuthorityTransportError("derived endpoint capability is invalid")
        elif capability is not None:
            raise DriverAuthorityTransportError("root endpoint must not declare capability")
        return _EndpointIdentity(role=role, launch_id=launch_id, capability=capability)

    def _state(self, response: dict[str, Any]) -> tuple[ProviderAdmissionState, str, str | None, str | None]:
        if response.get("version") != _PROTOCOL_VERSION:
            raise DriverAuthorityTransportError("authority protocol version mismatch")
        try:
            state = ProviderAdmissionState(response.get("state"))
        except (TypeError, ValueError) as exc:
            raise DriverAuthorityTransportError("authority decision state is invalid") from exc
        reason = self._nonempty_string(response.get("reason_code"), "reason_code")
        audit_id = response.get("audit_id")
        admission_id = response.get("admission_id")
        for value, field in ((audit_id, "audit_id"), (admission_id, "admission_id")):
            if value is not None and (not isinstance(value, str) or not value):
                raise DriverAuthorityTransportError(f"authority response {field} is invalid")
        return state, reason, audit_id, admission_id

    def _provider_decision(self, response: dict[str, Any]) -> ProviderCallDecision:
        state, reason, audit_id, admission_id = self._state(response)
        return ProviderCallDecision(state, reason, audit_id=audit_id, admission_id=admission_id)

    def _derived_decision(
        self, response: dict[str, Any], received_fd: int | None
    ) -> DerivedLaunchDecision:
        """Translate one response while owning ``received_fd`` on every path."""
        try:
            state, reason, audit_id, admission_id = self._state(response)
        except Exception:
            if received_fd is not None:
                try:
                    os.close(received_fd)
                except OSError:
                    pass
            raise
        if state is ProviderAdmissionState.GRANTED:
            if received_fd is None:
                raise DriverAuthorityTransportError("granted launch omitted child endpoint")
            endpoint: socket.socket | None = None
            try:
                endpoint = socket.socket(fileno=received_fd)
                if (
                    endpoint.family != socket.AF_UNIX
                    or (endpoint.type & socket.SOCK_STREAM) != socket.SOCK_STREAM
                ):
                    raise DriverAuthorityTransportError(
                        "granted child endpoint must be an AF_UNIX stream socket"
                    )
                # A stream socket's type alone is insufficient: an unconnected
                # local socket cannot be the Driver-held peer endpoint.
                endpoint.getpeername()
                os.set_inheritable(endpoint.fileno(), False)
            except (OSError, DriverAuthorityTransportError) as exc:
                try:
                    if endpoint is not None:
                        endpoint.close()
                    else:
                        os.close(received_fd)
                except OSError:
                    pass
                raise DriverAuthorityTransportError("granted child endpoint is invalid") from exc
            return DerivedLaunchDecision(
                state,
                reason,
                audit_id=audit_id,
                admission_id=admission_id,
                child_endpoint_lease=DriverChildEndpointLease(endpoint),
            )
        if received_fd is not None:
            # A policy decision stays authoritative despite this framing
            # violation: release the resource without erasing reason/audit.
            try:
                os.close(received_fd)
            except OSError:
                pass
        return DerivedLaunchDecision(state, reason, audit_id=audit_id, admission_id=admission_id)


class UnavailableDriverAuthorityAdapter(ProviderCallAdmissionPort):
    """Constrained composition placeholder that reports transport absence."""

    __slots__ = ()

    def derived_provider_parent(
        self, call_class: ProviderCallClass
    ) -> DerivedProviderAdmission:
        """Give Core a derived-shaped context that still fails at this Port."""

        return begin_derived_provider_admission(
            RootProviderAdmission(
                correlation_id="driver-authority-unavailable",
                policy_version="driver-authority.v1",
            ),
            call_class,
        )

    def authorize_provider_call(
        self,
        _parent: ProviderAdmissionParent,
        _call_class: ProviderCallClass,
    ) -> ProviderCallDecision:
        return ProviderCallDecision(
            ProviderAdmissionState.INDETERMINATE,
            "derived_admission_port_unconnected",
        )

    def authorize_derived_launch(
        self,
        _parent: RootProviderAdmission,
        _capability: DerivedLaunchCapability,
    ) -> DerivedLaunchDecision:
        return DerivedLaunchDecision(
            ProviderAdmissionState.INDETERMINATE,
            "derived_launch_admission_port_unconnected",
        )


class EndpointBindingMismatchAuthorityAdapter(ProviderCallAdmissionPort):
    """Fail closed after local child composition finds a wrong endpoint mode."""

    __slots__ = ()

    def derived_provider_parent(
        self, call_class: ProviderCallClass
    ) -> DerivedProviderAdmission:
        return begin_derived_provider_admission(
            RootProviderAdmission(
                correlation_id="driver-endpoint-binding-mismatch",
                policy_version="driver-authority.v1",
            ),
            call_class,
        )

    def authorize_provider_call(
        self,
        _parent: ProviderAdmissionParent,
        _call_class: ProviderCallClass,
    ) -> ProviderCallDecision:
        return ProviderCallDecision(
            ProviderAdmissionState.DENIED, "endpoint_binding_mismatch"
        )

    def authorize_derived_launch(
        self,
        _parent: RootProviderAdmission,
        _capability: DerivedLaunchCapability,
    ) -> DerivedLaunchDecision:
        return DerivedLaunchDecision(
            ProviderAdmissionState.DENIED, "endpoint_binding_mismatch"
        )


def authority_adapter_from_environment(
    *,
    missing_returns_none: bool = False,
    timeout: float = _DEFAULT_TIMEOUT_SECONDS,
) -> DriverAuthorityAdapter | UnavailableDriverAuthorityAdapter | None:
    """Build the adapter from the Driver's inherited-fd locator.

    A missing locator may be represented as ``None`` for a persisted derived
    child, preserving its precise ``required_*_port_missing`` reason.  Any
    present but invalid/unusable descriptor returns an unconnected adapter so
    it cannot degrade to a legacy allow path.
    """

    raw_fd = os.environ.pop(DRIVER_AUTHORITY_FD_ENV, None)
    if raw_fd is None:
        return None if missing_returns_none else UnavailableDriverAuthorityAdapter()
    try:
        fd = int(raw_fd)
    except (TypeError, ValueError):
        return UnavailableDriverAuthorityAdapter()
    try:
        return DriverAuthorityAdapter.from_inherited_fd(fd, timeout=timeout)
    except DriverAuthorityTransportError:
        return UnavailableDriverAuthorityAdapter()


__all__ = [
    "DRIVER_AUTHORITY_FD_ENV",
    "DriverAuthorityAdapter",
    "DriverAuthorityEndpointBindingMismatch",
    "DriverAuthorityTransportError",
    "DriverChildEndpointLease",
    "UnavailableDriverAuthorityAdapter",
    "EndpointBindingMismatchAuthorityAdapter",
    "authority_adapter_from_environment",
    "close_child_endpoint_lease",
    "consume_posix_child_endpoint_lease",
]
