"""Core-owned declared host-plugin contract for official model-facing tools.

This is the kernel's *shape* for one official tool plugin: a static
:class:`ToolPluginDeclaration` constructed at import time, a least-privilege
:class:`ToolPluginHost` facade built from exactly the host ports a declaration
names in ``requires``, a kernel-owned reserved list of official plugin names,
and a fail-fast registrar that refuses a duplicate or unreserved name **before**
it binds anything and before any tool is mounted.

Three deliberate absences define this module as much as its exports:

- **No family knowledge.** The kernel never imports ``lingtai.tools`` and never
  learns what an official family *does*. It owns the declaration type, the
  ports, the reserved-name list, and the registration order; each family owns
  its own declaration, and ``src/lingtai/agent.py`` remains the Composition
  Root that wires the two together.
- **No discovery.** There is no filesystem scan, entry-point lookup, manifest
  compiler, or plugin-admission engine here. ``OFFICIAL_TOOL_PLUGIN_NAMES``
  below is a hand-edited, auditable literal, and a declaration reaches this
  module only because some caller passed it in.
- **No whole-``Agent`` argument.** :meth:`ToolPluginDeclaration.bind` receives a
  :class:`ToolPluginHost`, never the live ``Agent``. A port the declaration did
  not name is not reachable through the facade, and ``tool_mount`` is never
  grantable at all — an official plugin cannot mount itself.

See the sibling ``CONTRACT.md`` for the normative rules and ``ANATOMY.md`` for
where the production adapter and the first declaration live.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

__all__ = [
    "MANUAL_ACTION",
    "GRANTABLE_HOST_PORTS",
    "OFFICIAL_TOOL_PLUGIN_NAMES",
    "ToolPluginError",
    "ToolPluginDeclarationError",
    "UnreservedToolPluginNameError",
    "DuplicateToolPluginNameError",
    "OfficialToolNameCollisionError",
    "HostPortError",
    "WorkdirPort",
    "RuntimePort",
    "ProviderIdentityPort",
    "PromptSectionPort",
    "ToolMountPort",
    "ToolPluginHost",
    "BoundToolPlugin",
    "ToolPluginDeclaration",
    "register_official_tool_plugins",
]


#: The reserved action name every official family appends exactly once, from
#: its own manual. Kept as the kernel's single spelling of the reserved word so
#: the declaration can refuse an operational action that tries to claim it.
#: The reserved-action *rule* itself is normative in
#: ``src/lingtai/tools/CONTRACT.md`` ``### Dispatch and actions``; this constant
#: only lets the declaration enforce it before an Agent exists.
MANUAL_ACTION = "manual"


#: Every host port an official declaration may name in ``requires``.
#:
#: Earned, not enumerated: each name below is consumed by a real vertical slice
#: (``mcp`` or ``web``). Root ``CONTRACT.md`` rules 10-11 forbid a speculative
#: port taxonomy, so a later family adds the port it actually needs together with
#: its own slice.
#:
#: ``tool_mount`` is deliberately absent and MUST stay absent: mounting is the
#: host's own act, performed by :func:`register_official_tool_plugins` after the
#: name checks pass. A declaration that could mount could self-register.
GRANTABLE_HOST_PORTS: tuple[str, ...] = (
    "workdir",
    "runtime",
    "provider_identity",
    "prompt_section",
)


#: The kernel-owned reserved list of official plugin names.
#:
#: This is the auditable static registry of the official model-facing tool
#: namespace. A name here may be claimed by exactly one live declaration; a
#: declaration whose name is absent here is not official and is refused. Adding
#: a name is a reviewed kernel change, which is the point: it is a list, not a
#: discovery mechanism, and it holds names only — never a module path, an
#: import, or any knowledge of what the family does.
OFFICIAL_TOOL_PLUGIN_NAMES: tuple[str, ...] = ("mcp", "web")


# Opaque capability used only by the production host adapter's private
# authorized-mount route. Generic ``Agent.add_tool`` never receives this token;
# keeping it kernel-owned prevents the mount boundary from inferring authority
# from a caller-supplied name or declaration.
_OFFICIAL_MOUNT_TOKEN = object()
# Separate issuer capability for registrar-created mount transactions.  Python
# trusted-in-process code can inspect module globals; this is provenance for the
# public/declared and normal extension paths, not an absolute security boundary.
_OFFICIAL_MOUNT_ISSUER = object()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ToolPluginError(Exception):
    """Base class for every declared host-plugin defect.

    Deliberately **not** a ``ValueError``. The Composition Root's capability
    boot loop (``src/lingtai/agent.py``, both ``__init__`` and
    ``_setup_from_init``) wraps each ``_setup_capability`` call in
    ``except (ValueError, ImportError, TypeError)`` and downgrades what it
    catches to one ``capability_skipped`` log line. A reserved-name conflict,
    an unreserved official name, a missing host port, or a declaration that
    disagrees with what it ships would then be *silently* absorbed into a boot
    that comes up with the official tool missing — the exact failure mode this
    component exists to prevent. Skipping a capability is signalled by
    returning ``CAPABILITY_UNAVAILABLE`` (``src/lingtai/tools/registry.py``
    ``setup_capability``), never by raising from here, so these errors
    propagate past that guard and fail the boot loudly.
    """


class ToolPluginDeclarationError(ToolPluginError):
    """A declaration is malformed: bad name, actions, schemas, or requires."""


class UnreservedToolPluginNameError(ToolPluginError):
    """A declaration claims a name the kernel has not reserved as official."""


class DuplicateToolPluginNameError(ToolPluginError):
    """A second, different declaration claims an already-claimed official name."""


class OfficialToolNameCollisionError(ToolPluginError):
    """A generic or external mount attempted to take an official tool name."""


class HostPortError(ToolPluginError):
    """A required host port was not granted, or a granted port is not grantable."""


# ---------------------------------------------------------------------------
# Host ports — capability-native, one narrow promise each
# ---------------------------------------------------------------------------

class WorkdirPort(Protocol):
    """Read-only access to this agent's working directory.

    The whole capability is "where this agent's files live". It grants no
    read, write, listing, or lease operation: the plugin composes its own paths
    below :attr:`path` and uses ordinary filesystem calls, exactly as it did
    when it reached through the Agent.
    """

    @property
    def path(self) -> Path:
        """The agent working directory."""


class RuntimePort(Protocol):
    """One explicit setup-time value for a declared plugin.

    A nontrivial capability can need per-agent composition inputs (for example,
    a preselected browser transport and search-service specs) while its
    declaration must remain static and its binder must never receive the live
    Agent. The Composition Root supplies that one value for this registration;
    the port grants no Agent method, filesystem access, or implicit config
    lookup. The value's type and validation stay owned by the consuming family.
    """

    @property
    def value(self) -> Any:
        """The explicitly supplied per-registration runtime value."""


class ProviderIdentityPort(Protocol):
    """Read the current canonical LLM provider identity, if one exists.

    This is intentionally only the bounded provider label used by a capability
    authorization gate. It grants neither the provider service, credentials,
    model configuration, nor a mutable Agent/service reference.
    """

    @property
    def provider(self) -> str | None:
        """The current canonical provider name, or ``None`` when unavailable."""


class PromptSectionPort(Protocol):
    """Write this plugin's own protected system-prompt section.

    Deliberately not ``update_system_prompt(section, body, protected=...)``:
    the granted port is bound to the declaring plugin's name at grant time, so
    an official plugin can rewrite its own section and no other, and cannot
    write an unprotected one.
    """

    def write_protected_section(self, body: str) -> None:
        """Replace this plugin's protected prompt section with *body*."""


