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
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

from lingtai.kernel.tool_plugin import (
    BoundToolPlugin,
    ToolPluginDeclaration,
    register_official_tool_plugins,
)

__all__ = [
    "AgentWorkdirAdapter",
    "AgentPromptSectionAdapter",
    "AgentNotificationAdapter",
    "StaticConfigurationAdapter",
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


class AgentNotificationAdapter:
    """The narrow durable-notification port over one live Agent's store.

    Constructed from the canonical system-event method plus a store reader,
    rather than from an Agent object.  Its system-event fallback and latest
    channel publication deliberately preserve the pre-plugin Shell manager's
    compare-and-update semantics; the Shell family sees only these two typed
    operations and cannot reach any other Agent API.
    """

    __slots__ = ("_enqueue", "_store")

    def __init__(
        self,
        enqueue: Callable[..., Any],
        store: Callable[[], Any],
    ) -> None:
        self._enqueue = enqueue
        self._store = store

    def publish_system(
        self,
        *,
        source: str,
        ref_id: str,
        body: str,
        skip_if_ref_id_exists: bool = False,
    ) -> bool:
        try:
            self._enqueue(
                source=source,
                ref_id=ref_id,
                body=body,
                skip_if_ref_id_exists=skip_if_ref_id_exists,
            )
            # The historical Shell path considers a duplicate-suppressed event
            # a successful idempotent publication too.
            return True
        except Exception:
            pass
        try:
            import secrets
            import time
            from datetime import datetime, timezone

            from lingtai.kernel.notification_store import UNCONDITIONAL

            store = self._store()
            event_id = f"evt_{int(time.time()*1000):x}_{secrets.token_hex(8)}"
            received_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            def mutate(current_payload: dict) -> tuple[dict | None, bool, str]:
                current = current_payload if isinstance(current_payload, dict) else {}
                events = list(current.get("data", {}).get("events", []))
                if skip_if_ref_id_exists and any(
                    isinstance(event, dict) and event.get("ref_id") == ref_id
                    for event in events
                ):
                    return current_payload, False, ""
                events.append({
                    "event_id": event_id,
                    "source": source,
                    "ref_id": ref_id,
                    "body": body,
                    "at": received_at,
                })
                events = events[-20:]
                return ({
                    "header": f"{len(events)} system notification{'s' if len(events) != 1 else ''}",
                    "icon": "🔔",
                    "priority": "normal",
                    "published_at": received_at,
                    "data": {"events": events},
                }, True, event_id)

            store.compare_update_channel("system", UNCONDITIONAL, mutate)
            return True
        except Exception:
            return False

    def publish_channel(
        self,
        channel: str,
        payload: Mapping[str, Any],
        *,
        ref_id: str,
    ) -> bool:
        try:
            store = self._store()
            if hasattr(store, "compare_update_channel"):
                from lingtai.kernel.notification_store import UNCONDITIONAL

                def mutate(current_payload: dict) -> tuple[dict | None, bool, bool]:
                    current = current_payload if isinstance(current_payload, dict) else {}
                    data = current.get("data")
                    if isinstance(data, dict) and data.get("ref_id") == ref_id:
                        return current_payload, False, True
                    return dict(payload), True, True

                result = store.compare_update_channel(channel, UNCONDITIONAL, mutate)
                return bool(result.value)
            store.publish(channel, dict(payload))
            return True
        except Exception:
            return False


class StaticConfigurationAdapter:
    """Immutable, setup-selected values for one declared plugin binding."""

    __slots__ = ("_values",)

    def __init__(self, values: Mapping[str, Any] | None = None) -> None:
        self._values = MappingProxyType(dict(values or {}))

    @property
    def values(self) -> Mapping[str, Any]:
        return self._values


def agent_host_ports(
    agent: Any,
    plugin_name: str,
    *,
    configuration: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
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
        "notifications": AgentNotificationAdapter(
            agent._enqueue_system_notification,
            lambda: agent._notification_store,
        ),
        "configuration": StaticConfigurationAdapter(configuration),
    }


def register_agent_tool_plugins(
    agent: Any,
    declarations: Sequence[ToolPluginDeclaration],
    *,
    configuration: Mapping[str, Any] | None = None,
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
        ports_for=lambda declaration: agent_host_ports(
            agent, declaration.name, configuration=configuration,
        ),
        mount=_InternalMount(),
        claimed=agent.official_tool_plugins,
        claim=agent._claim_official_tool,
        authorize=agent._authorize_official_tool_declaration,
        record_bound=agent._record_official_tool_binding,
    )
