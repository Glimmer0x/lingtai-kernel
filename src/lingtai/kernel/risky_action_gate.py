"""Opt-in risky-action gate for kernel tool dispatch.

The gate is intentionally a policy/check module, not an executor: it never
sends notifications or dispatches a tool. When an opted-in proposal is risky it
writes an exact, durable pending request and returns a structured denial. A
separate approval/replay worker can consume those records later.

Opt-in is the presence of ``<working_dir>/.security/gate_config.json``. This
keeps existing agents unchanged while giving a deployment a mechanical,
fail-closed boundary for the first-class ``file`` and ``shell`` surfaces.
"""
from __future__ import annotations

import json
import os
import shlex
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .tool_call_guard import GuardDecision, ToolProposal

MERGED_LIST_KEYS = ("local_write_roots", "remote_write_roots", "ssh_hosts", "trusted_scripts")
APPROVAL_CHANNELS = ("telegram", "wechat")
DEFAULT_APPROVAL_TTL_SECONDS = 24 * 60 * 60
GATE_CHECK_NAME = "risky_action_gate"

# Commands with a known write/destructive meaning. Unknown commands are also
# treated as risky below: shell is free-form, so the safe default is deny.
_DESTRUCTIVE_VERBS = {"rm", "rmdir", "unlink", "shred", "truncate"}
_DESTINATION_VERBS = {"mv", "cp", "install", "rsync"}
_READ_ONLY_VERBS = {
    "cat", "cut", "date", "echo", "env", "head", "jq", "ls", "pwd",
    "printf", "rg", "sort", "tail", "true", "type", "uname", "wc", "which",
}
_READ_ONLY_GIT_SUBCOMMANDS = {"branch", "diff", "log", "ls-files", "remote", "show", "status", "tag"}
_WRAPPERS = {"command", "env", "exec", "nohup", "sudo", "time", "doas"}
_INTERPRETERS = {"bash", "fish", "node", "perl", "python", "python2", "python3", "ruby", "sh", "zsh"}
_CHAIN_SEPARATORS = ("&&", "||", ";", "|", "\n")


def _resolve(path: str | os.PathLike[str]) -> str:
    return str(Path(path).expanduser().resolve())


def _is_within_roots(path: str | os.PathLike[str], roots: list[str]) -> bool:
    resolved = _resolve(path)
    for root in roots:
        root_resolved = _resolve(root)
        if resolved == root_resolved or resolved.startswith(root_resolved.rstrip(os.sep) + os.sep):
            return True
    return False


def _list_value(config: dict[str, Any], key: str) -> list[str]:
    value = config.get(key, [])
    return [item for item in value if isinstance(item, str) and item] if isinstance(value, list) else []


def load_gate_config(working_dir: str | os.PathLike[str]) -> dict[str, Any] | None:
    """Load the opt-in config and union its sibling shared-network grants."""
    workdir = Path(working_dir).expanduser().resolve()
    own_path = workdir / ".security" / "gate_config.json"
    if not own_path.is_file():
        return None
    own = json.loads(own_path.read_text(encoding="utf-8"))
    if not isinstance(own, dict):
        raise ValueError("gate_config.json must contain a JSON object")

    shared_path = workdir.parent / "shared" / ".security" / "gate_config.json"
    if not shared_path.is_file():
        return dict(own)
    shared = json.loads(shared_path.read_text(encoding="utf-8"))
    if not isinstance(shared, dict):
        raise ValueError("shared gate_config.json must contain a JSON object")
    merged = dict(own)
    for key in MERGED_LIST_KEYS:
        values: list[str] = []
        for source in (shared, own):
            values.extend(_list_value(source, key))
        if values:
            merged[key] = list(dict.fromkeys(values))
    return merged


def _pending_dir(working_dir: Path, config: dict[str, Any]) -> Path:
    raw = config.get("pending_dir", ".security/pending")
    if not isinstance(raw, str) or not raw.strip():
        raw = ".security/pending"
    path = Path(raw).expanduser()
    return (working_dir / path).resolve() if not path.is_absolute() else path.resolve()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _token_is_ambiguous(token: str) -> bool:
    return any(char in token for char in ("*", "?", "$", "`")) or ("[" in token and "]" in token)


