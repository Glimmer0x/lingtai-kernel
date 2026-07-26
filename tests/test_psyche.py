"""Tests for the psyche intrinsic — identity, pad, context, and name."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from lingtai.agent import Agent
from lingtai.kernel.base_agent import BaseAgent
from tests._service_helpers import make_gemini_mock_service as make_mock_service




def _call(agent, args: dict) -> dict:
    """Dispatch a psyche tool call directly through the registered intrinsic."""
    return agent._intrinsics["psyche"](args)


_VALID_JOURNAL = """\
---
name: 2026-06-19-molt-1-test
description: A test session journal entry for the molt gate.
date: 2026-06-19
molt_count: 1
type: session-journal
---

## What this segment was about
Testing.

## Accomplishments
Wrote a valid session journal.
"""


def _write_session_journal(agent, rel="knowledge/session-journal/2026-06-19-molt-1-test/KNOWLEDGE.md"):
    """Write a valid session-journal entry so an agent-initiated molt passes
    the session-journal gate (issue #350). Returns the workdir-relative path."""
    path = agent._working_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_VALID_JOURNAL, encoding="utf-8")
    return rel


# ---------------------------------------------------------------------------
# Setup / registration
# ---------------------------------------------------------------------------


def test_psyche_is_intrinsic(tmp_path):
    """Psyche is now an intrinsic, not a capability — always registered."""
    agent = Agent(
        service=make_mock_service(), agent_name="test", working_dir=tmp_path / "test",
    )
    assert "psyche" in agent._intrinsics
    assert "eigen" not in agent._intrinsics
    agent.stop(timeout=1.0)


def test_psyche_capability_silently_dropped(tmp_path):
    """Legacy init.json with capabilities=['psyche'] should be tolerated —
    psyche is filtered out, the intrinsic still provides the tool."""
    agent = Agent(
        service=make_mock_service(), agent_name="test", working_dir=tmp_path / "test",
        capabilities=["psyche"],
    )
    assert "psyche" not in [name for name, _ in agent._capabilities]
    assert "psyche" in agent._intrinsics
    agent.stop(timeout=1.0)


def test_anima_alias_removed(tmp_path):
    """'anima' alias was removed — agent skips it (unknown capabilities are logged, not raised)."""
    agent = Agent(
        service=make_mock_service(), agent_name="test", working_dir=tmp_path / "test",
        capabilities=["anima"],
    )
    assert "anima" not in [name for name, _ in agent._capabilities]
    agent.stop(timeout=1.0)


# ---------------------------------------------------------------------------
# Lingtai (identity) actions
# ---------------------------------------------------------------------------


def test_lingtai_update_writes_lingtai_md(tmp_path):
    agent = Agent(
        service=make_mock_service(), agent_name="test", working_dir=tmp_path / "test",
        covenant="You are helpful",
    )
    result = _call(agent, {"action": "lingtai_update", "input": {"content": "I am a PDF specialist"}})
    assert result["status"] == "ok"
    character = (agent.working_dir / "system" / "lingtai.md").read_text()
    assert character == "I am a PDF specialist"
    agent.stop(timeout=1.0)


def test_lingtai_update_empty_clears(tmp_path):
    agent = Agent(
        service=make_mock_service(), agent_name="test", working_dir=tmp_path / "test",
    )
    _call(agent, {"action": "lingtai_update", "input": {"content": "something"}})
    _call(agent, {"action": "lingtai_update", "input": {"content": ""}})
    character = (agent.working_dir / "system" / "lingtai.md").read_text()
    assert character == ""
    agent.stop(timeout=1.0)


def test_lingtai_load_writes_character_section(tmp_path):
    """lingtai.md populates the standalone `character` section, NOT covenant.

    The two are semantically distinct: `covenant` is the operator-supplied
    contract (covenant.md alone); `character` is the agent's self-authored
    identity (lingtai.md alone). The character text must never leak into the
    covenant section.
    """
    agent = Agent(
        service=make_mock_service(), agent_name="test", working_dir=tmp_path / "test",
        covenant="You are helpful",
    )
    agent.start()
    try:
        _call(agent, {"action": "lingtai_update", "input": {"content": "I specialize in PDFs"}})
        _call(agent, {"action": "lingtai_load", "input": {}})

        # character section carries lingtai.md alone
        character = agent._prompt_manager.read_section("character")
        assert character is not None
        assert "I specialize in PDFs" in character

        # covenant section carries covenant.md alone — character text not folded in
        covenant = agent._prompt_manager.read_section("covenant") or ""
        assert "You are helpful" in covenant
        assert "I specialize in PDFs" not in covenant
    finally:
        agent.stop()


