---
related_files:
  - ANATOMY.md
  - src/lingtai/intrinsic_skills/ANATOMY.md
  - src/lingtai/tools/BEHAVIORS.md
  - src/lingtai/tools/CONTRACT.md
  - src/lingtai/kernel/tool_plugin/ANATOMY.md
  - src/lingtai/tools/feishu/BEHAVIORS.md
  - src/lingtai/tools/psyche/ANATOMY.md
  - src/lingtai/tools/plugin/ANATOMY.md
  - src/lingtai/tools/plugin/CONTRACT.md
  - src/lingtai/ANATOMY.md
  - src/lingtai/kernel/ANATOMY.md
  - src/lingtai/tools/notification/ANATOMY.md
  - src/lingtai/tools/telegram/BEHAVIORS.md
  - src/lingtai/tools/web_search/ANATOMY.md
  - src/lingtai/tools/web_search/CONTRACT.md
  - src/lingtai/tools/task_card/ANATOMY.md
  - src/lingtai/tools/task_card/CONTRACT.md
  - src/lingtai/tools/file/ANATOMY.md
  - src/lingtai/tools/file/CONTRACT.md
  - src/lingtai/tools/vision/ANATOMY.md
  - src/lingtai/tools/vision/CONTRACT.md
  - src/lingtai/tools/soul/ANATOMY.md
  - src/lingtai/tools/soul/CONTRACT.md
  - src/lingtai/tools/browser/ANATOMY.md
  - src/lingtai/tools/tool_family/ANATOMY.md
  - src/lingtai/tools/tool_family/CONTRACT.md
  - src/lingtai/tools/system/ANATOMY.md
  - src/lingtai/tools/system/CONTRACT.md
  - src/lingtai/tools/context/ANATOMY.md
  - src/lingtai/tools/context/CONTRACT.md
  - src/lingtai/tools/knowledge/ANATOMY.md
  - src/lingtai/tools/knowledge/CONTRACT.md
  - src/lingtai/tools/pad/ANATOMY.md
  - src/lingtai/tools/pad/CONTRACT.md
  - src/lingtai/tools/lingtai/ANATOMY.md
  - src/lingtai/tools/lingtai/CONTRACT.md
  - src/lingtai/tools/avatar/ANATOMY.md
  - src/lingtai/tools/avatar/CONTRACT.md
  - src/lingtai/tools/bash/ANATOMY.md
  - src/lingtai/tools/bash/CONTRACT.md
  - src/lingtai/tools/bash/_tool_family.py
  - src/lingtai/adapters/browser_transport.py
  - src/lingtai/mcp_servers/_plugin.py
  - src/lingtai/mcp_servers/telegram/plugin.py
  - src/lingtai/mcp_catalog.json
  - src/lingtai/services/plugin_registry.py
  - src/lingtai/kernel/base_agent/tools.py
  - src/lingtai/tools/registry.py
  - src/lingtai/tools/glossary_validator.py
  - ENVIRONMENT_VARIABLES.md
  - src/lingtai/tools/__init__.py
  - src/lingtai/tools/_manual.py
  - src/lingtai/tools/email/ANATOMY.md
  - src/lingtai/tools/i18n/__init__.py
  - src/lingtai/tools/i18n/en.json
  - src/lingtai/tools/i18n/wen.json
  - src/lingtai/tools/i18n/zh.json
  - src/lingtai/tools/mcp/ANATOMY.md
  - src/lingtai/tools/skills/ANATOMY.md
  - src/lingtai/tools/daemon/ANATOMY.md
  - src/lingtai/tools/daemon/interactive_terminal/ANATOMY.md