class ToolMountPort(Protocol):
    """Mount one registrar transaction onto the live model-facing surface.

    Host-only. It is never granted to a declaration (see
    :data:`GRANTABLE_HOST_PORTS`); only
    :func:`register_official_tool_plugins` calls it, and only after every name
    check has passed. The transaction binds the authorization to the exact
    declaration and bound plugin produced by that registration.
    """

    def mount_tool(self, transaction: "_OfficialMountTransaction") -> None:
        """Publish the registrar-created *transaction*."""


# ---------------------------------------------------------------------------
# The least-privilege host facade
# ---------------------------------------------------------------------------

class ToolPluginHost:
    """Exactly the host ports one declaration named in ``requires``.

    Attribute access is the whole surface: a granted port is an attribute, and
    anything else raises :class:`AttributeError`. The facade holds no reference
    to the live ``Agent`` — the Composition Root's adapters do, and they expose
    only their own port operation.

    Python cannot make a live object deeply unreachable, and this class does not
    pretend otherwise: an adapter's private attributes are still private
    attributes. The promise is about the *declared argument surface*. A plugin
    that reaches around a port into adapter internals violates this contract,
    exactly as a plugin reaching into ``agent._prompt_manager`` does today.
    """

    __slots__ = ("_plugin_name", "_ports")

    def __init__(self, plugin_name: str, ports: Mapping[str, Any]) -> None:
        self._plugin_name = plugin_name
        self._ports = dict(ports)

    @property
    def plugin_name(self) -> str:
        """The official plugin name this facade was granted to."""
        return self._plugin_name

    @property
    def granted(self) -> tuple[str, ...]:
        """The granted port names, in declaration order."""
        return tuple(self._ports)

    def __getattr__(self, name: str) -> Any:
        try:
            return self._ports[name]
        except KeyError:
            raise AttributeError(
                f"tool plugin {self._plugin_name!r} did not require host port "
                f"{name!r}; granted ports are {sorted(self._ports)}"
            ) from None

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return (
            f"ToolPluginHost(plugin_name={self._plugin_name!r}, "
            f"granted={self.granted!r})"
        )

    @classmethod
    def grant(
        cls,
        declaration: "ToolPluginDeclaration",
        ports: Mapping[str, Any],
    ) -> "ToolPluginHost":
        """Build the facade for *declaration* from the host's port table.

        Every name in ``declaration.requires`` must be present in *ports*;
        nothing else from *ports* is granted. A missing port is a wiring defect
        and fails loudly rather than degrading into a half-privileged plugin.
        """
        missing = [name for name in declaration.requires if name not in ports]
        if missing:
            raise HostPortError(
                f"tool plugin {declaration.name!r} requires host port(s) "
                f"{missing} that the host did not provide"
            )
        return cls(
            declaration.name,
            {name: ports[name] for name in declaration.requires},
        )