# ---------------------------------------------------------------------------
# Pad edit (with optional files=)
# ---------------------------------------------------------------------------


def test_pad_edit_content_only(tmp_path):
    agent = Agent(
        service=make_mock_service(), agent_name="test", working_dir=tmp_path / "test",
    )
    result = _call(agent, {"action": "pad_edit", "input": {"content": "my notes", "files": None}})
    assert result["status"] == "ok"
    md = (agent.working_dir / "system" / "pad.md").read_text()
    assert "my notes" in md
    agent.stop(timeout=1.0)


def test_pad_edit_with_files(tmp_path):
    agent = Agent(
        service=make_mock_service(), agent_name="test", working_dir=tmp_path / "test",
    )
    (agent.working_dir / "export1.txt").write_text("knowledge from export 1")
    (agent.working_dir / "export2.txt").write_text("knowledge from export 2")

    result = _call(agent, {
        "action": "pad_edit",
        "input": {
            "content": "My working notes.",
            "files": ["export1.txt", "export2.txt"],
        },
    })
    assert result["status"] == "ok"
    md = (agent.working_dir / "system" / "pad.md").read_text()
    assert "My working notes." in md
    assert "[file-1]" in md
    assert "knowledge from export 1" in md
    assert "[file-2]" in md
    assert "knowledge from export 2" in md
    agent.stop(timeout=1.0)


def test_pad_edit_files_only(tmp_path):
    agent = Agent(
        service=make_mock_service(), agent_name="test", working_dir=tmp_path / "test",
    )
    (agent.working_dir / "data.txt").write_text("file data")

    result = _call(agent, {
        "action": "pad_edit",
        "input": {"content": None, "files": ["data.txt"]},
    })
    assert result["status"] == "ok"
    md = (agent.working_dir / "system" / "pad.md").read_text()
    assert "[file-1]" in md
    assert "file data" in md
    agent.stop(timeout=1.0)


def test_pad_edit_missing_file_errors(tmp_path):
    agent = Agent(
        service=make_mock_service(), agent_name="test", working_dir=tmp_path / "test",
    )
    result = _call(agent, {
        "action": "pad_edit",
        "input": {"content": "notes", "files": ["nonexistent.txt"]},
    })
    assert "error" in result
    assert "nonexistent.txt" in result["error"]
    agent.stop(timeout=1.0)


def test_pad_edit_empty_errors(tmp_path):
    agent = Agent(
        service=make_mock_service(), agent_name="test", working_dir=tmp_path / "test",
    )
    result = _call(agent, {"action": "pad_edit", "input": {"content": None, "files": None}})
    assert "error" in result
    agent.stop(timeout=1.0)


# ---------------------------------------------------------------------------
# Pad load
# ---------------------------------------------------------------------------


def test_pad_load(tmp_path):
    agent = Agent(
        service=make_mock_service(), agent_name="test", working_dir=tmp_path / "test",
    )
    agent.start()
    try:
        system_dir = agent._working_dir / "system"
        system_dir.mkdir(exist_ok=True)
        (system_dir / "pad.md").write_text("loaded from disk")

        result = _call(agent, {"action": "pad_load", "input": {}})
        assert result["status"] == "ok"
        section = agent._prompt_manager.read_section("pad")
        assert "loaded from disk" in section
    finally:
        agent.stop()


# ---------------------------------------------------------------------------
# Molt (agent-initiated)
# ---------------------------------------------------------------------------


