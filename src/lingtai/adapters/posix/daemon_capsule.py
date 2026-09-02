"""Bounded one-shot daemon capsule transport with optional fd adoption."""
from __future__ import annotations

import array
import json
import os
import socket
from dataclasses import dataclass


CAPSULE_FD_ENV = "LINGTAI_DAEMON_CAPSULE_FD"
MAX_CAPSULE_BYTES = 4 * 1024 * 1024


def close_fd(fd: int | None) -> None:
    if fd is None:
        return
    try:
        os.close(fd)
    except OSError:
        pass


@dataclass(slots=True)
class ReceivedDaemonCapsule:
    """One in-memory capsule plus ownership of at most one received fd."""

    value: dict
    adopted_fd: int | None = None

    def take_fd(self) -> int | None:
        adopted_fd = self.adopted_fd
        self.adopted_fd = None
        return adopted_fd

    def close(self) -> None:
        close_fd(self.adopted_fd)
        self.adopted_fd = None


def encode_capsule(capsule: dict | None) -> bytes:
    payload = json.dumps(
        capsule or {}, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    if len(payload) > MAX_CAPSULE_BYTES:
        raise ValueError(f"daemon runtime capsule exceeds {MAX_CAPSULE_BYTES} bytes")
    return payload


def send_capsule(
    sock: socket.socket,
    payload: bytes,
    *,
    adopted_fd: int | None = None,
) -> None:
    """Send one capsule and optionally duplicate one fd into the receiver."""
    ancillary = []
    if adopted_fd is not None:
        ancillary = [
            (
                socket.SOL_SOCKET,
                socket.SCM_RIGHTS,
                array.array("i", [adopted_fd]),
            )
        ]
    sent = sock.sendmsg([payload], ancillary)
    if sent < len(payload):
        sock.sendall(payload[sent:])
    sock.shutdown(socket.SHUT_WR)


def receive_capsule(sock: socket.socket) -> ReceivedDaemonCapsule:
    """Receive a bounded capsule and adopt at most one SCM_RIGHTS descriptor."""
    chunks: list[bytes] = []
    received_fds: list[int] = []
    total = 0
    item_size = array.array("i").itemsize
    try:
        while True:
            chunk, ancillary, flags, _address = sock.recvmsg(
                65536,
                socket.CMSG_SPACE(item_size * 4),
            )
            for level, kind, data in ancillary:
                if level != socket.SOL_SOCKET or kind != socket.SCM_RIGHTS:
                    continue
                usable = len(data) - (len(data) % item_size)
                values = array.array("i")
                values.frombytes(data[:usable])
                received_fds.extend(values)
            if flags & socket.MSG_CTRUNC:
                raise ValueError("daemon runtime capsule descriptor data was truncated")
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_CAPSULE_BYTES:
                raise ValueError("daemon runtime capsule exceeds size limit")
            chunks.append(chunk)
        if len(received_fds) > 1:
            raise ValueError("daemon runtime capsule carried multiple descriptors")
        for received_fd in received_fds:
            os.set_inheritable(received_fd, False)
        value = json.loads(b"".join(chunks).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("daemon capsule must be an object")
        adopted_fd = received_fds.pop() if received_fds else None
        return ReceivedDaemonCapsule(value=value, adopted_fd=adopted_fd)
    except Exception:
        for received_fd in received_fds:
            close_fd(received_fd)
        raise


def receive_capsule_from_environment() -> ReceivedDaemonCapsule | None:
    """Consume the inherited capsule socket locator from the environment."""
    raw_fd = os.environ.pop(CAPSULE_FD_ENV, None)
    if raw_fd is None:
        return None
    capsule_fd: int | None = None
    try:
        capsule_fd = int(raw_fd)
        try:
            capsule_socket = socket.socket(fileno=capsule_fd)
        except OSError:
            chunks: list[bytes] = []
            total = 0
            try:
                while True:
                    chunk = os.read(capsule_fd, 65536)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_CAPSULE_BYTES:
                        raise ValueError("daemon runtime capsule exceeds size limit")
                    chunks.append(chunk)
            finally:
                close_fd(capsule_fd)
                capsule_fd = None
            value = json.loads(b"".join(chunks).decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("daemon capsule must be an object")
            return ReceivedDaemonCapsule(value=value)
        capsule_fd = None
        with capsule_socket:
            return receive_capsule(capsule_socket)
    except Exception:
        close_fd(capsule_fd)
        raise


__all__ = [
    "CAPSULE_FD_ENV",
    "MAX_CAPSULE_BYTES",
    "ReceivedDaemonCapsule",
    "close_fd",
    "encode_capsule",
    "receive_capsule",
    "receive_capsule_from_environment",
    "send_capsule",
]
