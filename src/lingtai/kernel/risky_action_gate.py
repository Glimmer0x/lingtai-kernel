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
# Read-only verbs that ALSO accept a write-destination flag (e.g. sort -o,
# curl -o, wget -O, tee). A bare ``-o``/``--output``/``-O``/``-i``/``--in-place``
# would turn an otherwise read-only invocation into a write; reject them.
_READ_ONLY_WRITE_FLAGS = {"-o", "--output", "-O", "--outfile", "-i", "--in-place"}
_READ_ONLY_GIT_SUBCOMMANDS = {"branch", "diff", "log", "ls-files", "remote", "show", "status", "tag"}
# Git subcommands whose bare-name form is read-only but whose positional form
# mutates (branch <name> creates, tag <name> creates, remote add mutates).
_GIT_LIST_ONLY_SUBCOMMANDS = {"branch", "remote", "tag"}
_WRAPPERS = {"command", "env", "exec", "nohup", "sudo", "time", "doas"}
# Environment variables whose assignment can redirect execution or load hostile
# code; ``env PATH=/attacker ls`` must not be unwrapped into a read-only ``ls``.
_ENV_EXECUTION_REDIRECT_KEYS = {
    "PATH", "ENV", "BASH_ENV", "LD_PRELOAD", "LD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES",
    "PYTHONPATH", "PYTHONSTARTUP", "PERL5LIB", "RUBYLIB", "NODE_PATH", "GEM_HOME", "GEM_PATH",
}
_INTERPRETERS = {"bash", "fish", "node", "perl", "python", "python2", "python3", "ruby", "sh", "zsh"}
_CHAIN_SEPARATORS = ("&&", "||", ";", "|", "\n", ">>", ">", "<<", "<", "|&")


def _is_write_destination_flag(token: str) -> bool:
    """True for any token that names a write destination on a read-only verb.

    Covers the standalone flags (``-o``/``--output``/``-O``/``-i``), their
    joined short forms (``sort -oFILE``, ``wget -OFILE``, ``sed -i.bak``), and
    the long ``--output=``/``--outfile=``/``--in-place=`` assignments.
    """
    if token in _READ_ONLY_WRITE_FLAGS:
        return True
    if token.startswith(("--output=", "--outfile=", "--in-place=")):
        return True
    if len(token) > 2 and token.startswith(("-o", "-O", "-i")):
        return True
    return False


# Read-only options for each list-only git subcommand. An option token is
# accepted only when its option name (before any ``=``) is in this set; every
# other option on branch/tag/remote fails closed so option-only mutations
# (``--unset-upstream``, ``--set-upstream-to=``, ``--edit-description``,
# ``-a``/``-s``/``-m`` for tags, ``remote set-url``) cannot be smuggled in.
_GIT_LIST_ONLY_READ_ONLY_OPTIONS: dict[str, set[str]] = {
    "branch": {
        "--list", "-l", "--all", "-a", "--remotes", "-r", "--verbose", "-v",
        "--no-color", "--color", "--format", "--contains", "--merged",
        "--no-merged", "--points-at", "--show-current", "--quiet", "-q",
        "--column", "--no-column", "--abbrev", "--no-abbrev",
    },
    "tag": {
        "--list", "-l", "--sort", "--format", "--color", "--no-color",
        "--contains", "--merged", "--no-merged", "--points-at", "--column",
        "--no-column", "--verify", "-v",
    },
    "remote": {"--verbose", "-v"},
}

# For ``git remote`` the first positional is the sub-subcommand; only these
# query forms are read-only. Any other sub-subcommand fails closed.
_GIT_REMOTE_READ_ONLY_SUBCOMMANDS = {"get-url", "show"}


def _git_list_only_risk(tokens: list[str], subcommand: str) -> str | None:
    """Fail-closed check for git branch/tag/remote list-only forms.

    Returns ``None`` for a read-only list/query form and a reason string for
    every creation, mutation, or unknown-option form. Only the allowed options
    (``_GIT_LIST_ONLY_READ_ONLY_OPTIONS``) and, for remote, the read-only
    sub-subcommands are accepted; everything else is denied.
    """
    # Drop ``git`` and the subcommand itself (handles global options such as
    # ``git -C <dir> branch`` by scanning for the first non-option token).
    index = next((i for i, t in enumerate(tokens[1:], start=1) if not t.startswith("-")), None)
    rest = tokens[(index + 1):] if index is not None else []
    positionals = [t for t in rest if not t.startswith("-")]
    options = [t for t in rest if t.startswith("-")]
    allowed_options = _GIT_LIST_ONLY_READ_ONLY_OPTIONS.get(subcommand, set())
    for option in options:
        if option.split("=", 1)[0] not in allowed_options:
            return f"git {subcommand} option {option} is not a read-only form"
    if subcommand == "remote":
        if positionals and positionals[0] not in _GIT_REMOTE_READ_ONLY_SUBCOMMANDS:
            return f"git remote subcommand {positionals[0]} is not read-only"
        return None
    # branch / tag: a bare positional (no --list) is creation; only a single
    # ``--list <pattern>`` positional is read-only.
    if len(positionals) > 1:
        return f"git {subcommand} with multiple positional arguments is not read-only"
    if positionals and "--list" not in options:
        return f"git {subcommand} with a positional argument is not read-only"
    return None



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