def test_molt_returns_faint_memory(tmp_path):
    """psyche(action="context_molt", input={summary, ...}) replays the molt's
    own ToolCallBlock as the opening assistant entry of the fresh session, and
    returns a faint-memory result dict."""
    from lingtai.kernel.llm.interface import ChatInterface, TextBlock, ToolCallBlock

    svc = make_mock_service()

    def fake_create_session(**kwargs):
        mock_chat = MagicMock()
        iface = ChatInterface()
        iface.add_system("You are helpful.")
        mock_chat.interface = iface
        mock_chat.context_window.return_value = 100_000
        return mock_chat

    svc.create_session.side_effect = fake_create_session

    agent = Agent(service=svc, agent_name="test", working_dir=tmp_path / "test")
    agent.start()
    try:
        agent._session.ensure_session()
        agent._session._chat.interface.add_user_message("Hello")
        agent._session._chat.interface.add_assistant_message([TextBlock(text="Hi there.")])

        journal_path = _write_session_journal(agent)
        molt_wire_id = "toolu_test_molt_001"
        molt_summary = "Key findings: X=42. Current task: analyze dataset Z."
        agent._session._chat.interface.add_assistant_message([
            ToolCallBlock(
                id=molt_wire_id,
                name="psyche",
                args={
                    "action": "context_molt",
                    "input": {
                        "summary": molt_summary,
                        "session_journal_path": journal_path,
                        "keep_tool_calls": None,
                        "keep_last": None,
                    },
                },
            ),
        ])

        result = _call(agent, {
            "action": "context_molt",
            "input": {
                "summary": molt_summary,
                "session_journal_path": journal_path,
                "keep_tool_calls": None,
                "keep_last": None,
            },
            "_tc_id": molt_wire_id,
        })

        assert result["status"] == "ok"
        iface = agent._session._chat.interface
        assistant_entries = [e for e in iface.entries if e.role == "assistant"]
        assert assistant_entries, "fresh session should contain the replayed molt tool_call"
        last = assistant_entries[-1]
        molt_calls = [b for b in last.content if isinstance(b, ToolCallBlock)]
        assert molt_calls, "last assistant entry should carry the molt ToolCallBlock"
        assert molt_calls[0].id == molt_wire_id
        assert molt_calls[0].args.get("input", {}).get("summary") == molt_summary
    finally:
        agent.stop()


def test_context_forget_still_works(tmp_path):
    """System-initiated molt records an honest schema-exempt replay pair."""
    from lingtai.kernel.llm.interface import ChatInterface, TextBlock, ToolCallBlock
    from lingtai.tools.psyche import context_forget

    svc = make_mock_service()

    def fake_create_session(**kwargs):
        mock_chat = MagicMock()
        iface = ChatInterface()
        iface.add_system("You are helpful.")
        mock_chat.interface = iface
        mock_chat.context_window.return_value = 100_000
        return mock_chat

    svc.create_session.side_effect = fake_create_session

    agent = Agent(service=svc, agent_name="test", working_dir=tmp_path / "test")
    agent.start()
    try:
        agent._session.ensure_session()
        agent._session._chat.interface.add_user_message("Hello")
        agent._session._chat.interface.add_assistant_message([TextBlock(text="Hi there.")])

        result = context_forget(agent)
        assert result.get("status") == "ok"
        iface = agent._session._chat.interface
        assistant_entries = [entry for entry in iface.entries if entry.role == "assistant"]
        synth_call = next(
            block
            for block in assistant_entries[-1].content
            if isinstance(block, ToolCallBlock)
        )
        assert synth_call.args == {
            "action": "context_molt",
            "input": {
                "summary": synth_call.args["input"]["summary"],
                "session_journal_path": None,
                "keep_tool_calls": None,
                "keep_last": None,
            },
            "_initiator": "system",
            "_source": "warning_ladder",
        }
        assert isinstance(synth_call.args["input"]["summary"], str)
    finally:
        agent.stop()


# ---------------------------------------------------------------------------
# Schema checks
# ---------------------------------------------------------------------------


def test_psyche_schema_has_correct_actions():
    from lingtai.tools.psyche import _ACTION_INPUT_FIELDS, _DISPATCH, get_schema
    SCHEMA = get_schema("en")
    assert set(SCHEMA["properties"]["action"]["enum"]) == {
        "lingtai_update", "lingtai_load",
        "pad_edit", "pad_load", "pad_append",
        "context_molt",
        "name_set", "name_nickname",
        "manual",
    }
    assert SCHEMA["required"] == ["action", "input"]
    assert SCHEMA["additionalProperties"] is False
    assert set(_ACTION_INPUT_FIELDS) == set(SCHEMA["properties"]["action"]["enum"])
    assert set(_DISPATCH) | {"manual"} == set(_ACTION_INPUT_FIELDS)


