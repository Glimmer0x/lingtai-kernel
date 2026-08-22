"""ManualTool stable contract: the family-owned reserved ``manual`` child.

Every LingTai-owned family offers a ``manual`` action (``tools/CONTRACT.md``
"Dispatch and actions"). This module upgrades the existing ``#1058``
``load_installed_manual()`` return shape into a stable, reusable, internal
MCP-compatible contract: a strict empty input, and a canonical child result
carrying the full installed ``SKILL.md`` body at ``content[0].text`` and the
model-visible host-local ``manual_path`` at ``structuredContent.manual_path``
— the two fields the approved v0.4 ManualTool acceptance requires of the
*actual* child result, not merely of an unused presentational helper. This is
the real, dispatched-to handler `ToolFamily.handle()` returns verbatim (no
double wrap): a family wanting the pre-migration flat
``load_installed_manual()`` shape (``status``, ``manual``, ``manual_path``)
back out — as ``web`` does — owns that adaptation itself, in its own Host/
presentation layer, per the no-double-wrap rule (``../CONTRACT.md`` "Dispatch
and actions"): the child's own canonical/raw result stays canonical.
"""
from __future__ import annotations

import copy
from typing import Any, Mapping

from .._manual import load_installed_manual
from . import ChildTool

__all__ = [
    "MANUAL_CHILD_TITLE",
    "MANUAL_INPUT_SCHEMA",
    "build_manual_child",
    "to_manual_result",
]

#: The one strict-empty ``manual`` input schema every family shares. ``required``
#: is stated explicitly rather than left implicit: an empty ``properties`` map
#: with ``additionalProperties: False`` already admits only ``{}``, so the key is
#: semantically exact, and stating it keeps one canonical spelling for consumers
#: that compare composed schemas byte-for-byte — whether a family registers
#: ``build_manual_child`` below or, like ``avatar``, supplies its own ``manual``
#: handler while still reusing this same literal. Exported so a family that
#: must also *declare* this schema (e.g. ``soul``'s module-level schema-only
#: ``ToolFamily`` built before an agent exists) references the one owned
#: definition instead of copying it — the schema and the child that dispatches
#: it cannot then drift apart.
MANUAL_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}

#: The ``manual`` child's schema branch title. Owned here so a family that
#: builds its own reserved child (``lingtai.tools._plugin.LocalToolPlugin``
#: does, to bind the child to its packaged bundle) produces a composed schema
#: byte-identical to one built by :func:`build_manual_child`.
MANUAL_CHILD_TITLE = "manual input"


def to_manual_result(loaded: Mapping[str, Any]) -> dict[str, Any]:
    """Map a ``load_installed_manual``-shaped dict to the canonical child result.

    Full body goes to ``content[0].text``; ``manual_path`` goes to
    ``structuredContent.manual_path`` (model-visible, never only in a
    ``_meta``-style side channel) — the two fields the approved v0.4
    acceptance line requires. ``status`` (and ``error``, when the loader
    reports a missing/degraded manual) are preserved verbatim as truthful
    loader facts alongside the two MCP-compatible fields; this is not a
    second wrapper, it is this child's own canonical result shape.

    Public because the reserved child is not always built by
    :func:`build_manual_child`: a packaged local-tool plugin
    (``lingtai.tools._plugin.LocalToolPlugin``) binds its own ``manual`` child
    to its bundled ``manual/SKILL.md`` and maps it through this same function,
    so a plugin-served manual and an installed-library one are the same shape.
    """
    result: dict[str, Any] = {
        "status": loaded.get("status", "ok"),
        "content": [{"type": "text", "text": loaded.get("manual", "")}],
        "structuredContent": {"manual_path": loaded.get("manual_path", "")},
    }
    if "error" in loaded:
        result["error"] = loaded["error"]
    return result


def build_manual_child(agent: Any, skill_name: str) -> ChildTool:
    """Build the reserved ``manual`` :class:`ChildTool` for one family.

    ``skill_name`` is the installed manual's public destination name (e.g.
    ``"web"``), matching ``Agent._install_intrinsic_manuals``'s directory
    mapping. The child's own input is validated as strict empty by
    :class:`ToolFamily.handle`, matching every other child. This
    :class:`ChildTool` is the family's actual, registered ``manual`` child —
    a family MUST register it directly in its own :class:`ToolFamily` so
    :meth:`ToolFamily.handle` dispatches back its canonical
    ``content``/``structuredContent`` result verbatim (no double wrap); a
    family wanting a different public result shape (as ``web`` does) adapts
    the dispatched result itself, after ``ToolFamily.handle`` returns, in its
    own Host/presentation layer — never inside this builder or its handler.
    """

    def handler(_input: Mapping[str, Any]) -> dict[str, Any]:
        loaded = load_installed_manual(agent, skill_name)
        return to_manual_result(loaded)

    return ChildTool(
        name="manual",
        # Deep copy: a shallow one would share the nested ``properties`` map,
        # letting one family's child mutate every other family's schema.
        input_schema=copy.deepcopy(MANUAL_INPUT_SCHEMA),
        handler=handler,
        title=MANUAL_CHILD_TITLE,
    )