# Environment-variable opt-in switch. The gate is opt-in and DEFAULT CLOSED:
# without ``LINGTAI_RISKY_ACTION_GATE`` set (or a ``.security/gate_config.json``
# present) existing agents see zero behavior change. Set it to a truthy value
# (``1``/``true``/``yes``/``on``) to enable the gate even without a config file;
# an empty config then denies every file write and every unclassified shell
# command until the deployment adds allowlists.
_GATE_OPT_IN_ENV = "LINGTAI_RISKY_ACTION_GATE"
_TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}


def _env_opt_in_enabled() -> bool:
    return os.environ.get(_GATE_OPT_IN_ENV, "").strip().lower() in _TRUTHY_ENV_VALUES


def load_gate_config(working_dir: str | os.PathLike[str]) -> dict[str, Any] | None:
    """Load the opt-in config and union its sibling shared-network grants.

    Returns ``None`` when the gate is not opted in at all: no config file AND
    no ``LINGTAI_RISKY_ACTION_GATE`` environment switch. When the env switch is
    present without a config file, returns an empty config (gate enabled,
    strict default).
    """
    workdir = Path(working_dir).expanduser().resolve()
    own_path = workdir / ".security" / "gate_config.json"
    if not own_path.is_file():
        if not _env_opt_in_enabled():
            return None
        return {}
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


def _unwrap(tokens: list[str]) -> list[str] | None:
    """Strip leading wrappers, returning ``None`` when a wrapper is unsafe.

    Returns the remaining tokens after benign wrappers (command/env/exec/etc.
    with plain flags and ordinary ``KEY=value`` assignments), or ``None`` when
    an ``env`` assignment redirects execution (PATH, LD_PRELOAD, PYTHONPATH,
    etc.) so the caller can fail closed instead of trusting the unwrapped verb.
    """
    index = 0
    while index < len(tokens) and tokens[index] in _WRAPPERS:
        wrapper = tokens[index]
        index += 1
        # ``env KEY=value command`` is common; skip assignments, but do not
        # attempt to model wrappers with option values (fail closed later).
        if wrapper == "env":
            while index < len(tokens) and "=" in tokens[index] and not tokens[index].startswith("="):
                key = tokens[index].split("=", 1)[0]
                if key in _ENV_EXECUTION_REDIRECT_KEYS:
                    return None
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
        unwrapped = _unwrap(tokens)
        if unwrapped is None:
            return "env assignment redirects execution (PATH/LD_*/PYTHONPATH/...)"
        tokens = unwrapped
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
            if subcommand in _GIT_LIST_ONLY_SUBCOMMANDS:
                reason = _git_list_only_risk(tokens, subcommand)
                if reason is not None:
                    return reason
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
        if any(_is_write_destination_flag(token) for token in tokens[1:]):
            return f"read-only verb {verb} carries a write-destination flag"
        if "/" in tokens[0]:
            # Any path-form executable (absolute, ../, bin/, ./) reduces to an
            # allowlisted basename via Path(...).name; only bare verbs are
            # classified read-only. Reject every path form so /tmp/ls, ../ls,
            # bin/ls, /usr/bin/printf and /usr/bin/env cannot masquerade as
            # their bare allowlisted names.
            return f"path-form executable {tokens[0]} is not a bare read-only verb"
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
        elif proposal.tool_name in ("shell", "bash"):
            # ``bash`` is the legacy compatibility name that the registry maps
            # to the ``shell`` capability after guard evaluation; treating it
            # as shell here prevents a compat-named shell call from bypassing
            # the opted-in gate.
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


def mark_approval(path: str | os.PathLike[str], channel: str, decision: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Record one human approval leg; replay remains a separate worker concern.

    An expired request is never replayable: this function refuses to record an
    approval (or anything else) on a request whose TTL has already elapsed, so
    a late human approval cannot resurrect an expired pending record.
    """
    if channel not in APPROVAL_CHANNELS:
        raise ValueError(f"unknown approval channel: {channel}")
    if decision not in {"approve", "deny"}:
        raise ValueError("decision must be approve or deny")
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
        _write_json_atomic(request_path, payload)
        return payload
    current = now or datetime.now(timezone.utc)
    if created + timedelta(seconds=max(ttl, 0)) <= current:
        payload["status"] = "expired"
        _write_json_atomic(request_path, payload)
        return payload
    payload.setdefault("approvals", {})[channel] = decision
    if decision == "deny":
        payload["status"] = "denied"
    elif all(payload["approvals"].get(item) == "approve" for item in APPROVAL_CHANNELS):
        payload["status"] = "approved"
    _write_json_atomic(request_path, payload)
    return payload