def test_psyche_schema_input_is_action_keyed_anyof():
    """Canonical contract: input is a strict per-action anyOf, one branch per
    action, each with additionalProperties=False."""
    from lingtai.tools.psyche import _ACTION_INPUT_FIELDS, get_schema
    SCHEMA = get_schema("en")
    branches = SCHEMA["properties"]["input"]["anyOf"]
    assert len(branches) == len(SCHEMA["properties"]["action"]["enum"])
    for branch in branches:
        assert branch["additionalProperties"] is False
        assert set(branch["required"]) == set(branch["properties"])
        action = branch["title"].removesuffix(" input")
        assert set(branch["properties"]) == _ACTION_INPUT_FIELDS[action]


def test_psyche_schema_pad_edit_has_files_field():
    from lingtai.tools.psyche import get_schema
    SCHEMA = get_schema("en")
    pad_edit_branch = next(
        b for b in SCHEMA["properties"]["input"]["anyOf"] if b["title"] == "pad_edit input"
    )
    assert "files" in pad_edit_branch["properties"]


def test_psyche_schema_context_molt_has_session_journal_path_field():
    """Issue #350: molt requires a structured session_journal_path arg."""
    from lingtai.tools.psyche import get_schema
    SCHEMA = get_schema("en")
    molt_branch = next(
        b for b in SCHEMA["properties"]["input"]["anyOf"] if b["title"] == "context_molt input"
    )
    prop = molt_branch["properties"].get("session_journal_path")
    assert prop is not None
    assert prop["type"] == "string"
    assert prop["description"]
    assert "session_journal_path" in molt_branch["required"]


def test_psyche_nested_anyof_survives_provider_envelopes():
    """Provider builders may scrub root combinators, never input.anyOf."""
    from lingtai.kernel.base_agent.tools import _build_tool_schemas
    from lingtai.llm.anthropic.adapter import _build_tools as anthropic_tools
    from lingtai.llm.openai.adapter import _build_responses_tools
    from lingtai.llm.openai.adapter import _build_tools as chat_tools
    import lingtai.tools.psyche as psyche_mod

    fake_agent = MagicMock()
    fake_agent._intrinsics = {"psyche": True}
    fake_agent._intrinsic_modules = {"psyche": psyche_mod}
    fake_agent._tool_schemas = []
    schema = next(
        item for item in _build_tool_schemas(fake_agent) if item.name == "psyche"
    )

    chat_params = chat_tools([schema])[0]["function"]["parameters"]
    responses_params = _build_responses_tools([schema])[0]["parameters"]
    anthropic_params = anthropic_tools([schema])[0]["input_schema"]

    assert "anyOf" not in chat_params
    assert "anyOf" not in responses_params
    assert chat_params["properties"]["input"]["anyOf"]
    assert responses_params["properties"]["input"]["anyOf"]
    assert anthropic_params["properties"]["input"]["anyOf"]
    assert anthropic_params["required"] == ["action", "input"]


def test_molt_business_summary_never_requests_executor_summarization():
    """Nested input.summary is a string, not the root boolean control flag."""
    from lingtai.kernel.tool_result_summary import summary_requested

    args = {
        "action": "context_molt",
        "input": {
            "summary": "true",
            "session_journal_path": "knowledge/session-journal/x/KNOWLEDGE.md",
            "keep_tool_calls": None,
            "keep_last": None,
        },
    }
    assert summary_requested(args) is False


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_invalid_object(tmp_path):
    agent = Agent(
        service=make_mock_service(), agent_name="test", working_dir=tmp_path / "test",
    )
    result = _call(agent, {"action": "bogus", "input": {}})
    assert "error" in result
    agent.stop(timeout=1.0)


