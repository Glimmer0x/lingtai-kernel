"""Verify the real Driver -> detached-daemon first-hop lifecycle.

This is a cross-repository acceptance probe.  Unlike the dispatch/audit
probe, it does not construct a detached host or insert a child descriptor by
hand.  It starts from a root Agent, lets DaemonManager request a real Driver
lease, and then follows the production chain:

    root Agent -> PosixDaemonSupervisorAdapter -> supervisor entrypoint
    -> execution-child entrypoint -> admitted provider call

The deterministic fake LLM exists only to avoid a live model dependency.  The
Driver server, lease, two process boundaries, entrypoint adoption, and
provider-call adjudication are all real.
"""
from __future__ import annotations

import argparse
from importlib.metadata import PackageNotFoundError, version
import os
import sys
import tempfile
import time
from pathlib import Path


def _require_e2e_environment() -> None:
    """Fail before product setup when the required MCP server API is absent."""

    try:
        from mcp.server import ServerRequestContext  # noqa: F401
    except (ImportError, ModuleNotFoundError) as exc:
        try:
            installed = version("mcp")
        except PackageNotFoundError:
            installed = "not installed"
        raise RuntimeError(
            "E2E_ENVIRONMENT_INVALID: the selected mcp "
            f"({installed}) does not provide mcp.server.ServerRequestContext; "
            "recreate this exact checkout with `uv sync --locked` before "
            "interpreting the Driver lifecycle verdict"
        ) from exc


def _load(lingtai_src: Path, puffo_src: Path):
    _require_e2e_environment()
    lingtai_src = lingtai_src.resolve(strict=True)
    puffo_src = puffo_src.resolve(strict=True)
    tests_dir = lingtai_src.parent / "tests"
    if not tests_dir.is_dir():
        raise ValueError(f"LingTai tests directory is missing: {tests_dir}")
    sys.path[:0] = [str(puffo_src), str(lingtai_src)]
    from lingtai.adapters.acp.driver_authority import DriverAuthorityAdapter
    from lingtai.agent import Agent
    from lingtai.kernel.config import AgentConfig
    from lingtai.kernel.provider_admission import (
        RootProviderAdmission,
        bind_provider_admission,
        clear_provider_admission,
    )
    from lingtai.tools.daemon.run_dir import DaemonRunDir
    from puffo_agent.agent.harness.driver_authority_server import DriverAuthorityServer
    return (
        tests_dir,
        DriverAuthorityAdapter,
        Agent,
        AgentConfig,
        RootProviderAdmission,
        bind_provider_admission,
        clear_provider_admission,
        DaemonRunDir,
        DriverAuthorityServer,
    )


class _RootService:
    """Minimal root service shape used only to compose the real daemon tool."""

    provider = "lingtai-supervisor-test-fake"
    model = "fake-model"
    api_key = "driver-first-hop-test-key"
    _base_url = None
    _provider_defaults: dict[str, object] = {}


def _wait_terminal(run_dir, *, timeout_s: float) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        state = run_dir.read_state_from_disk(run_dir.path)
        if state.get("state") in {"done", "failed", "cancelled", "timeout"}:
            return state
        time.sleep(0.05)
    raise AssertionError(f"run did not become terminal within {timeout_s}s: {run_dir.path}")


