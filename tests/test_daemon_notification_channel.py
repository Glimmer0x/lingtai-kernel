"""Daemon terminal notices route through the built-in `daemon` channel.

Controlling design (Jason, Telegram 12435/12439/12443/12449-12452): a batch of
emanations must be able to report terminal state without each arrival waking
the parent. `<agent>/notification.json` sets
`channels.daemon.alarm_threshold`; below it, daemon state stays readable
through notification snapshot/check but must not move the attention
fingerprint (no wake, no injection). The strict first `count > N` crossing
produces exactly one alarm edge, and clearing/dismissing the channel resets the
batch so a later crossing can alarm again. With no valid threshold configured,
every terminal notice wakes exactly as before — now carried by the daemon
channel rather than `system`.

Per-run `daemon.json` / result files remain the terminal source of truth;
the top-level `.notification/daemon.json` is only a report, and this channel is
the parent-facing wake surface.
"""
from __future__ import annotations

import json
import multiprocessing
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from lingtai.kernel.base_agent.messaging import _enqueue_system_notification

from lingtai.kernel.notifications import (
    DAEMON_CHANNEL,
    apply_daemon_attention_mask,
    daemon_alarm_threshold,
    daemon_batch_state,
    is_channel_allowed,
    next_daemon_batch_state,
)

from tests._daemon_helpers import make_daemon_agent
from tests._notification_store_helpers import publish_test_payload, snapshot_notifications


def _write_threshold(agent, threshold) -> None:
    """Write `<workdir>/notification.json` with a daemon alarm threshold."""
    path = agent._working_dir / "notification.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"channels": {DAEMON_CHANNEL: {"alarm_threshold": threshold}}}),
        encoding="utf-8",
    )


def _publish(agent, ref_id: str) -> str:
    """Append one terminal daemon notice the way the manager publisher does."""
    return agent._enqueue_system_notification(
        source="daemon",
        ref_id=ref_id,
        body=f"Daemon {ref_id} done.",
        idempotency_key=f"daemon-terminal:{ref_id}",
        skip_if_idempotency_key_exists=True,
        extra={"kind": "daemon_terminal", "status": "done"},
        channel=DAEMON_CHANNEL,
    )


class _ProcessDaemonAgent:
    def __init__(self, workdir: str):
        from lingtai.adapters.posix.notification_store import PosixNotificationStoreAdapter

        self._working_dir = Path(workdir)
        self._notification_store = PosixNotificationStoreAdapter(self._working_dir)

    def _log(self, *_args, **_kwargs):
        return None

    def _wake_nap(self, *_args, **_kwargs):
        return None


def _publish_from_process(workdir: str, ref_id: str, barrier) -> None:
    agent = _ProcessDaemonAgent(workdir)
    barrier.wait(timeout=30)
    _enqueue_system_notification(
        agent,
        source="daemon",
        ref_id=ref_id,
        body=f"Daemon {ref_id} checkpoint.",
        idempotency_key=f"daemon-process:{ref_id}",
        skip_if_idempotency_key_exists=True,
        channel=DAEMON_CHANNEL,
    )


def _attention_fp(agent) -> tuple:
    from lingtai.kernel.notifications import agent_attention_fingerprint

    return agent_attention_fingerprint(agent)


# ---------------------------------------------------------------------------
# 1. The channel exists as a built-in surface
# ---------------------------------------------------------------------------


def test_daemon_is_a_builtin_allowlisted_channel():
    """`daemon` is allowlisted without any hook registration or workdir."""
    assert is_channel_allowed(DAEMON_CHANNEL) is True


def test_terminal_notice_lands_on_the_daemon_channel_not_system(tmp_path):
    agent = make_daemon_agent(tmp_path)
    _publish(agent, "em-1")

    snapshot = snapshot_notifications(agent._working_dir)
    assert "system" not in snapshot
    events = snapshot[DAEMON_CHANNEL]["data"]["events"]
    assert [e["ref_id"] for e in events] == ["em-1"]
    assert events[0]["source"] == "daemon"
    assert events[0]["kind"] == "daemon_terminal"
    assert events[0]["status"] == "done"


def test_root_report_is_not_a_daemon_event_source(tmp_path):
    agent = make_daemon_agent(tmp_path)
    root_path = agent._working_dir / ".notification" / "daemon.json"
    root_path.parent.mkdir(parents=True, exist_ok=True)
    legacy = {
        "header": "1 daemon notification",
        "icon": "🔔",
        "data": {"events": [{"event_id": "legacy-event", "ref_id": "legacy-run"}]},
    }
    root_path.write_text(json.dumps(legacy), encoding="utf-8")

    _publish(agent, "new-run")

    snapshot = snapshot_notifications(agent._working_dir)[DAEMON_CHANNEL]
    assert [event["ref_id"] for event in snapshot["data"]["events"]] == ["new-run"]
    # The compatibility report is non-authoritative and deliberately not
    # rebuilt on the per-run append hot path. A pre-existing legacy report is
    # ignored for delivery rather than rewritten by a reader or every writer.
    assert json.loads(root_path.read_text(encoding="utf-8")) == legacy
    assert (agent._working_dir / ".notification" / "daemon" / "new-run.json").is_file()


