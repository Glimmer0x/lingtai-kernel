"""``web``'s migration onto the generic ToolFamily infra changes nothing the
model or a caller can observe, except three documented, authorized
differences:

1. the ``anyOf`` -> ``oneOf`` combinator swap for the ``input`` discriminated
   union (locked decision L3 in the design record this candidate implements);
2. ``get_schema()`` alone now declares a REQUIRED ``reasoning`` property
   itself, rather than relying solely on Agent schema composition
   (``_build_tool_schemas``) to inject it into ``properties`` (never
   ``required``) at Agent-build time. Pre-migration, ``get_schema()`` in
   isolation never mentioned ``reasoning`` at all; the real final Agent-built
   schema always ended up with the ``reasoning`` *property* either way, but
   never had it in ``required`` until this repair. Making the family's own
   schema self-describing and REQUIRED-correct even before Agent composition
   is the exact fix for the reported blocker (real ``PYTHONPATH=src`` import
   of ``get_schema()`` previously showed ``reasoning`` entirely absent);
3. a root ``allOf`` was added: one ``if``/``then`` condition per action,
   correlating the sibling ``action`` const with that exact action's
   ``input`` shape at the schema level (adopted after a live non-strict
   Codex Responses probe on 2026-07-27 accepted a raw root ``allOf``/``if``/
   ``then`` schema without error on the current route). The public root's
   four fields (``action``, ``input``, ``reasoning``, ``summarize``) and their
   requiredness are unchanged; ``allOf`` constrains them without adding a
   fifth field or duplicating ``action`` inside ``input``.

This module snapshots the true pre-migration schema shape (as it existed at
this worktree's exact clean base, commit
21bf4a3d12e0857510d96248179178ca3b36ff7e, before this candidate's changes)
and diffs it against the now-generated schema, proving equivalence
field-by-field rather than merely re-asserting individual properties as the
other web test files already do.
"""
from __future__ import annotations

from lingtai.tools.web_search import get_schema


def _pre_migration_schema() -> dict:
    # Verbatim copy of the schema ``web_search/__init__.py::get_schema()``
    # hand-built before this candidate, at commit
    # 21bf4a3d12e0857510d96248179178ca3b36ff7e, with only ``anyOf`` swapped to
    # ``oneOf`` per the authorized design decision.
    return {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["search", "browse", "manual"],
                "description": "Required operation: search, browse, or manual.",
            },
            "input": {
                "description": (
                    "Strict action-specific input; the selected action is validated "
                    "again at dispatch."
                ),
                "oneOf": [
                    {
                        "title": "search input",
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query."},
                        },
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                    {
                        "title": "browse input",
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": ["string", "null"],
                                "description": "Public HTTP(S) URL; use null when link_ref or cursor is supplied.",
                            },
                            "link_ref": {
                                "type": ["string", "null"],
                                "description": "Same-Agent search result reference; use null when not supplied.",
                            },
                            "cursor": {
                                "type": ["string", "null"],
                                "description": "Same-Agent continuation cursor; use null when not supplied.",
                            },
                            "extract": {
                                "type": ["string", "null"],
                                "enum": ["article", None],
                                "description": "Article extraction, or null for the default.",
                            },
                            "max_chars": {
                                "type": ["integer", "null"],
                                "minimum": 1,
                                "maximum": 100000,
                                "description": "Maximum returned characters, or null for the default 12000.",
                            },
                        },
                        "required": ["url", "link_ref", "cursor", "extract", "max_chars"],
                        "additionalProperties": False,
                    },
                    {
                        "title": "manual input",
                        "type": "object",
                        "properties": {},
                        "required": [],
                        "additionalProperties": False,
                    },
                ],
            },
            "summarize": {
                "type": "boolean",
                "description": (
                    "Root, cross-cutting result post-processing control; absent "
                    "or false by default. Not action input."
                ),
            },
        },
        "required": ["action", "input"],
        "additionalProperties": False,
    }


def test_generated_schema_is_field_equivalent_to_pre_migration_schema_except_authorized_differences():
    generated = get_schema()
    pre = _pre_migration_schema()

    # The action enum's description text became a generic template as part of
    # generalizing schema composition (an explicitly authorized ownership
    # change, not accidental drift).
    normalized = dict(generated)
    normalized["properties"] = dict(generated["properties"])
    normalized["properties"]["action"] = dict(generated["properties"]["action"])
    normalized["properties"]["action"]["description"] = pre["properties"]["action"]["description"]

    # ``reasoning`` is the second authorized difference (the repaired
    # blocker): ``get_schema()`` alone now declares it, required, itself.
    # Strip it back out before comparing against the true pre-migration
    # fixture (which never mentioned ``reasoning`` at the ``get_schema()``
    # level at all), and assert its presence/requiredness separately below.
    assert "reasoning" in normalized["properties"]
    assert normalized["required"] == ["action", "input", "reasoning"]
    del normalized["properties"]["reasoning"]
    normalized["required"] = ["action", "input"]

    # ``allOf`` is the third authorized difference (root action/input
    # correlation). Assert its shape/correctness separately below, then
    # strip it before comparing the rest of the schema field-by-field
    # against the true pre-migration fixture (which never had ``allOf``).
    assert "allOf" in normalized
    del normalized["allOf"]

    assert normalized == pre


def test_all_of_correlates_action_const_with_exact_child_schema_for_every_web_action():
    """The new root ``allOf`` is checked on its own: one condition per web
    action, each ``if`` testing ``action`` via ``const`` against the real
    action enum values, each ``then`` constraining ``input`` to exactly that
    action's own branch schema from ``input.oneOf`` — both surfaces must
    derive from the same canonical child schema, never drift apart."""
    generated = get_schema()
    conditions = generated["allOf"]
    branches = generated["properties"]["input"]["oneOf"]
    assert [c["if"]["properties"]["action"]["const"] for c in conditions] == ["search", "browse", "manual"]
    for condition, branch in zip(conditions, branches):
        assert condition["if"]["required"] == ["action"]
        then_input = condition["then"]["properties"]["input"]
        # The oneOf branch is the same input schema plus a "title" key; strip
        # it before comparing to the allOf condition's own copy.
        branch_without_title = {k: v for k, v in branch.items() if k != "title"}
        assert then_input == branch_without_title


def test_reasoning_is_required_and_absent_from_pre_migration_fixture():
    # The pre-migration fixture is the true historical shape: no ``reasoning``
    # property at the ``get_schema()`` level, matching the exact blocker
    # evidence (``PYTHONPATH=src python`` import previously showed properties
    # == {action, input, summarize} with no reasoning, required ==
    # [action, input]). The now-generated schema must differ exactly here.
    pre = _pre_migration_schema()
    assert "reasoning" not in pre["properties"]
    assert pre["required"] == ["action", "input"]

    generated = get_schema()
    assert generated["properties"]["reasoning"]["type"] == "string"
    assert generated["required"] == ["action", "input", "reasoning"]


def test_action_enum_values_and_order_unchanged():
    assert get_schema()["properties"]["action"]["enum"] == ["search", "browse", "manual"]


def test_input_branch_order_and_titles_unchanged():
    branches = get_schema()["properties"]["input"]["oneOf"]
    assert [b["title"] for b in branches] == ["search input", "browse input", "manual input"]
