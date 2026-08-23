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
    "AgentSystemRuntimeAdapter",
    "AgentIdentityAdapter",
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


class AgentSystemRuntimeAdapter:
    """SystemRuntimePort composed from narrow Agent callbacks, never an Agent."""

    __slots__ = (
        "_admin", "_language", "_log", "_token_usage", "_load_preset",
        "_activate_preset", "_activate_default_preset", "_retry_failed_mcps",
        "_perform_refresh", "_resuscitate", "_sleep",
    )

    def __init__(
        self,
        *,
        admin: Callable[[], Mapping[str, Any]],
        language: Callable[[], str],
        log: Callable[..., None],
        token_usage: Callable[[], Mapping[str, Any]],
        load_preset: Callable[[str], dict],
        activate_preset: Callable[[str], None],
        activate_default_preset: Callable[[], None],
        retry_failed_mcps: Callable[[], Mapping[str, Any]],
        perform_refresh: Callable[[], None],
        resuscitate: Callable[[str], Any],
        sleep: Callable[[str, bool], dict],
    ) -> None:
        self._admin = admin
        self._language = language
        self._log = log
        self._token_usage = token_usage
        self._load_preset = load_preset
        self._activate_preset = activate_preset
        self._activate_default_preset = activate_default_preset
        self._retry_failed_mcps = retry_failed_mcps
        self._perform_refresh = perform_refresh
        self._resuscitate = resuscitate
        self._sleep = sleep

    @property
    def admin(self) -> Mapping[str, Any]:
        return MappingProxyType(dict(self._admin() or {}))

    @property
    def language(self) -> str:
        return self._language()

    def log(self, event: str, **fields: Any) -> None:
        self._log(event, **fields)

    def token_usage(self) -> Mapping[str, Any]:
        return self._token_usage()

    def load_preset(self, name: str) -> dict:
        return self._load_preset(name)

    def activate_preset(self, name: str) -> None:
        self._activate_preset(name)

    def activate_default_preset(self) -> None:
        self._activate_default_preset()

    def retry_failed_mcps(self) -> Mapping[str, Any]:
        return self._retry_failed_mcps()

    def perform_refresh(self) -> None:
        self._perform_refresh()

    def resuscitate(self, address: str) -> Any:
        return self._resuscitate(address)

    def sleep(self, reason: str, *, force: bool) -> dict:
        return self._sleep(reason, force)


class AgentIdentityAdapter:
    """IdentityPort over exactly the System naming surface."""

    __slots__ = ("_name", "_set_name", "_set_nickname")

    def __init__(
        self,
        name: Callable[[], str | None],
        set_name: Callable[[str], None],
        set_nickname: Callable[[str], None],
    ) -> None:
        self._name = name
        self._set_name = set_name
        self._set_nickname = set_nickname

    @property
    def name(self) -> str | None:
        return self._name()

    def set_name(self, name: str) -> None:
        self._set_name(name)

    def set_nickname(self, nickname: str) -> None:
        self._set_nickname(nickname)


def _sleep_agent(agent: Any, reason: str, force: bool) -> dict:
    """Adapt System's self-sleep to the live Agent without exposing it."""
    from lingtai.kernel.i18n import t
    from lingtai.kernel.notifications import _workdir_key, attention_fingerprint, is_channel_allowed
    from lingtai.kernel.state import AgentState

    pending_fp = attention_fingerprint(
        agent._notification_store,
        lambda ch: is_channel_allowed(ch, workdir=_workdir_key(agent)),
        _workdir_key(agent),
    )
    has_pending = pending_fp != agent._notification_fp
    if has_pending and not force:
        agent._log(
            "sleep_refused_pending_notifications", reason=reason,
            pending_fp=list(pending_fp), committed_fp=list(agent._notification_fp or ()),
        )
        return {"status": "ok", "message": t(
            agent._config.language, "system_tool.sleep_refused_pending_notifications",
        )}
    if has_pending:
        agent._log("sleep_forced_with_pending_notifications", reason=reason, pending_fp=list(pending_fp))
    agent._log("self_sleep", reason=reason)
    agent._set_state(AgentState.ASLEEP, reason="self-sleep")
    agent._asleep.set()
    agent._cancel_event.set()
    return {"status": "ok", "message": t(agent._config.language, "system_tool.sleep_message")}


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
        "system_runtime": AgentSystemRuntimeAdapter(
            admin=lambda: agent._admin,
            language=lambda: agent._config.language,
            log=agent._log,
            token_usage=agent.get_token_usage,
            load_preset=agent.load_preset,
            activate_preset=agent._activate_preset,
            activate_default_preset=agent._activate_default_preset,
            retry_failed_mcps=lambda: getattr(agent, "_retry_failed_mcps", lambda: {})(),
            perform_refresh=agent._perform_refresh,
            resuscitate=agent._cpr_agent,
            sleep=lambda reason, force: _sleep_agent(agent, reason, force),
        ),
        "identity": AgentIdentityAdapter(
            lambda: agent.agent_name, agent.set_name, agent.set_nickname
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