def _command_segments(command: str) -> list[list[str]]:
    # shlex does not interpret shell operators; splitting first gives a
    # conservative classifier while retaining the original command verbatim in
    # the pending record for exact replay.
    segments = [command]
    for separator in _CHAIN_SEPARATORS:
        segments = [part for segment in segments for part in segment.split(separator)]
    result: list[list[str]] = []
    for segment in segments:
        try:
            tokens = shlex.split(segment, posix=True)
        except ValueError:
            return []
        if tokens:
            result.append(tokens)
    return result


def _unwrap(tokens: list[str]) -> list[str]:
    index = 0
    while index < len(tokens) and tokens[index] in _WRAPPERS:
        wrapper = tokens[index]
        index += 1
        # ``env KEY=value command`` is common; skip assignments, but do not
        # attempt to model wrappers with option values (fail closed later).
        if wrapper == "env":
            while index < len(tokens) and "=" in tokens[index] and not tokens[index].startswith("="):
                index += 1
    return tokens[index:]


def _shell_risk_reason(command: str, config: dict[str, Any], *, cwd: str | None = None) -> str | None:
    segments = _command_segments(command)
    if not segments:
        return "shell command cannot be parsed safely"
    trusted_scripts = {_resolve(path) for path in _list_value(config, "trusted_scripts")}
    resolve_cwd = Path(cwd).expanduser().resolve() if isinstance(cwd, str) and cwd else None
    ssh_hosts = set(_list_value(config, "ssh_hosts"))
    for tokens in segments:
        tokens = _unwrap(tokens)
        if not tokens:
            return "shell command has no resolvable executable"
        verb = Path(tokens[0]).name
        if any(_token_is_ambiguous(token) for token in tokens):
            return "shell command contains an ambiguous token"
        if verb in _DESTRUCTIVE_VERBS:
            return f"destructive shell command: {verb}"
        if verb in _DESTINATION_VERBS:
            return f"destination-writing shell command: {verb}"
        if verb == "git":
            subcommand = next((token for token in tokens[1:] if not token.startswith("-")), None)
            if subcommand not in _READ_ONLY_GIT_SUBCOMMANDS:
                return f"git subcommand is not classified read-only: {subcommand or '<missing>'}"
            continue
        if verb == "ssh":
            host = next((token for token in tokens[1:] if not token.startswith("-")), None)
            if host not in ssh_hosts:
                return "ssh target is not in ssh_hosts"
            return "remote shell execution is risky"
        if verb in _INTERPRETERS:
            if any(flag in tokens for flag in ("-c", "-e")):
                return "inline interpreter code is risky"
            script = next((token for token in tokens[1:] if not token.startswith("-")), None)
            script_path = (
                (resolve_cwd / script).resolve()
                if script is not None and resolve_cwd is not None and not Path(script).is_absolute()
                else _resolve(script)
                if script is not None
                else None
            )
            if script_path is None or str(script_path) not in trusted_scripts:
                return "interpreter script is not in trusted_scripts"
            continue
        if any(
            token in {"|", ">", ">>", "<", "<<", "|&"}
            or token.startswith((">", "<"))
            for token in tokens
        ):
            return "shell pipeline or redirection is risky"
        if verb == "curl" and any("bash" in token or "sh" == token for token in tokens):
            return "piped installer execution is risky"
        if verb not in _READ_ONLY_VERBS:
            return f"shell command is not classified read-only: {verb}"
    return None


def _file_risk_reason(args: dict[str, Any], config: dict[str, Any]) -> tuple[str, str] | None:
    action = args.get("action")
    if action not in {"write", "edit"}:
        return None
    action_input = args.get("input")
    if not isinstance(action_input, dict):
        return "file action input is invalid", ""
    target = action_input.get("file_path")
    if not isinstance(target, str) or not target:
        return "file target is missing", ""
    if _is_within_roots(target, _list_value(config, "local_write_roots")):
        return None
    return f"file.{action} target is outside local_write_roots", _resolve(target)


