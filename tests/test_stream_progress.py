"""Contract tests for the Core-owned stream-progress Port.

Covers the Port shape and Core technology-neutrality, the shared discovery
known vectors (pinned identically in the Go client), the memory-only
generation-bound state lifecycle (an old generation's late deltas/end never
touch a newer active snapshot), `SessionManager` bracketing (begin-before-wait,
per-delta counts bound to the generation `begin` returned, `finally`-clear of
that same generation on success and failure, fail-open, explicit
`streaming=False`, unchanged no-Port call shape), the System-runtime-policy sources,
`BaseAgent` factory injection (never called for an explicit `streaming=False`),
and the loopback read-only endpoint.
"""
from __future__ import annotations

import ast
import inspect
import json
import os
import socket
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lingtai.adapters.stream_progress import (
    LoopbackStreamProgressPublisher,
    loopback_stream_progress_factory,
)
from lingtai.kernel.base_agent import BaseAgent
from lingtai.kernel.config import AgentConfig
from lingtai.kernel.config_resolve import parse_jsonc
from lingtai.kernel.session import SessionManager
from lingtai.kernel.stream_progress import (
    STREAM_PROGRESS_PATH,
    STREAM_PROGRESS_SCHEMA,
    StreamProgressPort,
    StreamProgressSnapshot,
    StreamProgressState,
    candidate_ports,
    discovery_seed,
)
from lingtai.tools.registry import INTRINSICS as _TEST_INTRINSICS

from tests._agent_presence_helpers import make_test_presence_store
from tests._lifecycle_clock_helpers import make_test_lifecycle_clock
from tests._notification_store_helpers import notification_store_for
from tests._service_helpers import make_tool_result_mock_service as make_mock_service
from tests._snapshot_helpers import make_test_snapshot_port, make_test_source_revision_port
from tests._workdir_lease_helpers import make_test_lease

ROOT = Path(__file__).resolve().parents[1]

# Pinned byte-for-byte with tui/internal/streamprogress/client_test.go.
KNOWN_VECTORS: dict[str, tuple[int, list[int]]] = {
    "20260826-120000-abcd": (58026, [59026, 46945, 54864, 42783, 50702, 58621, 46540, 54459]),
    "orch": (4407, [45407, 53326, 41245, 49164, 57083, 45002, 52921, 60840]),
    "": (29159, [50159, 58078, 45997, 53916, 41835, 49754, 57673, 45592]),
    "器灵-01": (38923, [59923, 47842, 55761, 43680, 51599, 59518, 47437, 55356]),
}

SNAPSHOT_FIELDS = {
    "schema", "agent_id", "generation", "active", "streamed_chars", "updated_unix_ms", "pid",
}


# ---------------------------------------------------------------------------
# Port shape / Core neutrality / discovery
# ---------------------------------------------------------------------------

def test_port_is_three_operations_and_abstract() -> None:
    assert StreamProgressPort.__abstractmethods__ == frozenset({"begin", "add_chars", "end"})
    with pytest.raises(TypeError):
        StreamProgressPort()  # type: ignore[abstract]


