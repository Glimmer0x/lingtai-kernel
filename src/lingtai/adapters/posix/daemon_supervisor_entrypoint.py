"""Ordinary importable/executable entrypoint for the detached daemon supervisor.

``PosixDaemonSupervisorAdapter.spawn_detached`` launches
``<python_executable> -m lingtai.adapters.posix.daemon_supervisor_entrypoint
<encoded-request>``, where ``<encoded-request>`` is the compact deterministic
JSON payload produced by
``lingtai.kernel.daemon_supervisor.encode_request``. This module is the only
thing on argv; it decodes the request and hands off to the Core-owned
``run_supervisor`` for the actual run-manifest read, emanation execution,
terminal-state commit, and notification publish.

This module is process/transport mechanism, not technology-neutral Core
logic, so it lives beside ``PosixDaemonSupervisorAdapter`` under
``adapters/posix`` rather than in the kernel — it is only ever invoked as a
subprocess entrypoint via ``python -m``. It performs no policy of its own.
"""
from __future__ import annotations

import sys

from lingtai.adapters.posix.daemon_capsule import (
    ReceivedDaemonCapsule,
    receive_capsule_from_environment,
)
from lingtai.kernel.daemon_supervisor import decode_request
from lingtai.tools.daemon.supervisor_runtime import run_supervisor


def _read_capsule_wire() -> ReceivedDaemonCapsule | None:
    """Consume the inherited one-shot capsule socket and optional descriptor."""
    try:
        return receive_capsule_from_environment()
    except (OSError, ValueError, TypeError, UnicodeDecodeError):
        return None


def _read_capsule() -> dict | None:
    """Compatibility seam for tests that need only the JSON capsule."""
    wire = _read_capsule_wire()
    if wire is None:
        return None
    try:
        return wire.value
    finally:
        wire.close()


def main(argv: list[str]) -> int:
    """Decode the single encoded-request argument and run the supervisor.

    Expects exactly one argument: the ``encode_request`` payload. Fails
    loudly (propagates ``decode_request``'s ``ValueError``) on a malformed
    payload rather than silently doing nothing, so a transport defect is
    immediately visible instead of a supervisor process that spawned but
    never actually supervised anything.
    """
    if len(argv) != 1:
        raise SystemExit(
            "usage: python -m lingtai.adapters.posix.daemon_supervisor_entrypoint "
            "<encoded-request>"
        )
    request = decode_request(argv[0])
    wire = _read_capsule_wire()
    if wire is None:
        run_supervisor(request)
    else:
        adopted_fd = wire.take_fd()
        try:
            if adopted_fd is None:
                run_supervisor(request, capsule=wire.value)
            else:
                run_supervisor(
                    request,
                    capsule=wire.value,
                    adopted_fd=adopted_fd,
                )
        finally:
            wire.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))


__all__ = ["main"]
