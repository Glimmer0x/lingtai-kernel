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
  - src/lingtai/tools/system/ANATOMY.md
  - src/lingtai/tools/system/__init__.py
  - src/lingtai/tools/system/plugin.py
  - src/lingtai/intrinsic_skills/system-manual/SKILL.md
  - tests/test_system_declared_plugin.py
  - src/lingtai/tools/tool_family/ANATOMY.md
  - src/lingtai/tools/_manual.py
  - src/lingtai/agent.py
  - tests/test_tool_plugin_declaration.py
maintenance: |
  Keep related_files repo-relative, duplicate-free, and linked to real files.
  Keep this component's ANATOMY.md, CONTRACT.md, and BEHAVIORS.md reciprocal and
  keep parent/child anatomy links bidirectional (src/lingtai/kernel/ANATOMY.md
  upward; src/lingtai/tools/ANATOMY.md and src/lingtai/tools/mcp/ANATOMY.md
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

Where the kernel-owned declared host-plugin primitive lives, and how declared
families reach the live Agent body through narrow ports. Promises and normative
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
  - the five host Port Protocols `WorkdirPort`, `PromptSectionPort`,
    `SystemRuntimePort`, `IdentityPort`, and `ToolMountPort`;
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
- `src/lingtai/tools/system/__init__.py` / `plugin.py` — the second vertical
  slice: a static `system` declaration deriving its action/schema/manual
  identity in one package. Its binder builds a private handler bridge from only
  `workdir`, `system_runtime`, and `identity`; normal model-facing dispatch uses
  that registrar-mounted handler, while direct `handle(agent, args)` is only
  compatibility. `system-manual` remains the packaged intrinsic router bundle.
  `tests/test_system_declared_plugin.py` pins declaration, single mount,
  identity behavior, mounted runtime sleep, and installed manual path.
- `src/lingtai/adapters/tool_plugin_host.py` — the production Adapter set,
  outside the kernel package. `AgentWorkdirAdapter` reads the current workdir;
  `AgentPromptSectionAdapter` is bound to one plugin's section name and to
  `protected=True`; `AgentSystemRuntimeAdapter` holds only System's specific
  runtime/lifecycle callbacks; and `AgentIdentityAdapter` holds only naming
  callbacks. `agent_host_ports` composes that complete table per declaration;
  `register_agent_tool_plugins` constructs the registrar's mount seam locally.
  No public mount adapter or factory exists.
- `src/lingtai/tools/mcp/__init__.py` — the first declaring family.
  `DECLARATION` is built at module import; `_bind(host)` composes the
  per-host `ToolFamily` and the `handle_mcp` Host wrapper and returns a
  `BoundToolPlugin` whose `activate` is the boot reconcile; `setup(agent)` is
  now only composition wiring.

## Connections

- `lingtai.tools.mcp` and `lingtai.tools.system` import
  `lingtai.kernel.tool_plugin` (declarations depend on the shape). The kernel
  imports nothing from `lingtai.tools`; that edge is swept by
  `tests/test_tool_plugin_declaration.py`.
- `lingtai.adapters.tool_plugin_host` imports `lingtai.kernel.tool_plugin`
  (`Adapter -> Port <- Core`). Its adapters are composed from narrow callbacks:
  the workdir read, the protected prompt writer, System's individual runtime
  callbacks (authority, language, audit, preset/lifecycle, CPR, and self-sleep),
  and identity's name read/write callbacks. The adapter set also reads the
  public `official_tool_plugins` claim view on `BaseAgent`; a persistent
  declaration anchor and canonical bound-result map remain separate from that
  view. Composition changes claims only through the registrar-issued mounted
  transaction callback; clearing the live backing map cannot authorize a
  different declaration.
- The registrar-local transaction mount calls `BaseAgent._mount_official_tool`
  (`src/lingtai/kernel/base_agent/__init__.py`), which verifies the issuer,
  anchored declaration, and exact bound-result identity before delegating to
  `_add_tool` in `src/lingtai/kernel/base_agent/tools.py`. That common boundary
  performs the reserved-name guard; its seal check and same-name replacement
  for nonreserved tools remain unchanged. This is trusted-in-process Python
  provenance, not an absolute defense against deliberate private-state mutation.
- `lingtai.tools.mcp.setup()` calls
  `lingtai.adapters.tool_plugin_host.register_agent_tool_plugins`, reached
  through the ordinary capability boot loop in `src/lingtai/agent.py`
  (`_setup_capability` → `lingtai.tools.registry.setup_capability`).
- `lingtai.tools.system.setup()` calls the same registrar helper, reached by
  `Agent._setup_declared_intrinsic_tool_plugins()` after intrinsic wiring. Its
  mounted handler reaches retained System actions through the private
  `workdir` / `system_runtime` / `identity` bridge, never a direct Agent argument.
- `_build_family(host)` passes only `host.workdir` to
  `lingtai.tools.tool_family.manual.build_manual_child`, which reads the
  installed manual through `src/lingtai/tools/_manual.py`. That loader accepts
  the live Agent (private `_working_dir`) or a `WorkdirPort` (`path`), so
  migrated and unmigrated families share one loader.

## Composition

`import lingtai.tools.mcp` or `import lingtai.tools.system` → the respective
`ToolPluginDeclaration.__post_init__` validates the declared shape, with no
Agent in existence.

The two slices reach the same registrar by their appropriate composition routes:
MCP's ordinary capability boot is `Agent.__init__` / `Agent._setup_from_init`
→ `_setup_capability("mcp")` → `lingtai.tools.mcp.setup(agent)`; System's
injected-intrinsic boot is `Agent.__init__` / refresh →
`_setup_declared_intrinsic_tool_plugins()` → `lingtai.tools.system.setup(agent)`.
Each setup calls `register_agent_tool_plugins(agent, [DECLARATION])`, which calls
`register_official_tool_plugins` and then runs, in order:

1. check every declared name against `OFFICIAL_TOOL_PLUGIN_NAMES`, the batch,
   and the live claim map;
2. `ToolPluginHost.grant(declaration, agent_host_ports(agent, name))`. MCP is
   granted `workdir` / `prompt_section`; System is granted `workdir` /
   `system_runtime` / `identity`;
3. `declaration.bind(host)`. MCP's `_bind` composes its family and `handle_mcp`;
   System's `_bind` composes its family around a private bridge whose only state
   is those three ports. Each derives its tool name, per-action `input` schemas,
   and installed manual destination from `DECLARATION`; `bind()` then refuses a
   bound plugin whose advertised action enum is not `public_actions`;
4. run `bound.activate()` when supplied. MCP's `_reconcile(host)` writes the
   protected `mcp` prompt section; System supplies no activation step;
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
  foreign declaration. A capability dropped on refresh leaves no live claim;
  surviving capabilities re-register the same declaration idempotently.
- `ToolPluginHost._ports` — the granted subset, fixed at grant time.
- No other state. The component keeps no cache, no registry file, and no
  process handle.

## Boundaries

- Declaration *content* belongs to each family under `src/lingtai/tools/`; the
  LTP envelope and schema composition belong to
  `src/lingtai/tools/CONTRACT.md` and `src/lingtai/tools/tool_family/`.
- Which declarations are registered and when is Composition-Root work in
  `src/lingtai/agent.py` and the capability `setup()` it drives.
- External transport and launcher concerns — curated MCP server packages,
  `src/lingtai/mcp_catalog.json`, `mcp_registry.jsonl`, Agent Plugins v1.0.0 —
  live outside this component and are unchanged by it.

## Extension points

- A new host port: add the Protocol, extend `GRANTABLE_HOST_PORTS`, add the
  adapter in `src/lingtai/adapters/tool_plugin_host.py`, and land it together
  with the one real family that consumes it.
- A new official family: add its name to `OFFICIAL_TOOL_PLUGIN_NAMES` (a
  reviewed contract change), build its module-level `DECLARATION`, and route
  its `setup()` through `register_agent_tool_plugins`.
