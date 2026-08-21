"""Focused invariants for daemon attention delay and daemon event observability.

Four distinct promises, one table per promise:

1. A live ``daemon`` delay suppresses *attention* only — daemon truth stays
   readable and its byte-exact version keeps describing the delivered bytes.
2. Independent registered hook channels still wake the parent while the daemon
   channel is delayed, and expiry cannot strand an ASLEEP parent.
3. Follow-up (``ask``) events are not terminal outcomes, including the legacy
   shapes already on disk.
4. A dismissal/clear/reset can never report a negative daemon delta.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lingtai.kernel.base_agent import (
    _daemon_notification_summary,
    _daemon_summary_delta,
    _is_terminal_daemon_event,
)
from lingtai.kernel.notifications import (
    DAEMON_CHANNEL,
    DAEMON_DELAYED_ATTENTION_TOKEN,
    DELAY_ALARM_CHANNEL,
    apply_daemon_attention_mask,
    coherent_attention_read,
    daemon_attention_token,
    delay_notification_channel,
    is_channel_allowed,
    masked_empty_attention_fp,
    reconcile_notification_delay,
)
from tests.test_daemon_notification_channel import (
    _make_daemon_sync_agent,
    _publish,
    _write_threshold,
)
from tests._notification_store_helpers import publish_test_payload


def _observe(agent):
    workdir = str(agent._working_dir)
    return coherent_attention_read(
        agent._notification_store,
        lambda channel: is_channel_allowed(channel, workdir=workdir),
        workdir,
    )


def _delay(agent, channel: str, seconds: int) -> dict:
    return delay_notification_channel(agent, channel, seconds)


def _expire(agent) -> None:
    state_path = agent._working_dir / ".notification" / ".delay_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["deadline_epoch"] = state["started_epoch"] - 1
    state_path.write_text(json.dumps(state), encoding="utf-8")


def _entry(fingerprint: tuple, channel: str):
    name = f"{channel}.json"
    return next((e for e in fingerprint if e and e[0] == name), None)


# --- 1. delay masks daemon attention without hiding daemon truth ------------

@pytest.mark.parametrize(
    "threshold, delayed, expected",
    [
        (None, False, None),                              # default: raw hash
        (None, True, DAEMON_DELAYED_ATTENTION_TOKEN),     # delay alone masks
        (3, False, "daemon:alarm=0"),                     # threshold quiet
        (0, False, "daemon:alarm=1"),                     # threshold alarmed
        (0, True, DAEMON_DELAYED_ATTENTION_TOKEN),        # delay wins while live
    ],
)
def test_daemon_attention_token_table(threshold, delayed, expected) -> None:
    payload = {"data": {DAEMON_CHANNEL: {"count": 1, "alarm_fired": False}}}
    assert daemon_attention_token(payload, threshold, delayed=delayed) == expected


def test_delayed_daemon_stays_readable_and_byte_versioned(tmp_path) -> None:
    """Delay hides no daemon truth: payload, raw version, and file all survive."""
    agent = _make_daemon_sync_agent(tmp_path)
    _publish(agent, "em-1")
    mini = agent._working_dir / ".notification" / DAEMON_CHANNEL / "em-1.json"
    before = mini.read_bytes()
    raw_before = _entry(_observe(agent).raw_fp, DAEMON_CHANNEL)

    assert _delay(agent, DAEMON_CHANNEL, 30)["action"] == "delayed"
    observed = _observe(agent)

    assert mini.read_bytes() == before, "delay must not touch producer storage"
    assert DAEMON_CHANNEL in observed.payloads, "daemon truth must stay readable"
    assert _entry(observed.raw_fp, DAEMON_CHANNEL) == raw_before
    assert _entry(observed.masked_fp, DAEMON_CHANNEL)[2] == DAEMON_DELAYED_ATTENTION_TOKEN


def test_delayed_daemon_appends_do_not_move_the_attention_fingerprint(tmp_path) -> None:
    agent = _make_daemon_sync_agent(tmp_path)
    _publish(agent, "em-1")
    _delay(agent, DAEMON_CHANNEL, 30)
    masked_before = _observe(agent).masked_fp

    _publish(agent, "em-2")
    observed = _observe(agent)

    assert observed.masked_fp == masked_before, "a delayed daemon must not wake"
    assert observed.raw_fp != masked_before, "raw truth must still record the append"
    assert _daemon_notification_summary(observed.payloads[DAEMON_CHANNEL])["run_count"] == 2


def test_non_daemon_delay_keeps_hiding_its_target(tmp_path) -> None:
    """Only the daemon channel changed; ordinary targets stay hidden."""
    agent = _make_daemon_sync_agent(tmp_path)
    publish_test_payload(agent._working_dir, "email", {"data": {"count": 2}})

    assert _delay(agent, "email", 30)["action"] == "delayed"

    assert "email" not in _observe(agent).payloads


def test_masked_empty_baseline_follows_a_live_daemon_delay(tmp_path) -> None:
    """A restart inside the delay window resolves its baseline through the mask."""
    agent = _make_daemon_sync_agent(tmp_path)
    workdir = str(agent._working_dir)
    assert masked_empty_attention_fp(workdir) == ()

    _delay(agent, DAEMON_CHANNEL, 30)

    assert masked_empty_attention_fp(workdir) == apply_daemon_attention_mask(
        (), None, None, delayed=True
    )


# --- 2. hook channels wake normally; expiry cannot strand the parent --------

def test_registered_hook_channel_wakes_while_daemon_is_delayed(tmp_path) -> None:
    from lingtai.kernel.notifications import add_hook, reset_hook_registry_for_tests
    from lingtai.kernel.message import MSG_TC_WAKE
    from lingtai.kernel.state import AgentState

    agent = _make_daemon_sync_agent(tmp_path)
    reset_hook_registry_for_tests()
    add_hook(agent, {
        "name": "watcher", "channel": "watcher", "source": "external",
        "description": "carrier", "how_to_modify": "edit", "how_to_cancel": "kill",
    })
    _publish(agent, "em-1")
    _delay(agent, DAEMON_CHANNEL, 30)
    agent._sync_notifications()
    while not agent.inbox.empty():
        agent.inbox.get_nowait()
    agent._state = AgentState.ASLEEP
    agent._asleep.set()

    # A daemon append stays quiet; the independent hook channel still wakes.
    _publish(agent, "em-2")
    agent._sync_notifications()
    assert agent.inbox.empty(), "a delayed daemon append must not wake the parent"
    assert agent._state == AgentState.ASLEEP

    publish_test_payload(agent._working_dir, "watcher", {"data": {"hit": 1}})
    agent._sync_notifications()

    assert agent._state == AgentState.IDLE, "a hook channel must wake normally"
    assert agent.inbox.get_nowait().type == MSG_TC_WAKE
    reset_hook_registry_for_tests()


def test_expiry_wakes_an_asleep_parent_and_republishes_daemon_attention(tmp_path) -> None:
    from lingtai.kernel.state import AgentState

    agent = _make_daemon_sync_agent(tmp_path)
    _publish(agent, "em-1")
    _delay(agent, DAEMON_CHANNEL, 30)
    agent._sync_notifications()
    while not agent.inbox.empty():
        agent.inbox.get_nowait()
    agent._state = AgentState.ASLEEP
    agent._asleep.set()
    _publish(agent, "em-2")
    _expire(agent)

    agent._sync_notifications()

    assert agent._state == AgentState.IDLE, "an expired delay must wake the parent"
    assert (agent._working_dir / ".notification" / f"{DELAY_ALARM_CHANNEL}.json").is_file()
    assert _entry(_observe(agent).masked_fp, DAEMON_CHANNEL)[2] != DAEMON_DELAYED_ATTENTION_TOKEN


def test_corrupt_delay_state_fails_open_to_daemon_attention(tmp_path) -> None:
    agent = _make_daemon_sync_agent(tmp_path)
    _publish(agent, "em-1")
    _delay(agent, DAEMON_CHANNEL, 30)
    state_path = agent._working_dir / ".notification" / ".delay_state.json"
    state_path.write_text("{not json", encoding="utf-8")

    observed = _observe(agent)

    assert _entry(observed.masked_fp, DAEMON_CHANNEL)[2] != DAEMON_DELAYED_ATTENTION_TOKEN
    assert observed.masked_fp == observed.raw_fp
    assert reconcile_notification_delay(agent._working_dir, agent._notification_store) is False


def test_delayed_daemon_alarm_edge_is_deferred_not_dropped(tmp_path) -> None:
    """A crossing during the delay still alarms once the delay expires."""
    agent = _make_daemon_sync_agent(tmp_path)
    _write_threshold(agent, 1)
    _publish(agent, "em-1")
    _delay(agent, DAEMON_CHANNEL, 30)
    _publish(agent, "em-2")
    _publish(agent, "em-3")

    assert _entry(_observe(agent).masked_fp, DAEMON_CHANNEL)[2] == DAEMON_DELAYED_ATTENTION_TOKEN

    _expire(agent)
    assert _entry(_observe(agent).masked_fp, DAEMON_CHANNEL)[2] == "daemon:alarm=1"


# --- 3. follow-up events are not terminal outcomes --------------------------

@pytest.mark.parametrize(
    "event, terminal",
    [
        ({"kind": "daemon_terminal", "status": "done"}, True),
        ({"idempotency_key": "daemon-terminal:run-1", "status": "failed"}, True),
        ({"kind": "daemon_followup", "status": "follow-up completed"}, False),
        # legacy detached follow-up: typed terminal, follow-up key
        ({"kind": "daemon_terminal", "idempotency_key": "daemon-followup:run-1:2",
          "status": "follow-up failed"}, False),
        # legacy in-process follow-up: typed terminal, no key at all
        ({"kind": "daemon_terminal", "status": "follow-up completed"}, False),
        ({"kind": "daemon_checkpoint", "status": "running"}, False),
        ({}, False),
    ],
)
def test_terminal_classification_table(event, terminal) -> None:
    assert _is_terminal_daemon_event(event) is terminal


def test_followup_keeps_its_run_active_in_the_summary() -> None:
    payload = {"data": {"events": [
        {"ref_id": "em-1", "kind": "daemon_checkpoint", "at": "2026-01-01T00:00:00Z"},
        {"ref_id": "em-1", "kind": "daemon_followup", "status": "follow-up completed",
         "at": "2026-01-01T00:01:00Z"},
    ]}}

    summary = _daemon_notification_summary(payload)

    assert summary["event_count"] == 2
    assert summary["run_count"] == 1
    assert summary["active_run_count"] == 1
    assert summary["terminal_run_count"] == 0
    assert summary["terminal_by_status"] == {}
    assert summary["latest_terminal"] == []


# --- 4. deltas are never negative ------------------------------------------

@pytest.mark.parametrize(
    "previous, current, expected",
    [
        # first delivery
        ({}, {"event_count": 2, "run_count": 2, "terminal_run_count": 1},
         {"event_count_delta": 2, "run_count_delta": 2, "terminal_run_count_delta": 1}),
        # ordinary growth
        ({"event_count": 2, "run_count": 2, "terminal_run_count": 1},
         {"event_count": 5, "run_count": 3, "terminal_run_count": 2},
         {"event_count_delta": 3, "run_count_delta": 1, "terminal_run_count_delta": 1}),
        # dismissal shrank the aggregate: report the remaining batch, not a negative
        ({"event_count": 5, "run_count": 3, "terminal_run_count": 2},
         {"event_count": 1, "run_count": 1, "terminal_run_count": 0},
         {"event_count_delta": 1, "run_count_delta": 1, "terminal_run_count_delta": 0,
          "baseline_reset": True}),
        # malformed baseline counts read as zero rather than poisoning the delta
        ({"event_count": "many", "run_count": None, "terminal_run_count": True},
         {"event_count": 1, "run_count": 1, "terminal_run_count": 1},
         {"event_count_delta": 1, "run_count_delta": 1, "terminal_run_count_delta": 1}),
    ],
)
def test_daemon_delta_table(previous, current, expected) -> None:
    current = {**current, "latest_terminal": []}
    delta = _daemon_summary_delta(previous, current)

    assert {k: v for k, v in delta.items() if k != "latest_terminal"} == expected
    assert all(
        value >= 0 for key, value in delta.items() if key.endswith("_delta")
    )


def test_dismissal_reset_delta_is_reported_on_the_next_wake(tmp_path) -> None:
    from lingtai.kernel.notifications import dismiss_channel
    from lingtai.kernel.state import AgentState

    agent = _make_daemon_sync_agent(tmp_path)
    _publish(agent, "em-1")
    _publish(agent, "em-2")
    agent._sync_notifications()
    assert agent._notification_delivered_daemon_summary["run_count"] == 2

    dismiss_channel(agent, DAEMON_CHANNEL, invoked_by="notification", force=True)
    _publish(agent, "em-3")
    agent._state = AgentState.ASLEEP
    agent._asleep.set()
    agent._sync_notifications()

    result = agent._chat_stub.interface.entries[-1].content[0]
    daemon_wake = result.metadata["agent_meta"]["agent_state"]["notification_wake"]["daemon"]
    assert daemon_wake["baseline_reset"] is True
    assert daemon_wake["event_count_delta"] == 1
    assert daemon_wake["run_count_delta"] == 1


# --- current summary stays current on the quiet path ------------------------

def test_quiet_and_delayed_reads_keep_the_daemon_summary_current(tmp_path) -> None:
    agent = _make_daemon_sync_agent(tmp_path)
    _write_threshold(agent, 5)
    _publish(agent, "em-1")
    agent._sync_notifications()
    assert agent._notification_daemon_summary["run_count"] == 1

    # Sub-threshold arrival: quiet (no wake) but the current summary advances.
    _publish(agent, "em-2")
    agent._sync_notifications()
    assert agent.inbox.empty()
    assert agent._notification_daemon_summary["run_count"] == 2

    # Same for a delayed daemon channel.
    _delay(agent, DAEMON_CHANNEL, 30)
    _publish(agent, "em-3")
    agent._sync_notifications()
    assert agent._notification_daemon_summary["run_count"] == 3
