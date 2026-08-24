#!/usr/bin/env python3
"""Guarded macOS-only external stack capture for one live LingTai agent.

This is deliberately an *external producer* diagnostic. It does not import or
exercise NotificationStore locking. Its only optional agent mutation is one
unique, content-free ``mcp.*`` file created after read-only preflight passes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from lingtai.adapters.posix.git_cli import PosixGitCliAdapter
from lingtai.adapters.posix.process_identity import process_identity, process_identity_matches
from lingtai.adapters.posix.process_scan import PosixAgentProcessScanAdapter
from lingtai.kernel.process_match import match_agent_run
from lingtai.kernel.runtime_identity import _source_root, runtime_identity

SAMPLE_TOOL = Path("/usr/bin/sample")
_MAX_SAMPLE_SECONDS = 10
_MAX_RELATED_PIDS = 8
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_BURST_PREFIX = "mcp.external-attach-diagnostic."
_BURST_SUFFIX = ".json"


class DiagnosticError(RuntimeError):
    """A refused or failed diagnostic operation with a safe reason."""


@dataclass(frozen=True)
class ObservedProcess:
    pid: int
    start_identity: str
    run_form: str | None


def _parse_pid(value: str) -> int:
    try:
        pid = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("PID must be a positive integer") from exc
    if pid <= 0:
        raise argparse.ArgumentTypeError("PID must be a positive integer")
    return pid


def _canonical_existing_directory(value: str | Path, *, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise DiagnosticError(f"{label} must be an existing canonical absolute directory")
    if path != path.resolve():
        raise DiagnosticError(f"{label} must not use a symlink or non-canonical path")
    return path


def _new_artifact_directory(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute() or path.exists() or path.is_symlink():
        raise DiagnosticError("--artifact-dir must be an absent canonical absolute directory")
    parent = path.parent
    if not parent.is_dir() or parent.is_symlink() or parent != parent.resolve():
        raise DiagnosticError("--artifact-dir parent must be an existing canonical absolute directory")
    return path


def _require_supported_host_and_tool() -> None:
    """Fail before any artifact or agent-directory mutation on unsupported hosts."""
    if sys.platform != "darwin":
        raise DiagnosticError("external attach diagnostic is supported only on macOS (/usr/bin/sample)")
    if not SAMPLE_TOOL.is_file() or not os.access(SAMPLE_TOOL, os.X_OK):
        raise DiagnosticError("macOS /usr/bin/sample is unavailable; no artifacts were created")


def _find_target_run(agent_dir: Path, pid: int) -> str:
    """Bind a PID to one exact workdir through canonical runtime policy."""
    for observed_pid, command in PosixAgentProcessScanAdapter().iter_process_commands():
        if observed_pid == pid:
            form = match_agent_run(command, str(agent_dir))
            if form is not None:
                return form
            break
    raise DiagnosticError("--pid is not a live LingTai run for --agent-dir")


def _observe_target(agent_dir: Path, pid: int) -> ObservedProcess:
    """Capture a PID incarnation before and after canonical ownership matching."""
    start_identity = process_identity(pid)
    if not start_identity:
        raise DiagnosticError("cannot obtain a stable process-incarnation identity for --pid")
    run_form = _find_target_run(agent_dir, pid)
    if not process_identity_matches(pid, start_identity):
        raise DiagnosticError("--pid changed incarnation during ownership verification")
    return ObservedProcess(pid=pid, start_identity=start_identity, run_form=run_form)


def _observe_related(pids: Iterable[int]) -> list[ObservedProcess]:
    observed: list[ObservedProcess] = []
    for pid in pids:
        identity = process_identity(pid)
        if not identity or not process_identity_matches(pid, identity):
            raise DiagnosticError(f"cannot obtain a stable process-incarnation identity for related PID {pid}")
        observed.append(ObservedProcess(pid=pid, start_identity=identity, run_form=None))
    return observed


def _identity_digest(identity: str) -> str:
    """Do not place raw OS incarnation tokens in external evidence."""
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def _heartbeat_age_seconds(agent_dir: Path) -> float | None:
    try:
        return round(max(0.0, time.time() - (agent_dir / ".agent.heartbeat").stat().st_mtime), 3)
    except OSError:
        return None


def _safe_counts(agent_dir: Path) -> dict[str, int]:
    """Count only names; never parse notification, prompt, tool, or secret bodies."""
    notification_dir = agent_dir / ".notification"
    if not notification_dir.is_dir():
        return {"notification_json_files": 0, "mcp_notification_files": 0, "daemon_mini_files": 0}
    try:
        children = list(notification_dir.iterdir())
    except OSError:
        return {"notification_json_files": 0, "mcp_notification_files": 0, "daemon_mini_files": 0}
    json_names = [path.name for path in children if path.is_file() and path.suffix == ".json"]
    daemon_dir = notification_dir / "daemon"
    try:
        daemon_mini_files = sum(1 for path in daemon_dir.iterdir() if path.is_file() and path.suffix == ".json")
    except OSError:
        daemon_mini_files = 0
    return {
        "notification_json_files": len(json_names),
        "mcp_notification_files": sum(name.startswith("mcp.") for name in json_names),
        "daemon_mini_files": daemon_mini_files,
    }


def _kernel_identity(agent_dir: Path) -> dict[str, object]:
    """Use the imported kernel checkout identity, never the enclosing agent repo."""
    del agent_dir  # Process binding owns this path; kernel identity owns its source root.
    try:
        module_path = Path(runtime_identity.__code__.co_filename).resolve()
        raw = runtime_identity(PosixGitCliAdapter(_source_root(module_path)))
    except Exception:
        return {"status": "unavailable"}
    allowed = ("version", "stamp", "mode", "source", "installed_version", "git_commit", "git_dirty")
    return {key: raw[key] for key in allowed if isinstance(raw.get(key), (str, bool))}


def _burst_path(agent_dir: Path, run_id: str) -> Path:
    return agent_dir / ".notification" / f"{_BURST_PREFIX}{run_id}{_BURST_SUFFIX}"


def _validate_run_id(run_id: str | None) -> str:
    if not isinstance(run_id, str) or _RUN_ID_RE.fullmatch(run_id) is None:
        raise DiagnosticError("--burst-run-id must be 1-64 ASCII letters/digits/_/- and start alphanumeric")
    return run_id


def _is_exact_controlled_burst(payload: object, run_id: str) -> bool:
    data = payload.get("data") if isinstance(payload, dict) else None
    return bool(
        isinstance(data, dict)
        and data.get("kind") == "external_attach_controlled_burst"
        and data.get("diagnostic_run_id") == run_id
        and data.get("content_free") is True
    )


def _validate_burst_plan(agent_dir: Path, *, run_id: str, cleanup: bool) -> Path:
    notification_dir = agent_dir / ".notification"
    if not notification_dir.is_dir() or notification_dir.is_symlink():
        raise DiagnosticError("agent has no canonical .notification directory; refusing controlled burst")
    target = _burst_path(agent_dir, run_id)
    if cleanup:
        if not target.is_file() or target.is_symlink():
            raise DiagnosticError("exact controlled-burst target is absent; refusing cleanup")
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise DiagnosticError("exact controlled-burst target is unreadable; refusing cleanup") from exc
        if not _is_exact_controlled_burst(payload, run_id):
            raise DiagnosticError("target is not this exact controlled burst; refusing cleanup")
    elif target.exists() or target.is_symlink():
        raise DiagnosticError("exact controlled-burst target already exists; refusing overwrite")
    return target


def _write_exclusive(path: Path, content: bytes) -> None:
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _capture_stack(observed: ObservedProcess, output: Path, seconds: int) -> None:
    """Capture only a bounded process stack, never a semantic stage-timing trace."""
    try:
        result = subprocess.run(
            [str(SAMPLE_TOOL), str(observed.pid), str(seconds), "-file", str(output)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            check=False, timeout=float(seconds) + 8.0,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DiagnosticError(f"/usr/bin/sample failed for PID {observed.pid}; no diagnostic interpretation was made") from exc
    if result.returncode != 0 or not output.is_file():
        raise DiagnosticError(f"/usr/bin/sample failed for PID {observed.pid}; no diagnostic interpretation was made")
    if not process_identity_matches(observed.pid, observed.start_identity):
        raise DiagnosticError(f"PID {observed.pid} changed incarnation during stack capture")


def _create_controlled_burst(target: Path, run_id: str) -> None:
    payload = {
        "header": "External diagnostic controlled burst",
        "icon": "🔬",
        "priority": "normal",
        "published_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "instructions": "External diagnostic control marker; no prompt, notification, or tool body was captured.",
        "data": {"kind": "external_attach_controlled_burst", "diagnostic_run_id": run_id, "content_free": True},
    }
    _write_exclusive(target, (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))


def _remove_exact_controlled_burst(target: Path, run_id: str) -> None:
    """Only remove the exact-run-id control file validated in preflight."""
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DiagnosticError("exact controlled-burst target changed; refusing cleanup") from exc
    if not _is_exact_controlled_burst(payload, run_id):
        raise DiagnosticError("exact controlled-burst target changed; refusing cleanup")
    try:
        target.unlink()
    except FileNotFoundError as exc:
        raise DiagnosticError("exact controlled-burst target disappeared; no cleanup performed") from exc


def _evidence(*, target: ObservedProcess, related: list[ObservedProcess], agent_dir: Path, burst_target: Path | None, controlled_burst: bool, cleanup: bool) -> dict[str, object]:
    return {
        "schema": "lingtai.external_attach_diagnostic.v1",
        "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "interpretation": "Stacks only; not semantic stage timings.",
        "privacy": "No prompt, notification, tool, or secret bodies were read into this evidence.",
        "target": {"pid": target.pid, "run_form": target.run_form, "start_identity_sha256_16": _identity_digest(target.start_identity)},
        "related_pids": [{"pid": item.pid, "start_identity_sha256_16": _identity_digest(item.start_identity)} for item in related],
        "heartbeat_age_seconds": _heartbeat_age_seconds(agent_dir),
        "safe_counts": _safe_counts(agent_dir),
        "kernel_identity": _kernel_identity(agent_dir),
        "controlled_burst": {"requested": controlled_burst, "cleanup_requested": cleanup, "target_filename": burst_target.name if burst_target is not None else None, "store_locking_exercised": False},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Guarded macOS external attach diagnostic; captures stacks, not semantic timings.")
    parser.add_argument("--agent-dir", required=True, help="Canonical absolute LingTai agent working directory")
    parser.add_argument("--pid", required=True, type=_parse_pid, help="PID of that live LingTai agent run")
    parser.add_argument("--artifact-dir", required=True, help="Absent canonical absolute directory for content-free evidence")
    parser.add_argument("--related-pid", action="append", default=[], type=_parse_pid, help="Optional related PID to sample (repeatable; max 8)")
    parser.add_argument("--sample-seconds", default=3, type=int, help="Per-PID /usr/bin/sample duration (1-10; default 3)")
    parser.add_argument("--controlled-burst", action="store_true", help="Explicitly atomically create one content-free mcp.* control file")
    parser.add_argument("--cleanup-controlled-burst", action="store_true", help="Explicitly remove only this script's exact-run-id control file")
    parser.add_argument("--burst-run-id", help="Required with either controlled-burst option; exact identity of one control file")
    return parser


def run(args: argparse.Namespace) -> dict[str, object]:
    _require_supported_host_and_tool()
    if not 1 <= args.sample_seconds <= _MAX_SAMPLE_SECONDS:
        raise DiagnosticError("--sample-seconds must be between 1 and 10")
    if len(args.related_pid) > _MAX_RELATED_PIDS:
        raise DiagnosticError("at most 8 --related-pid values are allowed")
    if args.controlled_burst and args.cleanup_controlled_burst:
        raise DiagnosticError("--controlled-burst and --cleanup-controlled-burst are mutually exclusive")
    if (args.controlled_burst or args.cleanup_controlled_burst) and not args.burst_run_id:
        raise DiagnosticError("--burst-run-id is required for controlled-burst creation or cleanup")
    if args.burst_run_id and not (args.controlled_burst or args.cleanup_controlled_burst):
        raise DiagnosticError("--burst-run-id requires a controlled-burst option")

    agent_dir = _canonical_existing_directory(args.agent_dir, label="--agent-dir")
    artifact_dir = _new_artifact_directory(args.artifact_dir)
    target = _observe_target(agent_dir, args.pid)
    related = _observe_related(args.related_pid)
    burst_target = None
    run_id = None
    if args.controlled_burst or args.cleanup_controlled_burst:
        run_id = _validate_run_id(args.burst_run_id)
        burst_target = _validate_burst_plan(agent_dir, run_id=run_id, cleanup=args.cleanup_controlled_burst)

    # All preflight above is read-only. This is the first filesystem write.
    artifact_dir.mkdir(mode=0o700)
    _capture_stack(target, artifact_dir / f"pid-{target.pid}.stack.txt", args.sample_seconds)
    for item in related:
        _capture_stack(item, artifact_dir / f"related-pid-{item.pid}.stack.txt", args.sample_seconds)
    if not process_identity_matches(target.pid, target.start_identity):
        raise DiagnosticError("--pid changed incarnation before final diagnostic record")
    if args.controlled_burst:
        assert burst_target is not None and run_id is not None
        _create_controlled_burst(burst_target, run_id)
    elif args.cleanup_controlled_burst:
        assert burst_target is not None and run_id is not None
        _remove_exact_controlled_burst(burst_target, run_id)

    record = _evidence(target=target, related=related, agent_dir=agent_dir, burst_target=burst_target, controlled_burst=args.controlled_burst, cleanup=args.cleanup_controlled_burst)
    _write_exclusive(artifact_dir / "evidence.json", (json.dumps(record, sort_keys=True, indent=2) + "\n").encode("utf-8"))
    return record


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        record = run(args)
    except DiagnosticError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"status": "ok", "artifact_dir": args.artifact_dir, "target_pid": record["target"]["pid"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