def test_invalid_action_for_object(tmp_path):
    agent = Agent(
        service=make_mock_service(), agent_name="test", working_dir=tmp_path / "test",
    )
    result = _call(agent, {"action": "lingtai_submit", "input": {}})
    assert "error" in result
    assert "lingtai_update" in result["error"] or "Unknown action" in result["error"]
    agent.stop(timeout=1.0)


def test_input_must_be_object(tmp_path):
    agent = Agent(
        service=make_mock_service(), agent_name="test", working_dir=tmp_path / "test",
    )
    result = _call(agent, {"action": "pad_load", "input": "not-a-dict"})
    assert "error" in result
    agent.stop(timeout=1.0)


def test_unsupported_input_field_rejected(tmp_path):
    agent = Agent(
        service=make_mock_service(), agent_name="test", working_dir=tmp_path / "test",
    )
    result = _call(agent, {"action": "pad_edit", "input": {"content": "x", "files": None, "bogus": 1}})
    assert "error" in result
    agent.stop(timeout=1.0)


def test_unsupported_root_field_rejected(tmp_path):
    agent = Agent(
        service=make_mock_service(), agent_name="test", working_dir=tmp_path / "test",
    )
    result = _call(agent, {"action": "pad_load", "input": {}, "bogus_root": 1})
    assert "error" in result
    agent.stop(timeout=1.0)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"action": "lingtai_update", "input": {}}, "Missing required"),
        ({"action": "lingtai_update", "input": {"content": 1}}, "must be a string"),
        ({"action": "pad_edit", "input": {"content": "x"}}, "Missing required"),
        (
            {"action": "pad_edit", "input": {"content": "x", "files": "bad"}},
            "array of strings",
        ),
        (
            {
                "action": "context_molt",
                "input": {
                    "summary": 1,
                    "session_journal_path": "journal.md",
                    "keep_tool_calls": None,
                    "keep_last": None,
                },
            },
            "summary",
        ),
        (
            {
                "action": "context_molt",
                "input": {
                    "summary": "summary",
                    "session_journal_path": "journal.md",
                    "keep_tool_calls": None,
                    "keep_last": True,
                },
            },
            "integer or null",
        ),
        ({"action": "pad_load", "input": {}, 1: "bad"}, "keys must be strings"),
        ({"action": "pad_load", "input": {1: "bad"}}, "field names"),
        (
            {"action": "pad_load", "input": {}, "reasoning": 1},
            "reasoning must be a string",
        ),
    ],
)
def test_strict_dispatch_rejects_malformed_calls_before_side_effects(
    tmp_path, payload, expected
):
    agent = Agent(
        service=make_mock_service(), agent_name="test", working_dir=tmp_path / "test",
    )
    system_dir = agent.working_dir / "system"
    system_dir.mkdir(exist_ok=True)
    lingtai_file = system_dir / "lingtai.md"
    pad_file = system_dir / "pad.md"
    lingtai_file.write_text("unchanged lingtai")
    pad_file.write_text("unchanged pad")

    result = _call(agent, payload)

    assert expected in result["error"]
    assert "current_setting" in result
    assert lingtai_file.read_text() == "unchanged lingtai"
    assert pad_file.read_text() == "unchanged pad"
    agent.stop(timeout=1.0)


def test_current_setting_is_captured_before_handler_and_result_is_copied(monkeypatch):
    from lingtai.tools import psyche as psyche_mod

    order = []
    shared_result = {"status": "ok"}

    monkeypatch.setattr(
        psyche_mod,
        "_current_setting",
        lambda agent: order.append("setting") or {"source": "call-start"},
    )

    def fake_handler(agent, args):
        order.append("handler")
        return shared_result

    monkeypatch.setitem(psyche_mod._DISPATCH, "pad_load", fake_handler)
    result = psyche_mod.handle(object(), {"action": "pad_load", "input": {}})

    assert order == ["setting", "handler"]
    assert result["current_setting"] == {"source": "call-start"}
    assert "current_setting" not in shared_result


def test_stop_does_not_overwrite_pad_md(tmp_path):
    """Pad is disk-authoritative — stop() must not clobber existing pad.md."""
    agent = Agent(
        service=make_mock_service(), agent_name="test", working_dir=tmp_path / "test",
    )
    pad_file = agent.working_dir / "system" / "pad.md"
    pad_file.parent.mkdir(exist_ok=True)
    pad_file.write_text("previous session pad")
    agent.stop()
    assert pad_file.read_text() == "previous session pad"


