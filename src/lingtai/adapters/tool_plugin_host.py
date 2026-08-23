"""Production adapters translating the live Agent body into host plugin ports.

`lingtai.kernel.tool_plugin` owns the Ports; this module is the one production
Adapter set that satisfies them for a running ``BaseAgent``, and it lives
outside the kernel package so the dependency still points inward
(``Adapter -> Port <- Core``, root ``CONTRACT.md`` rules 2-3).

Each adapter is constructed from one narrow callable — a bound method of the
agent, or a single-expression read closure — never from the agent object. That
is a real constraint on this file rather than a security boundary: an adapter
here cannot reach a second Agent API by accident, because it never holds the
Agent. Deep reachability through a bound method's ``__self__`` or a closure
cell is not prevented and is not claimed to be — the promise the contract makes
is about the declared argument surface handed to a plugin.

Which declarations get registered, and when, stays in the Composition Root
(``src/lingtai/agent.py`` and the capability ``setup()`` it drives). This module
only builds the ports.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Sequence

from lingtai.kernel.tool_plugin import (
    BoundToolPlugin,
    ToolPluginDeclaration,
    register_official_tool_plugins,
)

__all__ = [
    "AgentWorkdirAdapter",
    "AgentPromptSectionAdapter",
    "AgentSoulRuntimeAdapter",
    "agent_soul_runtime",
    "agent_host_ports",
    "register_agent_tool_plugins",
]


class AgentWorkdirAdapter:
    """:class:`~lingtai.kernel.tool_plugin.WorkdirPort` over ``Agent.working_dir``.

    Reads through on every access rather than snapshotting, so a plugin holding
    this port across a refresh never renders a stale directory.
    """

    __slots__ = ("_read",)

    def __init__(self, read: Callable[[], Path]) -> None:
        self._read = read

    @property
    def path(self) -> Path:
        return self._read()


class AgentPromptSectionAdapter:
    """:class:`~lingtai.kernel.tool_plugin.PromptSectionPort` for one section.

    Bound at construction to the declaring plugin's own section name and to
    ``protected=True``. The plugin passes only a body, so it can neither
    address another plugin's section nor downgrade its own to unprotected.
    """

    __slots__ = ("_section", "_write")

    def __init__(
        self,
        section: str,
        write: Callable[..., None],
    ) -> None:
        self._section = section
        self._write = write

    def write_protected_section(self, body: str) -> None:
        self._write(self._section, body, protected=True)



class AgentSoulRuntimeAdapter:
    """``SoulRuntimePort`` over the exact live-self operations Soul consumes.

    The adapter stores individual getters, setters, and bound operations rather
    than an Agent. Its explicit surface covers Soul's real conversation,
    cadence, lock, and notification semantics without granting an unrelated
    tool, mount, or generic Agent API.
    """

    __slots__ = (
        "_working_dir", "_config", "_service", "_chat", "_session",
        "_agent_name", "_state", "_idle_event", "_shutdown", "_soul_delay",
        "_set_soul_delay", "_soul_timer", "_set_soul_timer", "_fire_lock",
        "_notification_store", "_notification_fingerprint", "_appendix_ids",
        "_log", "_restart_soul_timer", "_run_consultation_fire",
        "_sync_notifications", "_wake_nap", "_persist_soul_entry",
        "_append_soul_flow_record", "_publish_notification",
        "_clear_notification", "_dismiss_notification",
    )

    def __init__(
        self,
        *,
        working_dir: Callable[[], Path],
        config: Callable[[], Any],
        service: Callable[[], Any],
        chat: Callable[[], Any],
        session: Callable[[], Any],
        agent_name: Callable[[], str],
        state: Callable[[], Any],
        idle_event: Callable[[], Any],
        shutdown: Callable[[], Any],
        soul_delay: Callable[[], float],
        set_soul_delay: Callable[[float], None],
        soul_timer: Callable[[], Any],
        set_soul_timer: Callable[[Any], None],
        fire_lock: Callable[[], Any],
        notification_store: Callable[[], Any],
        notification_fingerprint: Callable[[], Any],
        appendix_ids: Callable[[], dict[str, str]],
        log: Callable[..., None],
        restart_soul_timer: Callable[[], None],
        run_consultation_fire: Callable[[], None],
        sync_notifications: Callable[[], None],
        wake_nap: Callable[[str], None],
        persist_soul_entry: Callable[..., None],
        append_soul_flow_record: Callable[[dict], None],
        publish_notification: Callable[..., None],
        clear_notification: Callable[[str], None],
        dismiss_notification: Callable[..., dict],
    ) -> None:
        self._working_dir = working_dir
        self._config = config
        self._service = service
        self._chat = chat
        self._session = session
        self._agent_name = agent_name
        self._state = state
        self._idle_event = idle_event
        self._shutdown = shutdown
        self._soul_delay = soul_delay
        self._set_soul_delay = set_soul_delay
        self._soul_timer = soul_timer
        self._set_soul_timer = set_soul_timer
        self._fire_lock = fire_lock
        self._notification_store = notification_store
        self._notification_fingerprint = notification_fingerprint
        self._appendix_ids = appendix_ids
        self._log = log
        self._restart_soul_timer = restart_soul_timer
        self._run_consultation_fire = run_consultation_fire
        self._sync_notifications = sync_notifications
        self._wake_nap = wake_nap
        self._persist_soul_entry = persist_soul_entry
        self._append_soul_flow_record = append_soul_flow_record
        self._publish_notification = publish_notification
        self._clear_notification = clear_notification
        self._dismiss_notification = dismiss_notification

    @property
    def working_dir(self) -> Path:
        return self._working_dir()

    @property
    def config(self) -> Any:
        return self._config()

    @property
    def service(self) -> Any:
        return self._service()

    @property
    def chat(self) -> Any:
        return self._chat()

    @property
    def session(self) -> Any:
        return self._session()

    @property
    def agent_name(self) -> str:
        return self._agent_name()

    @property
    def state(self) -> Any:
        return self._state()

    @property
    def idle_event(self) -> Any:
        return self._idle_event()

    @property
    def shutdown(self) -> Any:
        return self._shutdown()

    @property
    def soul_delay(self) -> float:
        return self._soul_delay()

    @soul_delay.setter
    def soul_delay(self, value: float) -> None:
        self._set_soul_delay(value)

    @property
    def soul_timer(self) -> Any:
        return self._soul_timer()

    @soul_timer.setter
    def soul_timer(self, value: Any) -> None:
        self._set_soul_timer(value)

    @property
    def fire_lock(self) -> Any:
        return self._fire_lock()

    @property
    def notification_store(self) -> Any:
        return self._notification_store()

    @property
    def notification_fingerprint(self) -> Any:
        return self._notification_fingerprint()

    @property
    def appendix_ids_by_source(self) -> dict[str, str]:
        return self._appendix_ids()

    def log(self, event: str, **fields: Any) -> None:
        self._log(event, **fields)

    def restart_soul_timer(self) -> None:
        self._restart_soul_timer()

    def run_consultation_fire(self) -> None:
        self._run_consultation_fire()

    def sync_notifications(self) -> None:
        self._sync_notifications()

    def wake_nap(self, reason: str) -> None:
        self._wake_nap(reason)

    def persist_soul_entry(self, result: dict, mode: str = "flow", source: str = "agent") -> None:
        # Preserve the existing call shape for the default agent-source path;
        # source is an additive override used only by the /btw runner.
        if source == "agent":
            self._persist_soul_entry(result, mode=mode)
        else:
            self._persist_soul_entry(result, mode=mode, source=source)

    def append_soul_flow_record(self, record: dict) -> None:
        self._append_soul_flow_record(record)

    def publish_notification(self, channel: str, **kwargs: Any) -> None:
        self._publish_notification(channel, **kwargs)

    def clear_notification(self, channel: str) -> None:
        self._clear_notification(channel)

    def dismiss_notification(self, channel: str, *, invoked_by: str) -> dict:
        return self._dismiss_notification(channel, invoked_by=invoked_by)


def agent_soul_runtime(agent: Any) -> AgentSoulRuntimeAdapter:
    """Bind Soul's explicit runtime port to one live Agent.

    This is composition-only: each value is a single read closure or bound
    operation. The resulting adapter retains no Agent attribute, and callers
    can reach only its declared SoulRuntimePort vocabulary.
    """
    from lingtai.kernel.notifications import clear, dismiss_channel, submit

    return AgentSoulRuntimeAdapter(
        working_dir=lambda: agent.working_dir if isinstance(getattr(type(agent), "working_dir", None), property) else agent._working_dir,
        config=lambda: getattr(agent, "_config", None),
        service=lambda: getattr(agent, "service", None),
        chat=lambda: getattr(agent, "_chat", None),
        session=lambda: getattr(agent, "_session", None),
        agent_name=lambda: getattr(agent, "agent_name", ""),
        state=lambda: agent.state if isinstance(getattr(type(agent), "state", None), property) else getattr(agent, "_state", None),
        idle_event=lambda: getattr(agent, "_idle", None),
        shutdown=lambda: getattr(agent, "_shutdown", None),
        soul_delay=lambda: getattr(agent, "_soul_delay", 0.0),
        set_soul_delay=lambda value: setattr(agent, "_soul_delay", value),
        soul_timer=lambda: getattr(agent, "_soul_timer", None),
        set_soul_timer=lambda value: setattr(agent, "_soul_timer", value),
        fire_lock=lambda: getattr(agent, "_soul_fire_lock", None),
        notification_store=lambda: getattr(agent, "_notification_store", None),
        notification_fingerprint=lambda: getattr(agent, "_notification_fp", None),
        appendix_ids=lambda: getattr(agent, "_appendix_ids_by_source", {}),
        log=getattr(agent, "_log", lambda *_args, **_kwargs: None),
        restart_soul_timer=getattr(agent, "_start_soul_timer", lambda: None),
        run_consultation_fire=getattr(agent, "_run_consultation_fire", lambda: None),
        sync_notifications=getattr(agent, "_sync_notifications", lambda: None),
        wake_nap=getattr(agent, "_wake_nap", lambda _reason: None),
        persist_soul_entry=getattr(agent, "_persist_soul_entry", lambda *_args, **_kwargs: None),
        append_soul_flow_record=getattr(agent, "_append_soul_flow_record", lambda _record: None),
        publish_notification=lambda channel, **kwargs: submit(agent, channel, **kwargs),
        clear_notification=lambda channel: clear(agent, channel),
        dismiss_notification=lambda channel, *, invoked_by: dismiss_channel(
            agent, channel, invoked_by=invoked_by
        ),
    )


def agent_host_ports(agent: Any, plugin_name: str) -> dict[str, Any]:
    """Build the full grantable port table for *plugin_name* on *agent*.

    Every key is a name in
    :data:`~lingtai.kernel.tool_plugin.GRANTABLE_HOST_PORTS`; the registrar
    grants each declaration only the subset it named in ``requires``.
    """
    return {
        "workdir": AgentWorkdirAdapter(lambda: agent.working_dir),
        "prompt_section": AgentPromptSectionAdapter(
            plugin_name, agent.update_system_prompt
        ),
        "soul_runtime": agent_soul_runtime(agent),
    }


def register_agent_tool_plugins(
    agent: Any,
    declarations: Sequence[ToolPluginDeclaration],
) -> tuple[BoundToolPlugin, ...]:
    """Wire *declarations* onto *agent* through the kernel registrar.

    One declaration per call is the shipped shape today (one family recuts at a
    time). The registrar's name check is batch-wide and runs before the first
    bind, so a **name conflict** is refused as a unit: nothing in the batch
    binds, activates, or mounts. That is the exact scope of the promise — a
    failure raised later, by a binder or by a missing host port on member *N*,
    leaves members 1..*N*-1 mounted and claimed and propagates, because
    unmounting is not a capability this component owns.

    The port table is built per declaration, on demand, because
    :class:`AgentPromptSectionAdapter` is bound to the declaring plugin's own
    section name. The mount seam is deliberately constructed inside this
    registrar call: it accepts only the kernel's one-use declaration/bound
    transaction, never a caller-supplied plugin or token. Claims are observed
    through the public read-only view and changed through BaseAgent's narrow
    internal claim hook.
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
