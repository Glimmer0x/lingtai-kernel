---
name: declared-host-tool-plugin
contract_version: 1
root_contract: CONTRACT.md
related_files:
  - src/lingtai/kernel/tool_plugin/ANATOMY.md
  - src/lingtai/kernel/tool_plugin/BEHAVIORS.md
  - src/lingtai/kernel/tool_plugin/__init__.py
  - src/lingtai/adapters/tool_plugin_host.py
  - src/lingtai/kernel/base_agent/tools.py
  - src/lingtai/kernel/base_agent/__init__.py
  - src/lingtai/kernel/base_agent/CONTRACT.md
  - src/lingtai/tools/CONTRACT.md
  - src/lingtai/tools/mcp/__init__.py
  - src/lingtai/tools/mcp/manual/SKILL.md
  - src/lingtai/agent.py
  - tests/test_tool_plugin_declaration.py
maintenance: |
  This component contract is governed by the root CONTRACT.md and owns the
  declared host-plugin contract every official model-facing tool family follows.
  Keep related_files complete and repo-relative: the paired ANATOMY.md and
  BEHAVIORS.md, the Port module, the production Adapter
  (src/lingtai/adapters/tool_plugin_host.py), the host mount seam
  (src/lingtai/kernel/base_agent/tools.py), the owning LTP contract
  (src/lingtai/tools/CONTRACT.md), the one declared slice and its manual, the
  Composition Root, and the contract tests. OFFICIAL_TOOL_PLUGIN_NAMES is
  normative: adding, removing, or renaming a reserved official name is a change
  to this contract and must move the list, this file, BEHAVIORS.md, and
  tests/test_tool_plugin_declaration.py together. Ports are earned by real
  slices (root CONTRACT.md rules 10-11) — add a host port only with the family
  that consumes it, and never widen GRANTABLE_HOST_PORTS to a whole-Agent
  argument or to tool_mount. Update the Port, affected Adapters, contract tests,
  and this contract in the same change; update the paired Anatomy when structure
  changes; bump contract_version for a breaking Port-contract change. Follow the
  root Anatomy/Contract pairing rule, report mismatches, and do not duplicate or
  auto-fix the rule here.
---
# Declared Host Tool Plugin Contract

