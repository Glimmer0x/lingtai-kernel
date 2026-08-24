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
from functools import partial
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Callable, Mapping, Protocol, Sequence

from lingtai.kernel.llm.base import FunctionSchema
from lingtai.kernel.time_veil import now_iso as render_now_iso

if TYPE_CHECKING:
    from lingtai.tools.email import EmailResult, EmailRuntimeRequest

from lingtai.kernel.tool_plugin import (
    BoundToolPlugin,
    FileGrepMatch,
    FileTraversalStats,
    PluginCatalogState,
    ToolPluginDeclaration,
    register_official_tool_plugins,
)

__all__ = [
    "AgentWorkdirAdapter",
    "AgentPromptSectionAdapter",
    "AgentFileIOAdapter",
    "AgentContextRuntimeAdapter",
    "AgentAvatarParentAdapter",
    "AgentDaemonRuntimeAdapter",
    "AgentEmailRuntimeAdapter",
    "AgentPluginCatalogAdapter",
    "AgentNotificationStateAdapter",
    "agent_host_ports",
    "daemon_runtime_for_agent",
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


class _FileGlobOperation(Protocol):
    def __call__(self, pattern: str, root: str | None = None) -> list[str]: ...


class _FileGrepOperation(Protocol):
    def __call__(
        self,
        pattern: str,
        path: str | None = None,
        max_results: int = 50,
        *,
        glob_filter: str | None = None,
    ) -> list[FileGrepMatch]: ...


class AgentFileIOAdapter:
    """``FileIOPort`` assembled from only File's consumed host callables.

    The adapter owns no Agent, has no generic forwarding or dispatch operation,
    and never publishes the backing FileIOService. It receives individual
    service methods plus two read-only fact readers and forwards only the exact
    vocabulary the declared ``file`` family consumes. Workdir remains a separate
    port, and model-facing mounting remains registrar-only.
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
        *,
        read: Callable[[str], str],
        write: Callable[[str, str], None],
        glob: _FileGlobOperation,
        grep: _FileGrepOperation,
        last_traversal: Callable[[], FileTraversalStats | None],
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
    ) -> list[FileGrepMatch]:
        return self._grep(
            pattern,
            path=path,
            max_results=max_results,
            glob_filter=glob_filter,
        )

    @property
    def last_traversal(self) -> FileTraversalStats | None:
        return self._last_traversal()

    @property
    def max_result_chars(self) -> int | None:
        return self._max_result_chars()


class AgentNotificationStateAdapter:
    """Bind Notification Core's real agent-scoped operations to one narrow port.

    The adapter retains callbacks only. It never exposes the Agent, Store,
    notification fingerprints, or producer state to a plugin. Each callback
    still enters the existing Core function with the live Agent bound by the
    composition root, so producer guards, stale-delivery checks,
    acknowledgement, timers, hook manifests, and Store semantics remain in
    :mod:`lingtai.kernel.notifications`.
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



class AgentEmailRuntimeAdapter:
    """Email's narrow live-manager port over one call-time reader.

    The adapter owns no Agent and never dispatches through an intrinsic or an
    official tool handler.  It validates the Email-owned action set before it
    reads the current manager, then invokes that manager exactly once with the
    legacy flat payload it already owns.  The read callback is deliberately
    evaluated per request so refresh or reconstruction can replace the manager
    without leaving an already-bound declared family stale.
    """

    __slots__ = ("_read_manager",)

    def __init__(self, read_manager: Callable[[], Any]) -> None:
        self._read_manager = read_manager

    def handle_email(self, request: "EmailRuntimeRequest") -> "EmailResult":
        # Keep the action source of truth in Email's static declaration without
        # adding a family import edge at host-module import time.
        from lingtai.tools.email import DECLARATION as EMAIL_DECLARATION

        if request.action not in EMAIL_DECLARATION.actions:
            raise ValueError(f"unsupported Email runtime action: {request.action!r}")
        manager = self._read_manager()
        if manager is None:
            return {"error": "Internal: email manager not initialized. boot() was not called."}
        return manager.handle({"action": request.action, **dict(request.input)})


class _DaemonPresetToolCollector:
    """Host-private sandbox used by one daemon preset capability setup.

    It is created only inside the adapter's one ``setup_preset_capability``
    operation.  Daemon receives the resulting schema/handler dictionaries, not
    this collector and not the Agent it forwards to for established capability
    setup compatibility.
    """

    def __init__(self, agent: Any) -> None:
        self._agent = agent
        self.schemas: dict[str, FunctionSchema] = {}
        self.handlers: dict[str, Callable[[dict], dict]] = {}
        self._official_tool_plugins: dict[str, Any] = {}
        self._official_tool_declarations: dict[str, Any] = {}
        self._official_tool_bindings: dict[str, Any] = {}

    @property
    def official_tool_plugins(self):
        return MappingProxyType(self._official_tool_plugins)

    def _authorize_official_tool_declaration(self, declaration) -> None:
        from lingtai.kernel.base_agent import BaseAgent

        BaseAgent._authorize_official_tool_declaration(self, declaration)

    def _record_official_tool_binding(self, declaration, plugin) -> None:
        from lingtai.kernel.base_agent import BaseAgent

        BaseAgent._record_official_tool_binding(self, declaration, plugin)

    def _claim_official_tool(self, transaction) -> None:
        from lingtai.kernel.base_agent import BaseAgent

        BaseAgent._claim_official_tool(self, transaction)

    def _mount_official_tool(self, transaction) -> None:
        from lingtai.kernel.tool_plugin import (
            OFFICIAL_TOOL_PLUGIN_NAMES,
            _OfficialMountTransaction,
        )

        if not isinstance(transaction, _OfficialMountTransaction):
            raise PermissionError(
                "official tool mounting requires a registrar transaction"
            )
        declaration = transaction.declaration
        plugin = transaction.plugin
        name = declaration.name
        if (
            name not in OFFICIAL_TOOL_PLUGIN_NAMES
            or plugin.name != name
            or self._official_tool_declarations.get(name) is not declaration
            or self._official_tool_bindings.get(name) is not plugin
        ):
            raise PermissionError(
                "official mount transaction is not the canonical declaration/bind result"
            )
        live = self._official_tool_plugins.get(name)
        if live is not None and live is not declaration:
            raise PermissionError("official mount transaction is not for the live claim")
        transaction.consume()
        self.add_tool(
            name,
            schema=dict(plugin.schema),
            handler=plugin.handler,
            description=plugin.description,
            glossary_package=plugin.glossary_package,
        )
        transaction.mark_mounted(self)

    def add_tool(
        self,
        name: str,
        *,
        schema: dict | None = None,
        handler: Callable[[dict], dict] | None = None,
        description: str = "",
        system_prompt: str = "",
        glossary_package: str | None = None,
    ) -> None:
        if handler is not None:
            self.handlers[name] = handler
        if schema is not None:
            self.schemas[name] = FunctionSchema(
                name=name,
                description=description,
                parameters=schema,
                system_prompt=system_prompt,
                glossary_package=glossary_package,
            )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._agent, name)