def test_root_report_cannot_reinject_legacy_events_after_mini_dismissal(tmp_path):
    from lingtai.kernel.meta_block import _commit_notification_fp
    from lingtai.kernel.notifications import dismiss_channel

    agent = make_daemon_agent(tmp_path)
    root_path = agent._working_dir / ".notification" / "daemon.json"
    root_path.parent.mkdir(parents=True, exist_ok=True)
    root_path.write_text(
        json.dumps({"data": {"events": [{"ref_id": "legacy-run"}]} }),
        encoding="utf-8",
    )
    _publish(agent, "new-run")
    _commit_notification_fp(agent)

    result = dismiss_channel(
        agent, DAEMON_CHANNEL, invoked_by="notification", ref_id="new-run"
    )

    assert result["status"] == "ok" and result["removed"] == 1
    assert DAEMON_CHANNEL not in snapshot_notifications(agent._working_dir)
    # A stale legacy report cannot reinject events and is not rewritten by the
    # aggregate dismiss path merely to make its statistics look current.
    assert json.loads(root_path.read_text(encoding="utf-8"))["data"]["events"][0]["ref_id"] == "legacy-run"


def test_daemon_publish_without_id_never_falls_back_to_root_report(tmp_path):
    from lingtai.adapters.posix.notification_store import PosixNotificationStoreAdapter

    store = PosixNotificationStoreAdapter(tmp_path)
    with pytest.raises(ValueError, match="daemon_id"):
        store.publish(
            DAEMON_CHANNEL,
            {"data": {"events": [{"ref_id": "unmarked"}]}},
        )
    assert not (tmp_path / ".notification" / "daemon.json").exists()
    assert store.fingerprint(lambda channel: channel == DAEMON_CHANNEL) == ()


def test_same_run_retains_more_than_twenty_events_without_fixed_cap(tmp_path):
    agent = make_daemon_agent(tmp_path)
    for index in range(25):
        agent._enqueue_system_notification(
            source="daemon",
            ref_id="long-run",
            body=f"checkpoint-{index}",
            idempotency_key=f"daemon-checkpoint:long-run:{index}",
            skip_if_idempotency_key_exists=True,
            channel=DAEMON_CHANNEL,
        )

    mini = agent._working_dir / ".notification" / "daemon" / "long-run.json"
    payload = json.loads(mini.read_text(encoding="utf-8"))
    assert len(payload["data"]["events"]) == 25
    assert len(snapshot_notifications(agent._working_dir)[DAEMON_CHANNEL]["data"]["events"]) == 25


def test_independent_processes_append_separate_run_mini_channels(tmp_path):
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    processes = [
        context.Process(
            target=_publish_from_process,
            args=(str(tmp_path), ref_id, barrier),
        )
        for ref_id in ("process-a", "process-b")
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=30)
        assert process.exitcode == 0

    mini_dir = tmp_path / ".notification" / "daemon"
    assert {path.name for path in mini_dir.glob("*.json")} == {
        "process-a.json", "process-b.json"
    }
    refs = {
        event["ref_id"]
        for event in snapshot_notifications(tmp_path)[DAEMON_CHANNEL]["data"]["events"]
    }
    assert refs == {"process-a", "process-b"}


def test_idempotency_key_still_suppresses_a_duplicate_republish(tmp_path):
    """Receipt/idempotency semantics are unchanged by the channel move."""
    agent = make_daemon_agent(tmp_path)
    assert _publish(agent, "em-1") != ""
    assert _publish(agent, "em-1") == ""

    events = snapshot_notifications(agent._working_dir)[DAEMON_CHANNEL]["data"]["events"]
    assert len(events) == 1


# ---------------------------------------------------------------------------
# 2. Default behaviour — no configured threshold means the usual wake
# ---------------------------------------------------------------------------


def test_absent_threshold_reads_as_unset(tmp_path):
    agent = make_daemon_agent(tmp_path)
    assert daemon_alarm_threshold(str(agent._working_dir)) is None


@pytest.mark.parametrize(
    "value",
    [
        "3",       # string, not an int
        True,      # bool is not an accepted int
        -1,        # negative
        None,      # explicit null
        {"n": 3},  # wrong shape
    ],
)
def test_invalid_threshold_reads_as_unset(tmp_path, value):
    """A malformed threshold must never silence wakes — it reads as absent."""
    agent = make_daemon_agent(tmp_path)
    _write_threshold(agent, value)
    assert daemon_alarm_threshold(str(agent._working_dir)) is None


def test_malformed_notification_json_reads_as_unset(tmp_path):
    agent = make_daemon_agent(tmp_path)
    path = agent._working_dir / "notification.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert daemon_alarm_threshold(str(agent._working_dir)) is None


def test_without_threshold_every_terminal_notice_moves_the_fingerprint(tmp_path):
    """Default per-terminal wake behaviour, now via the daemon channel."""
    agent = make_daemon_agent(tmp_path)

    seen = []
    for i in range(4):
        _publish(agent, f"em-{i}")
        seen.append(_attention_fp(agent))

    assert len(set(seen)) == 4, "each arrival must be a distinct wake edge"


# ---------------------------------------------------------------------------
# 3. Below / at threshold — readable, but silent
# ---------------------------------------------------------------------------


