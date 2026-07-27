"""Knowledge LTP v2 family migration parity and wire correlation.

``knowledge`` keeps its exact public name and its two public action values
(``info``, ``manual``); what the migration changes is the root envelope, which
is now the closed LTP v2 ``action``/``input``/``reasoning``/``summarize`` shape
with per-action ``input`` correlation on both provider wires.

The behavioral point of these tests is that the migration is envelope-only:
``info`` still re-scans and reconciles the private catalog and returns health
(root/count/problems) without loading bodies or mutating entries, and ``manual``
still returns the current manual body/path without rescanning or mutating
anything.
"""
from __future__ import annotations

from pathlib import Path

from lingtai.agent import Agent
from lingtai.tools import knowledge as knowledge_tool
from tests._service_helpers import make_gemini_mock_service as make_mock_service


def _mk_agent(tmp_path: Path):
    workdir = tmp_path / "agent"
    agent = Agent(
        service=make_mock_service(),
        agent_name="knowledge-family-test",
        working_dir=workdir,
        capabilities={"knowledge": {}},
    )
    return agent, workdir


def _dispatch(agent, args: dict) -> dict:
    """Call the Host layer with an explicitly built family, as ``setup`` does.

    ``knowledge.handle`` takes the family the caller owns — there is no
    build-on-demand fallback in production, so tests build one the same way
    ``setup()`` does rather than relying on a test-only convenience branch.
    """
    return knowledge_tool.handle(knowledge_tool._build_family(agent), args)


def _write_entry(folder: Path, name: str, desc: str = "an entry", body: str = "Body.") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "KNOWLEDGE.md"
    path.write_text(f"---\nname: {name}\ndescription: {desc}\n---\n\n{body}\n")
    return path


# ---------------------------------------------------------------------------
# Schema: closed root envelope, strict-empty child inputs, action parity
# ---------------------------------------------------------------------------


def test_schema_root_is_closed_action_input_reasoning_summarize():
    schema = knowledge_tool.get_schema()
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    # ``reasoning`` is REQUIRED Host InvocationContext/audit metadata declared
    # by the family schema itself, not left to Agent schema composition (which
    # only re-injects the identical property text and never touches
    # ``required``).
    assert schema["required"] == ["action", "input", "reasoning"]
    assert set(schema["properties"]) == {"action", "input", "reasoning", "summarize"}
    assert schema["properties"]["reasoning"]["type"] == "string"
    assert schema["properties"]["summarize"]["type"] == "boolean"


def test_public_action_values_are_unchanged_by_the_migration():
    """The migration is envelope-only: the public action vocabulary is exactly
    the pre-migration ``info``/``manual``, with no authoring/search/edit
    action added."""
    schema = knowledge_tool.get_schema()
    assert schema["properties"]["action"]["enum"] == ["info", "manual"]


def test_child_inputs_are_canonical_strict_empty_objects():
    schema = knowledge_tool.get_schema()
    branches = schema["properties"]["input"]["oneOf"]
    assert [b["title"] for b in branches] == ["info input", "manual input"]
    for branch in branches:
        assert branch["type"] == "object"
        assert branch["properties"] == {}
        assert branch["required"] == []
        assert branch["additionalProperties"] is False
        # Envelope controls never leak into a child's own input.
        assert "reasoning" not in branch["properties"]
        assert "_reasoning" not in branch["properties"]
        assert "summarize" not in branch["properties"]


def test_root_allof_correlates_each_action_const_with_its_input_schema():
    schema = knowledge_tool.get_schema()
    conditions = schema["allOf"]
    assert len(conditions) == 2
    seen = {}
    for condition in conditions:
        const = condition["if"]["properties"]["action"]["const"]
        assert condition["if"]["required"] == ["action"]
        seen[const] = condition["then"]["properties"]["input"]
    assert set(seen) == {"info", "manual"}
    for action, input_schema in seen.items():
        assert input_schema["additionalProperties"] is False, action
        assert input_schema["properties"] == {}, action


# ---------------------------------------------------------------------------
# Wire correlation: Chat Completions and Responses
# ---------------------------------------------------------------------------


