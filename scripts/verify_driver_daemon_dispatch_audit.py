"""Cross-repository acceptance probe for the derived daemon tool surface.

This complements the narrower admission-seam probe.  It uses Puffo's actual
Driver server for a root-to-daemon endpoint handoff, composes LingTai's
``DetachedDaemonExecutionHost``, performs one legal provider call, and invokes
the real daemon and avatar dispatch handlers.  The same Driver audit stream
must contain the provider grant and both nested-launch denials.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from threading import Event
from typing import Any


def _load(lingtai_src: Path, puffo_src: Path) -> tuple[Any, ...]:
    sys.path[:0] = [str(puffo_src.resolve(strict=True)), str(lingtai_src.resolve(strict=True))]
    from lingtai.adapters.acp.driver_authority import (
        DRIVER_AUTHORITY_FD_ENV,
        DriverAuthorityAdapter,
        consume_posix_child_endpoint_lease,
    )
    from lingtai.kernel.daemon_supervisor.manifest import (
        build_manifest,
        manifest_path_for,
        mark_manifest_requires_derived_launch_admission,
        read_manifest,
        write_manifest,
    )
    from lingtai.kernel.provider_admission import (
        DerivedLaunchCapability,
        ProviderAdmittedLLMService,
        ProviderCallClass,
        RootProviderAdmission,
        bind_provider_admission,
        clear_provider_admission,
        current_provider_call_audit_id,
        require_derived_launch_admission,
    )
    from lingtai.tools.daemon.execution_host import DetachedDaemonExecutionHost
    from lingtai.tools.daemon.run_dir import DaemonRunDir
    from puffo_agent.agent.harness.driver_authority_server import DriverAuthorityServer

    return (
        DRIVER_AUTHORITY_FD_ENV,
        DriverAuthorityAdapter,
        consume_posix_child_endpoint_lease,
        build_manifest,
        manifest_path_for,
        mark_manifest_requires_derived_launch_admission,
        read_manifest,
        write_manifest,
        DerivedLaunchCapability,
        ProviderAdmittedLLMService,
        ProviderCallClass,
        RootProviderAdmission,
        bind_provider_admission,
        clear_provider_admission,
        current_provider_call_audit_id,
        require_derived_launch_admission,
        DetachedDaemonExecutionHost,
        DaemonRunDir,
        DriverAuthorityServer,
    )


def main(lingtai_src: Path, puffo_src: Path) -> None:
    (
        fd_env,
        Adapter,
        consume_lease,
        build_manifest,
        manifest_path_for,
        mark_required,
        read_manifest,
        write_manifest,
        Capability,
        AdmittedService,
        CallClass,
        RootAdmission,
        bind,
        clear,
        current_audit_id,
        require_launch,
        DetachedHost,
        RunDir,
        Server,
    ) = _load(lingtai_src, puffo_src)

    class RecordingProvider:
        def __init__(self) -> None:
            self.provider_calls: list[str | None] = []

        def generate(self, _prompt: str) -> str:
            self.provider_calls.append(current_audit_id())
            return "generated"

    prior_fd = os.environ.pop(fd_env, None)
    server = Server()
    root_adapter = None
    host = None
    try:
        with tempfile.TemporaryDirectory(prefix="lingtai-driver-daemon-") as raw:
            base = Path(raw)
            parent = base / "agent"
            parent.mkdir()
            (parent / "init.json").write_text(
                json.dumps(
                    {
                        "manifest": {
                            "agent_name": "driver-daemon-audit",
                            "language": "en",
                            "llm": {
                                "provider": "fake", "model": "test-model",
                                "api_key": "test-key", "base_url": None,
                            },
                            "capabilities": {"daemon": {}, "avatar": {}},
                            "soul": {"delay": 30}, "stamina": 60,
                            "context_limit": None, "molt_pressure": 0.8,
                            "molt_prompt": "", "max_turns": 1,
                            "admin": {"karma": True}, "streaming": False,
                        },
                        "principle": "", "covenant": "", "pad": "", "lingtai": "",
                    }
                ),
                encoding="utf-8",
            )
            run_dir = RunDir(
                parent_working_dir=parent,
                handle="driver-daemon-audit",
                run_id="driver-daemon-audit",
                task="verify derived daemon dispatch",
                tools=["file", "daemon", "avatar"],
                model="test-model",
                max_turns=1,
                timeout_s=30.0,
                parent_addr="driver-daemon-audit",
                parent_pid=os.getpid(),
                system_prompt="driver daemon dispatch probe",
                call_parameters={},
            )
            manifest = build_manifest(
                run_id=run_dir.run_id,
                backend="lingtai",
                parent_working_dir=str(parent),
                run_dir=str(run_dir.path),
                task="verify derived daemon dispatch",
                tools=["file", "daemon", "avatar"],
                max_turns=1,
                timeout_s=30.0,
                group_id=None,
                llm={
                    "provider": "fake", "model": "test-model", "api_key": None,
                    "base_url": None, "context_window": None,
                    "provider_defaults": None,
                },
            )
            write_manifest(run_dir.path, manifest)
            mark_required(run_dir.path)

            issued = server.issue_root(launch_id="root-daemon-dispatch-audit")
            root_adapter = Adapter.from_inherited_fd(os.dup(issued.fileno()))
            issued.close()
            root = RootAdmission("turn-daemon-dispatch-audit", "puffo-v0.e2e")
            token = bind(root)
            try:
                launch = require_launch(root_adapter, Capability.DAEMON)
            finally:
                clear(token)
            child_fd = consume_lease(launch.child_endpoint_lease)
            os.environ[fd_env] = str(child_fd)
            host = DetachedHost(
                run_dir, read_manifest(manifest_path_for(run_dir.path)), Event(), Event()
            )
            port = host._agent._provider_call_admission_port
            parent_admission = host._agent._derived_provider_admission_parent
            assert parent_admission.call_class is CallClass.DAEMON
            provider = RecordingProvider()
            host._agent.service = AdmittedService(provider, port)

            schemas, dispatch = host._build_lingtai_surface()
            names = {schema.name for schema in schemas}
            assert {"daemon", "avatar"} <= names
            assert {"daemon", "avatar"} <= set(dispatch)

            token = bind(parent_admission)
            try:
                assert host._agent.service.generate("legal child provider call") == "generated"
                provider_before_nested = list(provider.provider_calls)
                avatar = dispatch["avatar"](
                    {"action": "spawn", "input": {"name": "nested-avatar", "confirm": True}}
                )
                daemon = dispatch["daemon"](
                    {"action": "emanate", "input": {"tasks": [{"task": "nested", "tools": []}]}}
                )
            finally:
                clear(token)

            records = server.audit_records()
            provider_records = [r for r in records if r.operation == "authorize_provider_call"]
            nested_records = [
                r for r in records
                if r.operation == "authorize_derived_launch"
                and r.reason_code == "nested_derived_launch_denied"
            ]
            event_rows = [
                json.loads(line)
                for line in run_dir.events_path.read_text(encoding="utf-8").splitlines()
                if line
            ]
            daemon_decisions = [
                event for event in event_rows
                if event.get("event") == "derived_launch_admission_decision"
                and event.get("capability") == "daemon"
            ]
            print(f"provider_calls={provider.provider_calls}")
            print(f"provider_audits={[r.audit_id for r in provider_records]}")
            print(f"nested_audits={[r.audit_id for r in nested_records]}")
            print(f"avatar_result={avatar}")
            print(f"daemon_result={daemon}")
            print(f"daemon_decisions={daemon_decisions}")

            assert provider.provider_calls == [provider_records[0].audit_id]
            assert provider.provider_calls == provider_before_nested
            assert len(provider_records) == 1
            assert len(nested_records) == 2
            assert avatar["reason_code"] == "nested_derived_launch_denied"
            assert isinstance(avatar["audit_id"], str) and avatar["audit_id"]
            assert avatar["audit_id"] in [r.audit_id for r in nested_records]
            assert daemon == {
                "status": "error",
                "message": "derived launch was not admitted: nested_derived_launch_denied",
            }
            assert len(daemon_decisions) == 1
            daemon_decision = daemon_decisions[0]
            assert daemon_decision["state"] == "denied"
            assert daemon_decision["reason_code"] == "nested_derived_launch_denied"
            assert isinstance(daemon_decision["audit_id"], str) and daemon_decision["audit_id"]
            assert daemon_decision["audit_id"] in [r.audit_id for r in nested_records]
            assert daemon_decision["audit_id"] != avatar["audit_id"]
            assert all(isinstance(r.audit_id, str) and r.audit_id for r in nested_records)
    finally:
        if host is not None:
            authority = getattr(host._agent, "_derived_launch_admission_port", None)
            close = getattr(authority, "close", None)
            if callable(close):
                close()
        if root_adapter is not None:
            root_adapter.close()
        if prior_fd is not None:
            os.environ[fd_env] = prior_fd
        else:
            os.environ.pop(fd_env, None)
        server.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--lingtai-src", required=True, type=Path)
    parser.add_argument("--puffo-src", required=True, type=Path)
    args = parser.parse_args()
    main(args.lingtai_src, args.puffo_src)
