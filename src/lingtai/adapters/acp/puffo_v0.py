"""Operator-managed runtime registry for the constrained Puffo ACP profile."""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROFILE_NAME = "puffo-v0"
REGISTRY_VERSION = 1
FORCED_DISABLED_CAPABILITIES = frozenset({"avatar", "daemon", "mcp"})
_RUNTIME_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")


class PuffoV0RegistryError(ValueError):
    """A registry failure safe to expose as a bounded local startup error."""


@dataclass(frozen=True, slots=True)
class PuffoV0Runtime:
    """One pre-provisioned local identity selected by an opaque runtime id."""

    runtime_id: str
    agent_dir: Path
    workspace: Path
    config_digest: str


def default_registry_path() -> Path:
    """Return the one operator-managed registry location for this profile."""

    return Path.home() / ".lingtai" / PROFILE_NAME / "runtime-registry.json"


def _valid_runtime_id(runtime_id: object) -> str:
    if not isinstance(runtime_id, str) or _RUNTIME_ID.fullmatch(runtime_id) is None:
        raise PuffoV0RegistryError("runtime_id must be an opaque local identifier")
    return runtime_id


def _canonical_directory(path: Path, *, field: str) -> Path:
    try:
        resolved = path.expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise PuffoV0RegistryError(f"{field} must be an existing directory") from exc
    if not resolved.is_dir():
        raise PuffoV0RegistryError(f"{field} must be an existing directory")
    return resolved


def _canonical_entry(runtime_id: str, agent_dir: Path, workspace: Path) -> dict[str, Any]:
    return {
        "agent_dir": str(agent_dir),
        "disabled_capabilities": sorted(FORCED_DISABLED_CAPABILITIES),
        "mcp_servers": [],
        "profile": PROFILE_NAME,
        "runtime_id": runtime_id,
        "status": "active",
        "workspace": str(workspace),
    }


def _digest(entry: dict[str, Any]) -> str:
    canonical = json.dumps(entry, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _read_registry(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PuffoV0RegistryError("puffo-v0 runtime registry is unavailable or invalid") from exc
    if not isinstance(data, dict) or set(data) != {"runtimes", "version"}:
        raise PuffoV0RegistryError("puffo-v0 runtime registry has an invalid shape")
    if data["version"] != REGISTRY_VERSION or not isinstance(data["runtimes"], dict):
        raise PuffoV0RegistryError("puffo-v0 runtime registry has an unsupported version")
    return data


def _write_registry(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise PuffoV0RegistryError("puffo-v0 runtime registry could not be written") from exc


def provision_runtime(
    runtime_id: str,
    agent_dir: Path,
    workspace: Path,
    *,
    registry_path: Path | None = None,
) -> PuffoV0Runtime:
    """Bind one existing persistent agent identity to a local runtime id.

    This is an operator control-plane operation.  The ACP data-plane accepts
    only the resulting id and never accepts either filesystem path.
    """

    runtime_id = _valid_runtime_id(runtime_id)
    agent_dir = _canonical_directory(agent_dir, field="agent_dir")
    workspace = _canonical_directory(workspace, field="workspace")
    if not (agent_dir / "init.json").is_file():
        raise PuffoV0RegistryError("agent_dir must contain init.json")
    path = registry_path or default_registry_path()
    if path.exists():
        registry = _read_registry(path)
    else:
        registry = {"version": REGISTRY_VERSION, "runtimes": {}}
    runtimes = registry["runtimes"]
    if runtime_id in runtimes:
        raise PuffoV0RegistryError("runtime_id is already provisioned")
    entry = _canonical_entry(runtime_id, agent_dir, workspace)
    entry["config_digest"] = _digest(entry)
    runtimes[runtime_id] = entry
    _write_registry(path, registry)
    return PuffoV0Runtime(runtime_id, agent_dir, workspace, entry["config_digest"])


def revoke_runtime(runtime_id: str, *, registry_path: Path | None = None) -> None:
    """Mark a provisioned profile identity unavailable for future ACP spawns."""

    runtime_id = _valid_runtime_id(runtime_id)
    registry = _read_registry(registry_path or default_registry_path())
    entry = registry["runtimes"].get(runtime_id)
    if not isinstance(entry, dict):
        raise PuffoV0RegistryError("runtime_id is not provisioned")
    entry["status"] = "revoked"
    canonical = {key: value for key, value in entry.items() if key != "config_digest"}
    entry["config_digest"] = _digest(canonical)
    _write_registry(registry_path or default_registry_path(), registry)


def resolve_runtime(
    runtime_id: str, *, registry_path: Path | None = None
) -> PuffoV0Runtime:
    """Resolve one active runtime id into an immutable local spawn specification."""

    runtime_id = _valid_runtime_id(runtime_id)
    registry = _read_registry(registry_path or default_registry_path())
    entry = registry["runtimes"].get(runtime_id)
    if not isinstance(entry, dict):
        raise PuffoV0RegistryError("runtime_id is not provisioned")
    expected_keys = {
        "agent_dir", "config_digest", "disabled_capabilities", "mcp_servers",
        "profile", "runtime_id", "status", "workspace",
    }
    if set(entry) != expected_keys:
        raise PuffoV0RegistryError("runtime registry entry has an invalid shape")
    canonical = {key: value for key, value in entry.items() if key != "config_digest"}
    if (
        entry.get("profile") != PROFILE_NAME
        or entry.get("runtime_id") != runtime_id
        or entry.get("status") != "active"
        or entry.get("disabled_capabilities") != sorted(FORCED_DISABLED_CAPABILITIES)
        or entry.get("mcp_servers") != []
        or not isinstance(entry.get("config_digest"), str)
        or entry["config_digest"] != _digest(canonical)
    ):
        raise PuffoV0RegistryError("runtime registry entry is inactive or does not match puffo-v0")
    if not isinstance(entry.get("agent_dir"), str) or not isinstance(entry.get("workspace"), str):
        raise PuffoV0RegistryError("runtime registry entry has invalid paths")
    agent_dir = _canonical_directory(Path(entry["agent_dir"]), field="agent_dir")
    workspace = _canonical_directory(Path(entry["workspace"]), field="workspace")
    if not (agent_dir / "init.json").is_file():
        raise PuffoV0RegistryError("registered agent identity is no longer initialized")
    return PuffoV0Runtime(runtime_id, agent_dir, workspace, entry["config_digest"])


__all__ = [
    "FORCED_DISABLED_CAPABILITIES",
    "PROFILE_NAME",
    "PuffoV0RegistryError",
    "PuffoV0Runtime",
    "default_registry_path",
    "provision_runtime",
    "resolve_runtime",
    "revoke_runtime",
]