def main(lingtai_src: Path, puffo_src: Path) -> None:
    (
        tests_dir,
        Adapter,
        Agent,
        AgentConfig,
        RootAdmission,
        bind,
        clear,
        RunDir,
        Server,
    ) = _load(lingtai_src, puffo_src)

    # The production supervisor deliberately inherits these non-secret test
    # switches.  It must import the fake inside each spawned interpreter.
    old_pythonpath = os.environ.get("PYTHONPATH")
    os.environ["LINGTAI_DAEMON_SUPERVISOR_TEST_FAKE_LLM"] = "1"
    os.environ["LINGTAI_DAEMON_SUPERVISOR_TEST_FAKE_LLM_FINISH"] = "1"
    os.environ["PYTHONPATH"] = os.pathsep.join(
        dict.fromkeys([str(tests_dir), str(lingtai_src), *(old_pythonpath or "").split(os.pathsep)])
    )

    server = Server()
    root_adapter = None
    endpoint = None
    try:
        # Detached children may finish their terminal write just after their
        # durable state becomes `done`.  Directory cleanup is not part of this
        # probe's verdict, so it must not turn an already-proven lifecycle
        # result into a false failure by racing that final write.
        with tempfile.TemporaryDirectory(
            prefix="lingtai-driver-first-hop-", ignore_cleanup_errors=True
        ) as raw_workdir:
            workdir = Path(raw_workdir)
            agent = Agent(
                _RootService(),
                working_dir=workdir / "root-agent",
                # A Driver lease is intentionally incompatible with the
                # central manager: it must be carried through this exact
                # supervisor process chain.
                capabilities={"daemon": {"manager_pool_size": 0}},
                config=AgentConfig(),
            )
            endpoint = server.issue_root(launch_id="root-supervisor-e2e")
            root_adapter = Adapter.from_inherited_fd(os.dup(endpoint.fileno()))
            endpoint.close()
            endpoint = None
            agent._derived_launch_admission_port = root_adapter

            root = RootAdmission("turn-supervisor-e2e", "puffo-v0.e2e")
            token = bind(root)
            try:
                result = agent.get_capability("daemon").handle(
                    {
                        "action": "emanate",
                        "max_turns": 2,
                        "timeout": 30,
                        "tasks": [{"task": "Finish the deterministic test task.", "tools": []}],
                    }
                )
            finally:
                clear(token)
            assert result.get("status") == "dispatched", result
            run_id = result["ids"][0]
            run_dir = RunDir.attach(workdir / "root-agent" / "daemons" / run_id)
            state = _wait_terminal(run_dir, timeout_s=35)

            assert state.get("state") == "done", state
            assert isinstance(state.get("supervisor_pid"), int), state
            assert isinstance(state.get("execution_pid"), int), state
            assert state.get("execution_registration") == "registered", state

            records = list(server.audit_records())
            launch = [record for record in records if record.operation == "authorize_derived_launch"]
            provider = [record for record in records if record.operation == "authorize_provider_call"]
            assert len(launch) == 1, records
            assert (launch[0].state, launch[0].reason_code) == ("granted", "allowed")
            assert provider, records
            assert all((record.state, record.reason_code) == ("granted", "allowed") for record in provider)
            assert {record.launch_id for record in provider}.isdisjoint({launch[0].launch_id}), records

            print("root_to_supervisor_to_execution_child=ok")
            print(f"supervisor_pid={state['supervisor_pid']} execution_pid={state['execution_pid']}")
            print(f"launch_audit={launch[0].audit_id} provider_audits={[record.audit_id for record in provider]}")
            print(f"provider_launch_ids={sorted({record.launch_id for record in provider})}")
    finally:
        if endpoint is not None:
            endpoint.close()
        if root_adapter is not None:
            root_adapter.close()
        server.close()
        if old_pythonpath is None:
            os.environ.pop("PYTHONPATH", None)
        else:
            os.environ["PYTHONPATH"] = old_pythonpath


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--lingtai-src", required=True, type=Path)
    parser.add_argument("--puffo-src", required=True, type=Path)
    parser.add_argument(
        "--expect-failure",
        help="Treat only an exception containing this text as the expected must-red result.",
    )
    args = parser.parse_args()
    try:
        main(args.lingtai_src, args.puffo_src)
    except Exception as exc:
        if args.expect_failure and args.expect_failure in str(exc):
            print(f"expected_failure={args.expect_failure!r}")
            raise SystemExit(0) from None
        raise
    if args.expect_failure:
        raise AssertionError(f"expected failure was not observed: {args.expect_failure!r}")
