"""Composition root for ``lingtai-agent acp``."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TextIO


def add_acp_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "acp",
        help="Serve one existing LingTai agent over local ACP v1 stdio",
    )
    parser.add_argument(
        "--agent-dir",
        type=Path,
        required=True,
        help="Existing agent working directory containing init.json",
    )


def _force_exit_after_incomplete_stop(agent, stop_result, stop_error) -> None:
    """Terminate when bounded Agent stop cannot report completed teardown."""

    stopped = bool(stop_result is not None and stop_result.stopped)
    if stop_error is None and stopped:
        return
    # A post-quiescence cleanup exception may already have released the lease.
    # Never append to the workdir after that release; a timed-out stop still owns
    # the lease and may record the terminal diagnostic safely.
    if getattr(agent, "_workdir_lease_acquired", True):
        try:
            agent._log(
                "acp_force_exit_after_incomplete_stop",
                stop_error=type(stop_error).__name__ if stop_error is not None else None,
                run_loop_alive=getattr(stop_result, "run_loop_alive", None),
                provider_worker_alive=getattr(stop_result, "provider_worker_alive", None),
            )
        except Exception:
            pass
    try:
        sys.stderr.flush()
    except Exception:
        pass
    # A timed-out proof still owns heartbeat/lease; a post-proof cleanup error
    # may already have released them. In either case, immediate process termination
    # is the only boundary that guarantees this host performs no later state write.
    os._exit(70)


def run_acp(
    agent_dir: Path,
    *,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
) -> None:
    """Compose one Agent and the local ACP stdio driving adapter.

    The original stdout object is captured as the wire before any Agent/config
    construction. Application ``print`` calls are then redirected to stderr for
    the complete server lifetime, leaving only serialized JSON-RPC on the wire.
    """

    wire_in = input_stream if input_stream is not None else sys.stdin
    wire_out = output_stream if output_stream is not None else sys.stdout
    if input_stream is None:
        reconfigure_in = getattr(wire_in, "reconfigure", None)
        if callable(reconfigure_in):
            reconfigure_in(encoding="utf-8", errors="strict")
    if output_stream is None:
        reconfigure_out = getattr(wire_out, "reconfigure", None)
        if callable(reconfigure_out):
            reconfigure_out(
                encoding="utf-8",
                errors="strict",
                newline="\n",
                write_through=True,
            )
    original_stdout = sys.stdout
    sys.stdout = sys.stderr
    agent = None
    try:
        # Lazy imports keep ordinary CLI commands free of ACP startup wiring and
        # make stdout quarantine precede every potentially noisy boot operation.
        from lingtai.adapters.acp import AcpStdioServer
        from lingtai.cli import (
            _check_duplicate_process,
            _clean_signal_files,
            _force_exit_if_worker_poisoned,
            build_agent,
            load_init,
        )
        from lingtai.kernel.logging import setup_logging
        from lingtai.venv_resolve import resolve_venv

        _check_duplicate_process(agent_dir)
        _clean_signal_files(agent_dir)
        setup_logging(
            verbose=os.environ.get("LINGTAI_VERBOSE") == "1",
            log_dir=agent_dir / "logs",
        )
        data = load_init(agent_dir)
        venv_dir = resolve_venv(data)
        os.environ["LINGTAI_RUNTIME_PYTHON"] = sys.executable
        os.environ["LINGTAI_RUNTIME_VENV"] = str(venv_dir)
        data["venv_path"] = str(venv_dir)

        agent = build_agent(data, agent_dir)
        agent._venv_path = str(venv_dir)
        agent.start()
        server = AcpStdioServer(agent, wire_in, wire_out)
        try:
            server.serve()
        except (BrokenPipeError, OSError, UnicodeError, KeyboardInterrupt):
            # Local client disconnects and malformed stream encodings are clean
            # transport termination, not reasons to leak a Python traceback.
            server.close()
    finally:
        if agent is not None:
            stop_result = None
            stop_error = None
            try:
                stop_result = agent.stop(timeout=10.0)
            except BaseException as exc:
                stop_error = exc
            try:
                _force_exit_after_incomplete_stop(agent, stop_result, stop_error)
            except NameError:
                # Agent construction failed before helper imports completed.
                if stop_error is not None:
                    raise stop_error
            try:
                _force_exit_if_worker_poisoned(agent)
            except NameError:
                pass
        sys.stdout = original_stdout


def handle_acp_command(args) -> None:
    agent_dir = args.agent_dir.resolve()
    if not agent_dir.is_dir():
        print(f"error: {agent_dir} is not a directory", file=sys.stderr)
        raise SystemExit(1)
    run_acp(agent_dir)


__all__ = ["add_acp_parser", "handle_acp_command", "run_acp"]