def test_knowledge_family_schema_survives_chat_and_responses_wires(tmp_path):
    from lingtai.kernel.base_agent.tools import _build_tool_schemas
    from lingtai.llm.openai.adapter import _build_responses_tools, _build_tools

    agent, _ = _mk_agent(tmp_path)
    try:
        schemas = _build_tool_schemas(agent)
        knowledge = next(s for s in schemas if s.name == "knowledge")
        chat = _build_tools([knowledge])[0]["function"]["parameters"]
        responses = _build_responses_tools([knowledge])[0]["parameters"]

        for wire, combinator in ((chat, "oneOf"), (responses, "anyOf")):
            assert wire["type"] == "object"
            assert wire["required"] == ["action", "input", "reasoning"]
            assert wire["additionalProperties"] is False
            assert set(wire["properties"]) == {"action", "input", "reasoning", "summarize"}
            branches = wire["properties"]["input"][combinator]
            assert [b["title"] for b in branches] == ["info input", "manual input"]
            for branch in branches:
                assert branch["additionalProperties"] is False
                assert "reasoning" not in branch["properties"]
                assert "_reasoning" not in branch["properties"]
                assert "summarize" not in branch["properties"]

        # Root ``allOf`` action/input correlation reaches both wires. Chat
        # keeps it verbatim; the Responses builder preserves a root ``allOf``
        # rather than stripping it.
        for wire in (chat, responses):
            consts = [c["if"]["properties"]["action"]["const"] for c in wire["allOf"]]
            assert consts == ["info", "manual"]
    finally:
        agent.stop(timeout=1.0)


# ---------------------------------------------------------------------------
# Dispatch: pre-I/O rejection
# ---------------------------------------------------------------------------


def test_missing_input_is_rejected_before_any_io(tmp_path, monkeypatch):
    """A call with no ``input`` fails at the envelope, before either action's
    handler runs — no rescan, no manual read."""
    agent, _ = _mk_agent(tmp_path)
    try:
        calls: list[str] = []
        monkeypatch.setattr(
            knowledge_tool, "_reconcile", lambda _agent: calls.append("reconcile") or {},
        )
        monkeypatch.setattr(
            knowledge_tool,
            "_knowledge_manual",
            lambda _agent: calls.append("manual") or {},
        )
        for action in ("info", "manual"):
            result = _dispatch(agent, {"action": action, "reasoning": "no input"})
            assert result["status"] == "failed"
            assert result["error_code"] == "INVALID_ARGUMENT"
        assert calls == []
    finally:
        agent.stop(timeout=1.0)


def test_extra_input_field_is_rejected_before_any_io(tmp_path, monkeypatch):
    """Both children declare a strict-empty input, so ANY input key is a
    cross-branch/unknown key and is rejected at dispatch before handler I/O."""
    agent, _ = _mk_agent(tmp_path)
    try:
        calls: list[str] = []
        monkeypatch.setattr(
            knowledge_tool, "_reconcile", lambda _agent: calls.append("reconcile") or {},
        )
        monkeypatch.setattr(
            knowledge_tool,
            "_knowledge_manual",
            lambda _agent: calls.append("manual") or {},
        )
        # Exercise the registered handler (the family ``setup`` built once),
        # not just the module-level ``handle`` helper.
        registered = agent._tool_handlers["knowledge"]
        for dispatch in (lambda a: _dispatch(agent, a), registered):
            for action in ("info", "manual"):
                result = dispatch(
                    {
                        "action": action,
                        "input": {"query": "find something"},
                        "reasoning": "smuggle an authoring/search field",
                    }
                )
                assert result["status"] == "failed"
                assert result["error_code"] == "INVALID_ARGUMENT"
                assert "unsupported knowledge input field" in result["message"]
        assert calls == []
    finally:
        agent.stop(timeout=1.0)


def test_unknown_root_field_and_non_boolean_summarize_are_rejected(tmp_path):
    agent, _ = _mk_agent(tmp_path)
    try:
        unknown_root = _dispatch(
            agent,
            {"action": "info", "input": {}, "reasoning": "r", "parameters": {}},
        )
        assert unknown_root["status"] == "failed"
        assert unknown_root["error_code"] == "INVALID_ARGUMENT"

        bad_summarize = _dispatch(
            agent,
            {"action": "info", "input": {}, "reasoning": "r", "summarize": "yes"},
        )
        assert bad_summarize["status"] == "failed"
        assert bad_summarize["error_code"] == "INVALID_ARGUMENT"
        assert "summarize must be a boolean" in bad_summarize["message"]
    finally:
        agent.stop(timeout=1.0)


