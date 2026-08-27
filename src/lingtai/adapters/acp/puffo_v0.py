"""Operator-managed runtime registry for the constrained Puffo ACP profile."""
from __future__ import annotations

from contextlib import contextmanager, suppress
import hashlib
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


PROFILE_NAME = "puffo-v0"
REGISTRY_VERSION = 2
REVOCATION_LOG_REQUIRED = "required"
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


def _require_posix_registry_security() -> None:
    """Fail closed until puffo-v0 has an owner-only Windows ACL adapter.

    POSIX file modes are part of this profile's control-plane confidentiality
    boundary.  Windows cannot provide the equivalent guarantee through chmod,
    so this Phase A registry deliberately has no Windows implementation rather
    than silently creating a broadly readable registry there.
    """

    if os.name != "posix":
        raise PuffoV0RegistryError(
            "puffo-v0 registry requires POSIX owner-only filesystem permissions"
        )


def _secure_registry_directory(path: Path) -> None:
    """Create and harden the registry parent independently of umask."""

    _require_posix_registry_security()
    try:
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
        os.chmod(path, 0o700)
    except OSError as exc:
        raise PuffoV0RegistryError(
            "puffo-v0 runtime registry directory could not be secured"
        ) from exc


def _secure_registry_file(path: Path) -> bool:
    """Harden an existing registry artifact; return false when it is absent."""

    _require_posix_registry_security()
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise PuffoV0RegistryError("puffo-v0 runtime registry is unavailable or invalid") from exc
    if not stat.S_ISREG(mode):
        raise PuffoV0RegistryError("puffo-v0 runtime registry has an invalid file type")
    try:
        os.chmod(path, 0o600)
    except OSError as exc:
        raise PuffoV0RegistryError("puffo-v0 runtime registry could not be secured") from exc
    return True


def _revocation_log_path(path: Path) -> Path:
    """Return the append-only, owner-only tombstone log beside a registry."""

    return path.with_name(f".{path.name}.revocations.jsonl")


def _initialize_revocation_log(path: Path) -> None:
    """Create the mandatory empty tombstone log before first registry write."""

    _secure_registry_directory(path.parent)
    tombstones = _revocation_log_path(path)
    descriptor: int | None = None
    try:
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(tombstones, flags, 0o600)
        os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
    except FileExistsError as exc:
        raise PuffoV0RegistryError(
            "puffo-v0 registry initialization found an unexpected revocation log"
        ) from exc
    except OSError as exc:
        raise PuffoV0RegistryError("puffo-v0 revocation log could not be initialized") from exc
    finally:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)


def _read_revoked_runtime_ids(path: Path) -> frozenset[str]:
    """Read monotonic revocation tombstones, rejecting malformed local state."""

    tombstones = _revocation_log_path(path)
    if not _secure_registry_file(tombstones):
        raise PuffoV0RegistryError("puffo-v0 revocation log is unavailable or invalid")
    try:
        lines = tombstones.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise PuffoV0RegistryError("puffo-v0 revocation log is unavailable or invalid") from exc
    revoked: set[str] = set()
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise PuffoV0RegistryError("puffo-v0 revocation log is unavailable or invalid") from exc
        if not isinstance(entry, dict) or set(entry) != {"runtime_id"}:
            raise PuffoV0RegistryError("puffo-v0 revocation log is unavailable or invalid")
        revoked.add(_valid_runtime_id(entry["runtime_id"]))
    return frozenset(revoked)


def _append_revocation_tombstone(path: Path, runtime_id: str) -> None:
    """Persist a terminal revocation before the mutable registry is updated."""

    _secure_registry_directory(path.parent)
    tombstones = _revocation_log_path(path)
    descriptor: int | None = None
    try:
        flags = os.O_APPEND | os.O_WRONLY
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(tombstones, flags, 0o600)
        os.fchmod(descriptor, 0o600)
        payload = (json.dumps({"runtime_id": runtime_id}, sort_keys=True) + "\n").encode("utf-8")
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written == 0:
                raise OSError("short write to puffo-v0 revocation log")
            offset += written
        os.fsync(descriptor)
    except OSError as exc:
        raise PuffoV0RegistryError("puffo-v0 revocation log could not be written") from exc
    finally:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)


@contextmanager
def _registry_mutation_lock(path: Path) -> Iterator[None]:
    """Serialize one registry read-modify-write across local processes."""

    _secure_registry_directory(path.parent)
    lock_path = path.with_name(f".{path.name}.lock")
    try:
        flags = os.O_CREAT | os.O_RDWR
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(lock_path, flags, 0o600)
        os.fchmod(descriptor, 0o600)
    except OSError as exc:
        raise PuffoV0RegistryError("puffo-v0 runtime registry lock is unavailable") from exc

    try:
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_EX)
    except OSError as exc:
        with suppress(OSError):
            os.close(descriptor)
        raise PuffoV0RegistryError("puffo-v0 runtime registry lock is unavailable") from exc
    try:
        yield
    finally:
        with suppress(OSError):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        with suppress(OSError):
            os.close(descriptor)


def _read_registry(path: Path) -> dict[str, Any]:
    _secure_registry_file(path)
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PuffoV0RegistryError("puffo-v0 runtime registry is unavailable or invalid") from exc
    if not isinstance(data, dict) or set(data) != {"revocation_log", "runtimes", "version"}:
        raise PuffoV0RegistryError("puffo-v0 runtime registry has an invalid shape")
    if (
        data["version"] != REGISTRY_VERSION
        or data["revocation_log"] != REVOCATION_LOG_REQUIRED
        or not isinstance(data["runtimes"], dict)
    ):
        raise PuffoV0RegistryError("puffo-v0 runtime registry has an unsupported version")
    return data


def _write_registry(path: Path, data: dict[str, Any]) -> None:
    _secure_registry_directory(path.parent)
    temporary: Path | None = None
    try:
        descriptor, raw_temporary = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary = Path(raw_temporary)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except OSError as exc:
        if temporary is not None:
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
    with _registry_mutation_lock(path):
        if path.exists():
            revoked_runtime_ids = _read_revoked_runtime_ids(path)
            registry = _read_registry(path)
        else:
            _initialize_revocation_log(path)
            revoked_runtime_ids = frozenset()
            registry = {
                "revocation_log": REVOCATION_LOG_REQUIRED,
                "version": REGISTRY_VERSION,
                "runtimes": {},
            }
        if runtime_id in revoked_runtime_ids:
            raise PuffoV0RegistryError("runtime_id is revoked and cannot be provisioned again")
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
    path = registry_path or default_registry_path()
    with _registry_mutation_lock(path):
        registry = _read_registry(path)
        entry = registry["runtimes"].get(runtime_id)
        if not isinstance(entry, dict):
            raise PuffoV0RegistryError("runtime_id is not provisioned")
        if runtime_id not in _read_revoked_runtime_ids(path):
            _append_revocation_tombstone(path, runtime_id)
        entry["status"] = "revoked"
        canonical = {key: value for key, value in entry.items() if key != "config_digest"}
        entry["config_digest"] = _digest(canonical)
        _write_registry(path, registry)


def resolve_runtime(
    runtime_id: str, *, registry_path: Path | None = None
) -> PuffoV0Runtime:
    """Resolve one active runtime id into an immutable local spawn specification."""

    runtime_id = _valid_runtime_id(runtime_id)
    path = registry_path or default_registry_path()
    _secure_registry_directory(path.parent)
    if runtime_id in _read_revoked_runtime_ids(path):
        raise PuffoV0RegistryError("runtime registry entry is inactive or does not match puffo-v0")
    registry = _read_registry(path)
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