def test_core_module_imports_no_transport_or_filesystem_modules() -> None:
    source = (ROOT / "src/lingtai/kernel/stream_progress/__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_roots: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])
    assert imported_roots.isdisjoint({"http", "json", "os", "pathlib", "socket"})


@pytest.mark.parametrize("agent_id", sorted(KNOWN_VECTORS))
def test_candidate_ports_known_vectors(agent_id: str) -> None:
    seed, ports = KNOWN_VECTORS[agent_id]
    assert discovery_seed(agent_id) == seed
    assert candidate_ports(agent_id) == ports


def test_candidate_ports_are_eight_in_documented_range() -> None:
    ports = candidate_ports("any-agent")
    assert len(ports) == 8
    assert all(41000 <= p < 61000 for p in ports)


def test_schema_and_path_constants() -> None:
    assert STREAM_PROGRESS_SCHEMA == "lingtai.stream-progress/v1"
    assert STREAM_PROGRESS_PATH == "/v1/stream-progress"


# ---------------------------------------------------------------------------
# Memory-only state
# ---------------------------------------------------------------------------

def _clock(values):
    it = iter(values)
    return lambda: next(it)


def test_state_lifecycle_begin_delta_end() -> None:
    state = StreamProgressState("a1", pid=4242, now_ms=_clock([1, 2, 3, 4, 5, 6]))
    s0 = state.snapshot()
    assert (s0.generation, s0.active, s0.streamed_chars, s0.updated_unix_ms, s0.pid) == (0, False, 0, 1, 4242)

    gen = state.begin()
    assert gen == 1
    s1 = state.snapshot()
    assert (s1.generation, s1.active, s1.streamed_chars, s1.updated_unix_ms) == (1, True, 0, 2)

    state.add_chars(gen, 5)
    state.add_chars(gen, 0)
    state.add_chars(gen, 7)
    s2 = state.snapshot()
    assert (s2.generation, s2.active, s2.streamed_chars, s2.updated_unix_ms) == (1, True, 12, 4)

    state.end(gen)
    s3 = state.snapshot()
    assert (s3.generation, s3.active, s3.streamed_chars, s3.updated_unix_ms) == (1, False, 0, 5)

    assert state.begin() == 2
    assert state.snapshot().generation == 2


def test_state_ignores_deltas_outside_an_active_response() -> None:
    state = StreamProgressState("a1", pid=1)
    state.add_chars(0, 9)
    state.add_chars(1, 9)
    assert state.snapshot().streamed_chars == 0
    gen = state.begin()
    state.add_chars(gen, 3)
    state.end(gen)
    state.add_chars(gen, 11)  # late delta from an abandoned worker
    state.end(gen)  # and a repeated end: idempotent, still cleared
    snap = state.snapshot()
    assert (snap.generation, snap.active, snap.streamed_chars) == (1, False, 0)


def test_state_old_generation_after_new_begin_never_alters_newer_snapshot() -> None:
    # Regression: a timed-out provider worker (generation 1) is abandoned but
    # keeps emitting after the session has begun generation 2. Its late deltas
    # and its late ``end`` must be ignored — the newer active snapshot keeps
    # exactly the characters generation 2 published and stays active.
    state = StreamProgressState("a1", pid=1, now_ms=_clock(range(1, 100)))
    old = state.begin()
    state.add_chars(old, 4)
    new = state.begin()  # old worker timed out; a new response begins
    assert (old, new) == (1, 2)
    fresh = state.snapshot()
    assert (fresh.generation, fresh.active, fresh.streamed_chars) == (2, True, 0)

    state.add_chars(old, 100)  # late old delta
    state.add_chars(new, 6)
    state.end(old)  # late old end
    state.add_chars(old, 100)
    snap = state.snapshot()
    assert (snap.generation, snap.active, snap.streamed_chars) == (2, True, 6)
    assert snap.updated_unix_ms == state.snapshot().updated_unix_ms  # ignored ops did not touch the clock

    # A future/unknown generation is ignored just like a stale one.
    state.add_chars(new + 1, 50)
    state.end(new + 1)
    assert (state.snapshot().active, state.snapshot().streamed_chars) == (True, 6)

    state.end(new)
    done = state.snapshot()
    assert (done.generation, done.active, done.streamed_chars) == (2, False, 0)


def test_snapshot_dict_has_exactly_documented_fields_and_no_text() -> None:
    snap = StreamProgressSnapshot(
        agent_id="a", generation=3, active=True, streamed_chars=40, updated_unix_ms=7, pid=9
    )
    body = snap.to_dict()
    assert set(body) == SNAPSHOT_FIELDS
    assert body["schema"] == STREAM_PROGRESS_SCHEMA
    assert all(isinstance(body[k], int) and not isinstance(body[k], bool)
               for k in ("generation", "streamed_chars", "updated_unix_ms", "pid"))
    assert body["active"] is True
    assert "text" not in json.dumps(body)


# ---------------------------------------------------------------------------
# SessionManager bracketing
# ---------------------------------------------------------------------------

class _RecorderPort(StreamProgressPort):
    """Records the exact operation sequence; optionally raises on chosen ops.

    ``begin`` hands out generations 1, 2, ... exactly like the real state so
    the recorded ``add``/``end`` entries carry the token they were bound to.
    """

    def __init__(self, *, raise_on: frozenset[str] = frozenset()) -> None:
        self.calls: list[tuple] = []
        self.raise_on = raise_on
        self.generation = 0

    def _record(self, *entry) -> None:
        self.calls.append(entry)
        if entry[0] in self.raise_on:
            raise RuntimeError("publisher exploded")

    def begin(self) -> int:
        self.generation += 1
        self._record("begin")
        return self.generation

    def add_chars(self, generation: int, count: int) -> None:
        self._record("add", generation, count)

    def end(self, generation: int) -> None:
        self._record("end", generation)


class _ProbingState(StreamProgressState):
    """Real state that also captures a snapshot after every delta."""

    def __init__(self) -> None:
        super().__init__("probe", pid=1)
        self.after_delta: list[StreamProgressSnapshot] = []

    def add_chars(self, generation: int, count: int) -> None:
        super().add_chars(generation, count)
        self.after_delta.append(self.snapshot())


def _make_session(port, *, streaming: bool = True, deltas=(), fail: Exception | None = None,
                  probe=None):
    svc = MagicMock()
    svc.model = "test-model"
    chat = MagicMock()
    chat.context_window.return_value = 100000
    chat.interface.estimate_context_tokens.return_value = 5000
    chat.interface.current_system_prompt = "test prompt"
    response = MagicMock(
        text="".join(deltas), tool_calls=[], thoughts=[],
        usage=MagicMock(input_tokens=100, output_tokens=50, thinking_tokens=10,
                        cached_tokens=20, extra={}),
    )
    calls: list[dict] = []

    def send_stream(message, on_chunk=None):
        calls.append({"on_chunk": on_chunk is not None, "probe": probe() if probe else None,
                      "chunk_fn": on_chunk})
        for delta in deltas:
            if on_chunk is not None:
                on_chunk(delta)
        if fail is not None:
            raise fail
        return response

    chat.send_stream = send_stream
    chat.send.return_value = response
    svc.create_session.return_value = chat
    sm = SessionManager(
        llm_service=svc,
        config=AgentConfig(),
        agent_name="test",
        streaming=streaming,
        build_system_prompt_fn=lambda: "test prompt",
        build_tool_schemas_fn=lambda: [],
        logger_fn=None,
        stream_progress=port,
    )
    return sm, chat, calls, response


def test_session_begins_before_the_provider_wait() -> None:
    state = StreamProgressState("s", pid=1)
    sm, _, calls, _ = _make_session(state, deltas=("hi",), probe=state.snapshot)
    sm.send("hello")
    seen = calls[0]["probe"]
    assert calls[0]["on_chunk"] is True
    assert (seen.generation, seen.active, seen.streamed_chars) == (1, True, 0)


def test_session_publishes_len_delta_unicode_characters_bound_to_generation() -> None:
    recorder = _RecorderPort()
    deltas = ("héllo", "", " wörld", "🙂", "器灵")
    sm, _, _, _ = _make_session(recorder, deltas=deltas)
    sm.send("hello")
    assert recorder.calls == [
        ("begin",), ("add", 1, 5), ("add", 1, 0), ("add", 1, 6), ("add", 1, 1), ("add", 1, 2), ("end", 1),
    ]
    # The second response carries the generation ``begin`` returned for it.
    sm.send("again")
    assert recorder.calls[7:] == [
        ("begin",), ("add", 2, 5), ("add", 2, 0), ("add", 2, 6), ("add", 2, 1), ("add", 2, 2), ("end", 2),
    ]

    probing = _ProbingState()
    sm, _, _, _ = _make_session(probing, deltas=deltas)
    sm.send("hello")
    assert [s.streamed_chars for s in probing.after_delta] == [5, 5, 11, 12, 14]
    assert all(s.active and s.generation == 1 for s in probing.after_delta)


def test_session_clears_in_finally_on_success_and_preserves_response_semantics() -> None:
    state = StreamProgressState("s", pid=1)
    sm, _, _, response = _make_session(state, deltas=("abc", "def"))
    out = sm.send("hello")
    assert out is response
    snap = state.snapshot()
    assert (snap.generation, snap.active, snap.streamed_chars) == (1, False, 0)
    assert sm._text_already_streamed is True
    assert sm._intermediate_text_streamed is False


def test_session_clears_in_finally_on_failure() -> None:
    state = StreamProgressState("s", pid=1)
    recorder = _RecorderPort()
    sm, _, _, _ = _make_session(state, deltas=("abc",), fail=RuntimeError("provider down"))
    with pytest.raises(RuntimeError, match="provider down"):
        sm.send("hello")
    snap = state.snapshot()
    assert (snap.generation, snap.active, snap.streamed_chars) == (1, False, 0)

    sm, _, _, _ = _make_session(recorder, deltas=("abc",), fail=RuntimeError("provider down"))
    with pytest.raises(RuntimeError):
        sm.send("hello")
    assert recorder.calls == [("begin",), ("add", 1, 3), ("end", 1)]


def test_session_abandoned_old_worker_cannot_contaminate_newer_generation() -> None:
    # Regression: the first provider call times out (raises) but its worker
    # thread is still alive and keeps invoking the on_chunk closure it was
    # given. Once the session has begun the next response, those late calls —
    # and the old ``end`` — must not alter the new generation's snapshot.
    state = StreamProgressState("s", pid=1)
    sm, _, calls, _ = _make_session(state, deltas=("ab",), fail=TimeoutError("provider timeout"))
    with pytest.raises(TimeoutError):
        sm.send("first")
    old_chunk = calls[0]["chunk_fn"]
    assert (state.snapshot().generation, state.snapshot().active) == (1, False)

    # Late delta after the old response was cleared: still cleared.
    old_chunk("late-after-end")
    assert (state.snapshot().active, state.snapshot().streamed_chars) == (False, 0)

    # A new response begins on the same session while the old worker lives on.
    seen: list[StreamProgressSnapshot] = []

    def send_stream(message, on_chunk=None):
        on_chunk("x" * 6)
        old_chunk("ZZZZZZZZZZ")  # abandoned generation-1 worker emits mid-stream
        seen.append(state.snapshot())
        state.end(1)  # and its late ``end`` lands
        seen.append(state.snapshot())
        on_chunk("yy")
        return MagicMock(text="xxxxxxyy", tool_calls=[], thoughts=[],
                         usage=MagicMock(input_tokens=1, output_tokens=1, thinking_tokens=0,
                                         cached_tokens=0, extra={}))

    sm._chat.send_stream = send_stream
    sm.send("second")
    assert [(s.generation, s.active, s.streamed_chars) for s in seen] == [(2, True, 6), (2, True, 6)]
    final = state.snapshot()
    assert (final.generation, final.active, final.streamed_chars) == (2, False, 0)


def test_session_is_fail_open_when_the_port_raises(caplog) -> None:
    # add/end raise: every op is still attempted, the response is returned,
    # and the session warns exactly once.
    recorder = _RecorderPort(raise_on=frozenset({"add", "end"}))
    sm, _, _, response = _make_session(recorder, deltas=("abc", "de"))
    with caplog.at_level("WARNING"):
        out = sm.send("hello")
    assert out is response
    assert recorder.calls == [("begin",), ("add", 1, 3), ("add", 1, 2), ("end", 1)]
    assert sum("stream_progress_publish_failed" in r.getMessage() for r in caplog.records) == 1

    # begin raises: no generation exists, so nothing further is published for
    # that call (no unbound add/end), the provider is still called with no
    # on_chunk, and the response is returned.
    caplog.clear()
    recorder = _RecorderPort(raise_on=frozenset({"begin"}))
    sm, _, calls, response = _make_session(recorder, deltas=("abc",))
    with caplog.at_level("WARNING"):
        assert sm.send("hello") is response
    assert recorder.calls == [("begin",)]
    assert calls[0]["on_chunk"] is False
    assert sum("stream_progress_publish_failed" in r.getMessage() for r in caplog.records) == 1


def test_session_treats_non_int_generation_from_begin_as_publish_failure(caplog) -> None:
    class _LegacyPort(_RecorderPort):
        def begin(self):  # type: ignore[override]
            self._record("begin")
            return None

    port = _LegacyPort()
    sm, _, calls, response = _make_session(port, deltas=("abc",))
    with caplog.at_level("WARNING"):
        assert sm.send("hello") is response
    assert port.calls == [("begin",)]
    assert calls[0]["on_chunk"] is False
    assert any("stream_progress_publish_failed" in r.getMessage() for r in caplog.records)


def test_session_explicit_streaming_false_uses_send_and_never_touches_port() -> None:
    recorder = _RecorderPort()
    sm, chat, calls, response = _make_session(recorder, streaming=False, deltas=("abc",))
    assert sm.streaming is False
    assert sm.send("hello") is response
    chat.send.assert_called_once()
    assert calls == []
    assert recorder.calls == []


def test_session_without_port_keeps_pre_existing_call_shape() -> None:
    sm, _, calls, _ = _make_session(None, deltas=("abc",))
    assert sm.stream_progress is None
    sm.send("hello")
    assert calls == [{"on_chunk": False, "probe": None, "chunk_fn": None}]


# ---------------------------------------------------------------------------
# Default-on sources and explicit opt-out
# ---------------------------------------------------------------------------

def _make_agent(tmp_path, **kwargs):
    workdir = tmp_path / "sp_agent"
    return BaseAgent(
        intrinsics=_TEST_INTRINSICS,
        service=make_mock_service(),
        working_dir=workdir,
        workdir_lease=make_test_lease(),
        agent_presence=make_test_presence_store(),
        lifecycle_clock=make_test_lifecycle_clock(),
        snapshot_port=make_test_snapshot_port(),
        source_revision_port=make_test_source_revision_port(),
        notification_store=notification_store_for(workdir),
        **kwargs,
    )


def test_baseagent_streaming_defaults_on_and_explicit_false_stays_false(tmp_path) -> None:
    params = inspect.signature(BaseAgent.__init__).parameters
    assert params["streaming"].default is True
    assert params["stream_progress_factory"].default is None
    assert _make_agent(tmp_path)._session.streaming is True
    assert _make_agent(tmp_path / "off", streaming=False)._session.streaming is False


def test_agent_wrapper_passes_streaming_default_through(tmp_path) -> None:
    from lingtai import Agent

    captured: dict = {}

    class _Captured(Exception):
        pass

    def fake_init(self, *args, **kwargs):
        captured.update(kwargs)
        raise _Captured

    with patch.object(BaseAgent, "__init__", fake_init):
        with pytest.raises(_Captured):
            Agent(make_mock_service(), working_dir=tmp_path / "sp-wrapper")
    assert "streaming" not in captured  # BaseAgent's default (True) applies
    assert "stream_progress_factory" not in captured  # wrapper composes no endpoint


def _write_init(tmp_path: Path, manifest_overrides: dict | None = None) -> dict:
    manifest = {
        "agent_name": "test-agent",
        "language": "en",
        "llm": {"provider": "anthropic", "model": "test-model", "api_key": "test-key", "base_url": None},
        "capabilities": {},
        "soul": {"delay": 30},
        "stamina": 60,
        "context_limit": None,
        "max_turns": 10,
        "admin": {"karma": True},
    }
    manifest.update(manifest_overrides or {})
    data = {"manifest": manifest, "principle": "", "covenant": "Be helpful.", "pad": "", "lingtai": ""}
    (tmp_path / "init.json").write_text(json.dumps(data), encoding="utf-8")
    from lingtai.cli import load_init

    return load_init(tmp_path)


@patch("lingtai.cli.LLMService")
@patch("lingtai.cli.Agent")
@patch("lingtai.cli.PosixFilesystemMailAdapter")
def test_cli_system_runtime_policy_controls_streaming_and_composes_loopback_factory(
    mock_mail, mock_agent, mock_llm, tmp_path, monkeypatch
) -> None:
    from lingtai.cli import build_agent
    from lingtai.tools.system.settings import STREAMING_ENV

    monkeypatch.setenv(STREAMING_ENV, "on")
    data = _write_init(tmp_path)
    assert "streaming" not in data["manifest"]
    build_agent(data, tmp_path)
    kwargs = mock_agent.call_args.kwargs
    assert kwargs["streaming"] is True
    assert kwargs["stream_progress_factory"] is loopback_stream_progress_factory


@patch("lingtai.cli.LLMService")
@patch("lingtai.cli.Agent")
@patch("lingtai.cli.PosixFilesystemMailAdapter")
def test_cli_legacy_manifest_streaming_is_ignored(mock_mail, mock_agent, mock_llm, tmp_path, monkeypatch) -> None:
    from lingtai.cli import build_agent
    from lingtai.tools.system.settings import STREAMING_ENV

    monkeypatch.delenv(STREAMING_ENV, raising=False)
    data = _write_init(tmp_path, {"streaming": True})
    build_agent(data, tmp_path)
    assert mock_agent.call_args.kwargs["streaming"] is False
    assert mock_agent.call_args.kwargs["stream_progress_factory"] is loopback_stream_progress_factory


def test_canonical_init_template_does_not_declare_system_owned_streaming() -> None:
    data = parse_jsonc((ROOT / "src/lingtai/init.jsonc").read_text(encoding="utf-8"))
    assert "streaming" not in data["manifest"]


# ---------------------------------------------------------------------------
# BaseAgent factory injection
# ---------------------------------------------------------------------------

def test_baseagent_calls_factory_once_with_stable_agent_id_and_binds_port(tmp_path) -> None:
    seen: list[str] = []
    port = _RecorderPort()

    def factory(agent_id: str):
        seen.append(agent_id)
        return port

    agent = _make_agent(tmp_path, stream_progress_factory=factory)
    assert seen == [agent.agent_id]
    assert agent.agent_id
    assert agent._stream_progress is port
    assert agent._session.stream_progress is port


def test_baseagent_without_factory_has_no_port(tmp_path) -> None:
    agent = _make_agent(tmp_path)
    assert agent._stream_progress is None
    assert agent._session.stream_progress is None


def test_explicit_streaming_false_never_calls_factory_and_uses_non_stream_send(tmp_path) -> None:
    # BaseAgent: an explicit opt-out composes no publisher at all — the
    # factory is never invoked, so no unused endpoint is ever bound.
    seen: list[str] = []

    def factory(agent_id: str):
        seen.append(agent_id)
        return _RecorderPort()

    agent = _make_agent(tmp_path, streaming=False, stream_progress_factory=factory)
    assert seen == []
    assert agent._stream_progress is None
    assert agent._session.streaming is False
    assert agent._session.stream_progress is None

    # lingtai.Agent wrapper: the explicit False and the factory both pass
    # through to BaseAgent untouched, where the same opt-out applies.
    from lingtai import Agent

    seen_wrapper: list[str] = []
    wrapped = Agent(
        make_mock_service(),
        working_dir=tmp_path / "wrapper-off",
        streaming=False,
        stream_progress_factory=lambda agent_id: seen_wrapper.append(agent_id) or _RecorderPort(),
    )
    assert seen_wrapper == []
    assert wrapped._stream_progress is None
    assert wrapped._session.streaming is False
    # (SessionManager's own non-stream ``send`` path with streaming=False is
    # pinned by test_session_explicit_streaming_false_uses_send_and_never_touches_port.)


def test_baseagent_factory_failure_is_fail_open(tmp_path) -> None:
    def factory(agent_id: str):
        raise OSError("no loopback today")

    agent = _make_agent(tmp_path, stream_progress_factory=factory)
    assert agent._stream_progress is None
    assert agent._session.streaming is True


# ---------------------------------------------------------------------------
# Loopback endpoint
# ---------------------------------------------------------------------------

AGENT_ID = "20260826-120000-abcd"


def _get(port: int, path: str = STREAM_PROGRESS_PATH):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2) as resp:
        return resp.status, dict(resp.headers), json.loads(resp.read().decode("utf-8"))


