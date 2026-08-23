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
    "AgentFileIOAdapter",
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


class AgentFileIOAdapter:
    """``FileIOPort`` assembled from just File's consumed host callables.

    The adapter deliberately owns no Agent and never publishes the backing
    ``FileIOService``.  It receives individual service methods, two read-only
    facts, and forwards only the vocabulary that the declared ``file`` family
    consumes.  The workdir remains a separate port, so this is not an ambient
    filesystem/Agent escape hatch.
    """

    __slots__ = (
        "_read",
        "_write",
        "_glob",
        "_grep",
        "_last_traversal",
        "_max_result_chars",
    )

    def __init__(
        self,
        read: Callable[[str], str],
        write: Callable[[str, str], None],
        glob: Callable[..., list[str]],
        grep: Callable[..., list[Any]],
        last_traversal: Callable[[], Any | None],
        max_result_chars: Callable[[], int | None],
    ) -> None:
        self._read = read
        self._write = write
        self._glob = glob
        self._grep = grep
        self._last_traversal = last_traversal
        self._max_result_chars = max_result_chars

    def read(self, path: str) -> str:
        return self._read(path)

    def write(self, path: str, content: str) -> None:
        self._write(path, content)

    def glob(self, pattern: str, root: str | None = None) -> list[str]:
        return self._glob(pattern, root=root)

    def grep(
        self,
        pattern: str,
        path: str | None = None,
        max_results: int = 50,
        *,
        glob_filter: str | None = None,
    ) -> list[Any]:
        return self._grep(
            pattern,
            path=path,
            max_results=max_results,
            glob_filter=glob_filter,
        )

    @property
    def last_traversal(self) -> Any | None:
        return self._last_traversal()

    @property
    def max_result_chars(self) -> int | None:
        return self._max_result_chars()


def agent_host_ports(agent: Any, plugin_name: str) -> dict[str, Any]:
    """Build the full grantable port table for *plugin_name* on *agent*.

    Every key is a name in
    :data:`~lingtai.kernel.tool_plugin.GRANTABLE_HOST_PORTS`; the registrar
    grants each declaration only the subset it named in ``requires``.
    """
    file_io = agent._file_io
    return {
        "workdir": AgentWorkdirAdapter(lambda: agent.working_dir),
        "prompt_section": AgentPromptSectionAdapter(
            plugin_name, agent.update_system_prompt
        ),
        "file_io": AgentFileIOAdapter(
            file_io.read,
            file_io.write,
            file_io.glob,
            file_io.grep,
            lambda: getattr(file_io, "last_traversal", None),
            lambda: getattr(getattr(agent, "_executor", None), "_max_result_chars", None),
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