class AgentDaemonRuntimeAdapter:
    """``DaemonRuntimePort`` assembled from narrow Agent operation closures.

    The port is intentionally Daemon-specific: it exposes exactly the parent
    facts Daemon's existing manager consumes (model/service, regular tool
    surface, preset sandbox/load operations, notifications, logging, and
    resolved manager construction options).  It has no generic attribute
    forwarding and no model-facing mount operation.
    """

    __slots__ = (
        "_read_service",
        "_read_schemas",
        "_read_handlers",
        "_read_mcp_names",
        "_read_language",
        "_read_max_aed_attempts",
        "_read_tool_call_guard",
        "_manager_options",
        "_setup_preset_capability",
        "_read_preset",
        "_load_preset",
        "_enqueue_notification",
        "_read_task_card_watch",
        "_now_iso",
        "_log",
        "_manager",
    )

    def __init__(
        self,
        *,
        read_service: Callable[[], Any],
        read_schemas: Callable[[], tuple[Any, ...]],
        read_handlers: Callable[[], Mapping[str, Callable[[dict], dict]]],
        read_mcp_names: Callable[[], frozenset[str]],
        read_language: Callable[[], str],
        read_max_aed_attempts: Callable[[], int],
        read_tool_call_guard: Callable[[], Any],
        manager_options: Mapping[str, Any],
        setup_preset_capability: Callable[[str, Mapping[str, Any]], tuple[dict[str, Any], dict[str, Callable[[dict], dict]]]],
        read_preset: Callable[[], Mapping[str, Any]],
        load_preset: Callable[[str], dict],
        enqueue_notification: Callable[..., None],
        read_task_card_watch: Callable[[], bool],
        now_iso: Callable[[], str],
        log: Callable[..., None],
    ) -> None:
        self._read_service = read_service
        self._read_schemas = read_schemas
        self._read_handlers = read_handlers
        self._read_mcp_names = read_mcp_names
        self._read_language = read_language
        self._read_max_aed_attempts = read_max_aed_attempts
        self._read_tool_call_guard = read_tool_call_guard
        self._manager_options = dict(manager_options)
        self._setup_preset_capability = setup_preset_capability
        self._read_preset = read_preset
        self._load_preset = load_preset
        self._enqueue_notification = enqueue_notification
        self._read_task_card_watch = read_task_card_watch
        self._now_iso = now_iso
        self._log = log
        self._manager: Any = None

    @property
    def service(self) -> Any:
        return self._read_service()

    @property
    def tool_schemas(self) -> tuple[Any, ...]:
        return self._read_schemas()

    @property
    def tool_handlers(self) -> Mapping[str, Callable[[dict], dict]]:
        return self._read_handlers()

    @property
    def mcp_tool_names(self) -> frozenset[str]:
        return self._read_mcp_names()

    @property
    def language(self) -> str:
        return self._read_language()

    @property
    def max_aed_attempts(self) -> int:
        return self._read_max_aed_attempts()

    @property
    def tool_call_guard(self) -> Any:
        return self._read_tool_call_guard()

    @property
    def manager_options(self) -> Mapping[str, Any]:
        return dict(self._manager_options)

    def setup_preset_capability(
        self, name: str, kwargs: Mapping[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Callable[[dict], dict]]]:
        return self._setup_preset_capability(name, kwargs)

    def read_preset_from_init(self) -> Mapping[str, Any]:
        return self._read_preset()

    def load_preset(self, name: str) -> dict:
        return self._load_preset(name)

    def enqueue_daemon_notification(
        self,
        *,
        source: str,
        ref_id: str,
        body: str,
        idempotency_key: str | None,
        skip_if_idempotency_key_exists: bool,
        extra: Mapping[str, Any],
        channel: str,
    ) -> None:
        self._enqueue_notification(
            source=source,
            ref_id=ref_id,
            body=body,
            idempotency_key=idempotency_key,
            skip_if_idempotency_key_exists=skip_if_idempotency_key_exists,
            extra=dict(extra),
            channel=channel,
        )

    def has_active_task_card_watch(self) -> bool:
        return self._read_task_card_watch()

    def attach_daemon_manager(self, manager: Any) -> None:
        self._manager = manager

    def now_iso(self) -> str:
        return self._now_iso()

    @property
    def daemon_manager(self) -> Any:
        return self._manager

    def log(self, event_type: str, **fields: Any) -> None:
        self._log(event_type, **fields)


