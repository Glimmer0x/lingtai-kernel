"""Strict daemon/main all-empty response recovery parity tests."""

from __future__ import annotations

import inspect
import json
import threading
from types import SimpleNamespace

import pytest

from lingtai.kernel.llm.base import ChatSession, FunctionSchema, LLMResponse, ToolCall, UsageMetadata
from lingtai.kernel.llm.interface import ChatInterface, TextBlock, ToolCallBlock, ToolResultBlock
from lingtai.tools import daemon as daemon_tool
from tests._daemon_helpers import make_daemon_agent as _make_agent
from tests._daemon_helpers import make_daemon_run_dir as _make_run_dir


class _ParitySession(ChatSession):
    def __init__(self, responses, *, system_prompt, interface=None):
        self._interface = interface or ChatInterface()
        if interface is None:
            self._interface.add_system(system_prompt)
        self._responses = responses
        self.sent_messages = []

    @property
    def interface(self):
        return self._interface

    def send(self, message):
        self.sent_messages.append(message)
        if isinstance(message, str):
            self.interface.add_user_message(message)
        elif isinstance(message, list):
            self.interface.add_tool_results(message)
        else:
            raise TypeError(type(message).__name__)
        response = self._responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        # Canonical providers preserve the assistant entry, including an empty
        # successful response.  This matters for retry history and tool pairing.
        blocks = [TextBlock(response.text or "")]
        blocks.extend(
            ToolCallBlock(id=tc.id or "", name=tc.name, args=dict(tc.args or {}))
            for tc in response.tool_calls or []
        )
        self.interface.add_assistant_message(blocks)
        return response


class _ParityService:
    provider = "mock"
    model = "mock-model"
    api_key = "fake"
    _base_url = None
    _provider_defaults = {}

    def __init__(self, responses):
        self._responses = list(responses)
        self.sessions = []
        self.tool_results = []

    def create_session(self, *, system_prompt, interface=None, **_kwargs):
        session = _ParitySession(self._responses, system_prompt=system_prompt, interface=interface)
        self.sessions.append(session)
        return session

    def make_tool_result(self, tool_name, result, *, tool_call_id=None, provider=None):
        self.tool_results.append((tool_name, result, tool_call_id))
        return ToolResultBlock(id=tool_call_id or "", name=tool_name, content=result)


def _response(text="", tool_calls=None, thoughts=None):
    return LLMResponse(
        text=text,
        tool_calls=list(tool_calls or []),
        thoughts=list(thoughts or []),
        usage=UsageMetadata(input_tokens=1, output_tokens=1),
    )


def _fixture(tmp_path, monkeypatch, responses, *, max_turns=4, max_aed_attempts=3):
    agent = _make_agent(tmp_path, ["daemon"])
    agent._config.max_aed_attempts = max_aed_attempts
    service = _ParityService(responses)
    import lingtai.llm.service as service_mod

    monkeypatch.setattr(service_mod, "LLMService", lambda **_kwargs: service)
    monkeypatch.setattr(daemon_tool, "_wait_recovery_backoff", lambda *args: True)
    manager = agent.get_capability("daemon")
    run_dir = _make_run_dir(
        agent,
        em_id="em-parity",
        task="empty parity",
        max_turns=max_turns,
    )
    run_dir.update_state(
        call_parameters={
            "task": "empty parity",
            "tools": [],
            "mcp": [{"name": "daemon_common", "transport": "stdio"}],
        }
    )
    base_schemas, base_dispatch = manager._build_tool_surface([])
    completion_path = run_dir.path / "daemon_completion.json"

    finish_schema = FunctionSchema(
        name="finish",
        description="record completion",
        parameters={"type": "object", "properties": {}},
    )

    def finish(args):
        completion_path.write_text(
            json.dumps({"status": args.get("status"), "run_id": run_dir.run_id}),
            encoding="utf-8",
        )
        return {"status": "ok"}

    manager._emanations["em-parity"] = {
        "followup_buffer": "",
        "followup_lock": threading.Lock(),
        "run_dir": run_dir,
    }
    return (
        agent,
        manager,
        service,
        run_dir,
        [*base_schemas, finish_schema],
        {**base_dispatch, "finish": finish},
        completion_path,
    )


