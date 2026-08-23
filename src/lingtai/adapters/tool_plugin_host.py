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

from functools import partial
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
    "AgentNotificationStateAdapter",
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


class AgentNotificationStateAdapter:
    """Bind Notification Core's real agent-scoped operations to one narrow port.

    The adapter retains callbacks only.  It never exposes the Agent, Store,
    notification fingerprints, or producer state to a plugin.  Each callback
    still enters the existing Core function with the live Agent bound by the
    composition root, so the only implementation of producer guards, stale
    delivery checks, acknowledgement, timer, and hook-manifest state remains
    ``lingtai.kernel.notifications``.
    """

    __slots__ = ("_dismiss", "_delay", "_add", "_drop", "_edit", "_list", "_log")

    def __init__(
        self,
        *,
        dismiss: Callable[..., dict[str, Any]],
        delay: Callable[[str, int], dict[str, Any]],
        add_hook: Callable[[dict[str, Any]], dict[str, Any]],
        drop_hook: Callable[[str], dict[str, Any]],
        edit_hook: Callable[[str, dict[str, Any]], dict[str, Any]],
        list_hooks: Callable[[], list[dict[str, Any]] | dict[str, Any]],
        log: Callable[..., None],
    ) -> None:
        self._dismiss = dismiss
        self._delay = delay
        self._add = add_hook
        self._drop = drop_hook
        self._edit = edit_hook
        self._list = list_hooks
        self._log = log

    def dismiss(
        self,
        channel: str,
        *,
        force: bool,
        reason: str | None,
        event_id: str | None = None,
        ref_id: str | None = None,
    ) -> dict[str, Any]:
        return self._dismiss(
            channel,
            force=force,
            reason=reason,
            event_id=event_id,
            ref_id=ref_id,
        )

    def delay(self, channel: str, seconds: int) -> dict[str, Any]:
        return self._delay(channel, seconds)

    def add_hook(self, manifest: dict[str, Any]) -> dict[str, Any]:
        return self._add(manifest)

    def drop_hook(self, name: str) -> dict[str, Any]:
        return self._drop(name)

    def edit_hook(self, name: str, fields: dict[str, Any]) -> dict[str, Any]:
        return self._edit(name, fields)

    def list_hooks(self) -> list[dict[str, Any]] | dict[str, Any]:
        return self._list()

    def log(self, event_type: str, **fields: Any) -> None:
        self._log(event_type, **fields)


def agent_host_ports(agent: Any, plugin_name: str) -> dict[str, Any]:
    """Build the full grantable port table for *plugin_name* on *agent*.

    Every key is a name in
    :data:`~lingtai.kernel.tool_plugin.GRANTABLE_HOST_PORTS`; the registrar
    grants each declaration only the subset it named in ``requires``.
    """
    # Import Core lazily at the Composition Root boundary.  The kernel owns the
    # notification policy; this adapter binds that policy to the current Agent
    # without making either the Core package or the plugin depend on tools.
    from lingtai.kernel.notifications import (
        add_hook,
        delay_notification_channel,
        dismiss_channel,
        drop_hook,
        edit_hook,
        list_hooks,
    )

    def _read_workdir() -> Path:
        # Production Agents expose ``working_dir``; the private fallback keeps
        # this same generic seam usable by the narrow state-only test doubles.
        candidate = getattr(agent, "working_dir", None)
        if isinstance(candidate, (str, Path)):
            return Path(candidate)
        return Path(agent._working_dir)

    update_system_prompt = getattr(agent, "update_system_prompt", None)
    if not callable(update_system_prompt):
        # Narrow direct tests may provide only the ports a declaration needs;
        # the registrar grants from this complete table but never exposes an
        # unrequested port.  Keep the unused prompt adapter inert rather than
        # making a Notification state-port test double impersonate an Agent.
        update_system_prompt = lambda *_args, **_kwargs: None

    return {
        "workdir": AgentWorkdirAdapter(_read_workdir),
        "prompt_section": AgentPromptSectionAdapter(
            plugin_name, update_system_prompt
        ),
        "notification_state": AgentNotificationStateAdapter(
            dismiss=partial(dismiss_channel, agent, invoked_by="notification"),
            delay=partial(delay_notification_channel, agent),
            add_hook=partial(add_hook, agent),
            drop_hook=partial(drop_hook, agent),
            edit_hook=partial(edit_hook, agent),
            list_hooks=partial(list_hooks, agent),
            log=agent._log,
        ),
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