# ---------------------------------------------------------------------------
# Declaration and its bound result
# ---------------------------------------------------------------------------

def _advertised_actions(schema: Any) -> tuple[str, ...] | None:
    """The action inventory a composed model-facing schema advertises.

    This is the **one** structural fact the kernel reads out of a composed
    schema. It composes no schema and validates no other part of the LTP
    envelope — that stays owned by ``src/lingtai/tools/CONTRACT.md`` and
    ``lingtai.tools.tool_family`` — but the advertised action inventory *is*
    the model-facing identity a reserved official name was granted for, so
    :meth:`ToolPluginDeclaration.bind` compares it against the declaration
    rather than trusting the two to agree. Returns ``None`` when the schema
    advertises no enum at all, which :meth:`~ToolPluginDeclaration.bind`
    treats as a defect rather than as permission to skip the check.
    """
    properties = schema.get("properties") if isinstance(schema, Mapping) else None
    action = properties.get("action") if isinstance(properties, Mapping) else None
    enum = action.get("enum") if isinstance(action, Mapping) else None
    if isinstance(enum, (list, tuple)):
        return tuple(enum)
    return None


@dataclass(frozen=True)
class BoundToolPlugin:
    """One declaration bound to a host: the mountable model-facing surface.

    ``activate`` is the plugin's explicit, separate boot presentation step —
    the thing registration is *not*. Binding composes and validates; activation
    runs only when the registrar reaches it, after every name check. Neither
    starts a process, a server, or a transport.
    """

    name: str
    schema: Mapping[str, Any]
    handler: Callable[[dict], dict]
    description: str = ""
    glossary_package: str | None = None
    activate: Callable[[], None] | None = None