def _run(fixture, *, max_turns=4, cancel_event=None, timeout_event=None):
    _, manager, _, run_dir, schemas, dispatch, _ = fixture
    return manager._run_emanation(
        "em-parity",
        run_dir,
        schemas,
        dispatch,
        "task",
        cancel_event or threading.Event(),
        timeout_event,
        max_turns=max_turns,
    )


def _events(run_dir):
    if not run_dir.events_path.exists():
        return []
    return [json.loads(line) for line in run_dir.events_path.read_text().splitlines()]


def test_shared_predicate_is_exact_all_empty_contract():
    from lingtai.kernel.llm.base import is_all_empty_response

    assert is_all_empty_response(_response())
    assert is_all_empty_response(_response(text=None))
    assert not is_all_empty_response(_response(text=" \t"))
    assert not is_all_empty_response(_response(thoughts=["reasoning only"]))
    assert not is_all_empty_response(_response(tool_calls=[ToolCall("read", {}, "tc-1")]))
    assert not is_all_empty_response(_response(text="answer"))


def test_daemon_recovery_shares_only_the_pure_predicate():
    source = inspect.getsource(daemon_tool)
    assert "lingtai.kernel.base_agent.turn" not in source
    assert "EmptyLLMResponseError" not in source
    assert "_prepare_aed_retry_message" not in source
    assert "from lingtai.kernel.llm.base import FunctionSchema, is_all_empty_response" in source


def test_post_tool_empty_retry_refreshes_location_and_safe_event_error(tmp_path, monkeypatch):
    calls = []
    tool = ToolCall("side_effect", {"value": "one"}, "location-side-1")
    finish = ToolCall("finish", {"status": "done"}, "location-finish-1")
    fixture = _fixture(
        tmp_path,
        monkeypatch,
        [
            _response(tool_calls=[tool]),
            _response(),  # first empty after real tool results
            _response(),  # a retry is a fresh initial-send request
            _response(tool_calls=[finish]),
            _response("done"),
        ],
    )
    _, manager, service, run_dir, schemas, dispatch, _ = fixture
    schemas.append(FunctionSchema("side_effect", "side effect", {"type": "object"}))
    dispatch["side_effect"] = lambda args: calls.append(args) or {"ok": True}

    assert _run(fixture) == "done"
    assert calls == [{"value": "one"}]
    sent = [message for session in service.sessions for message in session.sent_messages]
    retry_messages = [
        message for message in sent
        if isinstance(message, str) and "Retrying." in message
    ]
    assert len(retry_messages) == 2
    assert "after tool results" in retry_messages[0]
    assert "on initial send" in retry_messages[1]
    retry_events = [
        event for event in _events(run_dir)
        if event["event"] == "daemon_aed_transient_retry"
    ]
    assert [event["error"] for event in retry_events] == [
        "LLM returned empty response (no text, no tool_calls, no thoughts) after tool results; ledger=daemon",
        "LLM returned empty response (no text, no tool_calls, no thoughts) on initial send; ledger=daemon",
    ]
    assert all(set(event) >= {"attempt", "backoff_s", "error"} for event in retry_events)


def test_buffered_followup_empty_recovery_is_a_fresh_request(tmp_path, monkeypatch):
    side_effect = ToolCall("side_effect", {"value": "one"}, "followup-side-1")
    finish = ToolCall("finish", {"status": "done"}, "followup-finish-1")
    fixture = _fixture(
        tmp_path,
        monkeypatch,
        [
            _response(tool_calls=[side_effect]),
            _response("initial"),
            _response(),  # buffered follow-up send
            _response(tool_calls=[finish]),
            _response("followed"),
        ],
    )
    _, manager, service, run_dir, schemas, dispatch, _ = fixture
    manager._emanations["em-parity"]["followup_buffer"] = "continue the task"
    schemas.append(FunctionSchema("side_effect", "side effect", {"type": "object"}))
    dispatch["side_effect"] = lambda _args: {"ok": True}

    assert _run(fixture, max_turns=3) == "followed"
    sent = [message for session in service.sessions for message in session.sent_messages]
    retry_messages = [
        message for message in sent
        if isinstance(message, str) and "Retrying." in message
    ]
    assert len(retry_messages) == 1
    assert "on initial send" in retry_messages[0]
    retry_events = [
        event for event in _events(run_dir)
        if event["event"] == "daemon_aed_transient_retry"
    ]
    assert retry_events[0]["error"].endswith("on initial send; ledger=daemon")