def _operation(proposal: ToolProposal, reason: str) -> dict[str, Any]:
    args = dict(proposal.tool_args)
    operation: dict[str, Any] = {
        "kind": (
            "file_write"
            if proposal.tool_name == "file" and args.get("action") == "write"
            else "file_edit"
            if proposal.tool_name == "file" and args.get("action") == "edit"
            else "shell_command"
            if proposal.tool_name == "shell"
            else "tool_call"
        ),
        "tool_name": proposal.tool_name,
        "args": args,
        "reason": reason,
    }
    if proposal.tool_name == "shell" and isinstance(args.get("input"), dict):
        operation["command"] = args["input"].get("command")
        operation["cwd"] = args["input"].get("working_dir")
    return operation


def _record_pending(working_dir: Path, config: dict[str, Any], proposal: ToolProposal, reason: str) -> tuple[str, Path]:
    request_id = uuid.uuid4().hex
    request = {
        "id": request_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_in_seconds": DEFAULT_APPROVAL_TTL_SECONDS,
        "status": "pending",
        "operation": _operation(proposal, reason),
        "approvals": {channel: None for channel in APPROVAL_CHANNELS},
    }
    directory = _pending_dir(working_dir, config)
    path = directory / f"{request_id}.json"
    _write_json_atomic(path, request)
    return request_id, path


def build_risky_action_check(working_dir: str | os.PathLike[str]):
    """Return the opt-in guard check for *working_dir*.

    Config errors deny rather than disabling the gate. Missing config is the
    explicit compatibility path and returns the existing default allow.
    """
    workdir = Path(working_dir).expanduser().resolve()

    def risky_action_check(proposal: ToolProposal) -> GuardDecision:
        try:
            config = load_gate_config(workdir)
        except Exception as exc:
            return GuardDecision.deny(
                check_name=GATE_CHECK_NAME,
                reason=f"risky-action gate configuration failed: {type(exc).__name__}",
            )
        if config is None:
            return GuardDecision.allow()
        reason: str | None = None
        if proposal.tool_name == "file":
            file_result = _file_risk_reason(proposal.tool_args, config)
            if file_result is not None:
                reason = file_result[0]
        elif proposal.tool_name == "shell":
            action_input = proposal.tool_args.get("input")
            action = proposal.tool_args.get("action")
            if action in (None, "run") and isinstance(action_input, dict):
                reason = _shell_risk_reason(
                    str(action_input.get("command", "")),
                    config,
                    cwd=action_input.get("working_dir"),
                )
        if not reason:
            return GuardDecision.allow()
        request_id, path = _record_pending(workdir, config, proposal, reason)
        return GuardDecision.deny(
            check_name=GATE_CHECK_NAME,
            reason=f"{reason}; pending dual-channel approval {request_id}",
            metadata={
                "pending_request_id": request_id,
                "pending_request_path": str(path),
                "approval_channels": list(APPROVAL_CHANNELS),
            },
        )

    risky_action_check.__name__ = GATE_CHECK_NAME
    return risky_action_check


def expire_pending(path: str | os.PathLike[str], *, now: datetime | None = None) -> dict[str, Any]:
    """Mark an unapproved request expired; expired requests are never replayable."""
    request_path = Path(path)
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    if payload.get("status") != "pending":
        return payload
    created_raw = payload.get("created_at")
    try:
        created = datetime.fromisoformat(str(created_raw))
        ttl = int(payload.get("expires_in_seconds", DEFAULT_APPROVAL_TTL_SECONDS))
    except (TypeError, ValueError):
        # A malformed timestamp is not permission to execute; fail closed.
        payload["status"] = "expired"
    else:
        current = now or datetime.now(timezone.utc)
        if created + timedelta(seconds=max(ttl, 0)) <= current:
            payload["status"] = "expired"
    if payload.get("status") == "expired":
        _write_json_atomic(request_path, payload)
    return payload


def mark_approval(path: str | os.PathLike[str], channel: str, decision: str) -> dict[str, Any]:
    """Record one human approval leg; replay remains a separate worker concern."""
    if channel not in APPROVAL_CHANNELS:
        raise ValueError(f"unknown approval channel: {channel}")
    if decision not in {"approve", "deny"}:
        raise ValueError("decision must be approve or deny")
    request_path = Path(path)
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    if payload.get("status") != "pending":
        return payload
    payload.setdefault("approvals", {})[channel] = decision
    if decision == "deny":
        payload["status"] = "denied"
    elif all(payload["approvals"].get(item) == "approve" for item in APPROVAL_CHANNELS):
        payload["status"] = "approved"
    _write_json_atomic(request_path, payload)
    return payload
