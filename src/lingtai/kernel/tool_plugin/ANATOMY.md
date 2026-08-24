---
related_files:
  - src/lingtai/kernel/tool_plugin/CONTRACT.md
  - src/lingtai/kernel/tool_plugin/BEHAVIORS.md
  - src/lingtai/kernel/tool_plugin/__init__.py
  - src/lingtai/kernel/ANATOMY.md
  - src/lingtai/adapters/tool_plugin_host.py
  - src/lingtai/kernel/base_agent/ANATOMY.md
  - src/lingtai/kernel/base_agent/tools.py
  - src/lingtai/kernel/base_agent/__init__.py
  - src/lingtai/tools/ANATOMY.md
  - src/lingtai/tools/mcp/ANATOMY.md
  - src/lingtai/tools/mcp/__init__.py
  - src/lingtai/tools/mcp/manual/SKILL.md
  - src/lingtai/tools/avatar/ANATOMY.md
  - src/lingtai/tools/avatar/__init__.py
  - src/lingtai/tools/avatar/manual/SKILL.md
  - src/lingtai/tools/context/__init__.py
  - src/lingtai/tools/context/manual/SKILL.md
  - src/lingtai/tools/daemon/ANATOMY.md
  - src/lingtai/tools/daemon/__init__.py
  - src/lingtai/tools/daemon/manual/SKILL.md
  - src/lingtai/tools/email/ANATOMY.md
  - src/lingtai/tools/email/__init__.py
  - src/lingtai/tools/email/manual/SKILL.md
  - src/lingtai/tools/tool_family/ANATOMY.md
  - src/lingtai/tools/_manual.py
  - src/lingtai/agent.py
  - tests/test_tool_plugin_declaration.py
  - tests/test_tool_family_avatar_migration.py
  - tests/test_context_declared_tool_plugin.py
  - tests/test_daemon.py
  - tests/test_email_official_tool_plugin.py
