"""Built-in tool registry — the composition seam owned by ``lingtai.tools``.

This is the tools' own catalog data plus the composition helpers that boot them
onto an agent. It owns two layers:

- :data:`INTRINSICS` — the mandatory-intrinsics mapping injected into
  ``BaseAgent(intrinsics=...)`` (the kernel reads it from ``lingtai.tools.registry``).
- the dynamic-capability registry: :data:`BUILTIN_TOOLS` (capability name →
  ``lingtai.tools.<pkg>`` module path), :data:`CORE_DEFAULTS`,
  :func:`setup_capability`, :func:`apply_core_defaults`,
  :func:`normalize_capabilities`,
  :func:`get_all_providers`, :data:`CAPABILITY_UNAVAILABLE`.

Import discipline: capability modules are resolved with ``importlib`` *inside*
:func:`setup_capability` / :func:`get_all_providers`, never at module top, so
``import lingtai.tools.registry`` does not eagerly import every tool (and, for the two
capability tools that lazily import ``lingtai`` services, does not pull
``lingtai``). The five intrinsic modules ARE imported statically below because
they are mandatory and cheap; they live under ``lingtai.tools`` and import only
``lingtai.kernel``.
"""
from __future__ import annotations

import copy
import importlib
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Mapping

# Register the tool string catalogs into the kernel i18n cache. Importing the
# registry is the canonical "tools are in play" signal, so this is where the
# en/zh/wen tool strings get injected via lingtai.kernel.i18n.register_strings.
from . import i18n as _i18n  # noqa: F401  (import side effect: register_strings)

if TYPE_CHECKING:
    from lingtai.kernel.base_agent import BaseAgent


# ---------------------------------------------------------------------------
# Layer 1 — mandatory intrinsic tools (injected into BaseAgent)
# ---------------------------------------------------------------------------
#
# Each value has the shape ``{"module": <module>}``; the module exposes the
# duck-typed intrinsic protocol: ``get_schema(lang)``, ``get_description(lang)``,
# ``handle(agent, args)``, and optionally ``boot(agent)``. ``BaseAgent`` iterates
# this mapping in ``_wire_intrinsics``; membership here is the mandatory-include
# mechanism (there is no manifest gate for intrinsics).
from . import email, system, psyche, soul, notification  # noqa: E402  (lingtai.tools.<pkg>)

INTRINSICS: dict[str, dict[str, Any]] = {
    "email": {"module": email},
    "system": {"module": system},
    "psyche": {"module": psyche},
    "soul": {"module": soul},
    "notification": {"module": notification},
}


# ---------------------------------------------------------------------------
# Layer 2 — dynamic capability tools (composed via setup_capability)
# ---------------------------------------------------------------------------