class _OfficialMountTransaction:
    """One-use registrar-issued authorization for one official mount.

    Construction is intentionally not a public ``(declaration, plugin)``
    operation. The registrar issues this object with the module-local issuer
    after ``declaration.bind()`` succeeds; the host mount route then consumes
    the exact declaration/bound result carried by that issuance. The issuer is
    provenance, not an absolute security boundary: trusted in-process Python
    can inspect private module state. It does ensure that public/declared and
    normal extension paths cannot manufacture a foreign handler/schema by
    calling this constructor or passing an arbitrary ``BoundToolPlugin``.
    """

    __slots__ = (
        "_declaration",
        "_plugin",
        "_issuer",
        "_consumed",
        "_mounted_agent",
    )

    def __init__(
        self,
        declaration: "ToolPluginDeclaration | None" = None,
        plugin: BoundToolPlugin | None = None,
        *,
        _issuer: object | None = None,
    ) -> None:
        if _issuer is not _OFFICIAL_MOUNT_ISSUER:
            raise PermissionError(
                "official mount transactions are issued only by the kernel registrar"
            )
        if not isinstance(declaration, ToolPluginDeclaration):
            raise TypeError("official mount transaction requires a declaration")
        if not isinstance(plugin, BoundToolPlugin):
            raise TypeError("official mount transaction requires a bound plugin")
        self._declaration = declaration
        self._plugin = plugin
        self._issuer = _issuer
        self._consumed = False
        self._mounted_agent = None

    @classmethod
    def issue(
        cls,
        declaration: "ToolPluginDeclaration",
        plugin: BoundToolPlugin,
    ) -> "_OfficialMountTransaction":
        return cls(declaration, plugin, _issuer=_OFFICIAL_MOUNT_ISSUER)

    @property
    def declaration(self) -> "ToolPluginDeclaration":
        return self._declaration

    @property
    def plugin(self) -> BoundToolPlugin:
        return self._plugin

    @property
    def mounted_agent(self) -> Any:
        return self._mounted_agent

    def consume(self) -> None:
        if self._consumed:
            raise PermissionError("official mount authorization was already consumed")
        self._consumed = True

    def mark_mounted(self, agent: Any) -> None:
        if not self._consumed or self._mounted_agent is not None:
            raise PermissionError("official mount transaction was not consumed for this mount")
        self._mounted_agent = agent


