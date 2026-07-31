"""Tests for OpenAIChatSession._pair_orphan_tool_calls — the final wire-layer
guard that synthesizes placeholder tool messages for any assistant[tool_calls]
not immediately followed by matching role=tool entries.

This guard is defense-in-depth: the canonical ChatInterface invariant + AED
healing + session restore healing all try to prevent dangling state from
reaching the wire. This guard catches anything that slips through and
prevents strict providers (OpenAI, DeepSeek) from returning generic 400s.

Synthesis is local to each serialization pass — canonical interface is not
mutated, and real tool_results that arrive later will be serialized
naturally on the next send (implicit dedup).
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from lingtai.llm.openai.adapter import OpenAIChatSession
from lingtai.kernel.llm.interface import (
    ChatInterface,
    ToolCallBlock,
    ToolResultBlock,
)
from tests._chat_completion_helpers import make_raw_response


_SYNTH_MARKER = "[synthesized placeholder"


def _make_session(client=None) -> OpenAIChatSession:
    """Build an isolated session with no real state; we only call
    _pair_orphan_tool_calls directly with hand-crafted message lists."""
    return OpenAIChatSession(
        client=client or MagicMock(),
        model="test",
        interface=ChatInterface(),
        tools=None,
        tool_choice=None,
        extra_kwargs={},
        client_kwargs={},
    )


def test_noop_when_no_tool_calls():
    s = _make_session()
    msgs = [
        {"role": "system", "content": "you are helpful"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    out = s._pair_orphan_tool_calls(msgs)
    assert out == msgs


def test_noop_when_tool_calls_properly_paired():
    s = _make_session()
    msgs = [
        {"role": "user", "content": "go"},
        {
            "role": "assistant",
            "content": "calling",
            "tool_calls": [
                {"id": "A", "type": "function", "function": {"name": "t", "arguments": "{}"}},
                {"id": "B", "type": "function", "function": {"name": "t", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "A", "content": "result A"},
        {"role": "tool", "tool_call_id": "B", "content": "result B"},
        {"role": "user", "content": "next"},
    ]
    out = s._pair_orphan_tool_calls(msgs)
    assert out == msgs  # untouched


def test_synthesizes_for_fully_orphan_tool_calls():
    """All tool_calls orphan — the next message is a non-tool entry."""
    s = _make_session()
    msgs = [
        {"role": "user", "content": "go"},
        {
            "role": "assistant",
            "content": "calling",
            "tool_calls": [
                {"id": "A", "type": "function", "function": {"name": "t", "arguments": "{}"}},
                {"id": "B", "type": "function", "function": {"name": "t", "arguments": "{}"}},
            ],
        },
        # System interleaved — this is the real-world pathology from context
        # mutating the prompt between assistant[tool_calls] and tool_results.
        {"role": "system", "content": "new system"},
        {"role": "user", "content": "next"},
    ]
    out = s._pair_orphan_tool_calls(msgs)
    # Expect tool messages synthesized right after the assistant turn.
    assert out[0] == msgs[0]
    assert out[1] == msgs[1]
    assert out[2]["role"] == "tool"
    assert out[2]["tool_call_id"] == "A"
    assert _SYNTH_MARKER in out[2]["content"]
    assert out[3]["role"] == "tool"
    assert out[3]["tool_call_id"] == "B"
    assert _SYNTH_MARKER in out[3]["content"]
    # Remainder preserved in original order.
    assert out[4] == msgs[2]  # the system entry
    assert out[5] == msgs[3]  # the later user entry
    assert len(out) == len(msgs) + 2


def test_synthesizes_for_partially_orphan_tool_calls():
    """Some tool_calls have results, others don't — synthesize only the missing."""
    s = _make_session()
    msgs = [
        {
            "role": "assistant",
            "tool_calls": [
                {"id": "A", "type": "function", "function": {"name": "t", "arguments": "{}"}},
                {"id": "B", "type": "function", "function": {"name": "t", "arguments": "{}"}},
                {"id": "C", "type": "function", "function": {"name": "t", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "A", "content": "result A"},
        # B is missing — cancelled or never ran
        {"role": "tool", "tool_call_id": "C", "content": "result C"},
        {"role": "user", "content": "next"},
    ]
    out = s._pair_orphan_tool_calls(msgs)
    # After the A and C tool messages, a synthesized B should be appended
    # BEFORE the run of real tool messages ends. But our implementation
    # appends the synthesis immediately after the assistant turn, so the
    # order becomes: assistant → synth(B) → real(A) → real(C) → user.
    # That's still valid OpenAI-compat wire format: all tool messages
    # follow the assistant turn contiguously before any non-tool entry.
    assert out[0] == msgs[0]
    # Three tool messages in a row, one of which is synthetic for B.
    tool_block = out[1:4]
    roles = [m["role"] for m in tool_block]
    assert roles == ["tool", "tool", "tool"]
    covered_ids = {m["tool_call_id"] for m in tool_block}
    assert covered_ids == {"A", "B", "C"}
    # The synth is the one for B.
    synth = next(m for m in tool_block if m["tool_call_id"] == "B")
    assert _SYNTH_MARKER in synth["content"]
    # The real A and C are unchanged.
    real_a = next(m for m in tool_block if m["tool_call_id"] == "A")
    assert real_a["content"] == "result A"
    real_c = next(m for m in tool_block if m["tool_call_id"] == "C")
    assert real_c["content"] == "result C"
    # User message still at the end.
    assert out[-1] == msgs[-1]


def test_tail_dangling_assistant_is_paired():
    """assistant[tool_calls] at the very end with nothing following → synth."""
    s = _make_session()
    msgs = [
        {"role": "user", "content": "go"},
        {
            "role": "assistant",
            "content": "calling",
            "tool_calls": [
                {"id": "X", "type": "function", "function": {"name": "t", "arguments": "{}"}},
            ],
        },
    ]
    out = s._pair_orphan_tool_calls(msgs)
    assert len(out) == 3
    assert out[-1]["role"] == "tool"
    assert out[-1]["tool_call_id"] == "X"
    assert _SYNTH_MARKER in out[-1]["content"]


def test_does_not_mutate_input():
    """Verify the function doesn't modify the input list in place."""
    s = _make_session()
    msgs = [
        {"role": "user", "content": "go"},
        {
            "role": "assistant",
            "tool_calls": [
                {"id": "A", "type": "function", "function": {"name": "t", "arguments": "{}"}},
            ],
        },
        {"role": "user", "content": "next"},
    ]
    original_len = len(msgs)
    original_first = dict(msgs[0])
    out = s._pair_orphan_tool_calls(msgs)
    assert len(msgs) == original_len
    assert msgs[0] == original_first
    assert len(out) == original_len + 1


def test_multiple_assistant_tool_call_turns():
    """Two separate assistant[tool_calls] turns, both orphan — both get
    synthesized independently."""
    s = _make_session()
    msgs = [
        {
            "role": "assistant",
            "tool_calls": [{"id": "A1", "type": "function", "function": {"name": "t", "arguments": "{}"}}],
        },
        {"role": "user", "content": "interrupt"},
        {
            "role": "assistant",
            "tool_calls": [{"id": "A2", "type": "function", "function": {"name": "t", "arguments": "{}"}}],
        },
        {"role": "user", "content": "end"},
    ]
    out = s._pair_orphan_tool_calls(msgs)
    # Synthesized for A1 after first assistant, and A2 after second.
    synth_positions = [i for i, m in enumerate(out) if m.get("role") == "tool"]
    assert len(synth_positions) == 2
    assert out[synth_positions[0]]["tool_call_id"] == "A1"
    assert out[synth_positions[1]]["tool_call_id"] == "A2"


def test_tool_call_with_missing_id_is_skipped():
    """Malformed tool_calls without an id are silently skipped (no synthesis)."""
    s = _make_session()
    msgs = [
        {
            "role": "assistant",
            "tool_calls": [
                {"type": "function", "function": {"name": "t", "arguments": "{}"}},  # no id
                {"id": "B", "type": "function", "function": {"name": "t", "arguments": "{}"}},
            ],
        },
        {"role": "user", "content": "next"},
    ]
    out = s._pair_orphan_tool_calls(msgs)
    # Only one synthesis (for B) — the id-less tool_call can't be matched or synthesized.
    tool_msgs = [m for m in out if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["tool_call_id"] == "B"


# ---------------------------------------------------------------------------
# Shared post-build/pre-SDK validator regressions
# ---------------------------------------------------------------------------


_VALID_TOOL_CALL = {
    "id": "call-known",
    "type": "function",
    "function": {"name": "lookup", "arguments": '{"secret":"do-not-leak"}'},
}


@pytest.mark.parametrize(
    ("label", "messages"),
    [
        (
            "standalone",
            [{"role": "tool", "tool_call_id": "old-call", "content": "secret-result"}],
        ),
        (
            "non_contiguous",
            [
                {"role": "assistant", "tool_calls": [_VALID_TOOL_CALL]},
                {"role": "user", "content": "separator"},
                {"role": "tool", "tool_call_id": "call-known", "content": "secret-result"},
            ],
        ),
        (
            "wrong_batch",
            [
                {"role": "assistant", "tool_calls": [_VALID_TOOL_CALL]},
                {"role": "tool", "tool_call_id": "other-call", "content": "secret-result"},
            ],
        ),
        (
            "duplicate",
            [
                {"role": "assistant", "tool_calls": [_VALID_TOOL_CALL]},
                {"role": "tool", "tool_call_id": "call-known", "content": "first-secret"},
                {"role": "tool", "tool_call_id": "call-known", "content": "second-secret"},
            ],
        ),
        (
            "idless",
            [
                {"role": "assistant", "tool_calls": [_VALID_TOOL_CALL]},
                {"role": "tool", "content": "secret-result"},
            ],
        ),
    ],
)
@pytest.mark.parametrize("streaming", [False, True], ids=["send", "send_stream"])
def test_malformed_tool_rows_fail_closed_before_client_call(label, messages, streaming):
    """Every malformed row is rejected after post-build pairing and before SDK dispatch."""
    client = MagicMock()
    session = _make_session(client)
    session._build_messages = lambda: messages

    with pytest.raises(ValueError) as exc_info:
        if streaming:
            session.send_stream(None)
        else:
            session.send(None)

    error = str(exc_info.value)
    assert "tool pairing" in error
    assert "phase=" in error
    assert "secret" not in error
    assert "call-known" not in error
    assert label in error
    assert client.chat.completions.create.call_count == 0


_MIXED_OBJECT_SENTINEL = "mixed-tool-call-secret-do-not-leak"


class _NonDictToolCall:
    def __repr__(self):
        return f"<non-dict-tool-call {_MIXED_OBJECT_SENTINEL}>"


@pytest.mark.parametrize("streaming", [False, True], ids=["send", "send_stream"])
def test_mixed_non_dict_tool_call_fails_closed_before_client_call(streaming, caplog):
    """A mixed call batch gets a sanitized structural error before dispatch."""
    client = MagicMock()
    session = _make_session(client)
    messages = [
        {
            "role": "assistant",
            "tool_calls": [_VALID_TOOL_CALL, _NonDictToolCall()],
        },
    ]
    session._build_messages = lambda: messages

    caplog.set_level(logging.WARNING)
    with pytest.raises(ValueError) as exc_info:
        if streaming:
            session.send_stream(None)
        else:
            session.send(None)

    error = exc_info.value
    assert str(error) == "tool pairing rejected: reason=invalid_call phase=wire_pairing"
    assert error.reason == "invalid_call"
    assert error.phase == "wire_pairing"
    assert _MIXED_OBJECT_SENTINEL not in str(error)
    assert _MIXED_OBJECT_SENTINEL not in caplog.text
    assert client.chat.completions.create.call_count == 0


def test_valid_single_and_parallel_batches_reach_sdk_unchanged():
    """Single and parallel result batches remain ordered/content-preserving."""
    client = MagicMock()
    client.chat.completions.create.return_value = make_raw_response(content="done")
    iface = ChatInterface()
    iface.add_assistant_message(
        [
            ToolCallBlock(id="single", name="lookup", args={}),
        ]
    )
    iface.add_tool_results([
        ToolResultBlock(id="single", name="lookup", content="single-result"),
    ])
    iface.add_assistant_message(
        [
            ToolCallBlock(id="parallel-a", name="lookup", args={}),
            ToolCallBlock(id="parallel-b", name="lookup", args={}),
        ]
    )
    # Parallel result order is intentionally not call order.
    iface.add_tool_results([
        ToolResultBlock(id="parallel-b", name="lookup", content="parallel-b-result"),
        ToolResultBlock(id="parallel-a", name="lookup", content="parallel-a-result"),
    ])
    session = OpenAIChatSession(
        client=client,
        model="test",
        interface=iface,
        tools=None,
        tool_choice=None,
        extra_kwargs={},
        client_kwargs={},
    )

    session.send(None)

    sent = client.chat.completions.create.call_args.kwargs["messages"]
    assert [m["role"] for m in sent] == [
        "assistant", "tool", "assistant", "tool", "tool",
    ]
    assert [m.get("tool_call_id") for m in sent if m["role"] == "tool"] == [
        "single", "parallel-b", "parallel-a",
    ]
    assert [m["content"] for m in sent if m["role"] == "tool"] == [
        "single-result", "parallel-b-result", "parallel-a-result",
    ]