def test_below_and_at_threshold_is_readable_but_does_not_wake(tmp_path):
    agent = make_daemon_agent(tmp_path)
    _write_threshold(agent, 3)

    # The initial empty-channel baseline is also quiet: creating the first
    # below-threshold daemon.json must not wake merely because the tuple gained
    # an entry.
    quiet_fp = _attention_fp(agent)
    _publish(agent, "em-0")
    assert _attention_fp(agent) == quiet_fp

    # Fill the batch exactly up to the threshold (count == 3, not > 3).
    _publish(agent, "em-1")
    assert _attention_fp(agent) == quiet_fp
    _publish(agent, "em-2")
    assert _attention_fp(agent) == quiet_fp

    payload = snapshot_notifications(agent._working_dir)[DAEMON_CHANNEL]
    count, alarm_fired = daemon_batch_state(payload)
    assert (count, alarm_fired) == (3, False)

    # Silence is only about attention: the events remain fully readable.
    events = payload["data"]["events"]
    assert [e["ref_id"] for e in events] == ["em-0", "em-1", "em-2"]


# ---------------------------------------------------------------------------
# 4. The strict count > N crossing alarms exactly once
# ---------------------------------------------------------------------------


def test_strict_crossing_produces_exactly_one_alarm_edge(tmp_path):
    agent = make_daemon_agent(tmp_path)
    _write_threshold(agent, 3)

    for ref in ("em-0", "em-1", "em-2"):
        _publish(agent, ref)
    quiet_fp = _attention_fp(agent)

    # count 3 -> 4 is the strict crossing: one edge.
    _publish(agent, "em-3")
    alarm_fp = _attention_fp(agent)
    assert alarm_fp != quiet_fp

    payload = snapshot_notifications(agent._working_dir)[DAEMON_CHANNEL]
    assert daemon_batch_state(payload) == (4, True)

    # Every further arrival stays on the alarmed side — no second edge.
    for ref in ("em-4", "em-5", "em-6"):
        _publish(agent, ref)
        assert _attention_fp(agent) == alarm_fp


def test_threshold_zero_alarms_on_the_first_notice(tmp_path):
    """`alarm_threshold: 0` means "count > 0" — the first notice alarms."""
    agent = make_daemon_agent(tmp_path)
    _write_threshold(agent, 0)

    _publish(agent, "em-0")
    payload = snapshot_notifications(agent._working_dir)[DAEMON_CHANNEL]
    assert daemon_batch_state(payload) == (1, True)


# ---------------------------------------------------------------------------
# 5. Clear / dismiss resets the batch
# ---------------------------------------------------------------------------


def test_clear_resets_the_batch_and_a_later_crossing_alarms_again(tmp_path):
    from lingtai.kernel.notifications import dismiss_channel

    agent = make_daemon_agent(tmp_path)
    _write_threshold(agent, 2)

    for ref in ("em-0", "em-1", "em-2"):
        _publish(agent, ref)
    alarmed = snapshot_notifications(agent._working_dir)[DAEMON_CHANNEL]
    assert daemon_batch_state(alarmed) == (3, True)

    # The generic pre-existing stale-version rail applies to this channel like
    # any other: an agent that has not read the current state must force the
    # clear. Forcing here is the "agent dismissed a batch it has seen" path.
    result = dismiss_channel(
        agent, DAEMON_CHANNEL, invoked_by="notification", force=True
    )
    assert result["status"] == "ok"
    assert DAEMON_CHANNEL not in snapshot_notifications(agent._working_dir)

    # New batch: the odometer and the alarm latch both start over, so the
    # first arrivals are quiet again and a later crossing can alarm afresh.
    _publish(agent, "em-3")
    fresh = snapshot_notifications(agent._working_dir)[DAEMON_CHANNEL]
    assert daemon_batch_state(fresh) == (1, False)

    quiet_fp = _attention_fp(agent)
    _publish(agent, "em-4")
    assert _attention_fp(agent) == quiet_fp

    _publish(agent, "em-5")
    assert _attention_fp(agent) != quiet_fp
    assert daemon_batch_state(
        snapshot_notifications(agent._working_dir)[DAEMON_CHANNEL]
    ) == (3, True)


# ---------------------------------------------------------------------------
# 6. The detached/manager publisher agrees with the in-process one
# ---------------------------------------------------------------------------


def test_detached_supervisor_publishes_the_same_channel_and_batch_state(tmp_path):
    """The out-of-process publisher must be indistinguishable from the manager's.

    A detached supervisor has no live parent agent, so it writes the channel
    through the Store Port directly. It must still land on `daemon`, carry the
    same `data.daemon` batch state, and cross the alarm on the same strict
    `count > N` event — otherwise the parent's attention mask would behave
    differently depending on which process finished the run.
    """
    from types import SimpleNamespace

    from lingtai.adapters.posix.notification_store import (
        PosixNotificationStoreAdapter,
    )
    from lingtai.tools.daemon.supervisor_runtime import (
        _publish_daemon_notification,
    )

    workdir = tmp_path / "parent"
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "notification.json").write_text(
        json.dumps({"channels": {DAEMON_CHANNEL: {"alarm_threshold": 2}}}),
        encoding="utf-8",
    )
    run_dir = SimpleNamespace(handle="em-9", path=str(workdir / "run"))
    manifest = {"parent_working_dir": str(workdir)}
    store = PosixNotificationStoreAdapter(workdir)

    observed = []
    for i in range(4):
        assert _publish_daemon_notification(
            run_dir,
            manifest,
            status="done",
            state={"task": "t", "result_preview": "p"},
            idempotency_key=f"daemon-terminal:em-9-{i}",
        ) is True
        snapshot = store.snapshot(lambda ch: ch == DAEMON_CHANNEL)
        observed.append(daemon_batch_state(snapshot.get(DAEMON_CHANNEL)))

    assert observed == [(1, False), (2, False), (3, True), (4, True)]
    assert not (workdir / ".notification" / "system.json").exists()