def test_reasoning_and_summarize_never_reach_a_child_handler(tmp_path):
    """Children receive only their own ``input`` mapping — never ``action``,
    ``reasoning``, ``_reasoning``, or ``summarize``."""
    agent, _ = _mk_agent(tmp_path)
    try:
        assert set(knowledge_tool._build_family(agent).child_names) == {"info", "manual"}

        seen: list[dict] = []

        def record(input_mapping):
            seen.append(dict(input_mapping))
            return {"status": "ok"}

        recording = knowledge_tool.ToolFamily(
            "knowledge",
            [
                knowledge_tool.ChildTool(
                    "info", knowledge_tool._EMPTY_INPUT_SCHEMA, record, title="info input",
                ),
                knowledge_tool.ChildTool(
                    "manual", knowledge_tool._EMPTY_INPUT_SCHEMA, record, title="manual input",
                ),
            ],
        )
        recording.handle(
            {
                "action": "info",
                "input": {},
                "reasoning": "why",
                "_reasoning": "internal",
                "summarize": True,
            }
        )
        assert seen == [{}]
    finally:
        agent.stop(timeout=1.0)


# ---------------------------------------------------------------------------
# Preserved semantics: info scans, manual does not
# ---------------------------------------------------------------------------


def test_info_rescans_and_reports_exact_count_and_problems(tmp_path):
    """``info`` re-scans and reconciles the catalog: an entry authored after
    setup is picked up on the next call, and a malformed entry is reported in
    ``problems`` — the exact pre-migration behavior."""
    agent, workdir = _mk_agent(tmp_path)
    try:
        first = _dispatch(
            agent, {"action": "info", "input": {}, "reasoning": "initial health"}
        )
        assert first["status"] == "ok"
        assert first["knowledge_dir"] == str(workdir / "knowledge")
        assert first["catalog_size"] == 0
        assert first["problems"] == []

        _write_entry(workdir / "knowledge" / "alpha", "alpha")
        _write_entry(workdir / "knowledge" / "beta", "beta")
        # A folder whose KNOWLEDGE.md lacks required frontmatter is a problem,
        # not an entry.
        broken = workdir / "knowledge" / "broken"
        broken.mkdir(parents=True, exist_ok=True)
        (broken / "KNOWLEDGE.md").write_text("no frontmatter here\n")

        second = _dispatch(
            agent, {"action": "info", "input": {}, "reasoning": "rescan after authoring"}
        )
        assert second["status"] == "ok"
        assert second["catalog_size"] == 2
        assert len(second["problems"]) == 1
        assert set(second) == {"status", "knowledge_dir", "catalog_size", "problems"}
    finally:
        agent.stop(timeout=1.0)


def test_info_does_not_load_bodies_or_mutate_entries(tmp_path):
    agent, workdir = _mk_agent(tmp_path)
    try:
        secret = "SENTINEL-BODY-must-not-be-returned"
        path = _write_entry(workdir / "knowledge" / "alpha", "alpha", body=secret)
        before = path.read_bytes()

        result = _dispatch(
            agent, {"action": "info", "input": {}, "reasoning": "health only"}
        )
        assert result["catalog_size"] == 1
        assert secret not in repr(result)
        # No entry mutation: the capability is pure presentation.
        assert path.read_bytes() == before
    finally:
        agent.stop(timeout=1.0)


