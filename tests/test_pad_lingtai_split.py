"""Evidence for splitting `pad` and `lingtai` out of the former `psyche` into their own roots.

One change's local evidence, in the sense `src/lingtai/tools/CONTRACT.md`
"Contract tests" permits — not a universal conformance suite. Chosen for this
split's own risks:

1. **Three roots, not one plus aliases.** The split must produce exactly one
   model-facing `pad`, one `lingtai`, and one `context`, with the five
   old leaves genuinely gone rather than shimmed.
2. **Two destructive full rewrites changed owner.** `pad(action='edit')` and
   `lingtai(action='update')` must keep their intended/non-empty safety across
   the move, and cross-branch input must still be refused *before* any write.
3. **Boot and post-molt reload moved.** Each family now owns its own boot hook;
   the prompt sections must survive a molt exactly as before.
4. **Ownership claims must be truthful.** Each family's reserved `manual` must
   return that family's own manual, never a context-owned one.

Every stateful test runs against a pytest `tmp_path`, never the live workdir.
"""
from __future__ import annotations

import pytest

from lingtai.agent import Agent
from lingtai.tools import lingtai as lingtai_tool
from lingtai.tools import pad as pad_tool
from lingtai.tools import context as context_tool
from tests._service_helpers import make_gemini_mock_service as make_mock_service


def _agent(tmp_path, **kwargs):
    return Agent(
        service=make_mock_service(), agent_name="test",
        working_dir=tmp_path / "test", **kwargs,
    )


def _pad(agent, args: dict) -> dict:
    return agent._intrinsics["pad"](args)


def _lingtai(agent, args: dict) -> dict:
    return agent._intrinsics["lingtai"](args)


def _context(agent, args: dict) -> dict:
    return agent._intrinsics["context"](args)


# ---------------------------------------------------------------------------
# 1. Exactly three roots with the exact action inventories.
# ---------------------------------------------------------------------------


def test_pad_and_lingtai_are_independent_roots_with_exact_action_order():
    pad_schema = pad_tool.get_schema("en")
    assert pad_schema["properties"]["action"]["enum"] == [
        "edit", "load", "append", "manual",
    ]
    assert pad_tool.ACTION_ORDER == ("edit", "load", "append", "manual")

    lingtai_schema = lingtai_tool.get_schema("en")
    assert lingtai_schema["properties"]["action"]["enum"] == [
        "update", "load", "manual",
    ]
    assert lingtai_tool.ACTION_ORDER == ("update", "load", "manual")


def test_context_no_longer_exposes_pad_or_lingtai_leaves():
    """The five old leaves are gone with no compatibility alias."""
    actions = set(context_tool.get_schema("en")["properties"]["action"]["enum"])
    for gone in (
        "pad_edit", "pad_load", "pad_append", "lingtai_update", "lingtai_load",
    ):
        assert gone not in actions
    # And the current inventory carries no leaf spelling from either split.
    assert context_tool.ACTION_ORDER == (
        "molt", "summarize", "rebuild", "manual",
    )


@pytest.mark.parametrize(
    "gone",
    ["pad_edit", "pad_load", "pad_append", "lingtai_update", "lingtai_load"],
)
def test_old_split_leaves_are_rejected_at_dispatch(tmp_path, gone):
    """Not an alias: each old leaf is an unknown context action and fails loudly."""
    agent = _agent(tmp_path)
    try:
        result = _context(agent, {"action": gone, "input": {}})
        assert "error" in result
        assert "Unknown context action" in result["error"]
        # Nothing written by the refused call.
        assert (agent._working_dir / "system" / "pad.md").read_text() == ""
    finally:
        agent.stop(timeout=1.0)


def test_each_root_is_registered_exactly_once_as_an_intrinsic():
    from lingtai.tools.registry import BUILTIN_TOOLS, INTRINSICS

    assert INTRINSICS["pad"]["module"] is pad_tool
    assert INTRINSICS["lingtai"]["module"] is lingtai_tool
    assert INTRINSICS["context"]["module"] is context_tool
    # Three distinct modules — no root is an alias of another.
    assert len({id(pad_tool), id(lingtai_tool), id(context_tool)}) == 3
    # Intrinsics only: never also dynamic capabilities.
    for name in ("pad", "lingtai", "context"):
        assert name not in BUILTIN_TOOLS