# ---------------------------------------------------------------------------
# Molt summary persistence (system/summaries/)
# ---------------------------------------------------------------------------


def test_molt_writes_summary_file_for_agent_path(tmp_path):
    """Agent-initiated molt persists summary to system/summaries/ with source=agent."""
    from lingtai.kernel.llm.interface import ChatInterface, TextBlock, ToolCallBlock

    svc = make_mock_service()

    def fake_create_session(**kwargs):
        mock_chat = MagicMock()
        iface = ChatInterface()
        iface.add_system("You are helpful.")
        mock_chat.interface = iface
        mock_chat.context_window.return_value = 100_000
        return mock_chat

    svc.create_session.side_effect = fake_create_session

    agent = Agent(service=svc, agent_name="test", working_dir=tmp_path / "test")
    agent.start()
    try:
        agent._session.ensure_session()
        agent._session._chat.interface.add_user_message("Hello")
        agent._session._chat.interface.add_assistant_message([TextBlock(text="Hi.")])

        journal_path = _write_session_journal(agent)
        molt_id = "toolu_test_summary_001"
        molt_summary = "Worked on dataset Z analysis. Found anomaly in column foo."
        agent._session._chat.interface.add_assistant_message([
            ToolCallBlock(
                id=molt_id,
                name="psyche",
                args={
                    "action": "context_molt",
                    "input": {
                        "summary": molt_summary,
                        "session_journal_path": journal_path,
                        "keep_tool_calls": None,
                        "keep_last": None,
                    },
                },
            ),
        ])

        result = _call(agent, {
            "action": "context_molt",
            "input": {
                "summary": molt_summary,
                "session_journal_path": journal_path,
                "keep_tool_calls": None,
                "keep_last": None,
            },
            "_tc_id": molt_id,
        })

        assert result["status"] == "ok"
        assert result.get("summary_path") is not None

        summary_file = agent._working_dir / result["summary_path"]
        assert summary_file.is_file()
        content = summary_file.read_text()
        # Frontmatter present
        assert content.startswith("---\n")
        assert "molt_count: 1" in content
        assert "source: agent" in content
        assert "tokens_shed:" in content
        # Summary body present after frontmatter
        assert molt_summary in content
    finally:
        agent.stop()


def test_context_forget_writes_summary_file_for_system_path(tmp_path):
    """System-initiated molt also persists summary; source field reflects trigger."""
    from lingtai.kernel.llm.interface import ChatInterface, TextBlock
    from lingtai.tools.psyche import context_forget

    svc = make_mock_service()

    def fake_create_session(**kwargs):
        mock_chat = MagicMock()
        iface = ChatInterface()
        iface.add_system("You are helpful.")
        mock_chat.interface = iface
        mock_chat.context_window.return_value = 100_000
        return mock_chat

    svc.create_session.side_effect = fake_create_session

    agent = Agent(service=svc, agent_name="test", working_dir=tmp_path / "test")
    agent.start()
    try:
        agent._session.ensure_session()
        agent._session._chat.interface.add_user_message("Hello")
        agent._session._chat.interface.add_assistant_message([TextBlock(text="Hi.")])

        result = context_forget(agent, source="warning_ladder")
        assert result.get("status") == "ok"
        assert result.get("summary_path") is not None

        summary_file = agent._working_dir / result["summary_path"]
        assert summary_file.is_file()
        content = summary_file.read_text()
        assert "source: warning_ladder" in content
        assert "molt_count: 1" in content
    finally:
        agent.stop()