def test_manual_returns_body_and_path_without_rescanning(tmp_path, monkeypatch):
    """``manual`` returns the current manual body/path and performs no catalog
    scan or reconciliation."""
    agent, workdir = _mk_agent(tmp_path)
    try:
        manual_path = (
            workdir / ".library" / "intrinsic" / "capabilities" / "knowledge" / "SKILL.md"
        )
        manual_path.parent.mkdir(parents=True, exist_ok=True)
        body = "---\nname: knowledge\n---\n\n# knowledge manual sentinel\n"
        manual_path.write_text(body, encoding="utf-8")

        scans: list[str] = []
        monkeypatch.setattr(
            knowledge_tool,
            "_reconcile",
            lambda _agent: scans.append("scan") or {"status": "ok"},
        )
        # Authoring an entry after setup would change catalog_size if manual
        # rescanned; it must not.
        _write_entry(workdir / "knowledge" / "late-entry", "late-entry")

        result = _dispatch(
            agent, {"action": "manual", "input": {}, "reasoning": "load guidance"}
        )
        assert scans == []
        assert result["status"] == "ok"
        assert result["knowledge_manual"] == body
        assert result["manual_path"] == str(manual_path)
        # No double wrap: the child's canonical result is returned verbatim.
        assert set(result) == {"status", "knowledge_manual", "manual_path"}
        assert "content" not in result
        assert "structuredContent" not in result
    finally:
        agent.stop(timeout=1.0)


def test_manual_missing_is_degraded_and_still_no_rescan(tmp_path, monkeypatch):
    agent, workdir = _mk_agent(tmp_path)
    try:
        manual_path = (
            workdir / ".library" / "intrinsic" / "capabilities" / "knowledge" / "SKILL.md"
        )
        if manual_path.is_file():
            manual_path.unlink()

        scans: list[str] = []
        monkeypatch.setattr(
            knowledge_tool,
            "_reconcile",
            lambda _agent: scans.append("scan") or {"status": "ok"},
        )
        result = _dispatch(
            agent, {"action": "manual", "input": {}, "reasoning": "load guidance"}
        )
        assert scans == []
        assert result["status"] == "degraded"
        assert result["knowledge_manual"] == ""
        assert result["manual_path"] == str(manual_path)
        assert "error" in result
    finally:
        agent.stop(timeout=1.0)


# ---------------------------------------------------------------------------
# Registration wiring
# ---------------------------------------------------------------------------


def test_setup_registers_one_knowledge_tool_with_the_family_schema(tmp_path):
    agent, _ = _mk_agent(tmp_path)
    try:
        assert "knowledge" in agent._tool_handlers
        # No duplicate/old model root sneaks in alongside the family.
        assert "knowledge_info" not in agent._tool_handlers
        assert "knowledge_manual" not in agent._tool_handlers

        from lingtai.kernel.base_agent.tools import _build_tool_schemas

        schemas = [s for s in _build_tool_schemas(agent) if s.name == "knowledge"]
        assert len(schemas) == 1
        params = schemas[0].parameters
        assert params["properties"]["action"]["enum"] == ["info", "manual"]
        assert params["required"] == ["action", "input", "reasoning"]

        # The registered handler is the family handler: it dispatches the same
        # envelope the schema advertises.
        result = agent._tool_handlers["knowledge"](
            {"action": "info", "input": {}, "reasoning": "wired handler"}
        )
        assert result["status"] == "ok"
        assert "catalog_size" in result
    finally:
        agent.stop(timeout=1.0)


def test_knowledge_is_a_registered_ltp_v2_family_for_summarize(tmp_path):
    """Root ``summarize`` is the canonical control for this migrated family,
    and its envelope failures are not summarized away."""
    from lingtai.kernel.tool_result_summary import summary_requested

    assert summary_requested({"summarize": True}, tool_name="knowledge") is True
    # An unmigrated tool's own field named ``summarize`` is still not this control.
    assert summary_requested({"summarize": True}, tool_name="some_other_tool") is False


def test_family_has_no_authoring_search_or_edit_capability():
    """The signpost contract holds after migration: no action creates, edits,
    searches, or loads knowledge entries."""
    schema = knowledge_tool.get_schema()
    actions = set(schema["properties"]["action"]["enum"])
    forbidden = {
        "create", "write", "edit", "update", "delete", "search", "query",
        "load", "view", "submit", "consolidate",
    }
    assert actions.isdisjoint(forbidden)
    # And no child accepts an input field at all, so no authoring payload can
    # be smuggled through one.
    for branch in schema["properties"]["input"]["oneOf"]:
        assert branch["properties"] == {}
