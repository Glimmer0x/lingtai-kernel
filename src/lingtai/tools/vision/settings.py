"""Strict per-Agent settings for the ``vision`` capability's local endpoint.

``settings/vision.json`` is a family-owned provider configuration file for the
``provider: local`` route: it holds the operator-configured local
OpenAI-compatible vision endpoint (``base_url``, ``model``, optional
``api_key``/``max_tokens``). It mirrors the ``settings/web.json`` pattern from
``lingtai.tools.web_search.settings``: a bounded, race-checked read with a
stable digest so "default applied" is a truthful, verifiable fact.

Resolution order at capability setup: capability kwargs override
``settings/vision.json``; a missing file means defaults apply (base_url
defaults to the standard local port; model stays unset and setup raises
guided manual guidance). An invalid file is a hard setup error surfaced as
manual guidance, never a silent fallback.
"""
from __future__ import annotations

import hashlib
import json
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from lingtai.kernel.tool_plugin import WorkdirPort

MAX_SETTINGS_BYTES = 64 * 1024

DEFAULT_LOCAL_BASE_URL = "http://localhost:11434/v1"


class SettingsError(ValueError):
    """A settings snapshot was absent, unstable, malformed, or disallowed."""


@dataclass(frozen=True, slots=True)
class LocalVisionSettings:
    """Resolved local vision endpoint settings snapshot.

    ``base_url`` is the OpenAI-compatible endpoint URL. ``model`` is the
    vision model served at that endpoint; ``None`` means the operator has not
    configured one yet (setup must raise guided guidance). ``api_key`` is
    optional: local servers ignore it, so a placeholder satisfies the OpenAI
    SDK when unset. ``max_tokens`` caps the response length when set.
    """

    base_url: str | None
    model: str | None
    api_key: str | None
    max_tokens: int | None
    source: str
    revision: str
    digest: str | None
    error: str | None = None


def settings_path(workdir: "WorkdirPort") -> Path:
    """Return the one fixed, family-owned local vision settings path."""
    return workdir.path / "settings" / "vision.json"


def _default_snapshot() -> LocalVisionSettings:
    """Return the deterministic snapshot for a missing ``settings/vision.json``.

    ``revision``/``digest`` are computed over the effective default document
    (``{"schema_version": 1}``) so a caller can recompute and verify.
    """
    canonical = json.dumps(
        {"schema_version": 1},
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()[:32]
    return LocalVisionSettings(None, None, None, None, "default", "default", digest)


def _bounded_error(exc: Exception) -> str:
    # OS errors commonly include the absolute path passed to ``open``. The
    # result contract exposes only the agent-relative settings path, never the
    # host filesystem location.
    if isinstance(exc, OSError):
        return "settings/vision.json could not be read (OSError)"
    text = str(exc).replace("\n", " ").strip()
    return (text or "invalid settings")[:240]


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SettingsError("duplicate settings field")
        result[key] = value
    return result


def _read_stable(path: Path) -> tuple[bytes, str]:
    """Bounded, race-checked read of ``settings/vision.json``."""
    try:
        first = path.lstat()
    except FileNotFoundError:
        return b"", "missing"
    if stat.S_ISLNK(first.st_mode) or not stat.S_ISREG(first.st_mode):
        raise SettingsError("settings/vision.json must be a regular file")
    if first.st_size > MAX_SETTINGS_BYTES:
        raise SettingsError("settings/vision.json exceeds the 64 KiB size bound")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SettingsError(_bounded_error(exc)) from exc
    if len(raw) > MAX_SETTINGS_BYTES:
        raise SettingsError("settings/vision.json exceeds the 64 KiB size bound")
    try:
        second = path.lstat()
    except OSError as exc:
        raise SettingsError(_bounded_error(exc)) from exc
    if (second.st_mtime_ns, second.st_size) != (first.st_mtime_ns, first.st_size):
        raise SettingsError("settings/vision.json changed while being read")
    return raw, "file"


def _validate(doc: dict[str, Any]) -> LocalVisionSettings:
    """Validate a parsed vision settings document into a frozen snapshot."""
    allowed = {"schema_version", "base_url", "model", "api_key", "max_tokens"}
    unknown = sorted(set(doc) - allowed)
    if unknown:
        raise SettingsError(
            "settings/vision.json has unknown fields: " + ", ".join(unknown)
        )
    if doc.get("schema_version") != 1:
        raise SettingsError("settings/vision.json schema_version must be integer 1")

    base_url = doc.get("base_url")
    if base_url is not None and (
        not isinstance(base_url, str) or not base_url.strip()
    ):
        raise SettingsError("settings/vision.json base_url must be a non-empty string")
    model = doc.get("model")
    if model is not None and (not isinstance(model, str) or not model.strip()):
        raise SettingsError("settings/vision.json model must be a non-empty string")
    api_key = doc.get("api_key")
    if api_key is not None and not isinstance(api_key, str):
        raise SettingsError("settings/vision.json api_key must be a string")
    max_tokens = doc.get("max_tokens")
    if max_tokens is not None and (
        not isinstance(max_tokens, int)
        or isinstance(max_tokens, bool)
        or max_tokens <= 0
    ):
        raise SettingsError(
            "settings/vision.json max_tokens must be a positive integer"
        )

    canonical = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()[:32]
    return LocalVisionSettings(
        base_url=base_url.strip() if isinstance(base_url, str) else None,
        model=model.strip() if isinstance(model, str) else None,
        api_key=api_key,
        max_tokens=max_tokens,
        source="file",
        revision=digest,
        digest=digest,
    )


def read_local_settings(workdir: "WorkdirPort") -> LocalVisionSettings:
    """Read and validate the shared ``settings/vision.json`` snapshot.

    A missing file returns the deterministic default snapshot (no error). A
    present-but-invalid file raises ``SettingsError`` so setup can surface
    guided manual guidance instead of silently falling back.
    """
    path = settings_path(workdir)
    try:
        raw, source = _read_stable(path)
    except SettingsError:
        raise
    if source == "missing":
        return _default_snapshot()
    try:
        doc = json.loads(raw, object_pairs_hook=_pairs)
    except SettingsError:
        raise
    except Exception as exc:
        raise SettingsError(_bounded_error(exc)) from exc
    if not isinstance(doc, dict):
        raise SettingsError("settings/vision.json must contain a JSON object")
    return _validate(doc)
