"""Avatar's package-local model-facing descriptor and packaged manual owner.

This is deliberately a narrow static seam.  It owns the model-facing root's
name, description, strict action schemas, and the resource that backs Avatar's
flat ``manual`` result.  It does not construct agents, decide privileges,
register tools, create network state, or manage processes; those remain in
:class:`AvatarManager` and ``setup``.
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from typing import Any, Callable, Mapping

from ..tool_family import ChildTool, ToolFamily
from ..tool_family.manual import MANUAL_INPUT_SCHEMA

__all__ = ["AVATAR_TOOL_DESCRIPTOR", "AvatarToolDescriptor"]

# Canonical, strict per-action input schemas. Optionals are expressed as
# nullable required properties because that is what strict OpenAI-style
# validators demand of a closed object; null means "absent" to the action
# implementations (see ``AvatarManager._strip_nulls``).
#
# The spawn mission brief is deliberately NOT a property here: it is root
# ``reasoning``, and nested ``input`` must never carry
# ``reasoning``/``_reasoning``/``summarize``.
_SPAWN_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": (
                "True name for the avatar. Also the working-directory basename "
                "under .lingtai/. Single segment: letters/digits/underscore/"
                "hyphen, max 64 chars."
            ),
        },
        "type": {
            "type": ["string", "null"],
            "enum": ["shallow", "deep", None],
            "description": (
                "'shallow' (default): blank slate — init.json only. 'deep': "
                "full copy of character, pad, and codex. Null for the default."
            ),
        },
        "comment": {
            "type": ["string", "null"],
            "description": (
                "Persistent system note in the avatar's prompt (survives molt/"
                "refresh/wake). Not inherited. Null or empty unless you have "
                "something the avatar must never forget."
            ),
        },
        "dry_run": {
            "type": ["boolean", "null"],
            "description": (
                "Preview the spawn without creating a process. Use to "
                "sanity-check before committing. Null for the default false."
            ),
        },
        "confirm": {
            "type": ["boolean", "null"],
            "description": (
                "Confirm you have reviewed the mission and intend to spawn. "
                "Required when the mission looks empty/short/test-like. Null "
                "for the default false."
            ),
        },
    },
    "required": ["name", "type", "comment", "dry_run", "confirm"],
    "additionalProperties": False,
}

_RULES_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "rules_content": {
            "type": "string",
            "description": (
                "Plain text, one rule per line. Non-negotiable constraints "
                "distributed to self and all descendants. Requires karma."
            ),
        },
    },
    "required": ["rules_content"],
    "additionalProperties": False,
}

# Canonical action name → strict input schema, in model-facing enum order.
# ``ToolFamily`` deep-copies these schemas when it exposes them, and manager
# bindings only replace handlers; the public schemas therefore cannot drift.
_CHILD_SPECS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("spawn", _SPAWN_INPUT_SCHEMA),
    ("rules", _RULES_INPUT_SCHEMA),
    ("manual", MANUAL_INPUT_SCHEMA),
)


@dataclass(frozen=True, slots=True)
class AvatarToolDescriptor:
    """Static package-local descriptor for the one model-facing ``avatar`` root.

    ``bind_family`` is intentionally only composition: Host code supplies the
    instance-bound handlers.  This keeps agent/network creation, authorization,
    lifecycle/process ownership, and registration out of the descriptor while
    making the public schema and packaged-manual resource one owned unit.
    """

    name: str = "avatar"

    @property
    def action_names(self) -> tuple[str, ...]:
        """Canonical action order for schema-only and handler-bound families."""
        return tuple(name for name, _schema in _CHILD_SPECS)

    def bind_family(
        self, handlers: Mapping[str, Callable[[Mapping[str, Any]], dict[str, Any]]]
    ) -> ToolFamily:
        """Build one family from this descriptor's strict child declarations."""
        return ToolFamily(
            self.name,
            [
                ChildTool(name, schema, handlers[name], title=f"{name} input")
                for name, schema in _CHILD_SPECS
            ],
        )

    def description(self) -> str:
        """Return the static model-facing root description."""
        return (
            "Spawn an independent agent (他我), set network rules for descendants, "
            "or read the avatar manual. Requires an explicit action — no default. "
            "avatar(action='spawn', input={'name': 'researcher', ...}, "
            "reasoning='<the avatar's mission>'): inherits init.json, boots on "
            "default preset; your reasoning becomes the avatar's first prompt. "
            "avatar(action='rules', input={'rules_content': '...'}, reasoning='...'): "
            "distribute rules to self + all descendants (requires karma). "
            "avatar(action='manual', input={}, reasoning='...'): return the "
            "avatar-manual skill body. See avatar-manual skill for full guidance."
        )

    def manual_result(self) -> dict[str, Any]:
        """Return Avatar's own flat packaged-manual result without agent I/O.

        Unlike generic family manuals, Avatar's manual is not installed in an
        agent ``.library``.  Keeping its resource lookup here prevents an
        accidental substitution of ``build_manual_child`` and its incompatible
        installed-manual path/result contract.
        """
        resource = resources.files(__package__).joinpath("manual/SKILL.md")
        try:
            body = resource.read_text(encoding="utf-8")
        except (FileNotFoundError, ModuleNotFoundError, AttributeError, OSError):
            return {
                "status": "degraded",
                "action": "manual",
                "manual": "",
                "manual_path": str(resource),
                "error": "avatar manual missing",
            }
        return {
            "status": "ok",
            "action": "manual",
            "manual": body,
            "manual_path": str(resource),
        }


AVATAR_TOOL_DESCRIPTOR = AvatarToolDescriptor()