# ---------------------------------------------------------------------------
# 7. Pure policy units
# ---------------------------------------------------------------------------


def test_next_batch_state_latches_the_alarm_across_further_events():
    state = next_daemon_batch_state({}, 1)
    assert state == {"count": 1, "alarm_fired": False}
    state = next_daemon_batch_state({"data": {DAEMON_CHANNEL: state}}, 1)
    assert state == {"count": 2, "alarm_fired": True}
    state = next_daemon_batch_state({"data": {DAEMON_CHANNEL: state}}, 1)
    assert state == {"count": 3, "alarm_fired": True}


def test_mask_is_a_no_op_without_a_threshold():
    fp = (("daemon.json", 12, "abc"), ("email.json", 7, "def"))
    assert apply_daemon_attention_mask(fp, {}, None) == fp


def test_mask_only_rewrites_the_daemon_entry():
    fp = (("daemon.json", 12, "abc"), ("email.json", 7, "def"))
    masked = apply_daemon_attention_mask(
        fp, {"data": {DAEMON_CHANNEL: {"count": 1, "alarm_fired": False}}}, 5
    )
    assert masked[1] == ("email.json", 7, "def")
    assert masked[0][0] == "daemon.json"
    assert masked[0][2] != "abc"


def test_unreadable_batch_state_fails_toward_waking():
    """Missing/garbled state must read as a fresh batch, never as 'alarmed'."""
    assert daemon_batch_state(None) == (0, False)
    assert daemon_batch_state({"data": {DAEMON_CHANNEL: "nope"}}) == (0, False)
    assert daemon_batch_state({"data": {DAEMON_CHANNEL: {"count": -4}}}) == (0, False)


# ---------------------------------------------------------------------------
# 8. B1 — non-forced dismiss must compare against the RAW delivered
#    fingerprint, never the masked attention token (Opus review on #1407).
# ---------------------------------------------------------------------------


def test_nonforced_dismiss_succeeds_after_a_real_delivery(tmp_path):
    """A normal read/deliver of a masked (sub-threshold) daemon channel must
    permit a non-forced clear.

    Regression: ``dismiss_channel``'s optimistic-concurrency ``delivered``
    token used to be sourced from ``agent._notification_fp`` — the
    daemon-attention-*masked* fingerprint. Under a configured threshold that
    masked entry is a constant ``("daemon.json", 0, "daemon:alarm=0")`` token
    that can never equal the Store's real ``(name, size, sha256)`` triple, so
    every non-forced dismiss refused as stale no matter how fresh the read.
    """
    from lingtai.kernel.meta_block import _commit_notification_fp
    from lingtai.kernel.notifications import dismiss_channel

    agent = make_daemon_agent(tmp_path)
    _write_threshold(agent, 3)
    _publish(agent, "em-0")

    # Production commit path: the same helper the ACTIVE notification-stamp
    # path uses to commit the agent's "I have read current state" fingerprint.
    _commit_notification_fp(agent)

    result = dismiss_channel(agent, DAEMON_CHANNEL, invoked_by="notification", force=False)

    assert result["status"] == "ok"
    assert result["cleared"] is True
    assert DAEMON_CHANNEL not in snapshot_notifications(agent._working_dir)


def test_nonforced_dismiss_still_refuses_a_true_stale_read(tmp_path):
    """A producer update landing after delivery must still refuse a
    non-forced dismiss — the masked-token fix must not turn off CAS
    protection entirely, only stop it from always tripping."""
    from lingtai.kernel.meta_block import _commit_notification_fp
    from lingtai.kernel.notifications import dismiss_channel

    agent = make_daemon_agent(tmp_path)
    _write_threshold(agent, 3)
    _publish(agent, "em-0")
    _commit_notification_fp(agent)

    # A real producer update lands after the agent's delivered read.
    _publish(agent, "em-1")

    result = dismiss_channel(agent, DAEMON_CHANNEL, invoked_by="notification", force=False)

    assert result["status"] == "error"
    assert result["reason"] == "stale_channel_version"
    # The channel must still be intact — refusal must not clear anything.
    assert DAEMON_CHANNEL in snapshot_notifications(agent._working_dir)


def test_delivered_version_describes_the_bytes_actually_delivered(tmp_path):
    """B1 TOCTOU: a publish landing between delivery and commit must not
    become the agent's delivered version.

    ``attach_active_notifications`` snapshots the payload for the model, and the
    fingerprint commit used to be a *separate, later* store read. A producer
    publishing ``P2`` in that window meant the model received ``P1`` while the
    committed raw version described ``P2`` — so a non-forced
    ``dismiss_channel`` would clear ``P2``, bytes the agent had never seen.
    Committing the version that came from the same coherent read as the
    delivered payload closes the window: the dismiss must now refuse as stale.
    """
    from lingtai.kernel import meta_block
    from lingtai.kernel.meta_block import _collect_active_notifications
    from lingtai.kernel.notifications import dismiss_channel

    agent = make_daemon_agent(tmp_path)
    _write_threshold(agent, 3)
    _publish(agent, "em-0")

    # Deliver P1, then let a producer publish P2 *before* the commit runs.
    payload, delivered = _collect_active_notifications(agent)
    assert payload is not None
    delivered_events = payload["notifications"][DAEMON_CHANNEL]["data"]["events"]
    assert [e["ref_id"] for e in delivered_events] == ["em-0"]

    _publish(agent, "em-1")  # P2 — never delivered to the model.

    meta_block._commit_notification_fp(agent, delivered)

    # The committed version must describe P1, so clearing now is refused: the
    # agent would otherwise silently destroy the undelivered em-1 event.
    result = dismiss_channel(
        agent, DAEMON_CHANNEL, invoked_by="notification", force=False
    )
    assert result["status"] == "error"
    assert result["reason"] == "stale_channel_version"
    events = snapshot_notifications(agent._working_dir)[DAEMON_CHANNEL]["data"]["events"]
    assert [e["ref_id"] for e in events] == ["em-0", "em-1"]


