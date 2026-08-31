"""D6 executor-boundary probe (Boris, first review seat).

The delivered acceptance oracle exercises admission -> provider I/O only on
the synchronous same-thread path.  This probe stacks LingTai's real
``_GatedSession`` between the admission proxy and the recording provider, so
the actual provider call runs in ``APICallGate``'s thread pool.  That is the
boundary the archived D6 scope explicitly recorded as NOT exercised.

Modes:
  baseline  -- real APICallGate; the audit trace must survive the pool hop.
  nocontext -- _execute reverted to pre-fix ``item.fn()``; MUST go red, which
               is what proves this probe actually measures the propagation
               rather than passing for unrelated reasons.

Before running, create the supported isolated interpreter with
``scripts/setup_driver_supervisor_e2e_env.sh <venv-dir>``. Invoke this probe
through ``<venv-dir>/bin/python`` with both ``--lingtai-src`` and
``--puffo-src``; the latter is source-only and must not be installed into the
probe environment.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import threading


def load(lingtai_src: Path, puffo_src: Path):
    sys.path[:0] = [str(puffo_src.resolve(strict=True)), str(lingtai_src.resolve(strict=True))]
    from lingtai.adapters.acp.driver_authority import DriverAuthorityAdapter
    from lingtai.kernel.provider_admission import (
        ProviderAdmittedChatSession,
        RootProviderAdmission,
        bind_provider_admission,
        clear_provider_admission,
        current_provider_call_audit_id,
    )
    from lingtai.llm.api_gate import APICallGate
    from lingtai.llm.base import _GatedSession
    from puffo_agent.agent.harness.driver_authority_server import DriverAuthorityServer
    return (
        DriverAuthorityAdapter, ProviderAdmittedChatSession, RootProviderAdmission,
        bind_provider_admission, clear_provider_admission,
        current_provider_call_audit_id, APICallGate, _GatedSession,
        DriverAuthorityServer,
    )


def main(mode: str, lingtai_src: Path, puffo_src: Path) -> None:
    (Adapter, AdmittedSession, RootAdmission, bind, clear,
     current_audit_id, APICallGate, GatedSession, Server) = load(lingtai_src, puffo_src)

    if mode == "nocontext":
        # Revert exactly the shipped fix: run the work item without the
        # submitter's captured context.
        def _execute(item):
            try:
                item.future.set_result(item.fn())
            except BaseException as exc:  # noqa: BLE001
                item.future.set_exception(exc)
        APICallGate._execute = staticmethod(_execute)

    main_thread = threading.get_ident()

    class RecordingSession:
        """Stands in for a provider adapter session; records at real I/O."""
        interface = "probe"
        pre_request_hook = None

        def __init__(self):
            self.seen_audit_ids: list[str | None] = []
            self.seen_threads: list[int] = []

        def send(self, message):
            self.seen_audit_ids.append(current_audit_id())
            self.seen_threads.append(threading.get_ident())
            return "generated"

    server = Server()
    adapter = None
    gate = None
    try:
        endpoint = server.issue_root(launch_id=f"root-d6exec-{mode}")
        inherited = os.dup(endpoint.fileno())
        endpoint.close()
        adapter = Adapter.from_inherited_fd(inherited)

        inner = RecordingSession()
        gate = APICallGate(max_rpm=60, pool_size=2)
        session = AdmittedSession(GatedSession(inner, gate), adapter)

        token = bind(RootAdmission("turn-d6exec", "puffo-v0.e2e"))
        try:
            session.send("legal-operation")
        finally:
            clear(token)

        records = [r for r in server.audit_records()
                   if r.operation == "authorize_provider_call"]
        adjudications = [r.audit_id for r in records]

        crossed = [t for t in inner.seen_threads if t != main_thread]
        print(f"mode={mode}")
        print(f"adjudications={len(adjudications)} ids={adjudications}")
        print(f"provider_calls={len(inner.seen_audit_ids)} ids={inner.seen_audit_ids}")
        print(f"crossed_thread={bool(crossed)} (main={main_thread} io={inner.seen_threads})")
        print(f"trace_after_call={current_audit_id()!r}")

        # The probe is only meaningful if the provider call really left the
        # submitting thread.  Assert the hop before asserting propagation.
        assert inner.seen_threads and crossed, "provider I/O did not cross threads"
        assert len(adjudications) == 1
        audit_id = adjudications[0]
        assert isinstance(audit_id, str)
        assert inner.seen_audit_ids == [audit_id], "audit trace lost across the pool hop"
        assert current_audit_id() is None
    finally:
        if gate is not None:
            gate.shutdown()
        if adapter is not None:
            adapter.close()
        server.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--lingtai-src", required=True, type=Path)
    p.add_argument("--puffo-src", required=True, type=Path)
    p.add_argument("mode", choices=("baseline", "nocontext"))
    a = p.parse_args()
    main(a.mode, a.lingtai_src, a.puffo_src)
