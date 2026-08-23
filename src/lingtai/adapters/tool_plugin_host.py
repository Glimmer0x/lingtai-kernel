"""Production adapters translating the live Agent body into host plugin ports.

``lingtai.kernel.tool_plugin`` owns the Ports; this module is the one
production Adapter set that satisfies them for a running ``BaseAgent``, and it
lives outside the kernel package so the dependency still points inward
(``Adapter -> Port <- Core``, root ``CONTRACT.md`` rules 2-3).

Each adapter is constructed from narrow bound callables or single-purpose
closures, never from an Agent object. That constrains the declared argument
surface handed to an official plugin: a family gets only the ports it names,
not a convenience whole-Agent backdoor. Deep reachability through a bound
method or closure remains ordinary trusted-in-process Python and is not claimed
as a security boundary.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Sequence

from lingtai.kernel import notifications
from lingtai.kernel.tool_plugin import (
    BoundToolPlugin,
    ToolPluginDeclaration,
    register_official_tool_plugins,
)

__all__ = [
    "AgentWorkdirAdapter",
    "AgentPromptSectionAdapter",
    "AgentShutdownAdapter",
    "AgentTaskCardLifecycleAdapter",
    "AgentTaskCardNotificationsAdapter",
    "agent_host_ports",
    "register_agent_tool_plugins",
]


class AgentWorkdirAdapter:
    """``WorkdirPort`` over ``Agent.working_dir``, read on every access."""

    __slots__ = ("_read",)

    def __init__(self, read: Callable[[], Path]) -> None:
        self._read = read

    @property
    def path(self) -> Path:
        return self._read()


class AgentPromptSectionAdapter:
    """``PromptSectionPort`` permanently bound to one protected section."""

    __slots__ = ("_section", "_write")

    def __init__(self, section: str, write: Callable[..., None]) -> None:
        self._section = section
        self._write = write

    def write_protected_section(self, body: str) -> None:
        self._write(self._section, body, protected=True)


class AgentShutdownAdapter:
    """One-predicate ``ShutdownPort`` over the Agent shutdown event."""

    __slots__ = ("_is_set",)

    def __init__(self, is_set: Callable[[], bool]) -> None:
        self._is_set = is_set

    def is_set(self) -> bool:
        return self._is_set()


class AgentTaskCardLifecycleAdapter:
    """The one current-Agent manager slot Task Card needs across refreshes."""

    __slots__ = ("_current", "_retain", "_report")

    def __init__(
        self,
        current: Callable[[], Any | None],
        retain: Callable[[Any], None],
        report: Callable[[str], None],
    ) -> None:
        self._current = current
        self._retain = retain
        self._report = report

    def current_manager(self) -> Any | None:
        return self._current()

    def retain_manager(self, manager: Any) -> None:
        self._retain(manager)

    def report_resume_failure(self, error: str) -> None:
        self._report(error)


class AgentTaskCardNotificationsAdapter:
    """Task Card's existing three notification operations, without an Agent arg."""

    __slots__ = ("_enqueue", "_submit", "_clear")

    def __init__(
        self,
        enqueue: Callable[..., Any],
        submit: Callable[[int], None],
        clear: Callable[[], None],
    ) -> None:
        self._enqueue = enqueue
        self._submit = submit
        self._clear = clear

    def enqueue_system_notification(self, **kwargs: Any) -> None:
        self._enqueue(**kwargs)

    def submit_reminder(self, turns: int) -> None:
        self._submit(turns)

    def clear_reminder(self) -> None:
        self._clear()


def agent_host_ports(agent: Any, plugin_name: str) -> dict[str, Any]:
    """Build the full earned port table for *plugin_name* on *agent*.

    The registrar grants each declaration only its ``requires`` subset. The
    task-card closures deliberately retain its existing Agent-owned manager slot
    and producer notification behavior; no plugin receives the Agent itself.
    """

    def _retain_task_card_manager(manager: Any) -> None:
        agent._task_card_manager = manager

    def _report_task_card_resume_failure(error: str) -> None:
        log = getattr(agent, "_log", None)
        if callable(log):
            log("task_card_resume_failed", error=error)

    def _submit_task_card_reminder(turns: int) -> None:
        notifications.submit(
            agent,
            "task_card",
            data={"source": "task_card.reminder", "turns": turns},
            header="Task Card reminder",
            instructions=(
                "Check whether the Task Card is absent or stale; update or issue one only if useful."
            ),
        )

    def _clear_task_card_reminder() -> None:
        notifications.clear(agent, "task_card")

    return {
        "workdir": AgentWorkdirAdapter(lambda: agent.working_dir),
        "prompt_section": AgentPromptSectionAdapter(plugin_name, agent.update_system_prompt),
        "shutdown": AgentShutdownAdapter(agent._shutdown.is_set),
        "task_card_lifecycle": AgentTaskCardLifecycleAdapter(
            lambda: getattr(agent, "_task_card_manager", None),
            _retain_task_card_manager,
            _report_task_card_resume_failure,
        ),
        "task_card_notifications": AgentTaskCardNotificationsAdapter(
            agent._enqueue_system_notification,
            _submit_task_card_reminder,
            _clear_task_card_reminder,
        ),
    }


def register_agent_tool_plugins(
    agent: Any,
    declarations: Sequence[ToolPluginDeclaration],
) -> tuple[BoundToolPlugin, ...]:
    """Wire *declarations* onto *agent* through the kernel registrar.

    The name-conflict preflight covers the whole batch before bind, activation,
    or mount. A later host/binder/activation failure propagates after prior
    members have mounted because this component deliberately owns no unmount.
    """

    class _InternalMount:
        def mount_tool(self, transaction) -> None:
            agent._mount_official_tool(transaction)

    return register_official_tool_plugins(
        list(declarations),
        ports_for=lambda declaration: agent_host_ports(agent, declaration.name),
        mount=_InternalMount(),
        claimed=agent.official_tool_plugins,
        claim=agent._claim_official_tool,
        authorize=agent._authorize_official_tool_declaration,
        record_bound=agent._record_official_tool_binding,
    )