class _CapabilityUnavailable:
    """Signal that a capability setup skipped before registering tools."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "CAPABILITY_UNAVAILABLE"


CAPABILITY_UNAVAILABLE = _CapabilityUnavailable()

# Registry of built-in capability names → module paths. All entries are absolute
# ``lingtai.tools.<pkg>`` paths (this package is flat: no relative-vs-absolute split like
# the old capabilities/core divide). Resolved lazily by importlib inside
# setup_capability so importing the registry never imports every tool.
BUILTIN_TOOLS: dict[str, str] = {
    "knowledge": "lingtai.tools.knowledge",
    "skills": "lingtai.tools.skills",
    # ``bash`` remains a one-way read-only input alias only; the public
    # capability is canonically named ``shell`` while its implementation stays
    # in the retained internal package.
    "shell": "lingtai.tools.bash",
    "avatar": "lingtai.tools.avatar",
    "daemon": "lingtai.tools.daemon",
    "mcp": "lingtai.tools.mcp",
    # Unified public file capability: one package owning the composed schema,
    # the envelope dispatch, and all five operation implementations. The
    # pre-migration ``read``/``write``/``edit``/``glob``/``grep`` capabilities
    # and packages are gone, with no alias — those names now fail loudly.
    "file": "lingtai.tools.file",
    "vision": "lingtai.tools.vision",
    # Unified public web capability.  ``web_search`` is a one-way input alias
    # below so old presets materialize this single handler.
    "web": "lingtai.tools.web_search",
}

# Capabilities that boot by default on every Agent — the always-on floor.
# init.json's ``manifest.capabilities`` only needs to declare overrides (kwargs)
# or opt-ins beyond this set; ``manifest.disable`` is the opt-out channel.
#
# ``shell`` defaults to {"yolo": True} (unsandboxed). Hosts that want a sandbox
# pass {"policy_file": "..."} in init.json, which overrides the default kwargs.
# ``vision`` and ``web_search`` are NOT in this set — they require provider
# config and API keys, so they stay explicit opt-in.
CORE_DEFAULTS: dict[str, dict] = {
    "knowledge": {},
    "skills": {},
    "shell": {"yolo": True},
    "avatar": {},
    "daemon": {},
    "mcp": {},
    "file": {},
}


def apply_core_defaults(
    capabilities: dict[str, dict] | None,
    disable: list[str] | None = None,
) -> dict[str, dict]:
    """Merge ``CORE_DEFAULTS`` with user-supplied capabilities and drop disabled.

    Resolution order (per capability name):
    1. Start with ``CORE_DEFAULTS``.
    2. Overlay ``capabilities`` from init.json — init.json kwargs win on conflict.
       Entries with name not in ``CORE_DEFAULTS`` (e.g. ``vision``,
       ``web_search``) pass through unchanged.
    3. Drop any name listed in ``disable``.

    Returns a fresh dict; does not mutate inputs.
    """
    out: dict[str, dict] = {name: dict(kwargs) for name, kwargs in CORE_DEFAULTS.items()}
    if capabilities:
        # Normalize here too because callers loading init/preset data may call
        # this helper directly without first passing through Agent.
        for name, kwargs in normalize_capabilities(capabilities).items():
            if kwargs is None:
                # Explicit ``"name": null`` from JSON — disable without needing
                # the ``disable`` list. Useful for one-off opt-outs in init.json.
                out.pop(name, None)
                continue
            if name in out and isinstance(out[name], dict) and isinstance(kwargs, dict):
                merged = dict(out[name])
                merged.update(kwargs)
                out[name] = merged
            else:
                out[name] = kwargs
    if disable:
        for name in disable:
            out.pop(canonical_capability_name(name), None)
    return out


# One-way configuration input aliases: a retained legacy config key on the left,
# the canonical public capability it materializes on the right. Never emitted as
# a public capability or tool name. The five pre-migration file capabilities
# (``read``/``write``/``edit``/``glob``/``grep``) are deliberately absent — the
# ``file`` migration was a clean break, so those names are unknown capabilities
# and fail loudly rather than resolving silently.
_LEGACY_CAPABILITY_ALIASES: dict[str, str] = {
    "bash": "shell",
    "web_search": "web",
}


class CapabilityShapeDecision(str, Enum):
    """Typed result of the one canonical/legacy capability-shape evaluator."""

    PASS = "PASS"
    NUDGE = "NUDGE"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class CapabilityShapeEvidence:
    """Redaction-safe raw/effective evidence for capability compatibility."""

    decision: CapabilityShapeDecision
    compatibility_paths: tuple[dict[str, str], ...] = ()
    conflict_paths: tuple[str, ...] = ()


class CapabilityShapeConflict(ValueError):
    """Raised when canonical and legacy capability values disagree."""


def canonical_capability_name(name: str) -> str:
    """Return the public capability name for a retained legacy input key."""
    return _LEGACY_CAPABILITY_ALIASES.get(name, name)


def _copy_configuration(value: Any) -> Any:
    """Copy JSON-like containers while preserving opaque injected dependencies.

    Browser ports, fake services, locks, clients, and other runtime objects are
    caller-owned identity-bearing values.  ``deepcopy`` silently detached them
    during capability normalization; only configuration containers are copied.
    """
    if isinstance(value, dict):
        return {key: _copy_configuration(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy_configuration(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_copy_configuration(item) for item in value)
    if isinstance(value, set):
        return {_copy_configuration(item) for item in value}
    return value


def classify_capabilities(
    capabilities: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], CapabilityShapeEvidence]:
    """Evaluate and materialize the sole ``bash`` -> ``shell`` compatibility rule.

    The input is never mutated. A legacy-only or equal dual spelling is copied to
    one effective ``shell`` entry and produces ``NUDGE`` evidence. Differing dual
    values fail closed rather than allowing canonical-wins normalization. The
    returned mapping is the exact in-memory input for downstream capability setup.
    """
    if capabilities is None:
        return {}, CapabilityShapeEvidence(CapabilityShapeDecision.UNKNOWN)
    if not isinstance(capabilities, Mapping):
        return {}, CapabilityShapeEvidence(CapabilityShapeDecision.UNKNOWN)

    out = {key: _copy_configuration(value) for key, value in capabilities.items()}
    compatibility: list[dict[str, str]] = []
    conflicts: list[str] = []
    for legacy, canonical in _LEGACY_CAPABILITY_ALIASES.items():
        if legacy not in out:
            continue
        mapping = {
            "raw_path": f"manifest.capabilities.{legacy}",
            "effective_path": f"manifest.capabilities.{canonical}",
        }
        compatibility.append(mapping)
        if canonical in out and out[legacy] != out[canonical]:
            conflicts.extend((mapping["raw_path"], mapping["effective_path"]))
    if conflicts:
        return out, CapabilityShapeEvidence(
            CapabilityShapeDecision.BLOCKED,
            compatibility_paths=tuple(compatibility),
            conflict_paths=tuple(conflicts),
        )
    if compatibility:
        for legacy, canonical in _LEGACY_CAPABILITY_ALIASES.items():
            if legacy in out:
                if canonical not in out:
                    out[canonical] = out[legacy]
                out.pop(legacy, None)
        return out, CapabilityShapeEvidence(
            CapabilityShapeDecision.NUDGE,
            compatibility_paths=tuple(compatibility),
        )
    return out, CapabilityShapeEvidence(CapabilityShapeDecision.PASS)


def normalize_capabilities(capabilities: dict[str, dict]) -> dict[str, dict]:
    """Normalize capability configuration using the reader's shape decision.

    Legacy ``bash`` is accepted only as read-only input. Equal dual values and
    legacy-only input materialize one canonical ``shell`` mapping; a differing
    dual pair raises :class:`CapabilityShapeConflict` instead of silently
    choosing one side.
    """
    normalized, evidence = classify_capabilities(capabilities)
    if evidence.decision is CapabilityShapeDecision.BLOCKED:
        raise CapabilityShapeConflict(
            "conflicting capability aliases: "
            + ", ".join(evidence.conflict_paths)
        )
    if evidence.decision is CapabilityShapeDecision.UNKNOWN:
        raise CapabilityShapeConflict("unclassifiable manifest.capabilities shape")

    out: dict[str, dict] = {}
    for name, kwargs in normalized.items():
        destination = canonical_capability_name(name)
        if destination in out:
            # This is defensive for future aliases. The current evaluator has
            # already collapsed bash/shell and therefore cannot reach here.
            existing = out[destination]
            if isinstance(existing, dict) and isinstance(kwargs, dict):
                merged = dict(existing)
                merged.update(kwargs)
                out[destination] = merged
            continue
        out[destination] = kwargs
    return out


def setup_capability(agent: "BaseAgent", name: str, **kwargs: Any) -> Any:
    """Look up a capability by *name* and call its ``setup(agent, **kwargs)``.

    A setup function returns a manager instance or ``None`` after successful
    registration. ``None`` is success for several core capabilities. To skip
    registration, setup must return ``CAPABILITY_UNAVAILABLE`` before calling
    ``add_tool()``.

    Raises ``ValueError`` if the name is unknown or the module lacks ``setup``.
    """
    name = canonical_capability_name(name)
    module_path = BUILTIN_TOOLS.get(name)
    if module_path is None:
        raise ValueError(
            f"Unknown capability: {name!r}. "
            f"Available: {', '.join(sorted(BUILTIN_TOOLS))}."
        )
    mod = importlib.import_module(module_path)
    setup_fn = getattr(mod, "setup", None)
    if setup_fn is None:
        raise ValueError(
            f"Capability module {name!r} does not export a setup() function"
        )
    return setup_fn(agent, **kwargs)


def get_all_providers() -> dict[str, dict]:
    """Return provider metadata for all user-facing capabilities.

    Returns a dict mapping capability name to
    ``{"providers": [...], "default": ... }``.
    Used by ``lingtai-agent check-caps`` CLI.
    """
    _USER_FACING: dict[str, str] = {
        "file": "lingtai.tools.file",
        "shell": "lingtai.tools.bash",
        "web": "lingtai.tools.web_search",
        "knowledge": "lingtai.tools.knowledge",
        "skills": "lingtai.tools.skills",
        "vision": "lingtai.tools.vision",
        "avatar": "lingtai.tools.avatar",
        "daemon": "lingtai.tools.daemon",
    }
    result = {}
    for name, module_path in _USER_FACING.items():
        mod = importlib.import_module(module_path)
        providers = getattr(mod, "PROVIDERS", None)
        if providers is not None:
            result[name] = dict(providers)
        else:
            result[name] = {"providers": [], "default": "builtin"}
    return result