def test_alarm_crossing_survives_a_concurrent_clear_during_the_read(tmp_path):
    """An alarm edge must not be erased by a torn fingerprint/payload read.

    The fingerprint pass and the daemon-payload pass used to be independent
    store reads. If an alarmed write was observed by the first and a clear by
    the second, the alarmed entry was rewritten to the *quiet* token: it matched
    the prior quiet fingerprint, produced no wake, and the file was already
    gone, so nothing was left to replay the crossing. The coherent read
    verifies its bookend fingerprints, so an observation taken while the
    directory is being rewritten is reported unstable rather than being
    mistaken for confirmed quiet.
    """
    from lingtai.kernel.notifications import (
        DAEMON_CHANNEL as _DC,
        coherent_attention_read,
        is_channel_allowed,
    )
    from tests._notification_store_helpers import clear_test_payload

    agent = make_daemon_agent(tmp_path)
    _write_threshold(agent, 1)
    _publish(agent, "em-0")
    _publish(agent, "em-1")
    _publish(agent, "em-2")  # count=3 > 1 → alarmed on disk.

    store = agent._notification_store
    workdir = str(agent._working_dir)

    # Interleave a clear between the snapshot and the verifying fingerprint —
    # exactly the window that used to silently downgrade alarm=1 to alarm=0.
    real_snapshot = store.snapshot
    fired = {"n": 0}

    def _snapshot_then_clear(allow):
        out = real_snapshot(allow)
        if fired["n"] == 0:
            fired["n"] = 1
            clear_test_payload(agent._working_dir, _DC)
        return out

    store.snapshot = _snapshot_then_clear
    try:
        observed = coherent_attention_read(
            store, lambda ch: is_channel_allowed(ch, workdir=workdir), workdir
        )
    finally:
        store.snapshot = real_snapshot

    # The invariant: fingerprint and payload describe ONE instant. The masked
    # entry may say "a live daemon.json exists and is alarmed", or the virtual
    # "no daemon.json, quiet" token — never the torn hybrid the old code
    # produced, where a real alarmed file's hash was rewritten to alarm=0 using
    # a payload read after the clear. That hybrid claimed a live-but-quiet file
    # while nothing was left on disk to replay the crossing.
    entry = next(
        (e for e in observed.masked_fp if e[0] == f"{_DC}.json"), None
    )
    if entry is not None and entry[2] == "daemon:alarm=0":
        assert _DC not in observed.payloads, (
            "a quiet daemon token must correspond to a genuinely absent/quiet "
            "channel in the SAME observation, never to an alarmed file whose "
            "payload was re-read after a racing clear"
        )
    # And a raw entry for daemon.json implies the payload was captured with it.
    if any(e[0] == f"{_DC}.json" for e in observed.raw_fp):
        assert _DC in observed.payloads

    # Whatever was observed, the alarm state is never silently downgraded: an
    # alarmed payload in this observation must carry the alarmed token.
    if daemon_batch_state(observed.payloads.get(_DC))[1]:
        assert entry is not None and entry[2] == "daemon:alarm=1"


def test_forced_dismiss_is_unaffected_by_the_raw_fp_split(tmp_path):
    """force=true bypasses CAS entirely regardless of raw/masked fp state."""
    from lingtai.kernel.notifications import dismiss_channel

    agent = make_daemon_agent(tmp_path)
    _write_threshold(agent, 3)
    _publish(agent, "em-0")
    # Deliberately never commit any fingerprint (agent has not "read" state).

    result = dismiss_channel(agent, DAEMON_CHANNEL, invoked_by="notification", force=True)

    assert result["status"] == "ok"
    assert DAEMON_CHANNEL not in snapshot_notifications(agent._working_dir)


# ---------------------------------------------------------------------------
# 9. B2 — a quiet daemon clear must still be observed by sync so the stale
#    live holder is skeletonized, without waking the agent for the clear
#    itself (Opus review on #1407).
# ---------------------------------------------------------------------------


