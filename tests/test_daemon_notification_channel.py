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

Run-local `daemon.json` / result files remain the terminal source of truth;
this channel is only the parent-facing wake surface.
"""
from __future__ import annotations

import json

import pytest

from lingtai.kernel.notifications import (
    DAEMON_CHANNEL,
    apply_daemon_attention_mask,
    daemon_alarm_threshold,
    daemon_batch_state,
    is_channel_allowed,
    next_daemon_batch_state,
)

from tests._daemon_helpers import make_daemon_agent
from tests._notification_store_helpers import snapshot_notifications


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
