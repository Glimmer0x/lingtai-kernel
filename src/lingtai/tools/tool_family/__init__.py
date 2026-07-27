"""Generic internal ToolFamily composition: one model tool per family.

A ``ToolFamily`` groups cohesive child Tools (``ChildTool``) behind exactly
one model-facing tool. The model sees one aggregate schema composed from
each child's own canonical ``input_schema``: a root ``allOf`` of one
``if``/``then`` condition per registered child correlates the sibling
``action`` const with that exact child's ``input`` shape (schema-level
correlation, not just dispatch-time), plus a root ``input.oneOf`` retained
for model discoverability of every action's shape in one place. Both
surfaces are generated purely from the child registry — no name/schema
mapping table — and both derive from the same deep-copied canonical child
schemas. Root-level correlation via ``allOf``/``if``/``then`` was adopted
after a live non-strict Codex Responses probe on 2026-07-27 accepted a raw
root ``allOf``/``if``/``then`` schema without error on the current route,
superseding the earlier, more conservative assumption that root combinators
were universally rejected (see ``lingtai.llm.openai.adapter``'s
``_scrub_responses_schema`` for the corresponding wire-level change).
Children never consume model tool
slots. Dispatch remains the second, always-authoritative enforcement layer —
an in-process handler lookup keyed by the child's own name, which rejects
any ``input`` key outside the selected child's own declared schema before
the handler runs, fail-closed with no guessing/fallback — so a provider that
does not enforce ``allOf``/``if``/``then`` (or a call bypassing schema
validation entirely) still cannot smuggle a mismatched ``action``/``input``
pairing past dispatch. There is no transport, no external MCP surface, and
no second registry.

This module standardizes only the wire envelope and the composition/dispatch
boilerplate every hand-migrated LTP v2 family (see
``src/lingtai/tools/CONTRACT.md``) would otherwise duplicate. It is an
optional helper, not a mandatory base class: a family may use
:class:`ToolFamily` directly, or hand-write an equivalent ``handle()`` the way
``web`` did before adopting it. Two children in a family are not required to
share anything beyond their registration in one :class:`ToolFamily`.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

__all__ = [
    "ChildTool",
    "ToolFamily",
    "ToolFamilyError",
]

# The one reserved child name every family may offer at most once. Colliding
# with it at registration is a defect, not a naming choice to resolve
# silently — see ``tools/CONTRACT.md`` "Every LingTai-owned family MUST offer
# a `manual` action" and the ManualTool stable contract.
RESERVED_MANUAL_NAME = "manual"

# Envelope root fields admitted alongside ``action``/``input``.
_ROOT_FIELDS = {"action", "input", "reasoning", "_reasoning", "summarize"}

# Same canonical English reasoning-property description the kernel injects
# for every tool (``kernel/base_agent/tools.py:_REASONING_DESCRIPTION``).
# Declared here too so the composed family schema is self-describing and
# ``reasoning`` is REQUIRED before ``_build_tool_schemas`` merges its own
# (identical) property text in — that merge only overwrites ``properties``,
# never ``required``, so this is the one place a family schema must declare
# ``reasoning`` as required. Kept as a literal copy rather than an import to
# avoid a tools -> kernel dependency; the exact wording is a contract fact
# proven equal by ``tests/test_tool_family_wire_parity.py``.
_REASONING_DESCRIPTION = (
    "Brief explanation of why you are calling this tool "
    "(recorded in your diary)."
)


class ToolFamilyError(ValueError):
    """Raised for a ToolFamily construction defect (bad registry shape)."""


@dataclass(frozen=True, slots=True)
class ChildTool:
    """One family-owned child: canonical name, schema, and handler.

    ``name`` is simultaneously the child's registry key, the model-facing
    ``action`` constant, and the dispatch handler key — one name, three
    roles, no mapping layer. ``input_schema`` is this child's own strict
    JSON Schema object for ``input`` (closed, ``additionalProperties: false``
    is the child's own responsibility). ``handler`` receives only the
    validated ``input`` mapping (never ``action``, ``reasoning``, or
    ``summarize``) and returns the child's own raw, canonical result dict.
    """

    name: str
    input_schema: Mapping[str, Any]
    handler: Callable[[Mapping[str, Any]], dict[str, Any]]
    title: str | None = None

    def branch_title(self) -> str:
        return self.title or f"{self.name} input"


class ToolFamily:
    """One model-facing aggregate tool composed from a fixed child registry.

    Construction validates the registry (deterministic order, unique names,
    a reserved-name collision on ``manual`` fails loudly). :meth:`build_schema`
    recomputes the composed model-facing schema on every call rather than
    caching one at construction. :meth:`handle` is the family/Host dispatch
    boilerplate: it validates ``action``, strips and validates ``summarize``,
    rejects unknown envelope fields and cross-branch ``input`` keys, then
    calls the selected child's handler with only its own ``input``. Using
    this dispatcher is optional; a family may implement an equivalent
    ``handle()`` by hand and skip this class entirely.
    """

    def __init__(self, name: str, children: Sequence[ChildTool]) -> None:
        if not name or not isinstance(name, str):
            raise ToolFamilyError("ToolFamily name must be a non-empty string")
        if not children:
            raise ToolFamilyError(f"ToolFamily {name!r} must register at least one child")
        seen: dict[str, ChildTool] = {}
        manual_count = 0
        for child in children:
            if not isinstance(child, ChildTool):
                raise ToolFamilyError(f"ToolFamily {name!r} child must be a ChildTool")
            if not child.name or not isinstance(child.name, str):
                raise ToolFamilyError(f"ToolFamily {name!r} child name must be a non-empty string")
            if child.name in seen:
                raise ToolFamilyError(
                    f"ToolFamily {name!r} has a duplicate child name {child.name!r}"
                )
            if child.name == RESERVED_MANUAL_NAME:
                manual_count += 1
                if manual_count > 1:
                    raise ToolFamilyError(
                        f"ToolFamily {name!r} has a reserved-name collision on "
                        f"{RESERVED_MANUAL_NAME!r}"
                    )
            seen[child.name] = child
        self.name = name
        self._children: dict[str, ChildTool] = seen
        # Preserve caller-declared order for deterministic schema branches.
        self._order: list[str] = [child.name for child in children]

    @property
    def child_names(self) -> tuple[str, ...]:
        return tuple(self._order)

    def has_manual(self) -> bool:
        return RESERVED_MANUAL_NAME in self._children

    def build_schema(self) -> dict[str, Any]:
        """Compose the model-facing schema.

        Two enforcement layers, generated purely from the child registry (no
        name/schema mapping table), both built from the same deep-copied
        canonical child schemas so they cannot drift apart:

        1. **Schema-level correlation (``allOf``):** one ``if``/``then``
           condition per registered child. Each ``if`` tests root ``action``
           against that child's own name via ``const`` (guarded by
           ``required: ["action"]``, since a strict ``if`` with a missing
           property vacuously matches); each ``then`` constrains root
           ``input`` to that exact child's ``input_schema``. This lets a
           provider that enforces ``allOf``/``if``/``then`` reject a
           mismatched ``action``/``input`` pairing before the call is even
           made — a live non-strict Codex Responses probe on 2026-07-27
           showed this root construct is accepted, not rejected, by the
           current backend route.
        2. **``input.oneOf`` disclosure:** the same per-action branches,
           retained under ``input`` for model discoverability of every
           action's exact shape in one place (as before).

        The root carries ``action``, ``input``, required ``reasoning``, and
        optional ``summarize`` — exactly the four LTP v2 envelope fields
        (``tools/CONTRACT.md`` "Envelope"); `allOf`'s conditions constrain
        ``action``/``input`` without duplicating ``action`` inside ``input``
        or adding a fifth public field. ``reasoning`` is Host
        InvocationContext/audit metadata, never action input: it is declared
        here as REQUIRED so every family built on this infrastructure is
        model-visible-required by construction, not by relying on Agent
        schema composition (``kernel/base_agent/tools.py:_build_tool_schemas``)
        to add it — that step still re-injects the identical property text
        for every tool uniformly, but only touches ``properties``, never
        ``required``.

        Schema-level correlation is a second, additive layer, not a
        replacement for dispatch: :meth:`handle` remains the always-
        authoritative, fail-closed enforcement boundary regardless of
        whether a given provider actually validates ``allOf``/``if``/``then``
        before invocation.
        """
        input_branches = []
        all_of_conditions = []
        for child_name in self._order:
            child = self._children[child_name]
            # Deep-copy once per child so the ``oneOf`` branch and the
            # ``allOf`` condition's ``then.input`` never share a mutable
            # container with each other, the child's own canonical
            # ``input_schema``, or a previous ``build_schema()`` call.
            canonical_input_schema = copy.deepcopy(child.input_schema)

            branch = {"title": child.branch_title()}
            branch.update(copy.deepcopy(canonical_input_schema))
            input_branches.append(branch)

            all_of_conditions.append(
                {
                    "if": {
                        "properties": {"action": {"const": child_name}},
                        "required": ["action"],
                    },
                    "then": {
                        "properties": {"input": copy.deepcopy(canonical_input_schema)},
                    },
                }
            )
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": list(self._order),
                    "description": f"Required operation within the {self.name} family.",
                },
                "input": {
                    "description": (
                        "Strict action-specific input; the selected action is "
                        "validated again at dispatch."
                    ),
                    "oneOf": input_branches,
                },
                "reasoning": {
                    "type": "string",
                    "description": _REASONING_DESCRIPTION,
                },
                "summarize": {
                    "type": "boolean",
                    "description": (
                        "Root, cross-cutting result post-processing control; "
                        "absent or false by default. Not action input."
                    ),
                },
            },
            "required": ["action", "input", "reasoning"],
            "additionalProperties": False,
            "allOf": all_of_conditions,
        }

    def _allowed_input_keys(self, child: ChildTool) -> set[str]:
        properties = child.input_schema.get("properties") if isinstance(child.input_schema, Mapping) else None
        return set(properties) if isinstance(properties, Mapping) else set()

    def handle(self, args: Mapping[str, Any] | None) -> dict[str, Any]:
        """Validate the envelope, dispatch to the selected child, return its raw result.

        ``summarize`` is stripped and type-checked before the unknown-field
        check so a family opting into this dispatcher gets the same ordering
        ``web`` hand-wrote. Children receive only their own ``input`` mapping
        — never ``action``, ``reasoning``, ``_reasoning``, or ``summarize``.
        Per ``tools/CONTRACT.md`` "Dispatch and actions", schema conformance
        alone is not the dispatch-time authorization boundary: ``input`` keys
        are validated against the selected child's own declared
        ``input_schema`` properties, rejecting any key belonging to another
        action's branch, before the child handler ever runs.
        """
        raw = dict(args or {})
        action = raw.get("action")
        if action not in self._children:
            return self._envelope_error(
                "ACTION_REQUIRED",
                f"action must be one of {', '.join(self._order)}",
            )
        if "summarize" in raw:
            summarize = raw.pop("summarize")
            if not isinstance(summarize, bool):
                return self._envelope_error("INVALID_ARGUMENT", "summarize must be a boolean")
        unknown = set(raw) - _ROOT_FIELDS
        if unknown:
            return self._envelope_error("INVALID_ARGUMENT", f"unsupported {self.name} argument")
        action_input = raw.get("input")
        if not isinstance(action_input, Mapping):
            return self._envelope_error("INVALID_ARGUMENT", "input must be an object")
        child = self._children[action]
        allowed = self._allowed_input_keys(child)
        if set(action_input) - allowed:
            return self._envelope_error(
                "INVALID_ARGUMENT", f"unsupported {self.name} input field"
            )
        return child.handler(action_input)

    def _envelope_error(self, code: str, message: str) -> dict[str, Any]:
        return {"status": "failed", "error_code": code, "message": message}