def daemon_runtime_for_agent(
    agent: Any, manager_options: Mapping[str, Any]
) -> AgentDaemonRuntimeAdapter:
    """Build Daemon's adapter from the current Agent's narrow operations."""

    def _setup_preset_capability(
        name: str, kwargs: Mapping[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Callable[[dict], dict]]]:
        from lingtai.tools.registry import setup_capability

        collector = _DaemonPresetToolCollector(agent)
        setup_capability(collector, name, **dict(kwargs))
        return collector.schemas, collector.handlers

    def _read_language() -> str:
        value = getattr(getattr(agent, "_config", None), "language", "en")
        return value if isinstance(value, str) else "en"

    def _read_max_aed_attempts() -> int:
        value = getattr(getattr(agent, "_config", None), "max_aed_attempts", 3)
        return value if isinstance(value, int) and not isinstance(value, bool) else 3

    def _read_preset() -> Mapping[str, Any]:
        read = getattr(agent, "_read_preset_from_init", None)
        if not callable(read):
            return {}
        try:
            value = read()
        except Exception:
            return {}
        return value if isinstance(value, Mapping) else {}

    def _read_task_card_watch() -> bool:
        check = getattr(getattr(agent, "_task_card_manager", None), "has_active_watch", None)
        if not callable(check):
            return False
        try:
            return bool(check())
        except Exception:
            return False

    def _log(event_type: str, **fields: Any) -> None:
        log = getattr(agent, "_log", None)
        if callable(log):
            log(event_type, **fields)

    def _missing_load_preset(name: str) -> dict:
        raise KeyError(f"preset loading is unavailable for {name!r} on this daemon host")

    def _missing_notification(**_kwargs: Any) -> None:
        raise RuntimeError("daemon notifications are unavailable on this daemon host")

    def _enqueue_notification_live(**kwargs: Any) -> None:
        """Invoke the host's current notification route at publish time.

        Refresh/reconstruction may replace the route after this Daemon runtime
        port is bound. Looking it up here makes a replaced failing route report
        publication failure, so terminal receipt state remains retryable rather
        than acknowledging a stale callback's earlier success.
        """
        notify = getattr(agent, "_enqueue_system_notification", None)
        if not callable(notify):
            _missing_notification(**kwargs)
        notify(**kwargs)

    # Daemon's accepted email route is its task-scoped daemon_email MCP server,
    # explicitly requested per emanation.  Email's parent official declaration
    # must not turn that into inherited parent communication authority merely by
    # appearing in the regular tool surface; keep the pre-existing Daemon filter
    # at this composition boundary for both schema and dispatch views.
    def _read_daemon_schemas() -> tuple[Any, ...]:
        return tuple(
            schema
            for schema in getattr(agent, "_tool_schemas", ())
            if getattr(schema, "name", None) != "email"
        )

    def _read_daemon_handlers() -> Mapping[str, Callable[[dict], dict]]:
        return {
            name: handler
            for name, handler in dict(getattr(agent, "_tool_handlers", {})).items()
            if name != "email"
        }

    return AgentDaemonRuntimeAdapter(
        read_service=lambda: agent.service,
        read_schemas=_read_daemon_schemas,
        read_handlers=_read_daemon_handlers,
        read_mcp_names=lambda: frozenset(
            name for name in getattr(agent, "_mcp_tool_names", set()) if isinstance(name, str)
        ),
        read_language=_read_language,
        read_max_aed_attempts=_read_max_aed_attempts,
        read_tool_call_guard=lambda: getattr(agent, "_tool_call_guard", None),
        manager_options=manager_options,
        setup_preset_capability=_setup_preset_capability,
        read_preset=_read_preset,
        load_preset=getattr(agent, "load_preset", _missing_load_preset),
        enqueue_notification=_enqueue_notification_live,
        read_task_card_watch=_read_task_card_watch,
        now_iso=lambda: render_now_iso(agent),
        log=_log,
    )


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