## Purpose
Guarded by: [TP001](BEHAVIORS.md#behavior-tp001), [TP002](BEHAVIORS.md#behavior-tp002)

This component is the kernel's boundary for every declared official
model-facing tool plugin. Each official tool family follows the same generic
declaration contract. The C integration target names `mcp`, `email`, `file`,
`context`, `notification`, `soul`, `vision`, `web`, `daemon`, `system`, and
`task_card`; this target is not a claim that every candidate has merged. Each
family supplies a static declaration of its identity and public actions, a bind
step against a least-privilege host facade, and a
kernel-owned registrar that reserves official names and refuses a conflict
before anything is bound or mounted.

It owns exactly four things:

1. `ToolPluginDeclaration` — the static declaration shape and its
   construction-time validation.
2. The host Ports (`WorkdirPort`, `PromptSectionPort`, `ToolMountPort`) through
   which a plugin controls the live Agent body, and the `ToolPluginHost` facade
   that grants a declaration exactly the ports it named.
3. `OFFICIAL_TOOL_PLUGIN_NAMES` — the auditable, static, kernel-owned reserved
   list of official plugin names.
4. `register_official_tool_plugins` — the fail-fast registrar and its ordering
   promise.

It owns none of the following, and adding any of them here is a defect:
declaration *content* for any family; a module path, import, or behavioral
knowledge of a concrete family; filesystem, entry-point, or manifest discovery;
a wrapper runtime, universal MCP server compiler, or plugin-admission engine;
LTP envelope or JSON-schema composition (owned by
[`src/lingtai/tools/CONTRACT.md`](../../tools/CONTRACT.md) and
`lingtai.tools.tool_family`); transport, process, or connection lifecycle; and
third-party MCP or Agent Plugins v1.0.0 semantics, which are untouched.

**Host-local versus external implementation is not a product category.** A
declaration says what an official family *is*; whether its implementation runs
in this process, behind a stdio MCP server, in a spawned peer process (Avatar),
or over a channel (Telegram) is a transport/launcher choice made by an adapter
at the boundary where that technology actually varies (root `CONTRACT.md`
rule 8). Curated MCP server packages
(`src/lingtai/mcp_servers/_plugin.py`) and `src/lingtai/mcp_catalog.json`
therefore remain valid, unchanged, external-transport concerns — one adapter
form over a declaration, never the required form of every official tool.

## Behavior

Coding agents and LingTai agents MUST observe the following.

- **Declare statically.** A family's declaration is a module-level
  `ToolPluginDeclaration` constructed at import, before any `Agent` exists. It
  MUST NOT be built from a scanned directory, an entry point, a manifest file,
  or any runtime lookup. `registry.py` remains a hand-edited static table and
  gains no plugin packaging.
- **Never take the Agent.** A declaration's `binder` receives a
  `ToolPluginHost` and nothing else. Reaching around a granted port into an
  adapter's private attributes, or accepting an unguarded whole-`Agent`
  argument, is a contract violation.
- **Require only what you consume.** `requires` names ports the family actually
  uses in its own slice. Do not add a port speculatively, and do not add one
  without the real family that consumes it (root `CONTRACT.md` rules 10-11).
- **Do not self-register.** Binding composes and validates. Activation and
  mounting are the registrar's steps, in that order, and `tool_mount` is never
  grantable to a declaration.
- **Do not claim blanket conformance.** A family conforms only once its own
  vertical slice lands with its own evidence. The base checkout proves the
  `mcp` slice; the shared C register names additional target declarations
  without claiming that their candidate worktrees have merged.
- **Fail the boot, do not skip the capability.** Every error in this component
  descends from `ToolPluginError`, which is deliberately **not** a `ValueError`
  subclass. The Composition Root's capability loop
  (`src/lingtai/agent.py`, `__init__` and `_setup_from_init`) catches
  `(ValueError, ImportError, TypeError)` around `_setup_capability` and
  downgrades it to a `capability_skipped` log line, so a `ValueError`-based
  hierarchy would turn a violated official-name reservation into an agent that
  boots successfully with the official tool silently missing. Skipping a
  capability is signalled by returning `CAPABILITY_UNAVAILABLE`
  (`src/lingtai/tools/registry.py`), never by raising from here. Re-basing
  these errors on `ValueError`, or catching them in the boot loop, is a defect.
- **Report, do not normalize.** If an implementation and this contract
  disagree, treat the disagreement as a defect and report it rather than
  weakening the promise.

## Port

Ports are capability-native and narrow (root `CONTRACT.md`
`### Capability-native interfaces`). There is deliberately no single host
interface: each port carries the smallest vocabulary that expresses one
capability.

| Port | Operation | Promise |
|---|---|---|
| `WorkdirPort` | `path -> Path` | The agent working directory, read through on every access so a holder never renders a stale directory after a refresh. Grants no read, write, listing, or lease operation. |
| `PromptSectionPort` | `write_protected_section(body) -> None` | Replace **this plugin's own** protected system-prompt section. There is no section argument and no `protected` flag: the granted port is bound to the declaring plugin's name, so a plugin can neither address another's section nor write an unprotected one. |
| `ToolMountPort` | `mount_tool(transaction) -> None` | Publish the registrar-created one-use transaction carrying one declaration and its exact `BoundToolPlugin` on the live model-facing tool surface. **Host-only** — it is absent from `GRANTABLE_HOST_PORTS` and is held solely by the registrar. |

`GRANTABLE_HOST_PORTS` is the closed set a declaration may name. The base
checkout currently exposes `workdir` and `prompt_section` for the `mcp` slice.
The C integration target extends this vocabulary one real family slice at a time
with `intrinsic_dispatch`, `file_io`, `context_runtime`,
`notification_state`, `soul_runtime`, `active_provider`, `configuration`,
`runtime`, `provider_identity`, `daemon_runtime`, `system_runtime`, `identity`,
`shutdown`, `task_card_lifecycle`, and `task_card_notifications`; each family
must earn only the subset it consumes. This target wording does not claim those
candidate-local runtime changes have merged.

`ToolPluginHost` is the facade. A granted port is an attribute; anything else
raises `AttributeError` naming the missing port. The facade holds no reference
to the `Agent`. Python cannot make a live object deeply unreachable and this
contract does not pretend otherwise: the promise is about the **declared
argument surface** handed to a plugin, not about deep object-graph isolation.

## Adapters

`src/lingtai/adapters/tool_plugin_host.py` is the one production adapter set,
placed outside the kernel package so the dependency points inward
(`Adapter -> Port <- Core`). `AgentWorkdirAdapter` and
`AgentPromptSectionAdapter` translate the live
`BaseAgent` into the grantable ports, each constructed from a bound method rather
than from the agent object. `agent_host_ports` builds one declaration's grantable
table; `register_agent_tool_plugins` is the composition/registrar wiring helper.

The registrar-local mount seam reaches `BaseAgent._mount_official_tool`, then
`_add_tool` at the common model-facing boundary
(`src/lingtai/kernel/base_agent/tools.py`), whose existing semantics — including
the tool-surface seal after `start()` and same-name replacement for
nonreserved tools — are unchanged by this contract. This component adds a
common-boundary rejection for reserved official names. Direct generic `add_tool`,
external stdio/HTTP catalogs, and foreign registrar declarations cannot overwrite
an existing official claim; same-name replacement for nonreserved tools remains.

The Composition Root stays `src/lingtai/agent.py` and the capability `setup()`
it drives: it selects which declarations are registered and when. This
component never selects.

## Contract rules

1. **Declaration validity is checked at construction.** A declaration MUST have
   a non-empty `name`, `manual`, and `description`; at least one operational
   action; no duplicate action; no attempt to declare the reserved `manual`
   action; exactly one `input_schemas` entry per operational action; a callable
   `binder`; and a duplicate-free `requires` drawn only from
   `GRANTABLE_HOST_PORTS`. A violation raises `ToolPluginDeclarationError` at
   import.
2. **The reserved `manual` action is appended, never declared.**
   `public_actions` is `actions + ("manual",)` and `public_input_schemas()`
   adds the declaration's own `manual_input_schema`. The family still owns the
   manual child's handler and its packaged or installed source; this component
   only guarantees the reserved slot exists exactly once and last. The
   reserved-action rule itself remains normative in
   [`src/lingtai/tools/CONTRACT.md`](../../tools/CONTRACT.md).
3. **`OFFICIAL_TOOL_PLUGIN_NAMES` is the reserved official namespace.** It is a
   static literal in this package holding names only — never a module path, an
   import, or family behavior. A declaration whose name is absent is refused
   with `UnreservedToolPluginNameError`. Adding a name is a reviewed change to
   this contract.
4. **Name conflicts fail before bind.** `register_official_tool_plugins`
   validates every name in the batch — reserved, unique within the batch, and
   not already claimed by a *different* declaration — **before** the first
   `bind()`, the first `activate()`, and the first `mount_tool()`. A conflict
   raises `DuplicateToolPluginNameError` and leaves the live tool surface and
   the claim map exactly as they were. There is no last-registration-wins path
   here and a name conflict never leaves a partially mounted batch. The mount
   callback receives only a registrar-issued, one-use transaction created after
   this declaration's successful bind. Its issuer, persistent declaration anchor,
   and exact canonical bound-result identity are checked before handler/schema
   publication; a caller-supplied ``BoundToolPlugin`` or public adapter cannot
   manufacture an official mount. The Agent claim view is read-only and claims
   are accepted only for that transaction after a successful mount, not from a
   caller-supplied name/declaration. This is a trusted-in-process Python
   provenance boundary, not an absolute defense against code that deliberately
   mutates private module or Agent state. That all-or-nothing promise is scoped to the name checks, exactly:
   registrar mounts and claims each member as it goes, so a failure raised afterwards by
   `ports_for`, `grant`, `bind`, `activate`, or `mount_tool` on member *N*
   leaves members 1..*N*-1 mounted and claimed and propagates. This component
   owns no unmount port and MUST NOT be described as transactional beyond
   names.
5. **Re-registration of the same declaration is idempotent.**
   `_setup_from_init` re-runs the whole boot on every refresh, so re-registering
   the identical declaration object for an already-claimed name re-binds and
   re-mounts without raising. A *different* declaration claiming a live name is
   the collision rule 4 refuses.
6. **`bind()` is pure composition, and it checks what it composed.** It MUST
   NOT mount, activate, start a process or server, open a connection, or write
   a prompt section. It returns a `BoundToolPlugin`, whose name is checked
   against the declaration so a family cannot bind onto a name the kernel did
   not reserve for it. A host granted to a different plugin is refused with
   `HostPortError`.

   The bound plugin's **advertised action inventory** is checked too: the
   schema it ships must advertise exactly `public_actions`, or `bind()` raises
   `ToolPluginDeclarationError`. Declared-versus-shipped agreement is therefore
   enforced on every boot, in the registrar's own path, rather than asserted
   once in a test. This is the *only* structural fact this component reads out
   of a composed schema — it composes none and validates no other part of the
   LTP envelope, which stays owned by
   [`src/lingtai/tools/CONTRACT.md`](../../tools/CONTRACT.md). The remaining
   agreement is upheld at the source: a declaring family MUST derive its
   composed tool name, its per-action `input` schemas, and its installed manual
   destination *from its own declaration* rather than restating them, so there
   is no second literal to drift.
7. **Registration is not activation.** `BoundToolPlugin.activate` is the
   plugin's explicit, separate boot-presentation step. The registrar runs it
   only after every name check passes, and immediately before mounting. It MUST
   NOT start a server, spawn a process, or open a transport.
8. **Least privilege is enforced at grant.** `ToolPluginHost.grant` raises
   `HostPortError` when a required port is missing, and grants nothing beyond
   `requires`. `tool_mount` is never grantable.
9. **Public surface preservation.** Recutting a family onto this contract MUST
   NOT change its public tool name, action inventory or spelling, per-action
   strict `input` schemas, the closed LTP root, result shapes, error
   vocabulary, authorization gates, or side effects. It is an internal
   least-privilege recut, not a new public capability.

## Contract tests

`tests/test_tool_plugin_declaration.py` is the shared contract suite:

- declaration staticness and the `mcp` declared-versus-composed surface
  agreement (`test_mcp_declaration_is_static_and_needs_no_agent`,
  `test_mcp_is_reserved_and_declares_only_the_ports_it_consumes`);
- construction-time validation, including the reserved `manual` action,
  duplicate/empty actions, schema/action agreement, and the non-grantable
  `tool_mount` port;
- least privilege — granted-port scoping, `AttributeError` on an ungranted
  port, missing-port failure, foreign-host refusal, and that neither the facade
  nor the bound plugin exposes the `Agent` on its public surface;
- fail-fast names — unreserved name, duplicate within one batch, and a second
  different declaration against a live claim, each asserting zero mounts, zero
  binds, and an unchanged claim map;
- boot-path observability — an official-name conflict raised out of
  `Agent._setup_capability`, an unreserved name and a missing host port each
  failing a real `Agent(...)` boot instead of being absorbed as
  `capability_skipped`;
- declared-versus-shipped agreement — a plugin advertising undeclared actions
  or no action enum is refused at `bind()` with nothing mounted or claimed, and
  `mcp`'s manual destination and per-action `input` schemas follow its
  declaration;
- atomicity, stated exactly — a mid-batch host-port failure leaves the earlier
  member mounted and claimed;
- claim-map lifecycle — the claim is reachable through the public
  `official_tool_plugins` property, whose view cannot be cleared or overwritten;
  persistent declaration anchors prevent mutable backing-map tampering from
  admitting a foreign declaration, the live claim is dropped when a refresh
  disables the capability, and it is re-claimed (and still not overwritable)
  when it does;
- ordering — `bind` alone activates and mounts nothing;
  `activate` runs before `mount`;
- idempotent re-registration (the refresh path);
- the live slice — boot claims `mcp` and mounts exactly one `mcp` tool, a
  post-seal mount raises, a foreign declaration cannot take the live name, and
  neither a foreign `BoundToolPlugin` nor a directly constructed transaction
  can replace the official handler/schema/claim; the prompt-section port writes
  only this plugin's protected section;
- kernel isolation — no file under `src/lingtai/kernel/` imports
  `lingtai.tools`, with relative imports resolved so the kernel's own
  `base_agent.tools` module is not mistaken for it.

Also decisive for a change here:
`tests/test_mcp_capability.py`, `tests/test_tool_family_mcp_migration_parity.py`,
`tests/test_mcp_identity_discovery.py` (the slice's unchanged public behavior),
`tests/test_curated_mcp_plugin_package.py` (the external transport route is
undisturbed), and `tests/test_architecture_documents.py`.

## Maintenance

See the `maintenance` frontmatter above. The paired
[`ANATOMY.md`](ANATOMY.md) owns where the code lives and how it composes;
[`BEHAVIORS.md`](BEHAVIORS.md) owns the agent-executable proof of the clauses
above. Change one, re-check the other two.