@dataclass(frozen=True)
class ToolPluginDeclaration:
    """One official model-facing tool family, declared statically.

    Constructible at import time, before any ``Agent`` exists, and validated at
    construction so a packaging defect fails loudly at import instead of
    shipping silently.

    ``actions`` are the family's *operational* actions. The reserved
    :data:`MANUAL_ACTION` is never among them; it is appended by
    :attr:`public_actions` and its schema by :attr:`public_input_schemas`,
    mirroring ``lingtai.mcp_servers._plugin.CuratedMcpPlugin.actions``. The
    family still owns the manual child's handler and its packaged/installed
    source — the kernel only guarantees the reserved slot exists exactly once
    and last.

    ``binder`` is how this family composes itself against a granted host. It is
    called only through :meth:`bind`, which builds nothing itself.
    """

    name: str
    actions: tuple[str, ...]
    input_schemas: Mapping[str, Mapping[str, Any]]
    manual_input_schema: Mapping[str, Any]
    manual: str
    description: str
    binder: Callable[[ToolPluginHost], BoundToolPlugin]
    requires: tuple[str, ...] = ()
    glossary_package: str | None = None

    def __post_init__(self) -> None:
        for attribute in ("name", "manual", "description"):
            value = getattr(self, attribute)
            if not isinstance(value, str) or not value.strip():
                raise ToolPluginDeclarationError(
                    f"ToolPluginDeclaration {attribute!r} must be a non-empty string"
                )
        if not isinstance(self.actions, tuple) or not self.actions:
            raise ToolPluginDeclarationError(
                f"ToolPluginDeclaration {self.name!r} must declare at least one "
                "action, as a tuple"
            )
        if MANUAL_ACTION in self.actions:
            raise ToolPluginDeclarationError(
                f"ToolPluginDeclaration {self.name!r} must not declare the "
                f"reserved {MANUAL_ACTION!r} action; it is appended from the "
                "family's own manual"
            )
        if len(set(self.actions)) != len(self.actions):
            raise ToolPluginDeclarationError(
                f"ToolPluginDeclaration {self.name!r} declared a duplicate action"
            )
        declared_schemas = set(self.input_schemas)
        if declared_schemas != set(self.actions):
            raise ToolPluginDeclarationError(
                f"ToolPluginDeclaration {self.name!r} must declare exactly one "
                f"input schema per action; actions={sorted(self.actions)} "
                f"schemas={sorted(declared_schemas)}"
            )
        unknown = [name for name in self.requires if name not in GRANTABLE_HOST_PORTS]
        if unknown:
            raise ToolPluginDeclarationError(
                f"ToolPluginDeclaration {self.name!r} requires non-grantable host "
                f"port(s) {unknown}; grantable ports are "
                f"{list(GRANTABLE_HOST_PORTS)}"
            )
        if len(set(self.requires)) != len(self.requires):
            raise ToolPluginDeclarationError(
                f"ToolPluginDeclaration {self.name!r} requires a duplicate host port"
            )
        if not callable(self.binder):
            raise ToolPluginDeclarationError(
                f"ToolPluginDeclaration {self.name!r} binder must be callable"
            )

    @property
    def public_actions(self) -> tuple[str, ...]:
        """Declared actions plus the reserved ``manual``, in that order."""
        return (*self.actions, MANUAL_ACTION)

    def public_input_schemas(self) -> dict[str, Mapping[str, Any]]:
        """Declared ``input`` schemas plus the reserved ``manual`` schema."""
        schemas: dict[str, Mapping[str, Any]] = dict(self.input_schemas)
        schemas[MANUAL_ACTION] = self.manual_input_schema
        return schemas

    def bind(self, host: ToolPluginHost) -> BoundToolPlugin:
        """Compose this family against a granted host facade.

        Pure composition: it must not mount, start, spawn, or connect anything.
        The bound plugin's name is checked against the declaration so a family
        cannot bind itself onto a different model-facing name than the one the
        kernel reserved, and its advertised action inventory is checked against
        :attr:`public_actions` so a family cannot ship a public surface it did
        not declare. Both checks run on every boot, in the registrar's own
        path — declared-versus-shipped agreement is enforced here, not merely
        asserted once in a test.
        """
        if not isinstance(host, ToolPluginHost):
            raise HostPortError(
                f"tool plugin {self.name!r} must be bound to a ToolPluginHost, "
                f"not {type(host).__name__}"
            )
        if host.plugin_name != self.name:
            raise HostPortError(
                f"tool plugin {self.name!r} was handed a host granted to "
                f"{host.plugin_name!r}"
            )
        bound = self.binder(host)
        if not isinstance(bound, BoundToolPlugin):
            raise ToolPluginDeclarationError(
                f"ToolPluginDeclaration {self.name!r} binder returned "
                f"{type(bound).__name__}, expected BoundToolPlugin"
            )
        if bound.name != self.name:
            raise ToolPluginDeclarationError(
                f"ToolPluginDeclaration {self.name!r} bound itself as "
                f"{bound.name!r}"
            )
        advertised = _advertised_actions(bound.schema)
        if advertised is None:
            raise ToolPluginDeclarationError(
                f"ToolPluginDeclaration {self.name!r} bound a plugin whose "
                "schema advertises no action enum; an official plugin must "
                "ship the public actions it declared"
            )
        if advertised != self.public_actions:
            raise ToolPluginDeclarationError(
                f"ToolPluginDeclaration {self.name!r} declared public actions "
                f"{list(self.public_actions)} but bound a plugin advertising "
                f"{list(advertised)}"
            )
        return bound


# ---------------------------------------------------------------------------
# The fail-fast registrar
# ---------------------------------------------------------------------------

