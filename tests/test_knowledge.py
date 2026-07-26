"""Tests for the filesystem-backed knowledge capability.

Knowledge is structurally isomorphic to skills but physically separate:
entries live at ``<agent>/knowledge/<name>/KNOWLEDGE.md`` (not ``SKILL.md``).
The catalog injects only ``name``/``description``/``location`` from frontmatter;
bodies and supporting files are loaded on demand via the regular ``read`` tool.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from lingtai.agent import Agent
from tests._service_helpers import make_gemini_mock_service as make_mock_service




def _mk_agent(tmp_path: Path, knowledge_cfg: dict | None = None):
    caps = {"knowledge": knowledge_cfg or {}}
    workdir = tmp_path / "agent"
    agent = Agent(
        service=make_mock_service(),
        agent_name="test",
        working_dir=workdir,
        capabilities=caps,
    )
    return agent, workdir


def _write_entry(folder: Path, name: str, desc: str = "test entry", body: str = "Body text.") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "KNOWLEDGE.md"
    path.write_text(
        f"---\nname: {name}\ndescription: {desc}\n---\n\n{body}\n"
    )
    return path


# ---------------------------------------------------------------------------
# Setup & registration
# ---------------------------------------------------------------------------


def test_knowledge_setup_registers_only_knowledge_tool(tmp_path):
    agent, _ = _mk_agent(tmp_path)
    try:
        assert "knowledge" in agent._tool_handlers
        assert "library" not in agent._tool_handlers
        assert "codex" not in agent._tool_handlers
    finally:
        agent.stop(timeout=1.0)


def test_former_alias_capabilities_are_not_tools(tmp_path):
    """Legacy `library` / `codex` capability names must not register as tools.

    `knowledge` itself is now default-on, so it WILL be available — but the
    breaking-rename guarantee is still that the legacy names produce no
    `library(...)` / `codex(...)` tool handler.
    """
    for cap in ("library", "codex"):
        agent = Agent(
            service=make_mock_service(),
            agent_name=f"test-{cap}",
            working_dir=tmp_path / cap,
            capabilities=[cap],
        )
        try:
            assert cap not in agent._tool_handlers
        finally:
            agent.stop(timeout=1.0)


def test_knowledge_independent_of_psyche(tmp_path):
    """Knowledge is a separate capability; psyche is always-on as intrinsic."""
    agent, _ = _mk_agent(tmp_path)
    try:
        assert "psyche" in agent._intrinsics
        assert "knowledge" in agent._tool_handlers
    finally:
        agent.stop(timeout=1.0)


def test_legacy_knowledge_limit_kwarg_is_ignored(tmp_path):
    """Old presets may still carry knowledge_limit — must not error."""
    agent, _ = _mk_agent(tmp_path, {"knowledge_limit": 50})
    try:
        assert "knowledge" in agent._tool_handlers
        result = agent._tool_handlers["knowledge"]({"action": "info", "input": {}})
        assert result["status"] == "ok"
    finally:
        agent.stop(timeout=1.0)


# ---------------------------------------------------------------------------
# Tool surface — info action
# ---------------------------------------------------------------------------


def test_info_returns_runtime_snapshot(tmp_path):
    agent, workdir = _mk_agent(tmp_path)
    try:
        result = agent._tool_handlers["knowledge"]({"action": "info", "input": {}})
        assert result["status"] == "ok"
        assert result["knowledge_dir"] == str(workdir / "knowledge")
        assert result["catalog_size"] == 0
        assert result["problems"] == []
        assert result["current_setting"]["source"] == "missing"
    finally:
        agent.stop(timeout=1.0)


def test_manual_returns_body_and_current_setting(tmp_path):
    agent, _ = _mk_agent(tmp_path)
    try:
        result = agent._tool_handlers["knowledge"](
            {"action": "manual", "input": {}, "_reasoning": "load guidance"}
        )
        assert result["status"] == "ok"
        assert "# The Knowledge Capability" in result["knowledge_manual"]
        assert result["current_setting"]["source"] == "missing"
    finally:
        agent.stop(timeout=1.0)


def test_handler_rereads_settings_and_passes_exact_diagnostic_to_every_result(tmp_path, monkeypatch):
    from lingtai.tools import knowledge as knowledge_module

    agent, _ = _mk_agent(tmp_path)
    snapshots = [object() for _ in range(5)]
    settings = [{"call": index} for index in range(5)]
    reads = []

    def fake_read(current_agent, tool_name):
        reads.append((current_agent, tool_name))
        return snapshots.pop(0)

    def fake_current(snapshot, tool_name):
        assert tool_name == "knowledge"
        return settings[len(reads) - 1]

    monkeypatch.setattr(knowledge_module, "read_settings", fake_read)
    monkeypatch.setattr(knowledge_module, "current_setting", fake_current)
    monkeypatch.setattr(
        knowledge_module,
        "_knowledge_manual",
        lambda _agent: {"status": "degraded", "knowledge_manual": "", "error": "missing"},
    )
    try:
        handler = agent._tool_handlers["knowledge"]
        calls = [
            ({"action": "info", "input": {}}, "ok"),
            ({"action": "manual", "input": {}}, "degraded"),
            ({"action": "info"}, "error"),
            ({"action": "submit", "input": {}}, "error"),
            ({"action": "info", "input": {"title": "flat"}}, "error"),
        ]
        results = [handler(args) for args, _ in calls]
        assert [result["status"] for result in results] == [expected for _, expected in calls]
        assert [result["current_setting"] for result in results] == settings
        assert [result["current_setting"] is setting for result, setting in zip(results, settings)] == [True] * 5
        assert len(reads) == 5
        assert all(tool_name == "knowledge" and current_agent is agent for current_agent, tool_name in reads)
    finally:
        agent.stop(timeout=1.0)


def test_info_picks_up_authored_entry(tmp_path):
    workdir = tmp_path / "agent"
    _write_entry(
        workdir / "knowledge" / "tcp-retry",
        "tcp-retry",
        "How the mail service retries TCP — exponential backoff and failure modes.",
    )
    agent = Agent(
        service=make_mock_service(),
        agent_name="test",
        working_dir=workdir,
        capabilities={"knowledge": {}},
    )
    try:
        result = agent._tool_handlers["knowledge"]({"action": "info", "input": {}})
        assert result["catalog_size"] == 1
        assert result["problems"] == []
    finally:
        agent.stop(timeout=1.0)


def test_unknown_action_returns_error(tmp_path):
    """Removed JSON-store actions (submit/view/etc.) must be rejected."""
    agent, _ = _mk_agent(tmp_path)
    try:
        for action in ("submit", "view", "consolidate", "delete", "filter", "export"):
            result = agent._tool_handlers["knowledge"]({"action": action, "input": {}})
            assert result["status"] == "error", f"{action!r} should be rejected"
            assert "unknown action" in result["message"].lower()
            assert "current_setting" in result
        setting = agent._tool_handlers["knowledge"]({"action": "submit", "input": {}})["current_setting"]
        # Exact model-visible wording remains unchanged; only the truthful
        # settings diagnostic is added at the outer result boundary.
        assert agent._tool_handlers["knowledge"]({"action": "submit", "input": {}}) == {
            "status": "error",
            "message": "unknown action: 'submit', only 'info' or 'manual' is supported",
            "current_setting": setting,
        }
        # A missing action key renders the empty-string default, not None, when
        # the required nested input is present.
        assert agent._tool_handlers["knowledge"]({"input": {}}) == {
            "status": "error",
            "message": "unknown action: '', only 'info' or 'manual' is supported",
            "current_setting": agent._tool_handlers["knowledge"]({"input": {}})["current_setting"],
        }
        # Invalid JSON can make `action` unhashable: the router must render the
        # unknown-action envelope, not raise TypeError.
        for action, rendered in (([], "[]"), ({}, "{}")):
            result = agent._tool_handlers["knowledge"]({"action": action, "input": {}})
            assert result["message"] == f"unknown action: {rendered}, only 'info' or 'manual' is supported"
            assert "current_setting" in result
    finally:
        agent.stop(timeout=1.0)


def test_handler_rejects_action_only_flat_and_nonempty_input(tmp_path):
    agent, _ = _mk_agent(tmp_path)
    try:
        handler = agent._tool_handlers["knowledge"]
        for args in (
            {"action": "info"},
            {"action": "info", "title": "flat payload"},
            {"action": "info", "input": {"title": "non-empty"}},
            {"action": "info", "input": []},
        ):
            result = handler(args)
            assert result["status"] == "error"
            assert "current_setting" in result
            assert "knowledge" in result["message"]
    finally:
        agent.stop(timeout=1.0)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_schema_has_info_and_manual_actions():
    from lingtai.tools.knowledge import get_schema

    schema = get_schema("en")
    assert set(schema["properties"]) == {"action", "input"}
    assert schema["required"] == ["action", "input"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["action"]["enum"] == ["info", "manual"]
    branches = schema["properties"]["input"]["anyOf"]
    assert [branch["title"] for branch in branches] == ["info input", "manual input"]
    for branch in branches:
        assert branch == {
            "title": branch["title"],
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        }
    # The raw capability schema deliberately does not include Agent-injected
    # reasoning, and no branch may smuggle it in.
    assert "reasoning" not in schema["properties"]
    assert all("reasoning" not in branch["properties"] for branch in branches)


def test_actual_agent_inventory_prompt_and_batches_keep_reasoning_root_only(tmp_path):
    agent, _ = _mk_agent(tmp_path)
    try:
        schema = next(item for item in agent._build_tool_schemas() if item.name == "knowledge")
        params = schema.parameters
        assert set(params["properties"]) == {"action", "input", "reasoning"}
        assert params["required"] == ["action", "input"]
        assert params["additionalProperties"] is False
        branches = params["properties"]["input"]["anyOf"]
        assert all("reasoning" not in branch["properties"] for branch in branches)

        full_prompt = agent._build_system_prompt()
        batches = agent._build_system_prompt_batches()
        assert full_prompt == "\\n\\n".join(batch for batch in batches if batch)
        assert "knowledge(action=\"info\", input={}, reasoning=" in full_prompt
        assert "knowledge(action=\"manual\", input={}, reasoning=" in full_prompt
    finally:
        agent.stop(timeout=1.0)


def test_knowledge_schema_survives_openai_and_anthropic_envelopes():
    from lingtai.kernel.llm.base import WIRE_TOOL_DESCRIPTION, FunctionSchema
    from lingtai.llm.anthropic.adapter import _build_tools as build_anthropic_tools
    from lingtai.llm.openai.adapter import _build_responses_tools, _build_tools
    from lingtai.tools.knowledge import get_description, get_schema

    raw = get_schema()
    schema = FunctionSchema(name="knowledge", description=get_description(), parameters=raw)
    chat = _build_tools([schema])[0]
    responses = _build_responses_tools([schema])[0]
    anthropic = build_anthropic_tools([schema])[0]
    for envelope, parameters in (
        (chat["function"]["parameters"], chat["function"]["parameters"]),
        (responses["parameters"], responses["parameters"]),
        (anthropic["input_schema"], anthropic["input_schema"]),
    ):
        assert envelope == raw
        assert parameters["properties"]["input"]["anyOf"][0]["additionalProperties"] is False
    assert chat["function"]["description"] == WIRE_TOOL_DESCRIPTION
    assert responses["description"] == WIRE_TOOL_DESCRIPTION
    assert anthropic["description"] == WIRE_TOOL_DESCRIPTION


# ---------------------------------------------------------------------------
# Catalog metadata only — no body, no supporting-file content
# ---------------------------------------------------------------------------


def test_prompt_catalog_only_metadata_not_body(tmp_path):
    """Bodies and supplementary material must never enter the prompt section."""
    workdir = tmp_path / "agent"
    body_sentinel = "BODY_SENTINEL_should_never_appear_in_prompt"
    _write_entry(
        workdir / "knowledge" / "important-finding",
        "important-finding",
        "Short prompt-visible description.",
        body=f"## Notes\n\n{body_sentinel}\n\nLong reasoning paragraph here.\n",
    )
    # Add a supporting file — must never enter the prompt either.
    support_sentinel = "SUPPORT_SENTINEL_also_must_not_appear"
    (workdir / "knowledge" / "important-finding" / "raw-log.txt").write_text(
        support_sentinel
    )

    agent = Agent(
        service=make_mock_service(),
        agent_name="test",
        working_dir=workdir,
        capabilities={"knowledge": {}},
    )
    try:
        prompt = agent._prompt_manager.read_section("knowledge") or ""
        # name + description + location are present in the YAML catalog.
        assert "- name: important-finding" in prompt
        assert "Short prompt-visible description." in prompt
        # Body and supporting file content are absent.
        assert body_sentinel not in prompt
        assert support_sentinel not in prompt
    finally:
        agent.stop(timeout=1.0)


def test_catalog_clears_when_no_entries(tmp_path):
    agent, _ = _mk_agent(tmp_path)
    try:
        prompt = agent._prompt_manager.read_section("knowledge") or ""
        assert prompt == ""
    finally:
        agent.stop(timeout=1.0)


def test_catalog_refreshes_on_info(tmp_path):
    """info() re-scans so newly authored entries appear without restart."""
    agent, workdir = _mk_agent(tmp_path)
    try:
        assert (agent._prompt_manager.read_section("knowledge") or "") == ""

        _write_entry(
            workdir / "knowledge" / "late-arrival",
            "late-arrival",
            "Added after agent boot.",
        )
        result = agent._tool_handlers["knowledge"]({"action": "info", "input": {}})
        assert result["catalog_size"] == 1

        prompt = agent._prompt_manager.read_section("knowledge") or ""
        assert "late-arrival" in prompt
        assert "Added after agent boot." in prompt
    finally:
        agent.stop(timeout=1.0)


# ---------------------------------------------------------------------------
# Convention boundary: KNOWLEDGE.md vs SKILL.md
# ---------------------------------------------------------------------------


def test_knowledge_md_convention_distinct_from_skill_md(tmp_path):
    """The knowledge tool only picks up KNOWLEDGE.md files, not SKILL.md."""
    workdir = tmp_path / "agent"
    # Valid knowledge entry.
    _write_entry(
        workdir / "knowledge" / "real-entry",
        "real-entry",
        "Picked up because it has KNOWLEDGE.md.",
    )
    # A SKILL.md sibling inside knowledge/ must NOT be cataloged.
    skill_folder = workdir / "knowledge" / "skill-shaped-thing"
    skill_folder.mkdir(parents=True, exist_ok=True)
    (skill_folder / "SKILL.md").write_text(
        "---\nname: skill-shaped-thing\ndescription: would-be-skill\n---\nBody.\n"
    )

    agent = Agent(
        service=make_mock_service(),
        agent_name="test",
        working_dir=workdir,
        capabilities={"knowledge": {}},
    )
    try:
        result = agent._tool_handlers["knowledge"]({"action": "info", "input": {}})
        assert result["catalog_size"] == 1
        prompt = agent._prompt_manager.read_section("knowledge") or ""
        assert "real-entry" in prompt
        assert "skill-shaped-thing" not in prompt
        # The corrupted folder is reported as a problem (loose file, no KNOWLEDGE.md).
        problem_folders = [p["folder"] for p in result["problems"]]
        assert any("skill-shaped-thing" in f for f in problem_folders)
    finally:
        agent.stop(timeout=1.0)


# ---------------------------------------------------------------------------
# Entries may carry references, scripts, assets
# ---------------------------------------------------------------------------


def test_entries_may_have_scripts_and_assets(tmp_path):
    """Knowledge entries can carry supporting files like skills do."""
    workdir = tmp_path / "agent"
    entry_dir = workdir / "knowledge" / "rich-entry"
    _write_entry(
        entry_dir,
        "rich-entry",
        "An entry with scripts and assets.",
        body="See scripts/repro.sh and assets/diagram.png.\n",
    )
    (entry_dir / "scripts").mkdir()
    (entry_dir / "scripts" / "repro.sh").write_text("#!/bin/sh\necho hi\n")
    (entry_dir / "assets").mkdir()
    (entry_dir / "assets" / "diagram.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")

    agent = Agent(
        service=make_mock_service(),
        agent_name="test",
        working_dir=workdir,
        capabilities={"knowledge": {}},
    )
    try:
        result = agent._tool_handlers["knowledge"]({"action": "info", "input": {}})
        assert result["status"] == "ok"
        assert result["catalog_size"] == 1
        assert result["problems"] == []
    finally:
        agent.stop(timeout=1.0)


def test_entry_may_reference_local_paths_in_body(tmp_path):
    """Knowledge bodies may mention local paths, mail ids, logs — unlike skills.

    The capability does not parse the body; this test asserts that nothing
    blocks an agent from authoring such an entry and that the catalog still
    only injects the public-shaped frontmatter.
    """
    workdir = tmp_path / "agent"
    body = (
        "Saw this in mailbox/inbox/20260512T081132-fdb2/ and logs/agent.log.\n"
        "Cross-reference with /Users/me/private/notes.md.\n"
    )
    _write_entry(
        workdir / "knowledge" / "private-refs",
        "private-refs",
        "Notes citing local-only context — fine for knowledge.",
        body=body,
    )
    agent = Agent(
        service=make_mock_service(),
        agent_name="test",
        working_dir=workdir,
        capabilities={"knowledge": {}},
    )
    try:
        result = agent._tool_handlers["knowledge"]({"action": "info", "input": {}})
        assert result["catalog_size"] == 1
        prompt = agent._prompt_manager.read_section("knowledge") or ""
        # Body (and its private references) stays out of the prompt catalog.
        assert "mailbox/inbox" not in prompt
        assert "/Users/me/private" not in prompt
    finally:
        agent.stop(timeout=1.0)


# ---------------------------------------------------------------------------
# Health / problem reporting
# ---------------------------------------------------------------------------


def test_info_surfaces_missing_frontmatter(tmp_path):
    workdir = tmp_path / "agent"
    bad = workdir / "knowledge" / "missing-desc" / "KNOWLEDGE.md"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("---\nname: missing-desc\n---\nno description!\n")

    agent = Agent(
        service=make_mock_service(),
        agent_name="test",
        working_dir=workdir,
        capabilities={"knowledge": {}},
    )
    try:
        result = agent._tool_handlers["knowledge"]({"action": "info", "input": {}})
        problem_folders = [p["folder"] for p in result["problems"]]
        assert any("missing-desc" in f for f in problem_folders)
        assert result["catalog_size"] == 0
    finally:
        agent.stop(timeout=1.0)


def test_legacy_knowledge_json_migrates_to_knowledge_md(tmp_path):
    """Old JSON entries are converted once into KNOWLEDGE.md folders."""
    workdir = tmp_path / "agent"
    legacy_dir = workdir / "knowledge"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    (legacy_dir / "knowledge.json").write_text(
        '{"version": 1, "entries": [{'
        '"id": "abc123", '
        '"title": "TCP Retry Logic", '
        '"summary": "Covers retry backoff and failure modes.", '
        '"content": "The TCP mail service uses exponential backoff.", '
        '"supplementary": "Raw logs and citations."'
        '}]}',
        encoding="utf-8",
    )

    agent = Agent(
        service=make_mock_service(),
        agent_name="test",
        working_dir=workdir,
        capabilities={"knowledge": {}},
    )
    try:
        result = agent._tool_handlers["knowledge"]({"action": "info", "input": {}})
        assert result["catalog_size"] == 1
        assert result["problems"] == []

        entry = legacy_dir / "tcp-retry-logic"
        md = entry / "KNOWLEDGE.md"
        refs = entry / "references" / "supplementary.md"
        assert md.is_file()
        assert refs.is_file()
        text = md.read_text(encoding="utf-8")
        assert 'name: "tcp-retry-logic"' in text
        assert 'description: "Covers retry backoff and failure modes."' in text
        assert 'legacy_id: "abc123"' in text
        assert "The TCP mail service uses exponential backoff." in text
        assert "references/supplementary.md" in text
        assert refs.read_text(encoding="utf-8") == "Raw logs and citations.\n"

        assert not (legacy_dir / "knowledge.json").exists()
        assert (legacy_dir / "knowledge.json.migrated").is_file()

        prompt = agent._prompt_manager.read_section("knowledge") or ""
        assert "tcp-retry-logic" in prompt
        assert "Covers retry backoff and failure modes." in prompt
        assert "The TCP mail service uses exponential backoff." not in prompt
        assert "Raw logs and citations" not in prompt
    finally:
        agent.stop(timeout=1.0)


def test_legacy_knowledge_json_migration_uses_unique_slugs(tmp_path):
    workdir = tmp_path / "agent"
    legacy_dir = workdir / "knowledge"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    (legacy_dir / "knowledge.json").write_text(
        '{"entries": ['
        '{"id": "a1", "title": "Duplicate", "summary": "First"},'
        '{"id": "b2", "title": "Duplicate", "summary": "Second"}'
        ']}',
        encoding="utf-8",
    )

    agent = Agent(
        service=make_mock_service(),
        agent_name="test",
        working_dir=workdir,
        capabilities={"knowledge": {}},
    )
    try:
        result = agent._tool_handlers["knowledge"]({"action": "info", "input": {}})
        assert result["catalog_size"] == 2
        assert (legacy_dir / "duplicate" / "KNOWLEDGE.md").is_file()
        assert (legacy_dir / "duplicate-b2" / "KNOWLEDGE.md").is_file()
    finally:
        agent.stop(timeout=1.0)


def test_legacy_codex_json_migrates_to_knowledge_md(tmp_path):
    """Old codex/codex.json entries are converted into the new knowledge catalog."""
    workdir = tmp_path / "agent"
    codex_dir = workdir / "codex"
    codex_dir.mkdir(parents=True, exist_ok=True)
    (codex_dir / "codex.json").write_text(
        '{"version": 1, "entries": [{'
        '"id": "oldcodex", '
        '"title": "Old Codex Entry", '
        '"summary": "Migrated from the pre-rename codex store.", '
        '"content": "Historical codex content.", '
        '"supplementary": "Historical backing material."'
        '}]}',
        encoding="utf-8",
    )

    agent = Agent(
        service=make_mock_service(),
        agent_name="test",
        working_dir=workdir,
        capabilities={"knowledge": {}},
    )
    try:
        result = agent._tool_handlers["knowledge"]({"action": "info", "input": {}})
        assert result["catalog_size"] == 1
        assert result["problems"] == []

        entry = workdir / "knowledge" / "old-codex-entry"
        md = entry / "KNOWLEDGE.md"
        refs = entry / "references" / "supplementary.md"
        assert md.is_file()
        assert refs.is_file()
        text = md.read_text(encoding="utf-8")
        assert 'origin: "migrated-codex-json"' in text
        assert 'legacy_id: "oldcodex"' in text
        assert "Historical codex content." in text
        assert refs.read_text(encoding="utf-8") == "Historical backing material.\n"

        assert not (codex_dir / "codex.json").exists()
        assert (codex_dir / "codex.json.migrated").is_file()
    finally:
        agent.stop(timeout=1.0)