maintenance: |
  Keep this registry Anatomy connected to its parent and the unified web owner.
  Browser is an internal browse child, not a second public capability. The
  generic tool_family package is optional composition infrastructure any
  future family migration may adopt, not a second registry. context is its
  thirteenth consumer and the fifth migrated intrinsic. Update
  structural claims with code and keep reciprocal graph edges valid.
  The curated-MCP packaging, catalog, Agent Plugins, and host tool-registration
  entries in related_files are navigation for the paired Contract's
  `### Tool-to-MCP Plugin Contract`. The form that Contract selects is now the
  kernel-owned declared host-plugin contract
  (`src/lingtai/kernel/tool_plugin/ANATOMY.md`, linked here); the curated
  descriptor/catalog route is the retained external-transport/launcher adapter
  over a declaration, and the Agent Plugins entry is the excluded external
  standard kept only as the registration-versus-activation precedent. They are
  not a claim that any family here beyond `mcp` is declared or wrapped today,
  and the normative rules — including the selected form, the reserved
  official-name rule, and the governed-surface classification — stay in the
  Contract and in the kernel component's own Contract.
  Capability mentions in any document require explicit bidirectional
  related_files mapping to the implementing code (see root ## Maintenance).
---
# src/lingtai/tools/

This package owns concrete built-in tools and the registry that composes them
onto an Agent. The kernel owns generic tool machinery; this layer owns public
capability names and lazy adapters.

## Components

- `CONTRACT.md` — the LingTai Tool Protocol (LTP): the future canonical
  model-facing tool call contract, the two-level family/action settings
  addressing and ownership rules, the explicit per-tool migration boundary, and
  `### Tool-to-MCP Plugin Contract`, the additive future target for wrapping
  each first-party family in the selected curated-descriptor MCP plugin package
  form that owns its manual.
- `BEHAVIORS.md` — the paired LABT file: LP001 guards the closed LTP envelope,
  LP002 guards the Tool-to-MCP Plugin Contract's status, its two-class governed
  surface, its single selected wrapper form, the document graph, and the
  current-evidence claims.
- `registry.py` — intrinsic mapping, public `BUILTIN_TOOLS`, input aliases,
  defaults, normalization, setup, and check-caps metadata
  (`src/lingtai/tools/registry.py:39-344`).
- `web_search/` — public `web` composition owner for search, browse, settings,
  and manual (`src/lingtai/tools/web_search/ANATOMY.md`).
- `task_card/` — intrinsic channel-neutral declarative Task Card producer: one
  public `task_card` family, one agent-local artifact under `taskcard/`, and
  no transport ownership (`src/lingtai/tools/task_card/ANATOMY.md`).
- `file/` — sole owner of the public `file` capability: the composed schema,
  the envelope dispatch, and all five operation implementations in
  `_read.py`/`_write.py`/`_edit.py`/`_glob.py`/`_grep.py`
  (`src/lingtai/tools/file/ANATOMY.md`).
- `vision/` — public `vision` composition owner: one action-separated family
  with canonical `analyze`/`manual` children over the existing direct
  provider routing (`src/lingtai/tools/vision/ANATOMY.md`).
- `browser/` — internal static browse Core/Port used by `web`
  (`src/lingtai/tools/browser/ANATOMY.md`).
- `tool_family/` — generic, optional ToolFamily/ChildTool schema-composition
  and dispatch infrastructure implementing the LTP v2 envelope, and the
  reusable ManualTool builder; `web` is its first real consumer, `mcp` its
  second, `knowledge` its third, `file` its fourth, `vision` its fifth,
  `avatar` its sixth, `soul` its seventh, `shell` its eighth, `skills` its
  ninth, `notification` its tenth, `system` its eleventh, `daemon` its
  twelfth, `context` its thirteenth, and `plugin` its fourteenth
  (`src/lingtai/tools/tool_family/ANATOMY.md`).
- `plugin/` — the `plugin` capability: the per-agent Agent Plugins
  (agent-plugins.org, v1.0.0) catalog and registration snapshot, structural twin
  of `mcp` with the same `info`/`manual` children and the same tool/service split
  (`src/lingtai/tools/plugin/ANATOMY.md`, `src/lingtai/tools/plugin/CONTRACT.md`).
  A plugin *declared* in `init.json` `manifest.plugins` is mounted at boot — its
  `skills/` composed into the skills catalog, its `mcp.json` servers registered
  in `mcp_registry.jsonl` with `source="plugin:<name>"` — while one merely
  *discovered* on an inherited skills path is listed and nothing more. The tool
  itself stays read-only: mounting happens in
  `Agent._register_declared_plugins` before capability setup, unreachable from
  any action, which is what makes it safe in `CORE_DEFAULTS`. Registration is
  registry-level like `addons:[]`: registered, never running.
- `system/` — mandatory intrinsic owning the public `system` family: runtime,
  lifecycle, preset, and identity-naming actions behind one model-facing root
  (`src/lingtai/tools/system/ANATOMY.md`). It owns no public context-hygiene
  action — `summarize.py` stays here as the private engine `context` drives. Like `soul` and `notification` it is
  an intrinsic rather than a manager-owning capability, so it composes its
  schema from a module-level schema-only family and builds a dispatching one
  per `handle(agent, args)` call.
- `knowledge/` — private durable knowledge catalog, migrated to the LTP v2
  family envelope with the unchanged public actions `info`/`manual`
  (`src/lingtai/tools/knowledge/ANATOMY.md`).
- `soul/` — the `soul` intrinsic family: six action-separated children
  (`inquiry`, `flow`, `config`, `voice`, `dismiss`, `manual`) behind one
  model-facing root (`src/lingtai/tools/soul/ANATOMY.md`).
- `bash/` — public `shell` composition owner for run/poll/cancel/manual
  (`src/lingtai/tools/bash/ANATOMY.md`); the public model-facing schema is
  the ToolFamily-composed LTP v2 envelope (`bash/_tool_family.py`) and is the
  package's only schema/description pair, while `ShellManager` remains the
  unchanged execution engine behind an internal-only flat call shape.
- `notification/` — mandatory intrinsic owning the public `notification`
  family: `check`, three atomic dismiss actions, and `manual`
  (`src/lingtai/tools/notification/ANATOMY.md`). Its public model-facing schema
  is the ToolFamily-composed LTP v2 envelope; unlike the capability families it
  builds its dispatching family per call, because an intrinsic receives `agent`
  per call rather than owning a manager.
- `context/` — mandatory intrinsic owning the public `context` family: the
  agent's context lifecycle and hygiene — `molt`, `summarize`, `rebuild`, and
  `manual` — behind one root (`src/lingtai/tools/context/ANATOMY.md`). It
  replaces the former `psyche` root, which no longer exists at any
  model-visible or registry level: the two name actions moved to `system` and
  the public `system` summarize action moved in. `summarize` records only;
  `rebuild` is the sole active full reconstruction: canonical prompt composition,
  summary application, then provider replay. Refresh/molt invoke the same
  internal contract passively. Like `soul`/`notification` it builds its family
  per call and alone consumes kernel `_tc_id`.
- `pad/` — mandatory `append | manual` family. `append` validates/persists pinned
  references without hot-loading; private `_pad_load` participates only in the
  Agent's canonical reconstruction path (`src/lingtai/tools/pad/ANATOMY.md`).
- `lingtai/` — mandatory manual-only identity signpost. Private
  `_lingtai_load` composes character during canonical reconstruction; generic
  durable mutation is owned by `file` (`src/lingtai/tools/lingtai/ANATOMY.md`).
- `email/` — the filesystem-based `email` intrinsic: mailbox I/O, composition,
  search, contacts, and delivery, migrated to the LTP v2 family envelope
  (`src/lingtai/tools/email/ANATOMY.md`).
- `_manual.py` — bounded installed-manual loader
  (`src/lingtai/tools/_manual.py:1-61`). `load_installed_manual(source,
  skill_name)` resolves the agent working directory from either shape a family
  can hold: the live `Agent` (private `_working_dir`) for an unmigrated family,
  or a `lingtai.kernel.tool_plugin.WorkdirPort` (`path`) for one recut onto the
  declared host-plugin contract, so one loader still serves every family. A
  source that is neither raises an `AttributeError` naming that fact.
- `__init__.py` — the package docstring that fixes the flat one-directory-per-tool
  layout and the `lingtai → lingtai.tools → lingtai.kernel` import DAG enforced by
  `tests/test_kernel_isolation.py` (`src/lingtai/tools/__init__.py:1-12`).
- `i18n/` — the tool locale catalog (`en`/`zh`/`wen`) holding the *human-facing
  manager prose* concrete tools resolve through `lingtai.kernel.i18n.t(lang, key)`
  (`soul.system_prompt`, `knowledge.preamble`, `email.unread_digest`, …). It owns
  no model-facing schema or description text: that lives in canonical English tool
  source plus the per-package `glossary-{en,zh,wen}.md` resources
  (`src/lingtai/tools/i18n/__init__.py:1-14`).

## Connections

`Agent` calls registry setup. The public `web` row imports
`lingtai.tools.web_search` lazily. That owner imports the browser Core and
provider factory only at composition or action boundaries, and imports
`tool_family` to compose its schema and (optionally) dispatch. The public
`vision` row imports `lingtai.tools.vision`, which imports `tool_family` the
same way and reaches `lingtai.services.vision` only on the selected direct
route. The pinned browser transport remains an outer adapter. `web_search` is
accepted only as a one-way configuration input alias and is never emitted as a
public name. `soul` is a mandatory intrinsic (`INTRINSICS`, not
`BUILTIN_TOOLS`) and imports `tool_family` statically; because it is a module
rather than a per-Agent manager object, it composes its schema from a
module-level schema-only `ToolFamily` and builds an agent-bound one per
`handle(agent, args)` call. The public `shell` row imports `lingtai.tools.bash`
lazily; `bash/__init__.py` imports `tool_family` (via `bash/_tool_family.py`)
to compose the public action-separated schema (re-exported as the package's
canonical `get_schema`/`get_description`) and to translate `action`/`input`
calls into the internal flat shape `ShellManager.handle` consumes. `bash` is
the one-way legacy input alias for `shell` (`registry.py`) and is never
emitted as a public name or a second schema.

The public `file` row imports `lingtai.tools.file` lazily; that owner binds its
five operation modules once per manager and reaches the working tree only
through the injected `FileIOService`. Unlike `bash`/`web_search`, the file
migration kept no configuration aliases: `read`, `write`, `edit`, `glob`, and
`grep` are unknown capability names that fail loudly. Capability groups no
longer exist at all — `file` was `_GROUPS`' only entry, so the map,
`expand_groups`, and every consumer were deleted rather than left empty.

The public `task_card` row imports `lingtai.tools.task_card` lazily and owns
the artifact writer entirely within `lingtai.tools`. It writes only
`taskcard/status` and `taskcard/taskcard.md`; consumer-specific reading,
polling, and projection stay outside this package.

The form the paired Contract's `### Tool-to-MCP Plugin Contract` selects is the
kernel-owned declared host-plugin contract, and exactly one family in this
package is wired onto it today. These are the roles it separates, and where
each one already lives. `src/lingtai/kernel/tool_plugin/ANATOMY.md` is the
selected form's own component: the static `ToolPluginDeclaration`, the
least-privilege host ports, the reserved `OFFICIAL_TOOL_PLUGIN_NAMES` list, and
the fail-fast registrar. `src/lingtai/tools/mcp/__init__.py` `DECLARATION` is
the one declared slice — `mcp` binds against two granted host ports instead of
the whole `Agent`, with its public tool name, actions, inputs, and result
shapes unchanged. Every other family here still boots through `setup(agent)`
with the whole `Agent` and is a future migration unit.

`registry.py` remains the current first-party composition point and stays a
hand-edited static table: it imports no `lingtai.mcp_servers` packaging and no
plugin discovery, so no family *in this package* is wrapped as an MCP plugin
package; the Contract's governed surface is wider than this directory and also
classifies the kernel-shipped MCP families under `src/lingtai/mcp_servers/`.
`src/lingtai/mcp_servers/_plugin.py` is the retained curated
*external-transport/launcher* route — one curated package binding its server,
bundled `SKILL.md`, launch record, and reserved `manual` child, explicitly not
a plugin runtime — reclassified by the Contract as one adapter form over a
declaration rather than the required form of every official tool.
`src/lingtai/mcp_servers/telegram/plugin.py` is its reference descriptor slice
and `src/lingtai/mcp_catalog.json` the shipped catalog record each descriptor
must agree with.
`src/lingtai/services/plugin_registry.py` is the external Agent Plugins v1.0.0
*declaration and boot-registration* path, with activation kept separate (the
rendering tool is `src/lingtai/tools/plugin/ANATOMY.md`). The Contract excludes
that standard from conversion; it is navigation to the precedent for
registration versus activation, not an alternative declaration form.
`src/lingtai/kernel/base_agent/tools.py` is the final common model-facing mount
point. `_add_tool` retains same-name replacement for nonreserved tools, but its static reserved-name guard rejects generic `add_tool` and external stdio/HTTP catalogs before publication.

The registrar reaches the boundary only through a registrar-issued one-use
transaction created after the declaration's successful bind. The Agent mount
seam verifies the persistent declaration anchor and exact canonical bound result
before publication; a caller-supplied foreign plugin or constructed transaction
is refused. A live official claim is read-only through its public view and can
be recorded only from that transaction after mount. This is trusted-in-process
Python provenance, not an absolute defense against deliberate private-state
mutation. The Contract's collision policy is scoped to official declared names,
which the registrar refuses before any bind or mount. Read the Contract for the
rules; this file only names the route.

## Composition

The parent [`src/lingtai/ANATOMY.md`](../ANATOMY.md) owns Agent composition.
The paired tools Contract owns LTP: the future canonical `action` / `input` /
`reasoning` / `summarize` public call shape, family/action settings ownership,
the migration boundary, and the Tool-to-MCP Plugin Contract — whose selected
form is owned by `src/lingtai/kernel/tool_plugin/CONTRACT.md`. Read them there;
this Anatomy does not restate those promises, and `BEHAVIORS.md` LP002 (with
the kernel component's TP001/TP002) owns their verification. The web Contract specializes
that promise for the first real implementation; its Anatomy and the internal
browser Anatomy provide progressive disclosure. Other tool packages retain their
existing public shapes until explicitly migrated.

## State

No mutable state lives at package root. `WebManager` owns per-Agent engine
specs, lazy provider cache, BrowserEngine refs/snapshots/cursors, and settings
observations. No process-global environment mutation or cross-Agent state is
owned here.

## Notes

Retained physical legacy directories (`bash/`, `web_search/`) and
provider-native wire strings remain for compatibility. They must not become
registry, schema, prompt, check-caps, manual, or catalog entries under those old
public names. The five pre-migration file packages are not among them: they were
deleted outright into `file/`, so there is no legacy directory, contract,
glossary, or alias left for that surface.