def _make_daemon_sync_agent(tmp_path):
    """A BaseAgent subclass with a real ``ChatInterface`` so ``_sync_notifications``
    actually injects/skeletonizes instead of silently no-oping (unlike a
    MagicMock-backed ``make_daemon_agent``, whose chat session cannot receive
    a synthesized pair)."""
    import queue

    from lingtai.kernel.base_agent import BaseAgent
    from lingtai.kernel.llm.interface import ChatInterface
    from lingtai.kernel.state import AgentState
    from tests._notification_store_helpers import notification_store_for

    class _ChatStub:
        def __init__(self):
            self.interface = ChatInterface()

    chat = _ChatStub()
    workdir = tmp_path / "daemon-sync-agent"
    workdir.mkdir(parents=True, exist_ok=True)

    class _Agent(BaseAgent):
        def __init__(self, workdir):
            self._working_dir = workdir
            self._notification_store = notification_store_for(workdir)
            self._config = SimpleNamespace(
                time_awareness=False,
                timezone_awareness=False,
                context_limit=0,
                cache_miss_budget=None,
                language="en",
            )
            self._state = AgentState.IDLE
            self._notification_fp = ()
            self._notification_raw_fp = ()
            self._notification_deferred_log_fp = ()
            self._notification_block_id = None
            self._notification_live_holder = None
            self._notification_inject_seq = 0
            self._asleep = threading.Event()
            self._cancel_event = threading.Event()
            self._chat_stub = chat
            self._logs: list = []
            self.agent_name = "daemon-sync-stub"
            self.inbox = queue.Queue()

        @property
        def _chat(self):
            return self._chat_stub

        def _save_chat_history(self, *, ledger_source="main"):
            pass

        def _log(self, evt, **fields):
            self._logs.append((evt, fields))

        def _wake_nap(self, *_a, **_kw):
            pass

        def _set_state(self, state, *_a, **_kw):
            self._state = state

        def _reset_uptime(self):
            pass

    return _Agent(workdir)


def test_asleep_terminal_wake_has_bounded_daemon_stats_and_cause(tmp_path):
    """A daemon-only ASLEEP wake carries stable stats plus one-shot cause."""
    from lingtai.kernel.state import AgentState

    agent = _make_daemon_sync_agent(tmp_path)
    agent._state = AgentState.ASLEEP
    agent._asleep.set()
    _publish(agent, "em-terminal")

    agent._sync_notifications()

    result = agent._chat_stub.interface.entries[-1].content[0]
    state = result.metadata["agent_meta"]["agent_state"]
    assert state["daemon"] == {
        "run_count": 1,
        "event_count": 1,
        "active_run_count": 0,
        "terminal_run_count": 1,
        "terminal_by_status": {"done": 1},
        "latest_terminal": [
            {"run_id": "em-terminal", "status": "done", "at": state["daemon"]["latest_terminal"][0]["at"]}
        ],
    }
    wake = state["notification_wake"]
    assert wake["kind"] == "wake"
    assert wake["source_kind"] == DAEMON_CHANNEL
    assert wake["changed_channels"] == [DAEMON_CHANNEL]
    assert wake["daemon"]["event_count_delta"] == 1
    assert wake["daemon"]["terminal_run_count_delta"] == 1
    assert wake["daemon"]["latest_terminal"][0]["run_id"] == "em-terminal"
    assert getattr(agent, "_notification_wake_provenance", None) is None


def test_first_subthreshold_arrival_never_injects_or_wakes(tmp_path):
    """An agent first seeing a sub-threshold daemon file must stay silent.

    The agent's baseline starts at ``()``, but with a threshold configured the
    masked fingerprint of an *empty* directory is the virtual quiet daemon
    token, not ``()``. Comparing a fresh agent's ``()`` against that token read
    as a change, so the very first sub-threshold arrival injected a synthesized
    pair and posted a wake — precisely the arrival the threshold exists to keep
    quiet. ``masked_empty_attention_fp`` resolves the baseline through the same
    mask so first-sight-of-quiet is a genuine no-op.
    """
    agent = _make_daemon_sync_agent(tmp_path)
    _write_threshold(agent, 3)
    _publish(agent, "em-0")

    agent._sync_notifications()

    assert agent._notification_live_holder is None, (
        "a first sub-threshold arrival must not inject a synthesized pair"
    )
    assert agent._notification_block_id is None
    assert agent.inbox.empty(), (
        "a first sub-threshold arrival must not post MSG_TC_WAKE"
    )
    # The state is quiet, not hidden: it remains readable through snapshot.
    assert DAEMON_CHANNEL in snapshot_notifications(agent._working_dir)


def test_alarmed_first_write_still_wakes_a_fresh_agent(tmp_path):
    """The silent-baseline fix must not swallow an alarmed first arrival.

    Threshold ``0`` means "alarm on the first event", so the very first write a
    fresh agent ever sees is already past ``count > N``. Its masked token is
    ``daemon:alarm=1``, which differs from the quiet empty baseline, so it must
    inject and wake exactly as an unmasked channel would.
    """
    from lingtai.kernel.message import MSG_TC_WAKE

    agent = _make_daemon_sync_agent(tmp_path)
    _write_threshold(agent, 0)
    _publish(agent, "em-0")

    agent._sync_notifications()

    assert agent._notification_live_holder is not None, (
        "an alarmed first arrival must still inject"
    )
    assert not agent.inbox.empty(), "an alarmed first arrival must wake"
    assert agent.inbox.get_nowait().type == MSG_TC_WAKE