def _probe(agent_id: str, ports: list[int]) -> int | None:
    """The documented reader algorithm: first valid v1 body with matching identity."""
    for port in ports:
        try:
            status, _, body = _get(port)
        except Exception:
            continue
        if status == 200 and body.get("schema") == STREAM_PROGRESS_SCHEMA and body.get("agent_id") == agent_id:
            return port
    return None


@pytest.fixture
def publisher():
    pub = LoopbackStreamProgressPublisher(AGENT_ID)
    assert pub.start() is True
    try:
        yield pub
    finally:
        pub.close()


def test_endpoint_is_loopback_only_on_a_discovery_candidate_with_schema_identity_no_store(publisher) -> None:
    assert publisher.port in candidate_ports(AGENT_ID)
    assert publisher._server.server_address[0] == "127.0.0.1"
    status, headers, body = _get(publisher.port)
    assert status == 200
    assert headers["Cache-Control"] == "no-store"
    assert headers["Content-Type"].startswith("application/json")
    assert set(body) == SNAPSHOT_FIELDS
    assert body["schema"] == STREAM_PROGRESS_SCHEMA
    assert body["agent_id"] == AGENT_ID
    assert body["pid"] == os.getpid()
    assert body["active"] is False and body["streamed_chars"] == 0


def test_endpoint_reflects_live_transitions(publisher) -> None:
    gen = publisher.begin()
    assert gen == 1
    publisher.add_chars(gen, len("héllo wörld"))
    _, _, body = _get(publisher.port)
    assert (body["generation"], body["active"], body["streamed_chars"]) == (1, True, 11)
    publisher.add_chars(gen + 1, 99)  # wrong generation: ignored by the adapter too
    publisher.end(gen + 1)
    _, _, body = _get(publisher.port)
    assert (body["generation"], body["active"], body["streamed_chars"]) == (1, True, 11)
    publisher.end(gen)
    _, _, body = _get(publisher.port)
    assert (body["generation"], body["active"], body["streamed_chars"]) == (1, False, 0)