def test_intrinsic_roots_are_wired_exactly_once_on_a_real_agent(tmp_path):
    agent = _agent(tmp_path)
    try:
        for name in ("pad", "lingtai", "context"):
            assert name in agent._intrinsics
        schema_names = [s.name for s in agent._build_tool_schemas()]
        for name in ("pad", "lingtai", "context"):
            assert schema_names.count(name) == 1
    finally:
        agent.stop(timeout=1.0)


# ---------------------------------------------------------------------------
# 2. Closed LTP v2 envelope on both wires, per-action input isolation.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module", [pad_tool, lingtai_tool])
def test_the_root_is_the_closed_ltp_v2_envelope(module):
    schema = module.get_schema("en")
    assert set(schema["properties"]) == {
        "action", "input", "reasoning", "summarize",
    }
    assert schema["required"] == ["action", "input", "reasoning"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["summarize"]["type"] == "boolean"
    # The pre-migration `object` key never existed on these roots.
    assert "object" not in schema["properties"]
    # Schema-level action/input correlation, one condition per child.
    assert len(schema["allOf"]) == len(schema["properties"]["action"]["enum"])


def test_each_action_advertises_only_its_own_input():
    pad_props = {
        c["if"]["properties"]["action"]["const"]:
            set(c["then"]["properties"]["input"]["properties"])
        for c in pad_tool.get_schema("en")["allOf"]
    }
    assert pad_props == {
        "edit": {"content", "files"},
        "load": set(),
        "append": {"files"},
        "manual": set(),
    }

    lingtai_props = {
        c["if"]["properties"]["action"]["const"]:
            set(c["then"]["properties"]["input"]["properties"])
        for c in lingtai_tool.get_schema("en")["allOf"]
    }
    assert lingtai_props == {
        "update": {"content"},
        "load": set(),
        "manual": set(),
    }

    for module in (pad_tool, lingtai_tool):
        for cond in module.get_schema("en")["allOf"]:
            assert cond["then"]["properties"]["input"]["additionalProperties"] is False


@pytest.mark.parametrize("module", [pad_tool, lingtai_tool])
def test_schema_and_dispatch_come_from_one_registry(module):
    """A child cannot be schema-advertised but dispatch-rejected."""
    schema = module.get_schema("en")
    advertised = list(schema["properties"]["action"]["enum"])
    correlated = [c["if"]["properties"]["action"]["const"] for c in schema["allOf"]]
    branch_titles = [b["title"] for b in schema["properties"]["input"]["oneOf"]]
    assert advertised == list(module.ACTION_ORDER)
    assert correlated == advertised
    assert branch_titles == [f"{name} input" for name in advertised]


def test_both_roots_survive_both_wires_with_action_input_correlation(tmp_path):
    """One root per family on the Chat and Responses wires, correlation intact."""
    from lingtai.llm.openai.adapter import _scrub_responses_schema

    agent = _agent(tmp_path)
    try:
        schemas = {s.name: s for s in agent._build_tool_schemas()}
        for name, module in (("pad", pad_tool), ("lingtai", lingtai_tool)):
            chat = schemas[name].parameters
            assert chat["required"] == ["action", "input", "reasoning"]
            assert chat["additionalProperties"] is False
            correlated = [
                c["if"]["properties"]["action"]["const"] for c in chat["allOf"]
            ]
            assert correlated == list(module.ACTION_ORDER)

            responses = _scrub_responses_schema(chat)
            assert [
                c["if"]["properties"]["action"]["const"]
                for c in responses["allOf"]
            ] == correlated
    finally:
        agent.stop(timeout=1.0)


# ---------------------------------------------------------------------------
# 3. Envelope and cross-branch rejection before any handler I/O.
# ---------------------------------------------------------------------------


def test_wrong_branch_input_is_rejected_before_any_handler_io(tmp_path):
    """A cross-action smuggle writes nothing — both families."""
    agent = _agent(tmp_path)
    try:
        pad_path = agent._working_dir / "system" / "pad.md"
        # `files` belongs to pad's edit/append, never to lingtai's update.
        result = _lingtai(agent, {
            "action": "update", "input": {"content": "x", "files": ["a.txt"]},
        })
        assert result["status"] == "failed"
        assert result["error_code"] == "INVALID_ARGUMENT"
        assert "unsupported lingtai input field" in result["message"]
        # Nothing written at all: the refused call did not even create the file.
        lingtai_path = agent._working_dir / "system" / "lingtai.md"
        assert not lingtai_path.exists() or lingtai_path.read_text() == ""

        # `content` belongs to pad's edit, never to pad's append.
        result = _pad(agent, {
            "action": "append", "input": {"files": [], "content": "smuggled"},
        })
        assert result["status"] == "failed"
        assert result["error_code"] == "INVALID_ARGUMENT"
        assert "unsupported pad input field" in result["message"]
        assert pad_path.read_text() == ""
    finally:
        agent.stop(timeout=1.0)


@pytest.mark.parametrize(
    "module_name,action,action_input",
    [
        ("pad", "edit", {"content": "x", "files": None}),
        ("pad", "load", {}),
        ("pad", "append", {"files": None}),
        ("pad", "manual", {}),
        ("lingtai", "update", {"content": "x"}),
        ("lingtai", "load", {}),
        ("lingtai", "manual", {}),
    ],
)
def test_unknown_root_field_and_non_bool_summarize_are_rejected(
    tmp_path, module_name, action, action_input
):
    agent = _agent(tmp_path)
    try:
        call = agent._intrinsics[module_name]
        result = call({
            "action": action, "input": action_input, "mystery": 1,
        })
        assert result["status"] == "failed"
        assert result["error_code"] == "INVALID_ARGUMENT"
        assert f"unsupported {module_name} argument" in result["message"]

        result = call({
            "action": action, "input": action_input, "summarize": "yes",
        })
        assert result["status"] == "failed"
        assert result["error_code"] == "INVALID_ARGUMENT"
        assert "summarize must be a boolean" in result["message"]
    finally:
        agent.stop(timeout=1.0)


@pytest.mark.parametrize("bad_action", [[], {}, "nope", None])
def test_unhashable_or_unknown_action_renders_the_stable_error(tmp_path, bad_action):
    """Invalid JSON can make `action` unhashable — it must not raise (issue #513)."""
    agent = _agent(tmp_path)
    try:
        result = _pad(agent, {"action": bad_action, "input": {}})
        assert "error" in result
        assert "Unknown pad action" in result["error"]

        result = _lingtai(agent, {"action": bad_action, "input": {}})
        assert "error" in result
        assert "Unknown lingtai action" in result["error"]
    finally:
        agent.stop(timeout=1.0)


def test_non_object_input_is_rejected(tmp_path):
    agent = _agent(tmp_path)
    try:
        for call, name in ((_pad, "pad"), (_lingtai, "lingtai")):
            result = call(agent, {"action": "load", "input": "notanobject"})
            assert result["status"] == "failed"
            assert result["error_code"] == "INVALID_ARGUMENT"
            assert "input must be an object" in result["message"]
    finally:
        agent.stop(timeout=1.0)


def test_envelope_controls_and_tc_id_never_reach_a_handler(tmp_path):
    """`reasoning`/`summarize`/`_tc_id` are envelope, not action input.

    Neither family consumes `_tc_id` (only context’s molt does), so both drop it
    at their own Host boundary without widening the shared root field set.
    """
    for module in (pad_tool, lingtai_tool):
        for cond in module.get_schema("en")["allOf"]:
            branch = cond["then"]["properties"]["input"]["properties"]
            for reserved in ("reasoning", "_reasoning", "summarize", "_tc_id"):
                assert reserved not in branch

    agent = _agent(tmp_path)
    seen: list[dict] = []
    try:
        original = pad_tool._pad_load

        def spy(agent_arg, args):
            seen.append(dict(args))
            return original(agent_arg, args)

        saved = pad_tool._CHILD_SPECS
        pad_tool._CHILD_SPECS = tuple(
            (n, s, spy if n == "load" else h) for n, s, h in saved
        )
        try:
            result = _pad(agent, {
                "action": "load", "input": {},
                "reasoning": "check", "summarize": True, "_tc_id": "toolu_x",
            })
            assert result["status"] == "ok"
            # The spy really ran — otherwise the assertions below are vacuous.
            assert len(seen) == 1, "pad load handler was not the dispatched child"
            for reserved in ("reasoning", "_reasoning", "summarize", "_tc_id"):
                assert reserved not in seen[0]
        finally:
            pad_tool._CHILD_SPECS = saved
    finally:
        agent.stop(timeout=1.0)


# ---------------------------------------------------------------------------
# 4. Preserved semantics: destructive rewrites, pinning, read-only loads.
# ---------------------------------------------------------------------------


def test_pad_edit_is_a_full_rewrite_that_still_refuses_a_bare_call(tmp_path):
    """The pre-split safety survives the move, verbatim.

    `{"content": null, "files": null}` is the strict-schema spelling of "no
    argument given" and must stay a refusal, not a silent wipe.
    """
    agent = _agent(tmp_path)
    try:
        assert _pad(agent, {
            "action": "edit", "input": {"content": "notes", "files": None},
        })["status"] == "ok"
        pad = agent._working_dir / "system" / "pad.md"
        assert pad.read_text() == "notes"

        # Bare call refused — the existing pad survives.
        result = _pad(agent, {
            "action": "edit", "input": {"content": None, "files": None},
        })
        assert "error" in result
        assert pad.read_text() == "notes"

        # Explicit empty string clears (intended destruction).
        assert _pad(agent, {
            "action": "edit", "input": {"content": "", "files": None},
        })["status"] == "ok"
        assert pad.read_text() == ""
    finally:
        agent.stop(timeout=1.0)


def test_lingtai_update_is_a_full_rewrite_that_reloads_character(tmp_path):
    agent = _agent(tmp_path, covenant="You are helpful")
    agent.start()
    try:
        _lingtai(agent, {"action": "update", "input": {"content": "first"}})
        _lingtai(agent, {"action": "update", "input": {"content": "second"}})
        # Replaced entirely, not appended.
        assert (agent._working_dir / "system" / "lingtai.md").read_text() == "second"

        # `lingtai` remains the single canonical writer of `character`, and it
        # never leaks into the operator-owned `covenant` section.
        character = agent._prompt_manager.read_section("character")
        assert "second" in character
        assert "second" not in (agent._prompt_manager.read_section("covenant") or "")
    finally:
        agent.stop()


def test_pad_append_pinning_and_read_only_reload(tmp_path):
    """null reads the list; [] clears it; a set list is pinned and reloaded."""
    agent = _agent(tmp_path)
    agent.start()
    try:
        (agent._working_dir / "ref.txt").write_text("pinned reference")

        # null == query, mutating nothing.
        result = _pad(agent, {"action": "append", "input": {"files": None}})
        assert result == {"status": "ok", "files": [], "count": 0}

        result = _pad(agent, {"action": "append", "input": {"files": ["ref.txt"]}})
        assert result["status"] == "ok"
        assert result["action"] == "set"
        assert "pinned reference" in agent._prompt_manager.read_section("pad")

        result = _pad(agent, {"action": "append", "input": {"files": []}})
        assert result["action"] == "cleared"
    finally:
        agent.stop()


def test_pad_append_rejects_missing_and_binary_files(tmp_path):
    agent = _agent(tmp_path)
    try:
        result = _pad(agent, {"action": "append", "input": {"files": ["nope.txt"]}})
        assert "Files not found" in result["error"]

        binary = agent._working_dir / "blob.bin"
        binary.write_bytes(b"\x00\x01\x02")
        result = _pad(agent, {"action": "append", "input": {"files": ["blob.bin"]}})
        assert "Only text files" in result["error"]
    finally:
        agent.stop(timeout=1.0)


@pytest.mark.parametrize(
    "module_name,action", [("pad", "load"), ("lingtai", "load")]
)
def test_load_actions_mutate_no_durable_state(tmp_path, module_name, action):
    agent = _agent(tmp_path)
    agent.start()
    try:
        _pad(agent, {"action": "edit", "input": {"content": "keep me", "files": None}})
        _lingtai(agent, {"action": "update", "input": {"content": "identity"}})
        before_molt = agent._molt_count

        agent._intrinsics[module_name]({"action": action, "input": {}})

        assert (agent._working_dir / "system" / "pad.md").read_text() == "keep me"
        assert (agent._working_dir / "system" / "lingtai.md").read_text() == "identity"
        assert agent._molt_count == before_molt
    finally:
        agent.stop()


# ---------------------------------------------------------------------------
# 5. Family-correct reserved manuals, not double-wrapped.
# ---------------------------------------------------------------------------


def _install_manual(workdir, skill_name: str) -> tuple[str, object]:
    path = (
        workdir / ".library" / "intrinsic" / "capabilities" / skill_name / "SKILL.md"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    body = f"---\nname: {skill_name}\n---\n\n# {skill_name} sentinel\n"
    path.write_text(body, encoding="utf-8")
    return body, path


@pytest.mark.parametrize(
    "module_name,skill_name",
    [("pad", "pad-manual"), ("lingtai", "lingtai-manual"), ("context", "context-manual")],
)
def test_reserved_manual_is_family_correct_and_not_double_wrapped(
    tmp_path, module_name, skill_name
):
    """Each family returns *its own* manual, flattened once — never another family's."""
    agent = _agent(tmp_path)
    try:
        body, path = _install_manual(agent._working_dir, skill_name)
        result = agent._intrinsics[module_name]({"action": "manual", "input": {}})
        # Flat public shape, adapted post-dispatch: no canonical wrapper left.
        assert result == {
            "status": "ok", "manual": body, "manual_path": str(path),
        }
        assert "content" not in result
        assert "structuredContent" not in result
        assert skill_name in result["manual"]
    finally:
        agent.stop(timeout=1.0)


def test_pad_and_lingtai_manuals_are_installed_and_distinct_from_context(tmp_path):
    """The kernel actually ships and installs the two new manual bundles."""
    agent = _agent(tmp_path)
    try:
        capabilities = agent._working_dir / ".library" / "intrinsic" / "capabilities"
        bodies = {}
        for skill in ("pad-manual", "lingtai-manual", "context-manual"):
            skill_md = capabilities / skill / "SKILL.md"
            assert skill_md.is_file(), skill
            bodies[skill] = skill_md.read_text(encoding="utf-8")
            assert f"name: {skill}" in bodies[skill]
        # Three distinct documents, not one manual installed three times.
        assert len(set(bodies.values())) == 3
        # The split-out manuals teach their own call shape.
        assert "pad(action=" in bodies["pad-manual"]
        assert "lingtai(action=" in bodies["lingtai-manual"]
    finally:
        agent.stop(timeout=1.0)


@pytest.mark.parametrize("module_name", ["pad", "lingtai"])
def test_manual_rejects_any_input_key(tmp_path, module_name):
    agent = _agent(tmp_path)
    try:
        result = agent._intrinsics[module_name](
            {"action": "manual", "input": {"content": "x"}}
        )
        assert result["status"] == "failed"
        assert result["error_code"] == "INVALID_ARGUMENT"
    finally:
        agent.stop(timeout=1.0)


# ---------------------------------------------------------------------------
# 6. Registry, allowlist, and daemon inventory expose each root exactly once.
# ---------------------------------------------------------------------------


def test_both_roots_are_on_the_ltp_v2_summarize_allowlist():
    """A family advertising root `summarize` must join the allowlist, or the
    control it advertises to the model is silently ignored."""
    from lingtai.kernel.tool_result_summary import (
        _LTP_V2_MIGRATED_FAMILIES, summary_requested,
    )

    for name in ("pad", "lingtai", "context"):
        assert name in _LTP_V2_MIGRATED_FAMILIES
        assert summary_requested({"summarize": True}, name) is True
        assert summary_requested({"summarize": False}, name) is False


def test_both_roots_inherit_the_emanation_blacklist_boundary():
    """Prompt/identity-mutation authority follows the split rather than being
    lost in it."""
    from lingtai.tools.daemon import EMANATION_BLACKLIST

    for name in ("context", "pad", "lingtai"):
        assert name in EMANATION_BLACKLIST


def test_glossary_resources_exist_for_both_new_packages():
    from lingtai.tools.glossary_validator import validate_package

    for pkg in ("pad", "lingtai"):
        assert validate_package(pkg) == []


# ---------------------------------------------------------------------------
# 7. Boot and post-molt reload moved with their families.
# ---------------------------------------------------------------------------


def test_context_no_longer_owns_the_prompt_section_boot_hooks():
    """Boot moved; context defines no `boot` at all now."""
    assert not hasattr(context_tool, "boot")
    assert callable(pad_tool.boot)
    assert callable(lingtai_tool.boot)
    # The handlers live in their own packages — no stale re-export.
    assert not hasattr(context_tool, "_pad_load")
    assert not hasattr(context_tool, "_lingtai_load")


def test_boot_loads_both_sections_and_registers_post_molt_reload(tmp_path):
    """Each family's boot hook restores its own section after a shed."""
    agent = _agent(tmp_path)
    agent.start()
    try:
        _pad(agent, {"action": "edit", "input": {"content": "pad body", "files": None}})
        _lingtai(agent, {"action": "update", "input": {"content": "who I am"}})

        # Clear both derived sections, then run the registered post-molt hooks
        # exactly as the molt path does.
        agent._prompt_manager.delete_section("pad")
        agent._prompt_manager.delete_section("character")
        for hook in agent._post_molt_hooks:
            hook()

        assert "pad body" in (agent._prompt_manager.read_section("pad") or "")
        assert "who I am" in (agent._prompt_manager.read_section("character") or "")
    finally:
        agent.stop()
