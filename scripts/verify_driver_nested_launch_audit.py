"""Cross-repository D1 probe for Driver-audited nested launch denial.

This is deliberately a cross-repository acceptance script: the Driver audit
IDs must be issued by Puffo's real authority server, rather than by a LingTai
test double.  It exercises a legal root-to-one-hop daemon launch, one child
provider call, then nested daemon and avatar launch requests.  The latter two
must reach Driver, be denied with distinct non-empty audit IDs, and leave the
provider recorder unchanged.

It verifies the admission seam itself.  LingTai's daemon/avatar production
dispatch regressions live in the normal test suite and use the same typed seam.

Before running, create the supported isolated interpreter with
``scripts/setup_driver_supervisor_e2e_env.sh <venv-dir>``. Use
``<venv-dir>/bin/python`` and pass both source roots with ``--lingtai-src``
and ``--puffo-src``; do not install the Puffo runtime into that environment.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any


def _load(lingtai_src: Path, puffo_src: Path) -> tuple[Any, ...]:
    sys.path[:0] = [str(puffo_src.resolve(strict=True)), str(lingtai_src.resolve(strict=True))]
    from lingtai.adapters.acp.driver_authority import (
        DriverAuthorityAdapter,
        consume_posix_child_endpoint_lease,
    )
    from lingtai.kernel.provider_admission import (
        DerivedLaunchAdmissionError,
        DerivedLaunchCapability,
        ProviderAdmittedLLMService,
        ProviderCallClass,
        RootProviderAdmission,
        bind_provider_admission,
        clear_provider_admission,
        current_provider_call_audit_id,
        require_derived_launch_admission,
    )
    from puffo_agent.agent.harness.driver_authority_server import DriverAuthorityServer

    return (
        DriverAuthorityAdapter,
        consume_posix_child_endpoint_lease,
        DerivedLaunchAdmissionError,
        DerivedLaunchCapability,
        ProviderAdmittedLLMService,
        ProviderCallClass,
        RootProviderAdmission,
        bind_provider_admission,
        clear_provider_admission,
        current_provider_call_audit_id,
        require_derived_launch_admission,
        DriverAuthorityServer,
    )


def main(lingtai_src: Path, puffo_src: Path) -> None:
    (
        Adapter,
        consume_lease,
        LaunchError,
        LaunchCapability,
        AdmittedService,
        CallClass,
        RootAdmission,
        bind,
        clear,
        current_audit_id,
        require_launch,
        Server,
    ) = _load(lingtai_src, puffo_src)

    class RecordingProvider:
        def __init__(self) -> None:
            self.provider_calls: list[str | None] = []

        def generate(self, _prompt: str) -> str:
            self.provider_calls.append(current_audit_id())
            return "generated"

    server = Server()
    root_adapter = None
    child_adapter = None
    try:
        root_endpoint = server.issue_root(launch_id="root-nested-audit")
        root_fd = os.dup(root_endpoint.fileno())
        root_endpoint.close()
        root_adapter = Adapter.from_inherited_fd(root_fd)

        root = RootAdmission("turn-nested-audit", "puffo-v0.e2e")
        root_token = bind(root)
        try:
            launch = require_launch(root_adapter, LaunchCapability.DAEMON)
        finally:
            clear(root_token)

        child_fd = consume_lease(launch.child_endpoint_lease)
        child_adapter = Adapter.from_inherited_fd(child_fd)
        child_parent = child_adapter.derived_provider_parent(CallClass.DAEMON)
        provider = RecordingProvider()
        service = AdmittedService(provider, child_adapter)

        child_token = bind(child_parent)
        try:
            assert service.generate("legal child provider call") == "generated"
            nested = []
            for capability in (LaunchCapability.DAEMON, LaunchCapability.AVATAR):
                try:
                    require_launch(child_adapter, capability)
                except LaunchError as exc:
                    nested.append(exc.decision)
                else:
                    raise AssertionError(f"nested {capability.value} launch was granted")
        finally:
            clear(child_token)

        records = server.audit_records()
        provider_records = [
            record for record in records if record.operation == "authorize_provider_call"
        ]
        nested_records = [
            record
            for record in records
            if record.operation == "authorize_derived_launch"
            and record.reason_code == "nested_derived_launch_denied"
        ]
        print(f"provider_calls={provider.provider_calls}")
        print(f"provider_audits={[record.audit_id for record in provider_records]}")
        print(f"nested_audits={[record.audit_id for record in nested_records]}")

        assert len(provider_records) == 1
        assert provider.provider_calls == [provider_records[0].audit_id]
        assert len(nested) == 2
        assert all(decision.reason_code == "nested_derived_launch_denied" for decision in nested)
        assert all(isinstance(decision.audit_id, str) and decision.audit_id for decision in nested)
        assert [decision.audit_id for decision in nested] == [
            record.audit_id for record in nested_records
        ]
        assert len(nested_records) == 2
        assert len(provider.provider_calls) == 1
    finally:
        if child_adapter is not None:
            child_adapter.close()
        if root_adapter is not None:
            root_adapter.close()
        server.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--lingtai-src", required=True, type=Path)
    parser.add_argument("--puffo-src", required=True, type=Path)
    args = parser.parse_args()
    main(args.lingtai_src, args.puffo_src)