def test_quiet_clear_retires_stale_holder_even_with_another_channel_live(tmp_path):
    """A quiet daemon clear must retire the stale holder without waking.

    Regression (two bugs in one path): ``apply_daemon_attention_mask`` keeps a
    virtual quiet entry present whether or not ``daemon.json`` exists, so the
    masked fingerprint is identical before creation and after a sub-threshold
    clear — the clear is invisible to the wake comparison. And gating the
    holder release on the *whole snapshot* being empty missed exactly this
    case: with ``email`` still live the snapshot stays truthy, so the holder
    kept advertising daemon events that no longer exist.
    """
    from tests._notification_store_helpers import (
        clear_test_payload,
        publish_test_payload,
    )

    agent = _make_daemon_sync_agent(tmp_path)
    _write_threshold(agent, 3)
    # An alarmed-equivalent first delivery is not needed: publishing `email`
    # (an unmasked channel) is itself a wake-worthy change, so this first sync
    # legitimately injects and gives us a live holder advertising both.
    _publish(agent, "em-0")
    publish_test_payload(agent._working_dir, "email", {"count": 1})

    agent._sync_notifications()
    holder = agent._notification_live_holder
    assert holder is not None
    first_block_id = agent._notification_block_id
    while not agent.inbox.empty():
        agent.inbox.get_nowait()

    # Quiet-clear: daemon.json empties out without ever crossing the threshold,
    # while `email` stays live so the snapshot remains non-empty.
    clear_test_payload(agent._working_dir, DAEMON_CHANNEL)
    agent._sync_notifications()

    assert agent._notification_live_holder is None, (
        "a quiet clear must retire the holder still advertising the removed "
        "daemon events, even though `email` keeps the snapshot non-empty"
    )
    # Retiring is silent: no wake, and no new injected pair.
    assert agent.inbox.empty(), "a quiet clear must not post MSG_TC_WAKE"
    assert agent._notification_block_id == first_block_id
    # `email` is untouched by the daemon-channel clear.
    assert "email" in snapshot_notifications(agent._working_dir)


def test_quiet_clear_retries_when_the_interface_is_poisoned(tmp_path):
    """A poisoned interface must not consume the quiet-clear observation.

    Committing ``_notification_raw_fp`` before the poison check let the next
    healthy tick see matching raw state and return early at the raw comparison,
    permanently skipping the holder release. The commit must happen only after
    the release actually runs.
    """
    from tests._notification_store_helpers import (
        clear_test_payload,
        publish_test_payload,
    )

    agent = _make_daemon_sync_agent(tmp_path)
    _write_threshold(agent, 3)
    _publish(agent, "em-0")
    publish_test_payload(agent._working_dir, "email", {"count": 1})

    agent._sync_notifications()
    assert agent._notification_live_holder is not None
    while not agent.inbox.empty():
        agent.inbox.get_nowait()

    clear_test_payload(agent._working_dir, DAEMON_CHANNEL)

    # Poison the interface, then tick: the clear must be left uncommitted.
    agent._llm_worker_interface_poisoned = True
    agent._llm_worker_poison_artifact = "artifact.json"
    agent._sync_notifications()
    assert agent._notification_live_holder is not None, (
        "a poisoned tick must not release the holder"
    )

    # Recover and tick again: the same clear must still be acted on.
    agent._llm_worker_interface_poisoned = False
    agent._sync_notifications()
    assert agent._notification_live_holder is None, (
        "the quiet clear must be retried after the interface recovers"
    )
    assert agent.inbox.empty()


def test_daemon_ids_use_independent_mini_channels_and_aggregate_without_overwrite(tmp_path):
    agent = make_daemon_agent(tmp_path)
    _publish(agent, "em-1")
    _publish(agent, "em-2")

    mini_dir = agent._working_dir / ".notification" / "daemon"
    assert {path.name for path in mini_dir.glob("*.json")} == {"em-1.json", "em-2.json"}
    events = snapshot_notifications(agent._working_dir)[DAEMON_CHANNEL]["data"]["events"]
    assert {event["ref_id"] for event in events} == {"em-1", "em-2"}
    # Owner appends do not scan/rebuild a root aggregate report. Snapshot is
    # the authoritative derived daemon view; the compatibility report may be
    # absent or stale until a rare aggregate-administration compaction.
    assert not (agent._working_dir / ".notification" / "daemon.json").exists()


def test_same_daemon_checkpoint_and_terminal_append_to_one_mini_file(tmp_path):
    agent = make_daemon_agent(tmp_path)
    _publish(agent, "em-append")
    agent._enqueue_system_notification(
        source="daemon",
        ref_id="em-append",
        body="checkpoint",
        idempotency_key="daemon-checkpoint:em-append:1",
        skip_if_idempotency_key_exists=True,
        channel=DAEMON_CHANNEL,
    )
    agent._enqueue_system_notification(
        source="daemon",
        ref_id="em-append",
        body="terminal",
        idempotency_key="daemon-terminal:em-append-followup",
        skip_if_idempotency_key_exists=True,
        channel=DAEMON_CHANNEL,
    )

    mini = agent._working_dir / ".notification" / "daemon" / "em-append.json"
    assert mini.is_file()
    payload = json.loads(mini.read_text(encoding="utf-8"))
    assert [event["body"] for event in payload["data"]["events"]] == [
        "Daemon em-append done.", "checkpoint", "terminal"
    ]


def test_daemon_fingerprint_notices_add_remove_and_same_file_append(tmp_path):
    agent = make_daemon_agent(tmp_path)
    store = agent._notification_store
    before = store.fingerprint(lambda channel: channel == DAEMON_CHANNEL)
    _publish(agent, "em-fp")
    added = store.fingerprint(lambda channel: channel == DAEMON_CHANNEL)
    assert added != before
    agent._enqueue_system_notification(
        source="daemon",
        ref_id="em-fp",
        body="append",
        idempotency_key="daemon-terminal:em-fp-append",
        skip_if_idempotency_key_exists=True,
        channel=DAEMON_CHANNEL,
    )
    appended = store.fingerprint(lambda channel: channel == DAEMON_CHANNEL)
    assert appended != added
    assert store.clear(DAEMON_CHANNEL) is True
    removed = store.fingerprint(lambda channel: channel == DAEMON_CHANNEL)
    assert removed != appended
    assert removed == ()


