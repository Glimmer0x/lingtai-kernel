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

from copy import deepcopy
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable, Sequence

from lingtai.kernel.tool_plugin import (
    BoundToolPlugin,
    PluginCatalogState,
    ToolPluginDeclaration,
    register_official_tool_plugins,
)

__all__ = [
    "AgentWorkdirAdapter",
    "AgentPromptSectionAdapter",
    "AgentPluginCatalogAdapter",
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


class AgentPluginCatalogAdapter:
    """Read-only :class:`PluginCatalogPort` over the current Agent state.

    It holds only two narrow readers rather than an ``Agent``.  Each read creates
    a detached value projection: mutating a tool result cannot alter the Agent's
    registration snapshot or capability configuration, and the adapter grants no
    registration, prune, launch, or prompt operation.
    """

    __slots__ = ("_read_registration", "_read_capabilities")

    def __init__(
        self,
        read_registration: Callable[[], Any],
        read_capabilities: Callable[[], Any],
    ) -> None:
        self._read_registration = read_registration
        self._read_capabilities = read_capabilities

    def read_state(self) -> PluginCatalogState:
        registration = self._read_registration()
        snapshot = deepcopy(dict(registration)) if isinstance(registration, Mapping) else {}

        configured_paths: tuple[str, ...] = ()
        skill_paths: tuple[str, ...] = ()
        skills_enabled = False
        capabilities = self._read_capabilities()
        if isinstance(capabilities, (list, tuple)):
            for item in capabilities:
                if not isinstance(item, tuple) or len(item) != 2:
                    continue
                name, kwargs = item
                if name == "skills":
                    skills_enabled = True
                    if isinstance(kwargs, Mapping):
                        raw_paths = kwargs.get("paths", [])
                        if isinstance(raw_paths, (list, tuple)):
                            skill_paths = tuple(
                                path for path in raw_paths if isinstance(path, str)
                            )
                elif name == "plugin" and isinstance(kwargs, Mapping):
                    raw_paths = kwargs.get("paths", [])
                    if isinstance(raw_paths, (list, tuple)):
                        configured_paths = tuple(
                            path for path in raw_paths if isinstance(path, str)
                        )
        return PluginCatalogState(
            registration=snapshot,
            configured_paths=configured_paths,
            skill_paths=skill_paths,
            skills_enabled=skills_enabled,
        )


def agent_host_ports(agent: Any, plugin_name: str) -> dict[str, Any]:
    """Build the full grantable port table for *plugin_name* on *agent*.

    Every key is a name in
    :data:`~lingtai.kernel.tool_plugin.GRANTABLE_HOST_PORTS`; the registrar
    grants each declaration only the subset it named in ``requires``. The
    catalog adapter is a read-only value projection, so its presence in this
    full table gives no capability to a declaration that did not require it.
    """
    return {
        "workdir": AgentWorkdirAdapter(lambda: agent.working_dir),
        "prompt_section": AgentPromptSectionAdapter(
            plugin_name, agent.update_system_prompt
        ),
        "plugin_catalog": AgentPluginCatalogAdapter(
            lambda: getattr(agent, "_plugin_registration", {}),
            lambda: getattr(agent, "_capabilities", ()),
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