def test_endpoint_other_paths_404_and_non_get_405(publisher) -> None:
    with pytest.raises(urllib.error.HTTPError) as not_found:
        _get(publisher.port, "/v1/other")
    assert not_found.value.code == 404
    assert not_found.value.headers["Cache-Control"] == "no-store"

    req = urllib.request.Request(
        f"http://127.0.0.1:{publisher.port}{STREAM_PROGRESS_PATH}", data=b"{}", method="POST"
    )
    with pytest.raises(urllib.error.HTTPError) as not_allowed:
        urllib.request.urlopen(req, timeout=2)
    assert not_allowed.value.code == 405
    assert not_allowed.value.headers["Allow"] == "GET"


def test_second_publisher_binds_next_free_candidate_and_reader_rejects_foreign_identity(publisher) -> None:
    candidates = candidate_ports(AGENT_ID)
    # A foreign agent squatting on this agent's candidate list must be skipped
    # by the documented reader algorithm, and a second publisher for the same
    # id must move to the next free candidate rather than share a port.
    foreign = LoopbackStreamProgressPublisher("someone-else", candidates=candidates)
    same = LoopbackStreamProgressPublisher(AGENT_ID)
    try:
        assert foreign.start() is True
        assert same.start() is True
        ports = {publisher.port, foreign.port, same.port}
        assert len(ports) == 3
        assert ports <= set(candidates)
        assert candidates.index(foreign.port) > candidates.index(publisher.port)
        assert candidates.index(same.port) > candidates.index(foreign.port)
        assert _probe(AGENT_ID, candidates) == publisher.port
        assert _probe("someone-else", candidates) == foreign.port
        # Reattach after the first publisher goes away: the reader rescans and
        # lands on the next publisher for the same identity.
        publisher.close()
        assert _probe(AGENT_ID, candidates) == same.port
    finally:
        foreign.close()
        same.close()


def test_bind_failure_is_fail_open_and_factory_still_returns_a_port() -> None:
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    occupied = blocker.getsockname()[1]
    try:
        pub = LoopbackStreamProgressPublisher("blocked", candidates=[occupied])
        assert pub.start() is False
        assert pub.port is None
        gen = pub.begin()
        pub.add_chars(gen, 4)
        assert pub.state.snapshot().streamed_chars == 4
        pub.end(gen)
        pub.close()

        with patch("lingtai.adapters.stream_progress.candidate_ports", return_value=[occupied]):
            port = loopback_stream_progress_factory("blocked")
        assert isinstance(port, LoopbackStreamProgressPublisher)
        assert port.port is None
        port.end(port.begin())
    finally:
        blocker.close()


def test_factory_starts_a_publisher_on_a_candidate_and_close_is_idempotent() -> None:
    port = loopback_stream_progress_factory("factory-agent")
    try:
        assert isinstance(port, LoopbackStreamProgressPublisher)
        assert port.port in candidate_ports("factory-agent")
        assert _probe("factory-agent", candidate_ports("factory-agent")) == port.port
    finally:
        port.close()
        port.close()
    assert port.port is None
