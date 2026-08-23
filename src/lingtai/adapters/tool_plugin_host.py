"""Production adapters translating the live Agent body into host plugin ports.

`lingtai.kernel.tool_plugin` owns the Ports; this module is the one production
Adapter set that satisfies them for a running ``BaseAgent``, and it lives
outside the kernel package so the dependency still points inward
(``Adapter -> Port <- Core``, root ``CONTRACT.md`` rules 2-3).

Each Agent-derived adapter is constructed from one narrow callable — a bound
method of the agent, or a single-expression read closure — never from the agent
object. ``StaticRuntimeAdapter`` is narrower still: its value comes explicitly
from capability setup and contains no Agent reference. Deep reachability through
a bound method's ``__self__`` or a closure cell is not prevented and is not
claimed to be — the promise the contract makes is about the declared argument
surface handed to a plugin.

Which declarations get registered, and when, stays in the Composition Root
(``src/lingtai/agent.py`` and the capability ``setup()`` it drives). This module
only builds the ports.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from lingtai.kernel.tool_plugin import (
    BoundToolPlugin,
    ToolPluginDeclaration,
    register_official_tool_plugins,
)

__all__ = [
    "AgentWorkdirAdapter",
    "StaticRuntimeAdapter",
    "AgentProviderIdentityAdapter",
    "AgentPromptSectionAdapter",
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


class StaticRuntimeAdapter:
    """A :class:`~lingtai.kernel.tool_plugin.RuntimePort` over one supplied value.

    The value comes from the capability Composition Root, not from the Agent.
    It lets a static declaration bind per-agent search/browser wiring without a
    closure over, or a back-reference to, the live Agent body.
    """

    __slots__ = ("_value",)

    def __init__(self, value: Any) -> None:
        self._value = value

    @property
    def value(self) -> Any:
        return self._value


class AgentProviderIdentityAdapter:
    """A bounded provider-label view over the Agent's current service."""

    __slots__ = ("_read",)

    def __init__(self, read: Callable[[], Any]) -> None:
        self._read = read

    @property
    def provider(self) -> str | None:
        value = self._read()
        return value if isinstance(value, str) else None


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


_MISSING_RUNTIME = object()


def agent_host_ports(
    agent: Any,
    plugin_name: str,
    *,
    runtime: Any = _MISSING_RUNTIME,
) -> dict[str, Any]:
    """Build the full grantable port table for *plugin_name* on *agent*.

    Every key is a name in
    :data:`~lingtai.kernel.tool_plugin.GRANTABLE_HOST_PORTS`; the registrar
    grants each declaration only the subset it named in ``requires``. ``runtime``
    is deliberately caller-supplied rather than read from the Agent: it is the
    exact setup-time value a static declaration needs for one bind.
    """
    ports = {
        "workdir": AgentWorkdirAdapter(lambda: agent.working_dir),
        "provider_identity": AgentProviderIdentityAdapter(
            lambda: getattr(getattr(agent, "service", None), "provider", None)
        ),
        "prompt_section": AgentPromptSectionAdapter(
            plugin_name, agent.update_system_prompt
        ),
    }
    if runtime is not _MISSING_RUNTIME:
        ports["runtime"] = StaticRuntimeAdapter(runtime)
    return ports


def register_agent_tool_plugins(
    agent: Any,
    declarations: Sequence[ToolPluginDeclaration],
    *,
    runtimes: Mapping[str, Any] | None = None,
) -> tuple[BoundToolPlugin, ...]:
    """Wire *declarations* onto *agent* through the kernel registrar.

    One declaration per call is the shipped shape today (one family recuts at a
    time). The registrar's name check is batch-wide and runs before the first
    bind, so a **name conflict** is refused as a unit: nothing in the batch
    binds, activates, or mounts. That is the exact scope of the promise — a
    failure raised later, by a binder or by a missing host port on member *N*,
    leaves members 1..*N*-1 mounted and claimed and propagates, because
    unmounting is not a capability this component owns.

    ``runtimes`` is an explicit declaration-name to setup-value mapping. It
    exists so a static declaration can bind its per-agent dependencies without
    ever receiving the Agent; only a declaration that actually requires the
    ``runtime`` port receives the corresponding value. The port table is built
    per declaration because ``AgentPromptSectionAdapter`` is bound to the
    declaring plugin's own section name. The mount seam is deliberately
    constructed inside this registrar call: it accepts only the kernel's one-use
    declaration/bound transaction, never a caller-supplied plugin or token.
    Claims are observed through the public read-only view and changed through
    BaseAgent's narrow internal claim hook.
    """
    runtime_by_name = dict(runtimes or {})

    class _InternalMount:
        def mount_tool(self, transaction) -> None:
            agent._mount_official_tool(transaction)

    return register_official_tool_plugins(
        list(declarations),
        ports_for=lambda declaration: agent_host_ports(
            agent,
            declaration.name,
            runtime=runtime_by_name.get(declaration.name, _MISSING_RUNTIME),
        ),
        mount=_InternalMount(),
        claimed=agent.official_tool_plugins,
        claim=agent._claim_official_tool,
        authorize=agent._authorize_official_tool_declaration,
        record_bound=agent._record_official_tool_binding,
    )
