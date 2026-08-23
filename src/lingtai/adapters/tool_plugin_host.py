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
from typing import Any, Callable, Mapping, Sequence

from lingtai.kernel.tool_plugin import (
    BoundToolPlugin,
    ToolPluginDeclaration,
    register_official_tool_plugins,
)

__all__ = [
    "AgentWorkdirAdapter",
    "AgentPromptSectionAdapter",
    "AgentContextRuntimeAdapter",
    "AgentAvatarParentAdapter",
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


class AgentContextRuntimeAdapter:
    """``ContextRuntimePort`` over three bound Context operations.

    It stores only its narrow callbacks, never the Agent. The Context
    composition root supplies callbacks that retain the established live molt,
    summary, and reconstruction engines; the declared family receives only these
    three capability-native methods.
    """

    __slots__ = ("_molt", "_summarize", "_rebuild")

    def __init__(
        self,
        *,
        molt: Callable[[dict], dict],
        summarize: Callable[[dict], dict],
        rebuild: Callable[[dict], dict],
    ) -> None:
        self._molt = molt
        self._summarize = summarize
        self._rebuild = rebuild

    def molt(self, args: dict) -> dict:
        return self._molt(args)

    def summarize(self, args: dict) -> dict:
        return self._summarize(args)

    def rebuild(self, args: dict) -> dict:
        return self._rebuild(args)


class AgentAvatarParentAdapter:
    """Avatar's narrow parent-context port over the live Agent.

    The adapter exposes only the three current-Agent facts Avatar already uses:
    parent identity for the first prompt, an optional venv inheritance value,
    and the existing any-admin-value rule gate.  It owns no Agent object; each
    value is read through its one narrow closure when Avatar asks for it.
    """

    __slots__ = ("_parent_name", "_venv_path", "_has_rule_privilege")

    def __init__(
        self,
        parent_name: Callable[[], str],
        venv_path: Callable[[], str | None],
        has_rule_privilege: Callable[[], bool],
    ) -> None:
        self._parent_name = parent_name
        self._venv_path = venv_path
        self._has_rule_privilege = has_rule_privilege

    @property
    def parent_name(self) -> str:
        return self._parent_name()

    @property
    def venv_path(self) -> str | None:
        return self._venv_path()

    def has_rule_privilege(self) -> bool:
        return self._has_rule_privilege()


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
        "avatar_parent": AgentAvatarParentAdapter(
            lambda: agent.agent_name or agent.working_dir.name,
            lambda: getattr(agent, "_venv_path", None),
            lambda: any((getattr(agent, "_admin", {}) or {}).values()),
        ),
    }


def register_agent_tool_plugins(
    agent: Any,
    declarations: Sequence[ToolPluginDeclaration],
    *,
    extra_ports: Mapping[str, Any] | None = None,
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
        ports_for=lambda declaration: {
            **agent_host_ports(agent, declaration.name),
            **dict(extra_ports or {}),
        },
        mount=_InternalMount(),
        claimed=agent.official_tool_plugins,
        claim=agent._claim_official_tool,
        authorize=agent._authorize_official_tool_declaration,
        record_bound=agent._record_official_tool_binding,
    )