def test_compact_reset_empty_recovery_uses_fresh_send_location(tmp_path, monkeypatch):
    finish = ToolCall("finish", {"status": "done"}, "compact-finish-1")
    fixture = _fixture(
        tmp_path,
        monkeypatch,
        [
            _response(tool_calls=[finish]),
            _response(),  # mechanical compact continuation
            _response("after compact"),  # same-session transient retry
        ],
    )
    original_note_response = daemon_tool._DaemonMetaState.note_response

    def force_compact_due(self, response, session):
        original_note_response(self, response, session)
        if self.rounds == 1:
            self.compact_due = True

    monkeypatch.setattr(daemon_tool._DaemonMetaState, "note_response", force_compact_due)
    _, _, service, run_dir, _, _, _ = fixture

    assert _run(fixture, max_turns=2) == "after compact"
    assert len(service.sessions) == 2  # initial session + mechanical compact reset
    sent = [message for session in service.sessions for message in session.sent_messages]
    retry_messages = [
        message for message in sent
        if isinstance(message, str) and "Retrying." in message
    ]
    assert len(retry_messages) == 1
    assert "on initial send" in retry_messages[0]
    retry_events = [
        event for event in _events(run_dir)
        if event["event"] == "daemon_aed_transient_retry"
    ]
    assert retry_events[0]["error"].endswith("on initial send; ledger=daemon")


def test_terminal_counted_aed_does_not_compact_or_rebuild_again(tmp_path, monkeypatch):
    compact_sources = []

    def observe_compaction(*_args, **_kwargs):
        compact_sources.append(_kwargs.get("source"))
        return SimpleNamespace(
            scanned_blocks=0,
            compacted_blocks=0,
            original_chars_total=0,
            replacement_chars_total=0,
            artifact_paths=[],
        )

    monkeypatch.setattr(daemon_tool, "compact_oversized_history", observe_compaction)
    fixture = _fixture(
        tmp_path,
        monkeypatch,
        [_response()] * 4,  # kickoff + three same-session transient retries
        max_aed_attempts=1,
    )

    with pytest.raises(RuntimeError, match="empty-response recovery exhausted"):
        _run(fixture)
    _, _, _, run_dir, _, _, _ = fixture
    compact_events = [
        event for event in _events(run_dir)
        if event["event"] == "aed_history_compacted"
    ]
    assert [event["source"] for event in compact_events] == ["aed_transient"] * 3


def test_empty_recovery_mirrors_transient_then_counted_aed(tmp_path, monkeypatch):
    finish = ToolCall("finish", {"status": "done"}, "finish-1")
    fixture = _fixture(
        tmp_path,
        monkeypatch,
        [
            _response(),  # kickoff
            _response(),  # transient 1
            _response(),  # transient 2
            _response(),  # transient 3
            _response(),  # counted AED attempt 1, rebuild 1
            _response(tool_calls=[finish]),  # counted AED attempt 2, rebuild 2
            _response("recovered"),
        ],
    )

    assert _run(fixture) == "recovered"
    _, _, service, run_dir, _, _, completion_path = fixture
    assert json.loads(completion_path.read_text())["status"] == "done"
    assert len(service.sessions) == 3  # initial + two counted AED rebuilds
    sent = [message for session in service.sessions for message in session.sent_messages]
    assert len(sent) == 7  # kickoff + 3 transient + 2 counted + finish result
    assert all(isinstance(message, str) for message in sent[:6])
    assert isinstance(sent[6], list)
    assert all(message.startswith("[system]") for message in sent[1:6])
    assert all("LLM call failed" in message for message in sent[1:6])
    retries = [event for event in _events(run_dir) if event["event"] == "daemon_aed_transient_retry"]
    assert [event["backoff_s"] for event in retries] == [1, 2, 4]
    assert not any(event["event"] == "daemon_completion_recovery_decision" for event in _events(run_dir))
    assert [name for name, _, _ in service.tool_results].count("finish") == 1