def test_summary_write_failure_does_not_block_molt(tmp_path, monkeypatch):
    """If summary write fails, molt still completes; summary_path is None."""
    from lingtai.kernel.llm.interface import ChatInterface, TextBlock, ToolCallBlock
    from lingtai.tools import psyche as psyche_mod

    monkeypatch.setattr(psyche_mod, "_write_molt_summary", lambda *a, **kw: None)

    svc = make_mock_service()

    def fake_create_session(**kwargs):
        mock_chat = MagicMock()
        iface = ChatInterface()
        iface.add_system("You are helpful.")
        mock_chat.interface = iface
        mock_chat.context_window.return_value = 100_000
        return mock_chat

    svc.create_session.side_effect = fake_create_session

    agent = Agent(service=svc, agent_name="test", working_dir=tmp_path / "test")
    agent.start()
    try:
        agent._session.ensure_session()
        agent._session._chat.interface.add_user_message("Hello")
        agent._session._chat.interface.add_assistant_message([TextBlock(text="Hi.")])

        journal_path = _write_session_journal(agent)
        molt_id = "toolu_test_failguard_001"
        agent._session._chat.interface.add_assistant_message([
            ToolCallBlock(
                id=molt_id, name="psyche",
                args={
                    "action": "context_molt",
                    "input": {
                        "summary": "test",
                        "session_journal_path": journal_path,
                        "keep_tool_calls": None,
                        "keep_last": None,
                    },
                },
            ),
        ])

        result = _call(agent, {
            "action": "context_molt",
            "input": {
                "summary": "test",
                "session_journal_path": journal_path,
                "keep_tool_calls": None,
                "keep_last": None,
            },
            "_tc_id": molt_id,
        })

        # Molt succeeded
        assert result["status"] == "ok"
        # But summary_path is None (write was forced to fail)
        assert result.get("summary_path") is None
    finally:
        agent.stop()


# ---------------------------------------------------------------------------
# current_setting snapshot (settings/psyche.json no-op placeholder)
# ---------------------------------------------------------------------------


def test_current_setting_attached_to_success_result(tmp_path):
    agent = Agent(
        service=make_mock_service(), agent_name="test", working_dir=tmp_path / "test",
    )
    result = _call(agent, {"action": "pad_edit", "input": {"content": "notes", "files": None}})
    assert result["status"] == "ok"
    assert "current_setting" in result
    assert result["current_setting"]["configurable"] is False
    assert result["current_setting"]["source"] == "missing"
    agent.stop(timeout=1.0)


def test_current_setting_attached_to_error_result(tmp_path):
    agent = Agent(
        service=make_mock_service(), agent_name="test", working_dir=tmp_path / "test",
    )
    result = _call(agent, {"action": "pad_edit", "input": {"content": None, "files": None}})
    assert "error" in result
    assert "current_setting" in result
    agent.stop(timeout=1.0)


def test_current_setting_attached_to_manual_result(tmp_path):
    agent = Agent(
        service=make_mock_service(), agent_name="test", working_dir=tmp_path / "test",
    )
    result = _call(agent, {"action": "manual", "input": {}})
    assert "current_setting" in result
    agent.stop(timeout=1.0)


def test_current_setting_reflects_valid_settings_file(tmp_path):
    """A valid settings/psyche.json v1 file is reflected in current_setting
    without changing any behavior (no-op placeholder contract)."""
    import json as _json

    agent = Agent(
        service=make_mock_service(), agent_name="test", working_dir=tmp_path / "test",
    )
    settings_dir = agent._working_dir / "settings"
    settings_dir.mkdir(exist_ok=True)
    (settings_dir / "psyche.json").write_text(_json.dumps({"schema_version": 1}))

    result = _call(agent, {"action": "pad_load", "input": {}})
    assert result["status"] == "ok"
    assert result["current_setting"]["source"] == "settings/psyche.json"
    assert result["current_setting"]["configurable"] is False
    agent.stop(timeout=1.0)


def test_current_setting_reports_invalid_settings_file_without_changing_behavior(tmp_path):
    agent = Agent(
        service=make_mock_service(), agent_name="test", working_dir=tmp_path / "test",
    )
    settings_dir = agent._working_dir / "settings"
    settings_dir.mkdir(exist_ok=True)
    (settings_dir / "psyche.json").write_text("not json")

    result = _call(agent, {"action": "pad_edit", "input": {"content": "still works", "files": None}})
    # Behavior is unaffected — the edit still succeeds.
    assert result["status"] == "ok"
    assert "settings_error" in result["current_setting"]
    md = (agent.working_dir / "system" / "pad.md").read_text()
    assert "still works" in md
    agent.stop(timeout=1.0)