def agent_host_ports(
    agent: Any,
    plugin_name: str,
    extra_ports: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the complete grantable table for one declaration on *agent*.

    The table preserves the landed MCP, Avatar, Plugin, Context, Daemon, Email,
    and File wiring while constructing only each declaration's earned adapter.
    Notification receives its narrow state port at this composition boundary.
    The registrar grants just ``requires``, never this whole map.
    """
    ports = {"workdir": AgentWorkdirAdapter(lambda: agent.working_dir)}
    # Construct only the declaration's earned standard adapter. Lightweight Core
    # test agents need not implement MCP or Avatar APIs when Notification is being
    # granted its own narrow ports.
    if plugin_name in ("mcp", "plugin"):
        ports["prompt_section"] = AgentPromptSectionAdapter(
            plugin_name, agent.update_system_prompt
        )
    if plugin_name == "avatar":
        ports["avatar_parent"] = AgentAvatarParentAdapter(
            lambda: agent.agent_name or agent.working_dir.name,
            lambda: getattr(agent, "_venv_path", None),
            lambda: any((getattr(agent, "_admin", {}) or {}).values()),
        )
    elif plugin_name == "plugin":
        ports["plugin_catalog"] = AgentPluginCatalogAdapter(
            lambda: getattr(agent, "_plugin_registration", {}),
            lambda: getattr(agent, "_capabilities", ()),
        )
    elif plugin_name == "notification":
        # Import Notification Core lazily at the composition-root boundary. The
        # adapter binds Core policy to this live Agent without passing through
        # Agent/Store state.
        from lingtai.kernel.notifications import (
            add_hook,
            delay_notification_channel,
            dismiss_channel,
            drop_hook,
            edit_hook,
            list_hooks,
        )

        ports["notification_state"] = AgentNotificationStateAdapter(
            dismiss=partial(dismiss_channel, agent, invoked_by="notification"),
            delay=partial(delay_notification_channel, agent),
            add_hook=partial(add_hook, agent),
            drop_hook=partial(drop_hook, agent),
            edit_hook=partial(edit_hook, agent),
            list_hooks=partial(list_hooks, agent),
            log=agent._log,
        )
    if extra_ports:
        ports.update(extra_ports)
    return ports
def register_agent_tool_plugins(
    agent: Any,
    declarations: Sequence[ToolPluginDeclaration],
    *,
    extra_ports: Mapping[str, Any] | None = None,
    extra_ports_for: Callable[[ToolPluginDeclaration], Mapping[str, Any]] | None = None,
) -> tuple[BoundToolPlugin, ...]:
    """Wire *declarations* onto *agent* through the kernel registrar.

    One declaration per call is the shipped shape today (one family recuts at a
    time). The registrar's name check is batch-wide and runs before the first
    bind, so a **name conflict** is refused as a unit: nothing in the batch
    binds, activates, or mounts. That is the exact scope of the promise — a
    failure raised later, by a binder or by a missing host port on member *N*,
    leaves members 1..*N*-1 mounted and claimed and propagates, because
    unmounting is not a capability this component owns.

    ``extra_ports`` remains the current Context compatibility seam. Daemon,
    Email, and File use ``extra_ports_for`` so each can earn its runtime port;
    Notification receives its dedicated state port in ``agent_host_ports``.
    without granting it to every declaration. Both maps are merged per
    declaration; conflicting keys from the factory intentionally win only for
    that declaration.

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
            agent,
            declaration.name,
            {
                **dict(extra_ports or {}),
                **(
                    dict(extra_ports_for(declaration))
                    if extra_ports_for is not None
                    else {}
                ),
            },
        ),
        mount=_InternalMount(),
        claimed=agent.official_tool_plugins,
        claim=agent._claim_official_tool,
        authorize=agent._authorize_official_tool_declaration,
        record_bound=agent._record_official_tool_binding,
    )