def test_daemon_event_or_ref_dismiss_deletes_only_matching_mini_file(tmp_path):
    from lingtai.kernel.meta_block import _commit_notification_fp
    from lingtai.kernel.notifications import dismiss_channel

    agent = make_daemon_agent(tmp_path)
    first = _publish(agent, "em-remove")
    _publish(agent, "em-keep")
    _commit_notification_fp(agent)
    result = dismiss_channel(
        agent, DAEMON_CHANNEL, invoked_by="notification", ref_id="em-remove"
    )

    assert result["status"] == "ok" and result["removed"] == 1
    mini_dir = agent._working_dir / ".notification" / "daemon"
    assert not (mini_dir / "em-remove.json").exists()
    assert (mini_dir / "em-keep.json").exists()
    assert first


@pytest.mark.parametrize("same_run", (True, False), ids=("same-run-sibling", "other-run"))
def test_targeted_daemon_event_dismiss_preserves_only_the_selected_event(
    tmp_path, monkeypatch, same_run
):
    from lingtai.kernel.meta_block import _commit_notification_fp
    from lingtai.kernel.notifications import dismiss_channel

    agent = make_daemon_agent(tmp_path)
    removed_event_id = _publish(agent, "em-target")
    if same_run:
        surviving_event_id = agent._enqueue_system_notification(
            source="daemon", ref_id="em-target", body="same run sibling",
            idempotency_key="daemon-checkpoint:em-target:sibling",
            skip_if_idempotency_key_exists=True, channel=DAEMON_CHANNEL,
        )
    else:
        surviving_event_id = _publish(agent, "em-other")
    _commit_notification_fp(agent)
    store = agent._notification_store
    fingerprints = {}
    if same_run:
        original_compact = store._compact_daemon_tombstone

        def compact_with_fingerprint_guard():
            fingerprints["before"] = store.fingerprint(lambda channel: channel == DAEMON_CHANNEL)
            original_compact()
            fingerprints["after"] = store.fingerprint(lambda channel: channel == DAEMON_CHANNEL)

        monkeypatch.setattr(store, "_compact_daemon_tombstone", compact_with_fingerprint_guard)
    result = dismiss_channel(
        agent, DAEMON_CHANNEL, invoked_by="notification", event_id=removed_event_id
    )

    assert result["status"] == "ok" and result["removed"] == 1
    mini_dir = agent._working_dir / ".notification" / "daemon"
    if same_run:
        mini = mini_dir / "em-target.json"
        assert mini.exists()
        events = json.loads(mini.read_text(encoding="utf-8"))["data"]["events"]
        assert [event["event_id"] for event in events] == [surviving_event_id]
        assert fingerprints["before"] == fingerprints["after"]
    else:
        assert not (mini_dir / "em-target.json").exists()
        assert (mini_dir / "em-other.json").exists()
        events = snapshot_notifications(agent._working_dir)[DAEMON_CHANNEL]["data"]["events"]
        assert [event["event_id"] for event in events] == [surviving_event_id]


def test_daemon_clear_and_targeted_dismiss_overlap_cannot_resurrect_events(tmp_path):
    from lingtai.kernel.meta_block import _commit_notification_fp
    from lingtai.kernel.notifications import dismiss_channel

    agent = make_daemon_agent(tmp_path)
    event_id = _publish(agent, "em-overlap")
    _publish(agent, "em-other")
    _commit_notification_fp(agent)
    barrier = threading.Barrier(3)
    clear_results = []
    dismiss_results = []

    def clear() -> None:
        barrier.wait()
        clear_results.append(agent._notification_store.clear(DAEMON_CHANNEL))

    def dismiss() -> None:
        barrier.wait()
        dismiss_results.append(
            dismiss_channel(
                agent,
                DAEMON_CHANNEL,
                invoked_by="notification",
                force=True,
                event_id=event_id,
            )
        )

    clear_thread = threading.Thread(target=clear)
    dismiss_thread = threading.Thread(target=dismiss)
    clear_thread.start()
    dismiss_thread.start()
    barrier.wait()
    clear_thread.join(timeout=10)
    dismiss_thread.join(timeout=10)
    assert not clear_thread.is_alive() and not dismiss_thread.is_alive()
    assert clear_results == [True]
    assert dismiss_results[0]["status"] == "ok"
    assert DAEMON_CHANNEL not in snapshot_notifications(agent._working_dir)


def test_daemon_channel_dismiss_refuses_to_delete_late_mini_file(tmp_path):
    from lingtai.kernel.meta_block import _commit_notification_fp
    from lingtai.kernel.notifications import dismiss_channel

    agent = make_daemon_agent(tmp_path)
    _publish(agent, "em-old")
    _commit_notification_fp(agent)
    _publish(agent, "em-late")

    result = dismiss_channel(agent, DAEMON_CHANNEL, invoked_by="notification")
    assert result["status"] == "error"
    assert result["reason"] == "stale_channel_version"
    mini_dir = agent._working_dir / ".notification" / "daemon"
    assert (mini_dir / "em-old.json").exists()
    assert (mini_dir / "em-late.json").exists()