def test_recovery_sends_do_not_consume_max_turns(tmp_path, monkeypatch):
    finish = ToolCall("finish", {"status": "done"}, "finish-headroom")
    fixture = _fixture(
        tmp_path,
        monkeypatch,
        [
            _response(),  # kickoff
            _response(),  # transient 1
            _response(),  # transient 2
            _response(),  # transient 3; counted AED attempt 1 heals this response
            _response(tool_calls=[finish]),  # counted AED rebuild send
            _response("done"),
        ],
        max_turns=1,
        max_aed_attempts=2,
    )

    assert _run(fixture, max_turns=1) == "done"
    _, _, service, _, _, _, _ = fixture
    assert len(service.sessions) == 2  # counted AED rebuild is not a normal turn


def test_counted_aed_exhaustion_maps_to_failed_receipt(tmp_path, monkeypatch):
    fixture = _fixture(
        tmp_path,
        monkeypatch,
        [_response()] * 5,
        max_aed_attempts=1,
    )

    with pytest.raises(RuntimeError, match="empty-response recovery exhausted"):
        _run(fixture)
    _, _, service, run_dir, _, _, _ = fixture
    state = json.loads(run_dir.daemon_json_path.read_text())
    assert state["state"] == "failed"
    assert state["error"]["message"] == "daemon empty-response recovery exhausted"
    assert len(service.sessions) == 1


def test_thoughts_only_keeps_completion_failure_without_empty_recovery(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch, [_response(thoughts=["thinking"])])

    with pytest.raises(RuntimeError, match="completion MCP contract"):
        _run(fixture)
    _, _, service, run_dir, _, _, _ = fixture
    assert len(service.sessions[0].sent_messages) == 1
    assert not any(event["event"] == "daemon_aed_transient_retry" for event in _events(run_dir))


def test_empty_recovery_preserves_tool_side_effect_and_real_result(tmp_path, monkeypatch):
    calls = []
    tool = ToolCall("side_effect", {"value": "one"}, "side-1")
    finish = ToolCall("finish", {"status": "done"}, "finish-2")
    fixture = _fixture(
        tmp_path,
        monkeypatch,
        [
            _response(tool_calls=[tool]),
            _response(),
            _response(tool_calls=[finish]),
            _response("done"),
        ],
    )
    _, manager, service, run_dir, schemas, dispatch, _ = fixture
    schemas.append(FunctionSchema("side_effect", "side effect", {"type": "object"}))
    dispatch["side_effect"] = lambda args: calls.append(args) or {"ok": True}

    assert _run(fixture) == "done"
    assert calls == [{"value": "one"}]
    assert [name for name, _, _ in service.tool_results].count("side_effect") == 1
    assert [name for name, _, _ in service.tool_results].count("finish") == 1
    history = [json.loads(line) for line in run_dir.chat_path.read_text().splitlines()]
    assert any(entry["role"] == "assistant" and entry["text"] == "" for entry in history)
    tool_result_entries = [entry for entry in history if entry.get("kind") == "tool_results"]
    assert any("side_effect" in entry["text"] for entry in tool_result_entries)


def test_cancel_during_empty_recovery_backoff_does_not_send_recovery(tmp_path, monkeypatch):
    cancel = threading.Event()
    fixture = _fixture(tmp_path, monkeypatch, [_response()])

    def abort(*_args):
        cancel.set()
        return False

    monkeypatch.setattr(daemon_tool, "_wait_recovery_backoff", abort)
    assert _run(fixture, cancel_event=cancel) == "[cancelled]"
    _, _, service, run_dir, _, _, _ = fixture
    assert len(service.sessions[0].sent_messages) == 1
    assert len([event for event in _events(run_dir) if event["event"] == "daemon_aed_transient_retry"]) == 1


def test_timeout_during_empty_recovery_marks_timeout_without_send(tmp_path, monkeypatch):
    timeout_event = threading.Event()
    fixture = _fixture(tmp_path, monkeypatch, [_response()])

    def abort(*_args):
        timeout_event.set()
        return False

    monkeypatch.setattr(daemon_tool, "_wait_recovery_backoff", abort)
    assert _run(fixture, timeout_event=timeout_event) == "[cancelled]"
    _, _, service, run_dir, _, _, _ = fixture
    assert len(service.sessions[0].sent_messages) == 1
    assert json.loads(run_dir.daemon_json_path.read_text())["state"] == "timeout"


def test_no_old_finish_specific_recovery_surface():
    assert not hasattr(daemon_tool, "DAEMON_COMPLETION_RECOVERY_PROMPT")
