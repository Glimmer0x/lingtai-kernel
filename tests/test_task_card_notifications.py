"""Task Card-owned typed notification boundary and wire-parity tests.

The recorder below stands in for the Agent's generic system-event publisher
only. Everything between the producer's typed events and that publisher is the
real production path: the family-local ``TaskCardNotificationsAdapter`` feeding
the operation-native ``AgentTaskCardNotificationsAdapter`` that the host grants
as the kernel ``TaskCardNotificationsPort``.
"""

from __future__ import annotations

import inspect
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from lingtai.adapters.tool_plugin_host import AgentTaskCardNotificationsAdapter
from lingtai.kernel.tool_plugin import TaskCardNotificationsPort
from lingtai.tools.task_card import (
    TaskCardErrorNotification,
    TaskCardLimitNotification,
    TaskCardNotificationsAdapter,
    TaskCardRecoveredNotification,
    TaskCardManager,
)

NATIVE_OPERATIONS = (
    "publish_error",
    "publish_recovered",
    "publish_limit",
    "submit_reminder",
    "clear_reminder",
)


class _Recorder:
    """The Agent-side generic publisher and reminder sinks, recorded verbatim."""

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


def _native_port(recorder: _Recorder) -> AgentTaskCardNotificationsAdapter:
    return AgentTaskCardNotificationsAdapter(
        recorder.enqueue_system_notification,
        recorder.submit_reminder,
        recorder.clear_reminder,
    )


def _adapter() -> tuple[TaskCardNotificationsAdapter, _Recorder]:
    recorder = _Recorder()
    return TaskCardNotificationsAdapter(_native_port(recorder)), recorder


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


def test_native_port_exposes_exactly_five_closed_operations() -> None:
    """The granted port object has the kernel Protocol's five methods and no publisher."""
    native = _native_port(_Recorder())

    public = sorted(name for name in dir(native) if not name.startswith("_"))
    assert public == sorted(NATIVE_OPERATIONS)
    assert not hasattr(native, "enqueue_system_notification")
    assert not hasattr(native, "__dict__")  # __slots__: no attribute smuggling

    for name in NATIVE_OPERATIONS:
        port_params = inspect.signature(getattr(TaskCardNotificationsPort, name)).parameters
        adapter_params = inspect.signature(getattr(native, name)).parameters
        assert list(adapter_params) == [p for p in port_params if p != "self"], name
        assert all(
            p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD) for p in adapter_params.values()
        ), name
        for forbidden in ("source", "channel", "extra", "priority", "ref_id"):
            assert forbidden not in adapter_params, (name, forbidden)


@pytest.mark.parametrize(
    "operation, kwargs",
    [
        ("publish_error", {"watch_id": "tc_1", "body": "b", "code": "c", "retryable": True,
                           "idempotency_key": "k"}),
        ("publish_recovered", {"watch_id": "tc_1", "body": "b", "idempotency_key": "k"}),
        ("publish_limit", {"watch_id": "tc_1", "body": "b", "idempotency_key": "k",
                           "used": 1, "max_refreshes": 1}),
    ],
)
@pytest.mark.parametrize(
    "foreign",
    [
        {"source": "foreign.source"},
        {"channel": "foreign"},
        {"extra": {"source": "foreign"}},
        {"priority": "urgent"},
        {"skip_if_idempotency_key_exists": False},
    ],
)
def test_native_port_rejects_foreign_source_channel_and_fields(operation, kwargs, foreign) -> None:
    recorder = _Recorder()
    native = _native_port(recorder)
    with pytest.raises(TypeError):
        getattr(native, operation)(**kwargs, **foreign)
    assert recorder.events == []


def test_manager_retains_only_the_typed_notification_view() -> None:
    recorder = _Recorder()
    host = SimpleNamespace(
        workdir=SimpleNamespace(path=Path.cwd()),
        shutdown=threading.Event(),
        task_card_notifications=_native_port(recorder),
    )
    manager = TaskCardManager(host)

    assert isinstance(manager._host.task_card_notifications, TaskCardNotificationsAdapter)
    assert not hasattr(manager._host.task_card_notifications, "enqueue_system_notification")
    assert not hasattr(manager._host, "task_card_lifecycle")
    assert not hasattr(manager, "_agent")


def test_family_adapter_refuses_a_generic_publisher_port() -> None:
    """A port that offers a generic enqueue is not the native port and is refused."""
    recorder = _Recorder()
    with pytest.raises(TypeError):
        TaskCardNotificationsAdapter(recorder)  # has enqueue_system_notification
    with pytest.raises(TypeError):
        TaskCardNotificationsAdapter(
            SimpleNamespace(submit_reminder=lambda turns: None, clear_reminder=lambda: None)
        )


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
    with pytest.raises(TypeError):
        adapter.publish_error({"watch_id": "tc_1", "source": "foreign"})  # type: ignore[arg-type]
    assert not hasattr(adapter, "enqueue_system_notification")


@pytest.mark.parametrize("turns", [0, -1, True, "10"])
def test_reminder_operation_rejects_foreign_field_shapes(turns) -> None:
    adapter, recorder = _adapter()
    with pytest.raises(TypeError):
        adapter.submit_reminder(turns)
    assert recorder.reminders == []