def register_official_tool_plugins(
    declarations: Sequence[ToolPluginDeclaration],
    *,
    ports_for: Callable[[ToolPluginDeclaration], Mapping[str, Any]],
    mount: ToolMountPort,
    claimed: Mapping[str, ToolPluginDeclaration],
    claim: Callable[[_OfficialMountTransaction], None] | None = None,
    authorize: Callable[[ToolPluginDeclaration], None] | None = None,
    record_bound: Callable[[ToolPluginDeclaration, BoundToolPlugin], None] | None = None,
) -> tuple[BoundToolPlugin, ...]:
    """Register official declarations, refusing name conflicts before any bind.

    Order is the promise. Every name in *declarations* is checked against the
    kernel-owned reserved list, against the rest of the batch, and against
    *claimed* — the live official namespace — **before** the first
    :meth:`ToolPluginDeclaration.bind`, the first ``activate``, and the first
    :meth:`ToolMountPort.mount_tool`. A conflict therefore leaves the live tool
    surface exactly as it was: there is no last-registration-wins path here, and
    a name conflict never leaves a partially mounted batch.

    That promise is scoped to *names*, exactly. The second loop below mounts and
    claims each member as it goes, so a failure raised by ``ports_for``,
    ``grant``, ``bind``, ``activate``, or ``mount_tool`` on member *N* leaves
    members 1..*N*-1 mounted and claimed, and propagates. Rolling those back
    would require an unmount port this component deliberately does not own; the
    honest statement is that a *name* conflict is refused as a unit, while a
    binder or host defect fails loudly mid-batch.

    Re-registering the *same* declaration object for an already-claimed name is
    idempotent, because ``_setup_from_init`` re-runs the whole boot on every
    refresh. A *different* declaration claiming a live name is the collision
    this function exists to refuse.

    *ports_for* builds one declaration's full grantable port table; the
    declaration is then granted only the subset it named in ``requires``. It is
    a factory rather than a single table because a port may legitimately be
    bound to the declaring plugin's identity — ``prompt_section`` is bound to
    that plugin's own section name. *mount* is host-only and is never granted.
    """
    batch: list[ToolPluginDeclaration] = list(declarations)

    seen: set[str] = set()
    for declaration in batch:
        name = declaration.name
        if name not in OFFICIAL_TOOL_PLUGIN_NAMES:
            raise UnreservedToolPluginNameError(
                f"{name!r} is not a reserved official tool plugin name; "
                f"reserved names are {list(OFFICIAL_TOOL_PLUGIN_NAMES)}"
            )
        if name in seen:
            raise DuplicateToolPluginNameError(
                f"official tool plugin name {name!r} was declared twice in one "
                "registration batch"
            )
        seen.add(name)
        live = claimed.get(name)
        if live is not None and live is not declaration:
            raise DuplicateToolPluginNameError(
                f"official tool plugin name {name!r} is already claimed by a "
                "different declaration; official names are reserved first and "
                "are not overwritable"
            )

    # A live Agent supplies this callback to keep the canonical declaration
    # independent of its mutable live-claim view. It runs only after the whole
    # name-conflict pass, so a foreign declaration cannot reach bind/mount.
    if authorize is not None:
        for declaration in batch:
            authorize(declaration)

    bound_plugins: list[BoundToolPlugin] = []
    for declaration in batch:
        host = ToolPluginHost.grant(declaration, ports_for(declaration))
        bound = declaration.bind(host)
        if record_bound is not None:
            # The host records the exact bind result before issuance; the mount
            # route later rejects a transaction for any other plugin object.
            record_bound(declaration, bound)
        if bound.activate is not None:
            bound.activate()
        transaction = _OfficialMountTransaction.issue(declaration, bound)
        mount.mount_tool(transaction)
        if claim is None:
            # The standalone kernel registrar remains usable with a plain
            # mutable mapping in tests and other kernel-owned composition code.
            claimed[declaration.name] = declaration  # type: ignore[index]
        else:
            # Agent claims are accepted only for this registrar-issued
            # transaction after the mount seam has marked it mounted.
            claim(transaction)
        bound_plugins.append(bound)
    return tuple(bound_plugins)