maintenance: |
  Keep related_files repo-relative, duplicate-free, and linked to real files.
  Keep this component's ANATOMY.md, CONTRACT.md, and BEHAVIORS.md reciprocal and
  keep parent/child anatomy links bidirectional (src/lingtai/kernel/ANATOMY.md
  upward; src/lingtai/tools/ANATOMY.md, src/lingtai/tools/mcp/ANATOMY.md, and
  src/lingtai/tools/daemon/ANATOMY.md, and src/lingtai/tools/email/ANATOMY.md
  across to the declaring side). Code is the structural source of truth: update
  this anatomy in the same change that moves files, symbols, connections,
  composition, or state — in particular when a host port is added, when a family
  recuts onto the declared contract, or when OFFICIAL_TOOL_PLUGIN_NAMES changes.
  Name the guarding LABT ids (TP001, TP002) beside the implementing code. Verify
  every changed citation and run the architecture-document validation before
  merge. Follow the root Anatomy/Contract pairing rule, report mismatches, and do
  not duplicate or auto-fix the rule here.
  Capability mentions in any document require explicit bidirectional
  related_files mapping to the implementing code (see root ## Maintenance).
---
# Declared Host Tool Plugin Anatomy

Where the kernel-owned declared host-plugin primitive lives, and how each official
landed family reaches the live Agent body through a runtime-bound host bridge. Promises and normative
rules are in the paired [`CONTRACT.md`](CONTRACT.md); the agent-executable proof
is in [`BEHAVIORS.md`](BEHAVIORS.md).

## Components

- `src/lingtai/kernel/tool_plugin/__init__.py` — the whole Core. One module,
  because the component is a shape rather than a machine:
  - constants `MANUAL_ACTION`, `GRANTABLE_HOST_PORTS`, and
    `OFFICIAL_TOOL_PLUGIN_NAMES` (the auditable reserved official namespace,
    guarded by TP002);
  - errors `ToolPluginError` and its four subclasses
    (`ToolPluginDeclarationError`, `UnreservedToolPluginNameError`,
    `DuplicateToolPluginNameError`, `HostPortError`);
  - the six host Port Protocols `WorkdirPort`, `PromptSectionPort`,
    `AvatarParentPort`, `ContextRuntimePort`, `DaemonRuntimePort`, and
    `ToolMountPort`; `email_runtime` is also grantable, but its Protocol
    (`EmailRuntimePort`) deliberately remains Email-owned rather than kernel-owned;
  - `ToolPluginHost`, the `__slots__`-based least-privilege facade, and its
    `grant()` classmethod;
  - `BoundToolPlugin`, the frozen mountable result carrying `schema`,
    `handler`, `description`, `glossary_package`, and the optional separate
    `activate` step;
  - private `_OfficialMountTransaction`, a registrar-issued one-use object
    binding one anchored declaration to the exact canonical bound plugin for the
    internal mount seam; its constructor rejects caller-supplied declaration /
    plugin pairs;
  - `ToolPluginDeclaration`, the frozen static declaration, validated in
    `__post_init__` (guarded by TP001), with `public_actions`,
    `public_input_schemas()`, and `bind()` — which checks the bound plugin's
    name *and* its advertised action inventory against the declaration, via the
    module-private `_advertised_actions` reader;
  - `register_official_tool_plugins`, the fail-fast registrar whose two-phase
    body — check every name, then bind/activate/mount — is the ordering promise
    (guarded by TP002).
- `src/lingtai/adapters/tool_plugin_host.py` — the production Adapter set,
  outside the kernel package. `AgentWorkdirAdapter`,
  `AgentPromptSectionAdapter` (bound to one plugin's section name and to
  `protected=True`), `AgentAvatarParentAdapter`, `AgentContextRuntimeAdapter`,
  and `AgentDaemonRuntimeAdapter` (the latter reads the current notification
  route at publish time), plus `AgentEmailRuntimeAdapter`, which owns only a
  call-time manager reader and never an Agent or intrinsic dispatcher, plus
  `agent_host_ports` and
  `register_agent_tool_plugins`. The registrar constructs its mount seam
  locally; no public mount adapter or factory exists.
- `src/lingtai/tools/mcp/__init__.py` — the current base reference slice.
  `DECLARATION` is built at module import; `_bind(host)` composes the
  per-host `ToolFamily` and the `handle_mcp` Host wrapper and returns a
  `BoundToolPlugin` whose `activate` is the boot reconcile; `setup(agent)` is
  only composition wiring. `mcp` remains the shared-C base reference; Avatar,
  Context, Daemon, and Email below are the other accepted vertical slices. The
  later-family target register is limited to `file`, `notification`, `soul`,
  `vision`, `web`, `system`, and `task_card`; it is not an admission path.
- `src/lingtai/tools/avatar/__init__.py` — separately landed vertical evidence,
  not a C candidate claim. Its static `DECLARATION` binds `AvatarManager` to
  `workdir` plus the earned, narrow `avatar_parent` port; the local packaged
  manual stays a reserved child owned by the family, and `setup(agent)` only
  routes it through the registrar.
- `src/lingtai/tools/context/__init__.py` — current in-process vertical evidence.
  Its static `DECLARATION` preserves `molt | summarize | rebuild | manual` and
  binds only `workdir` plus the earned `context_runtime` operation port; the
  port delegates the established lifecycle engines without handing Context the
  Agent. Its package manual is the canonical runtime-installed `context-manual`.
- `src/lingtai/tools/daemon/__init__.py` is the fourth actual vertical slice.
  Its static `DECLARATION` preserves Daemon's action-separated public family and
  binds the established `DaemonManager`/dispatcher only to `workdir` plus the
  earned `daemon_runtime` port; no manager holds an Agent reference.
- `src/lingtai/tools/email/__init__.py` is the fifth accepted vertical slice.
  It owns `EmailRuntimeRequest` and `EmailRuntimePort`; its declaration consumes
  `workdir` plus `email_runtime`. `boot(agent)` first replaces the real
  `EmailManager`, then registers the declaration through `extra_ports_for` with
  `AgentEmailRuntimeAdapter(lambda: getattr(agent, "_email_manager", None))`.
  The adapter flattens an already-normalized request into one manager call and
  reads the manager at call time; Email has no dynamic `setup()` bridge.

## Connections

- `lingtai.tools.mcp`, `lingtai.tools.avatar`, `lingtai.tools.context`,
  `lingtai.tools.daemon`, and `lingtai.tools.email` import
  `lingtai.kernel.tool_plugin` (declarations depend on the shape). The kernel
  imports nothing from `lingtai.tools`; that edge is
  swept by `tests/test_tool_plugin_declaration.py`.
- `lingtai.adapters.tool_plugin_host` imports `lingtai.kernel.tool_plugin`
  (`Adapter -> Port <- Core`) and reaches the Agent only through the public
  `working_dir`, `update_system_prompt`, and the read-only
  `official_tool_plugins` surface. The last is the live claim view on
  `BaseAgent`; a persistent declaration anchor and canonical bound-result map
  remain separate from that view. Composition changes claims only through the
  registrar-issued mounted transaction callback; clearing the live backing map
  cannot authorize a different declaration.
- The registrar-local transaction mount calls `BaseAgent._mount_official_tool`
  (`src/lingtai/kernel/base_agent/__init__.py`), which verifies the issuer,
  anchored declaration, and exact bound-result identity before delegating to
  `_add_tool` in `src/lingtai/kernel/base_agent/tools.py`. That common boundary
  performs the reserved-name guard; its seal check and same-name replacement
  for nonreserved tools remain unchanged. This is trusted-in-process Python
  provenance, not an absolute defense against deliberate private-state mutation.
- `lingtai.tools.mcp.setup()`, `lingtai.tools.avatar.setup()`,
  `lingtai.tools.context.setup()`, and `lingtai.tools.daemon.setup()` call
  `lingtai.adapters.tool_plugin_host.register_agent_tool_plugins` through the
  ordinary capability boot loop. Email instead is an injected
  `official_plugin`: `BaseAgent._boot_official_intrinsics()` calls `email.boot`,
  which creates its manager before registering the declaration with its sole
  family-specific `email_runtime` grant.
- `_build_family(host)` passes only `host.workdir` to
  `lingtai.tools.tool_family.manual.build_manual_child`, which reads the
  installed manual through `src/lingtai/tools/_manual.py`. That loader accepts
  the live Agent (private `_working_dir`) or a `WorkdirPort` (`path`), so
  migrated and unmigrated families share one loader.

## Composition

`import lingtai.tools.mcp`, `import lingtai.tools.avatar`,
`import lingtai.tools.context`, `import lingtai.tools.daemon`, or
`import lingtai.tools.email` → `ToolPluginDeclaration.__post_init__` validates
its declared shape, with no Agent in existence.

Dynamic-family boot remains `Agent.__init__` / `Agent._setup_from_init` →
`_setup_capability(name)` → that family's `setup(agent)` →
`register_agent_tool_plugins(agent, [DECLARATION])`. Email's mandatory official
boot is `BaseAgent._boot_official_intrinsics()` → `email.boot(agent)` → create or
replace `EmailManager` → `register_agent_tool_plugins(..., extra_ports_for=...)`.
Both routes reach `register_official_tool_plugins`, which then runs, in order:

1. check every declared name against `OFFICIAL_TOOL_PLUGIN_NAMES`, the batch,
   and the live claim map;
2. `ToolPluginHost.grant(declaration, agent_host_ports(agent, name))`;
3. `declaration.bind(host)` → `_bind` composes the family and `handle_mcp`,
   deriving the tool name, the per-action `input` schemas, and the installed
   manual's destination from `DECLARATION` itself; `bind()` then refuses a
   bound plugin whose advertised action enum is not `public_actions`;
4. `bound.activate()` → `_reconcile(host)` writes the protected `mcp` prompt
   section;
5. record the exact bound result, issue a registrar-only one-use transaction,
   and call `agent._mount_official_tool(transaction)`; the Agent verifies the
   persistent declaration anchor and canonical bound identity before `_add_tool`
   performs the final common-boundary reserved-name guard;
6. record the claim through `agent._claim_official_tool(transaction)` only after
   the mount marks that issued transaction successful.

Step 1 completes for the whole batch before step 2 begins for any member, so a
*name conflict* never leaves a partially mounted surface. Steps 2-6 run per
member, in order, and are not transactional: a failure raised by `grant`,
`bind`, `activate`, or `mount_tool` on member N leaves members 1..N-1 mounted
and claimed and propagates. Rolling those back would need an unmount port this
component does not own.

## State

- `OFFICIAL_TOOL_PLUGIN_NAMES` — module-level immutable tuple; the reserved
  official namespace.
- `BaseAgent._official_tool_plugins` — per-agent `dict[str,
  ToolPluginDeclaration]`, initialized in `BaseAgent.__init__`
  (`src/lingtai/kernel/base_agent/__init__.py`) beside `_tool_handlers` /
  `_tool_schemas` and read publicly through the `official_tool_plugins`
  property. The live official namespace is written only by the registrar's
  mounted-transaction claim seam. Persistent
  `_official_tool_declarations` anchors and live
  `_official_tool_bindings` are separate: refresh clears the latter with the
  tool surface but not the former, so clearing the claim map cannot admit a
  foreign declaration. A dynamic capability dropped on refresh leaves no live
  claim; surviving dynamic families re-register their declaration idempotently.
  Email is a mandatory injected official family, so its refresh boot replaces its
  manager and re-registers its same declaration regardless of capability opt-out.
- `ToolPluginHost._ports` — the granted subset, fixed at grant time.
- No other state. The component keeps no cache, no registry file, and no
  process handle.

## Boundaries

- Declaration *content* belongs to each family under `src/lingtai/tools/`; the
  LTP envelope and schema composition belong to
  `src/lingtai/tools/CONTRACT.md` and `src/lingtai/tools/tool_family/`.
- Which declarations are registered and when is Composition-Root work in
  `src/lingtai/agent.py`, dynamic-family `setup()`, and injected official-family
  `boot()` hooks; the core never selects.
- External transport and launcher concerns — curated MCP server packages,
  `src/lingtai/mcp_catalog.json`, `mcp_registry.jsonl`, Agent Plugins v1.0.0 —
  live outside this component and are unchanged by it.

## Extension points

- A new host port: extend `GRANTABLE_HOST_PORTS`, keep the Protocol in the
  owning family when it is family-specific (as Email does), add the production
  adapter, and land all of it with the one real family that consumes it.
- A new official family: add its name to `OFFICIAL_TOOL_PLUGIN_NAMES` (a
  reviewed contract change), build its module-level `DECLARATION`, and route
  its approved composition hook through `register_agent_tool_plugins`; do not
  infer that every official family must be a dynamic `setup()` capability.
