"""Psyche's LTP v2 / ToolFamily migration evidence.

One family's local evidence, in the sense `src/lingtai/tools/CONTRACT.md`
"Contract tests" permits — not a universal conformance suite. Chosen for this
family's own risks, which differ from `soul`'s: psyche owns two destructive
full-rewrite operations (`lingtai_update`, `pad_edit`), a set-once identity,
and the molt — the single most irreversible operation any agent can perform.
So the emphasis here is on *refusal before mutation*: a mis-shaped envelope
must be rejected with nothing written, nothing shed, and no molt consumed.

Psyche is also the third migrated intrinsic, and the first family that
genuinely *consumes* the kernel-injected `_tc_id` rather than merely dropping
it — `context_molt` needs that wire id to locate and replay its own
ToolCallBlock. The isolation tests below pin that boundary.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from lingtai.agent import Agent
from lingtai.tools import psyche as psyche_tool
from lingtai.tools.psyche import ACTION_ORDER, get_schema
from tests._service_helpers import make_gemini_mock_service as make_mock_service


_VALID_JOURNAL = """\
---
name: 2026-07-27-molt-1-test
description: A test session journal entry for the molt gate.
date: 2026-07-27
molt_count: 1
type: session-journal
---

## What this segment was about
Testing the psyche ToolFamily migration.
"""

_JOURNAL_REL = "knowledge/session-journal/2026-07-27-molt-1-test/KNOWLEDGE.md"


def _agent(tmp_path, **kwargs):
    return Agent(
        service=make_mock_service(), agent_name="test",
        working_dir=tmp_path / "test", **kwargs,
    )


def _write_journal(agent, rel: str = _JOURNAL_REL) -> str:
    path = agent._working_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_VALID_JOURNAL, encoding="utf-8")
    return rel


def _call(agent, args: dict) -> dict:
    return agent._intrinsics["psyche"](args)


def _molt_input(journal_path, summary="briefing", **over):
    payload = {
        "summary": summary,
        "session_journal_path": journal_path,
        "keep_tool_calls": None,
        "keep_last": None,
    }
    payload.update(over)
    return payload


# ---------------------------------------------------------------------------
# One public root; the exact preserved operation inventory.
# ---------------------------------------------------------------------------


def test_one_public_psyche_root_with_the_preserved_operation_inventory():
    """Every pre-migration (object, action) pair survives as exactly one action.

    The migration collapsed a two-key matrix into the flat LTP v2 `action`
    enum. It added nothing, dropped nothing, renamed no capability, and merged
    no two operations into one.
    """
    schema = get_schema("en")
    assert schema["properties"]["action"]["enum"] == [
        "lingtai_update", "lingtai_load",     # lingtai: update | load
        "pad_edit", "pad_load", "pad_append",  # pad: edit | load | append
        "context_molt",                        # context: molt
        "name_set", "name_nickname",           # name: set | nickname
        "manual",                              # root manual (family-owned)
    ]
    # Eight migrated operations + the one reserved family-owned manual.
    assert len(ACTION_ORDER) == 9


def test_psyche_is_registered_exactly_once_as_an_intrinsic():
    from lingtai.tools.registry import BUILTIN_TOOLS, INTRINSICS

    assert INTRINSICS["psyche"]["module"] is psyche_tool
    # Not also a capability, and no second model-facing root or alias.
    assert "psyche" not in BUILTIN_TOOLS
    assert "anima" not in BUILTIN_TOOLS
    assert "pad" not in INTRINSICS


def test_the_root_is_the_closed_ltp_v2_envelope():
    schema = get_schema("en")
    assert set(schema["properties"]) == {"action", "input", "reasoning", "summarize"}
    assert schema["required"] == ["action", "input", "reasoning"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["summarize"]["type"] == "boolean"
    # The pre-migration `object` key is gone entirely — no alias, no shim.
    assert "object" not in schema["properties"]


def test_schema_and_dispatch_come_from_one_registry():
    """A child cannot be schema-advertised but dispatch-rejected."""
    schema = get_schema("en")
    advertised = list(schema["properties"]["action"]["enum"])
    branch_titles = [b["title"] for b in schema["properties"]["input"]["oneOf"]]
    correlated = [
        c["if"]["properties"]["action"]["const"] for c in schema["allOf"]
    ]
    assert advertised == list(ACTION_ORDER)
    assert correlated == advertised
    assert branch_titles == [f"{name} input" for name in advertised]


def test_each_action_advertises_only_its_own_input():
    """Per-action fields no longer leak onto every other action.

    Pre-migration one flat root advertised `content`, `files`, `summary`,
    `keep_tool_calls`, `keep_last`, and `session_journal_path` to all eight
    operations at once. Each now belongs to the action that consumes it.
    """
    schema = get_schema("en")
    props = {
        c["if"]["properties"]["action"]["const"]:
            set(c["then"]["properties"]["input"]["properties"])
        for c in schema["allOf"]
    }
    assert props["lingtai_update"] == {"content"}
    assert props["lingtai_load"] == set()
    assert props["pad_edit"] == {"content", "files"}
    assert props["pad_load"] == set()
    assert props["pad_append"] == {"files"}
    assert props["context_molt"] == {
        "summary", "session_journal_path", "keep_tool_calls", "keep_last",
    }
    assert props["name_set"] == {"content"}
    assert props["name_nickname"] == {"content"}
    assert props["manual"] == set()
    # Every branch is closed.
    for cond in schema["allOf"]:
        assert cond["then"]["properties"]["input"]["additionalProperties"] is False


# ---------------------------------------------------------------------------
# Strict schema / dispatch rejection for every action.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("action", [a for a in ACTION_ORDER])
def test_unknown_root_field_is_rejected_for_every_action(tmp_path, action):
    agent = _agent(tmp_path)
    try:
        result = _call(agent, {
            "action": action, "input": {}, "reasoning": "why", "bogus": 1,
        })
        assert result["status"] == "failed"
        assert result["error_code"] == "INVALID_ARGUMENT"
    finally:
        agent.stop(timeout=1.0)


@pytest.mark.parametrize("action", [a for a in ACTION_ORDER])
def test_non_bool_summarize_is_rejected_for_every_action(tmp_path, action):
    agent = _agent(tmp_path)
    try:
        result = _call(agent, {
            "action": action, "input": {}, "summarize": "yes",
        })
        assert result["status"] == "failed"
        assert result["error_code"] == "INVALID_ARGUMENT"
        assert "summarize must be a boolean" in result["message"]
    finally:
        agent.stop(timeout=1.0)


@pytest.mark.parametrize("bad_action", [[], {}, None, 3, "context_forget"])
def test_unhashable_or_unknown_action_renders_the_stable_error(tmp_path, bad_action):
    """Invalid JSON can make `action` unhashable (issue #513) — never a TypeError.

    `context_forget` is included deliberately: it is a real internal function
    but was never an agent-callable action, and must not become one.
    """
    agent = _agent(tmp_path)
    try:
        result = _call(agent, {"action": bad_action, "input": {}})
        assert "error" in result
        assert "Unknown psyche action" in result["error"]
    finally:
        agent.stop(timeout=1.0)


def test_wrong_branch_input_is_rejected_before_any_handler_io(tmp_path):
    """A cross-action smuggle writes nothing and sheds nothing."""
    agent = _agent(tmp_path)
    try:
        # `summary` belongs to context_molt, not pad_edit.
        result = _call(agent, {
            "action": "pad_edit",
            "input": {"content": "x", "summary": "smuggled"},
        })
        assert result["status"] == "failed"
        assert result["error_code"] == "INVALID_ARGUMENT"
        assert "unsupported psyche input field" in result["message"]
        # No pad written by the refused call.
        assert not (agent._working_dir / "system" / "pad.md").read_text()

        # And the reverse: pad fields cannot reach the molt.
        before = agent._molt_count
        result = _call(agent, {
            "action": "context_molt",
            "input": _molt_input(_JOURNAL_REL, files=["x.txt"]),
        })
        assert result["status"] == "failed"
        assert result["error_code"] == "INVALID_ARGUMENT"
        assert agent._molt_count == before
    finally:
        agent.stop(timeout=1.0)


def test_non_object_input_is_rejected(tmp_path):
    agent = _agent(tmp_path)
    try:
        result = _call(agent, {"action": "pad_load", "input": "notanobject"})
        assert result["status"] == "failed"
        assert result["error_code"] == "INVALID_ARGUMENT"
        assert "input must be an object" in result["message"]
    finally:
        agent.stop(timeout=1.0)


def test_reasoning_and_summarize_never_reach_a_handler(tmp_path):
    """Envelope controls are not action input, and never appear in a branch."""
    schema = get_schema("en")
    for cond in schema["allOf"]:
        branch = cond["then"]["properties"]["input"]["properties"]
        for reserved in ("reasoning", "_reasoning", "summarize", "_tc_id"):
            assert reserved not in branch

    agent = _agent(tmp_path)
    seen: list[dict] = []
    try:
        import lingtai.tools.psyche as mod

        original = mod._pad_load

        def spy(agent_arg, args):
            seen.append(dict(args))
            return original(agent_arg, args)

        saved = mod._CHILD_SPECS
        mod._CHILD_SPECS = tuple(
            (n, s, spy if n == "pad_load" else h) for n, s, h in saved
        )
        try:
            result = _call(agent, {
                "action": "pad_load", "input": {},
                "reasoning": "check", "summarize": True, "_tc_id": "toolu_x",
            })
            assert result["status"] == "ok"
            # The spy really ran — otherwise the assertions below are vacuous.
            assert len(seen) == 1, "pad_load handler was not the dispatched child"
            for reserved in ("reasoning", "_reasoning", "summarize", "_tc_id"):
                assert reserved not in seen[0]
        finally:
            mod._CHILD_SPECS = saved
    finally:
        agent.stop(timeout=1.0)


def test_tc_id_is_isolated_to_the_molt_handler(tmp_path):
    """`_tc_id` is stripped from the closed root but still reaches the molt.

    Psyche is the one migrated family that genuinely *consumes* this transport
    key rather than merely dropping it (`soul`/`notification` drop it). It must
    therefore neither break the closed-root check nor leak to any other action.
    """
    agent = _agent(tmp_path)
    try:
        # It does not trip the unknown-root-field check on an unrelated action.
        result = _call(agent, {
            "action": "pad_load", "input": {}, "_tc_id": "toolu_abc",
        })
        assert result["status"] == "ok"

        # And a molt without it is refused with the internal-guard message
        # rather than shedding context, once the journal gate has passed.
        _write_journal(agent)
        agent._session.ensure_session()
        before = agent._molt_count
        result = _call(agent, {
            "action": "context_molt", "input": _molt_input(_JOURNAL_REL),
        })
        assert "error" in result
        assert "_tc_id" in result["error"]
        assert agent._molt_count == before
    finally:
        agent.stop(timeout=1.0)


# ---------------------------------------------------------------------------
# Destructive / read-only risk semantics.
# ---------------------------------------------------------------------------


def test_pad_edit_is_a_full_rewrite_that_still_refuses_a_bare_call(tmp_path):
    """Empty content clears deliberately; neither-content-nor-files is refused.

    This is the pre-migration safety kept verbatim across the nullable
    representation: `{"content": null, "files": null}` is the strict-schema
    spelling of "no argument given" and must stay a refusal, not a silent wipe.
    """
    agent = _agent(tmp_path)
    try:
        assert _call(agent, {
            "action": "pad_edit", "input": {"content": "notes", "files": None},
        })["status"] == "ok"
        pad = agent._working_dir / "system" / "pad.md"
        assert pad.read_text() == "notes"

        # Bare call refused — the existing pad survives.
        result = _call(agent, {
            "action": "pad_edit", "input": {"content": None, "files": None},
        })
        assert "error" in result
        assert pad.read_text() == "notes"

        # Explicit empty string clears (intended destruction).
        assert _call(agent, {
            "action": "pad_edit", "input": {"content": "", "files": None},
        })["status"] == "ok"
        assert pad.read_text() == ""
    finally:
        agent.stop(timeout=1.0)


def test_lingtai_update_is_a_full_rewrite(tmp_path):
    agent = _agent(tmp_path)
    try:
        _call(agent, {"action": "lingtai_update", "input": {"content": "first"}})
        _call(agent, {"action": "lingtai_update", "input": {"content": "second"}})
        # Replaced entirely, not appended.
        assert (agent._working_dir / "system" / "lingtai.md").read_text() == "second"
    finally:
        agent.stop(timeout=1.0)


def test_pad_append_pinning_and_read_only_reload(tmp_path):
    """null reads the list; [] clears it; a set list is pinned and reloaded."""
    agent = _agent(tmp_path)
    agent.start()
    try:
        (agent._working_dir / "ref.txt").write_text("pinned reference")

        # null == query, mutating nothing.
        result = _call(agent, {"action": "pad_append", "input": {"files": None}})
        assert result == {"status": "ok", "files": [], "count": 0}

        result = _call(agent, {"action": "pad_append", "input": {"files": ["ref.txt"]}})
        assert result["status"] == "ok"
        assert result["action"] == "set"
        assert "pinned reference" in agent._prompt_manager.read_section("pad")

        result = _call(agent, {"action": "pad_append", "input": {"files": []}})
        assert result["action"] == "cleared"
    finally:
        agent.stop()


def test_pad_append_rejects_missing_and_binary_files(tmp_path):
    agent = _agent(tmp_path)
    try:
        result = _call(agent, {"action": "pad_append", "input": {"files": ["nope.txt"]}})
        assert "Files not found" in result["error"]

        binary = agent._working_dir / "blob.bin"
        binary.write_bytes(b"\x00\x01\x02")
        result = _call(agent, {"action": "pad_append", "input": {"files": ["blob.bin"]}})
        assert "Only text files" in result["error"]
    finally:
        agent.stop(timeout=1.0)


def test_name_set_is_once_while_nickname_stays_mutable(tmp_path):
    # No `agent_name=` at construction, so the true name is genuinely unset
    # and `name_set` exercises the real set-once path.
    agent = Agent(service=make_mock_service(), working_dir=tmp_path / "test")
    try:
        assert _call(agent, {"action": "name_set", "input": {"content": "悟空"}})["name"] == "悟空"
        # Set-once: a second true name is refused.
        assert "error" in _call(agent, {"action": "name_set", "input": {"content": "八戒"}})
        # Empty is refused rather than clearing the true name.
        assert "error" in _call(agent, {"action": "name_set", "input": {"content": ""}})

        # Nickname updates freely and clears on empty.
        assert _call(agent, {"action": "name_nickname", "input": {"content": "monkey"}})["nickname"] == "monkey"
        assert _call(agent, {"action": "name_nickname", "input": {"content": "king"}})["nickname"] == "king"
        assert _call(agent, {"action": "name_nickname", "input": {"content": ""}})["nickname"] is None
    finally:
        agent.stop(timeout=1.0)


@pytest.mark.parametrize("action", ["lingtai_load", "pad_load", "manual"])
def test_read_only_actions_mutate_no_durable_state(tmp_path, action):
    agent = _agent(tmp_path)
    agent.start()
    try:
        _call(agent, {"action": "pad_edit", "input": {"content": "keep me", "files": None}})
        _call(agent, {"action": "lingtai_update", "input": {"content": "identity"}})
        before_molt = agent._molt_count

        _call(agent, {"action": action, "input": {}})

        assert (agent._working_dir / "system" / "pad.md").read_text() == "keep me"
        assert (agent._working_dir / "system" / "lingtai.md").read_text() == "identity"
        assert agent._molt_count == before_molt
    finally:
        agent.stop()


# ---------------------------------------------------------------------------
# Molt: refusal before shed, and a successful disposable lifecycle.
# ---------------------------------------------------------------------------


def _molt_agent(tmp_path):
    """An agent with a real ChatInterface so a molt can actually run."""
    from lingtai.kernel.llm.interface import ChatInterface, TextBlock

    svc = make_mock_service()

    def fake_create_session(**kwargs):
        chat = MagicMock()
        iface = ChatInterface()
        iface.add_system("You are helpful.")
        chat.interface = iface
        chat.context_window.return_value = 100_000
        return chat

    svc.create_session.side_effect = fake_create_session
    agent = Agent(service=svc, agent_name="test", working_dir=tmp_path / "test")
    agent.start()
    agent._session.ensure_session()
    agent._session._chat.interface.add_user_message("Hello")
    agent._session._chat.interface.add_assistant_message([TextBlock(text="Hi.")])
    return agent


def _emit_molt_call(agent, wire_id, action_input):
    """Append the agent's own molt call to history, in the provider-valid shape.

    `_context_molt` replays this exact block into the fresh session, where it
    becomes model-visible history. So the fixture must emit what a real
    provider call looks like — every key `context_molt`'s strict schema marks
    required, with unused optionals as explicit null — not a convenient partial
    dict. Emitting a partial here would let the replay assertions pass against
    a shape the advertised schema rejects.
    """
    from lingtai.kernel.llm.interface import ToolCallBlock

    payload = _molt_input(
        action_input.get("session_journal_path"),
        summary=action_input.get("summary"),
        keep_tool_calls=action_input.get("keep_tool_calls"),
        keep_last=action_input.get("keep_last"),
    )
    agent._session._chat.interface.add_assistant_message([
        ToolCallBlock(
            id=wire_id, name="psyche",
            args={"action": "context_molt", "input": payload},
        ),
    ])


@pytest.mark.parametrize("journal,reason", [
    (None, "missing"),
    ("knowledge/session-journal/KNOWLEDGE.md", "parent index"),
    ("tmp/scratch.md", "scratch path"),
])
def test_molt_refuses_before_shedding_on_an_invalid_journal(tmp_path, journal, reason):
    """The gate runs before snapshot/archive/wipe/molt_count — fail closed."""
    agent = _molt_agent(tmp_path)
    try:
        wire = "toolu_psyche_gate"
        _emit_molt_call(agent, wire, {"summary": "briefing"})
        before_count = agent._molt_count
        before_chat = agent._session._chat

        result = _call(agent, {
            "action": "context_molt",
            "input": _molt_input(journal),
            "_tc_id": wire,
        })

        assert "error" in result, reason
        assert agent._molt_count == before_count
        assert agent._session._chat is before_chat
        # Nothing shed: no snapshot and no archive were written.
        assert not (agent._working_dir / "history" / "snapshots").exists()
        assert not (agent._working_dir / "history" / "chat_history_archive.jsonl").exists()
    finally:
        agent.stop()


def test_molt_refuses_an_empty_summary_before_the_journal_gate(tmp_path):
    agent = _molt_agent(tmp_path)
    try:
        _write_journal(agent)
        before = agent._molt_count
        result = _call(agent, {
            "action": "context_molt",
            "input": _molt_input(_JOURNAL_REL, summary=""),
            "_tc_id": "toolu_psyche_empty",
        })
        assert "empty" in result["error"].lower()
        assert agent._molt_count == before
    finally:
        agent.stop()


def test_successful_molt_lifecycle_in_a_disposable_workdir(tmp_path):
    """A full molt on a pytest tmp_path agent — never a live agent directory."""
    agent = _molt_agent(tmp_path)
    try:
        journal = _write_journal(agent)
        wire = "toolu_psyche_molt_ok"
        summary = "Findings: X=42. Next: analyze Z."
        action_input = {"summary": summary, "session_journal_path": journal}
        _emit_molt_call(agent, wire, action_input)

        result = _call(agent, {
            "action": "context_molt",
            "input": _molt_input(journal, summary=summary),
            "_tc_id": wire,
            "reasoning": "context is full",
        })

        # Outer result fields are exactly the pre-migration set.
        assert result["status"] == "ok"
        assert result["molt_count"] == 1
        assert result["session_journal_path"] == journal
        for key in ("note", "tokens_before", "tokens_after", "tokens_shed",
                    "kept_tool_calls", "kept_last", "archive_path", "summary_path"):
            assert key in result

        # Durable stores: summary written with the journal recorded.
        summary_file = agent._working_dir / result["summary_path"]
        assert "source: agent" in summary_file.read_text()
        assert journal in summary_file.read_text()

        # Snapshot persisted for past-self consultation.
        snapshots = sorted((agent._working_dir / "history" / "snapshots").glob("*.json"))
        assert len(snapshots) == 1
        assert json.loads(snapshots[0].read_text())

        # The molt's own call was replayed into the fresh session, verbatim,
        # in the migrated envelope — so history teaches a shape dispatch accepts.
        from lingtai.kernel.llm.interface import ToolCallBlock
        iface = agent._session._chat.interface
        last = [e for e in iface.entries if e.role == "assistant"][-1]
        replayed = [b for b in last.content if isinstance(b, ToolCallBlock)][0]
        assert replayed.id == wire
        assert replayed.args["action"] == "context_molt"
        assert replayed.args["input"]["summary"] == summary
        # The replayed block is model-visible history, so it must satisfy the
        # strict schema this family advertises — same obligation the synthesized
        # forced-molt pair carries.
        molt_schema = next(
            c["then"]["properties"]["input"] for c in get_schema("en")["allOf"]
            if c["if"]["properties"]["action"]["const"] == "context_molt"
        )
        assert set(replayed.args["input"]) == set(molt_schema["required"])
        assert not set(replayed.args["input"]) - set(molt_schema["properties"])

        # Post-molt reminder published.
        assert (agent._working_dir / ".notification" / "post-molt.json").is_file()
    finally:
        agent.stop()


def test_system_forced_molt_synthesizes_the_current_envelope(tmp_path):
    """`context_forget`'s synthesized pair is model-visible history.

    It is replayed to the provider as an assistant `tool_use` block, so it must
    carry the envelope the schema advertises — a model imitating the old flat
    `{"object": "context", "action": "molt"}` would now be rejected.
    """
    from lingtai.kernel.llm.interface import ToolCallBlock
    from lingtai.tools.psyche import context_forget
    from lingtai.tools.psyche._molt import SYSTEM_FORCED_MOLT_REASONING

    agent = _molt_agent(tmp_path)
    try:
        result = context_forget(agent, source="warning_ladder")
        assert result["status"] == "ok"
        assert result["_initiator"] == "system"

        iface = agent._session._chat.interface
        synth = [
            b for e in iface.entries if e.role == "assistant"
            for b in e.content if isinstance(b, ToolCallBlock)
        ][-1]
        assert synth.args["action"] == "context_molt"
        assert synth.args["reasoning"] == SYSTEM_FORCED_MOLT_REASONING

        # The replayed `input` must satisfy the strict schema this family
        # advertises — every required key present, with the three the forced
        # path does not use spelled as explicit null (the provider-compatible
        # representation of "absent"). A partial object here would teach a
        # model imitating its own history a call the schema rejects.
        molt_schema = next(
            c["then"]["properties"]["input"] for c in get_schema("en")["allOf"]
            if c["if"]["properties"]["action"]["const"] == "context_molt"
        )
        action_input = synth.args["input"]
        assert set(action_input) == set(molt_schema["required"])
        assert set(action_input) == {
            "summary", "session_journal_path", "keep_tool_calls", "keep_last",
        }
        assert action_input["summary"]
        assert action_input["session_journal_path"] is None
        assert action_input["keep_tool_calls"] is None
        assert action_input["keep_last"] is None
        # No key outside the branch's own declared properties.
        assert not set(action_input) - set(molt_schema["properties"])

        # Provenance stays OUTSIDE input — it is not action input.
        assert synth.args["_initiator"] == "system"
        assert "_initiator" not in action_input
        assert "_source" not in action_input
        assert "object" not in synth.args
    finally:
        agent.stop()


def test_kernel_detects_the_migrated_molt_call_shape():
    """The turn loop's molt-batch deferral reads the migrated spelling."""
    from lingtai.kernel.base_agent.turn import _batch_includes_context_molt
    from lingtai.kernel.llm.base import ToolCall

    migrated = ToolCall(
        name="psyche",
        args={"action": "context_molt", "input": {"summary": "s"}},
        id="call_molt",
    )
    assert _batch_includes_context_molt([migrated]) is True
    # A non-molt psyche call must not trigger the deferral.
    other = ToolCall(
        name="psyche", args={"action": "pad_load", "input": {}}, id="call_pad",
    )
    assert _batch_includes_context_molt([other]) is False


# ---------------------------------------------------------------------------
# Reserved manual: no double wrap, and no psyche operation.
# ---------------------------------------------------------------------------


def test_manual_child_returns_the_canonical_result_unwrapped(tmp_path):
    """`ToolFamily.handle()` returns the reserved child's result verbatim."""
    from lingtai.tools.psyche import _build_children
    from lingtai.tools.tool_family import ToolFamily

    agent = _agent(tmp_path)
    try:
        family = ToolFamily("psyche", _build_children(agent))
        raw = family.handle({"action": "manual", "input": {}})
        # Canonical ManualTool shape — full body + host-local path, no flatten.
        assert raw["content"][0]["text"]
        assert raw["structuredContent"]["manual_path"]
        assert "manual" not in raw  # not double-wrapped into psyche's flat shape
    finally:
        agent.stop(timeout=1.0)


def test_manual_public_result_is_flattened_post_dispatch(tmp_path):
    """Psyche's own Host layer restores its pinned flat public shape."""
    agent = _agent(tmp_path)
    try:
        result = _call(agent, {"action": "manual", "input": {}})
        assert result["status"] in ("ok", "degraded")
        assert result["manual"]
        assert result["manual_path"]
        # The canonical fields do not leak into the public result.
        assert "content" not in result
        assert "structuredContent" not in result
    finally:
        agent.stop(timeout=1.0)


def test_manual_rejects_any_input_key(tmp_path):
    agent = _agent(tmp_path)
    try:
        result = _call(agent, {"action": "manual", "input": {"content": "x"}})
        assert result["status"] == "failed"
        assert result["error_code"] == "INVALID_ARGUMENT"
    finally:
        agent.stop(timeout=1.0)


# ---------------------------------------------------------------------------
# Kernel allowlist + wire parity.
# ---------------------------------------------------------------------------


def test_psyche_is_on_the_ltp_v2_summarize_allowlist():
    """Advertising root `summarize` obliges joining the kernel allowlist."""
    from lingtai.kernel.tool_result_summary import summary_requested

    assert summary_requested({"summarize": True}, tool_name="psyche") is True
    assert summary_requested({"summarize": False}, tool_name="psyche") is False
    # `summary` is psyche's own molt domain field, never this control.
    assert summary_requested({"summary": "a briefing"}, tool_name="psyche") is False


def test_one_psyche_root_survives_both_wires_with_action_input_correlation(tmp_path):
    """Exactly one public root, closed, `reasoning` required, on both wires.

    Also proves the root `allOf` action/input correlation reaches the provider
    intact — including that `session_journal_path` stays bound to
    `context_molt`'s branch, which is what lets a provider reject a mis-paired
    molt before it is ever dispatched.
    """
    from lingtai.kernel.base_agent.tools import _build_tool_schemas
    from lingtai.llm.openai.adapter import _build_responses_tools, _build_tools

    live = _agent(tmp_path)
    try:
        schemas = _build_tool_schemas(live)
        psyche_schemas = [s for s in schemas if s.name == "psyche"]
        assert len(psyche_schemas) == 1, "exactly one public psyche root"

        chat = _build_tools(psyche_schemas)[0]["function"]["parameters"]
        responses = _build_responses_tools(psyche_schemas)[0]["parameters"]
        for wire, combinator in ((chat, "oneOf"), (responses, "anyOf")):
            assert set(wire["properties"]) == {
                "action", "input", "reasoning", "summarize",
            }
            # Agent composition re-injects the identical `reasoning` property
            # text but never touches `required` — the family's own composed
            # schema is what keeps it required.
            assert wire["required"] == ["action", "input", "reasoning"]
            assert wire["properties"]["action"]["enum"] == list(ACTION_ORDER)
            branches = wire["properties"]["input"][combinator]
            assert [b["title"] for b in branches] == [
                f"{a} input" for a in ACTION_ORDER
            ]
            assert len(wire["allOf"]) == len(ACTION_ORDER)
            molt = next(
                c["then"]["properties"]["input"] for c in wire["allOf"]
                if c["if"]["properties"]["action"]["const"] == "context_molt"
            )
            assert "session_journal_path" in molt["properties"]
    finally:
        live.stop(timeout=1.0)
