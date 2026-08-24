"""Task Card-owned typed notification boundary and wire-parity tests."""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from lingtai.tools.task_card import (
    TaskCardErrorNotification,
    TaskCardLimitNotification,
    TaskCardNotificationsAdapter,
    TaskCardRecoveredNotification,
    TaskCardManager,
)


class _Recorder:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self.reminders: list[int] = []
        self.clears = 0

    def enqueue_system_notification(self, **kwargs):
        self.events.append(kwargs)
        return "event-id"

    def submit_reminder(self, turns: int) -> None:
        self.reminders.append(turns)

    def clear_reminder(self) -> None:
        self.clears += 1


def _adapter() -> tuple[TaskCardNotificationsAdapter, _Recorder]:
    recorder = _Recorder()
    return TaskCardNotificationsAdapter(recorder), recorder


def test_typed_operations_pin_sources_fields_and_event_parity() -> None:
    adapter, recorder = _adapter()

    adapter.publish_error(
        TaskCardErrorNotification(
            watch_id="tc_7",
            body="Task Card watch tc_7 failed: renderer exited with status 3",
            code="renderer_nonzero_exit",
            retryable=True,
            idempotency_key="task_card.error:tc_7:1:renderer_nonzero_exit",
            last_valid_body_at="2026-08-23T18:00:00+00:00",
        )
    )
    adapter.publish_recovered(
        TaskCardRecoveredNotification(
            watch_id="tc_7",
            body="Task Card watch tc_7 recovered.",
            idempotency_key="task_card.recovered:tc_7:1",
        )
    )
    adapter.publish_limit(
        TaskCardLimitNotification(
            watch_id="tc_7",
            body="Task Card watch tc_7 reached its refresh limit.",
            idempotency_key="task_card.limit:tc_7:20",
            used=20,
            max_refreshes=20,
        )
    )
    adapter.submit_reminder(10)
    adapter.clear_reminder()

    assert recorder.events == [
        {
            "source": "task_card.error",
            "channel": "system",
            "ref_id": "tc_7",
            "body": "Task Card watch tc_7 failed: renderer exited with status 3",
            "idempotency_key": "task_card.error:tc_7:1:renderer_nonzero_exit",
            "skip_if_idempotency_key_exists": True,
            "priority": "high",
            "extra": {
                "watch_id": "tc_7",
                "state": "error",
                "code": "renderer_nonzero_exit",
                "retryable": True,
                "last_valid_body_at": "2026-08-23T18:00:00+00:00",
            },
        },
        {
            "source": "task_card.error",
            "channel": "system",
            "ref_id": "tc_7",
            "body": "Task Card watch tc_7 recovered.",
            "idempotency_key": "task_card.recovered:tc_7:1",
            "skip_if_idempotency_key_exists": True,
            "priority": "normal",
            "extra": {"watch_id": "tc_7", "state": "recovered"},
        },
        {
            "source": "task_card.limit",
            "channel": "system",
            "ref_id": "tc_7",
            "body": "Task Card watch tc_7 reached its refresh limit.",
            "idempotency_key": "task_card.limit:tc_7:20",
            "skip_if_idempotency_key_exists": True,
            "priority": "normal",
            "extra": {
                "watch_id": "tc_7",
                "state": "stopped",
                "reason": "max_refreshes",
                "used": 20,
                "max": 20,
            },
        },
    ]
    assert recorder.reminders == [10]
    assert recorder.clears == 1


def test_manager_retains_only_the_typed_notification_view() -> None:
    recorder = _Recorder()
    host = SimpleNamespace(
        workdir=SimpleNamespace(path=Path.cwd()),
        shutdown=threading.Event(),
        task_card_notifications=recorder,
    )
    manager = TaskCardManager(host)

    assert isinstance(manager._host.task_card_notifications, TaskCardNotificationsAdapter)
    assert not hasattr(manager._host.task_card_notifications, "enqueue_system_notification")


def test_typed_event_forms_reject_foreign_source_channel_and_fields() -> None:
    adapter, _ = _adapter()
    error = TaskCardErrorNotification(
        watch_id="tc_1",
        body="failure",
        code="renderer_failed",
        retryable=True,
        idempotency_key="task_card.error:tc_1:1:renderer_failed",
    )

    with pytest.raises(TypeError):
        TaskCardErrorNotification(  # type: ignore[call-arg]
            watch_id="tc_1",
            body="failure",
            code="renderer_failed",
            retryable=True,
            idempotency_key="task_card.error:tc_1:1:renderer_failed",
            source="foreign.source",
        )
    with pytest.raises(TypeError):
        adapter.publish_error(error, channel="foreign")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        adapter.publish_error(error, extra={"source": "foreign"})  # type: ignore[call-arg]
    assert not hasattr(adapter, "enqueue_system_notification")


@pytest.mark.parametrize("turns", [0, -1, True, "10"])
def test_reminder_operation_rejects_foreign_field_shapes(turns) -> None:
    adapter, recorder = _adapter()
    with pytest.raises(TypeError):
        adapter.submit_reminder(turns)
    assert recorder.reminders == []
