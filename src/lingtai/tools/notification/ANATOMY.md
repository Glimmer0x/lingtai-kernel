---
related_files:
  - src/lingtai/tools/notification/CONTRACT.md
  - src/lingtai/tools/notification/BEHAVIORS.md
  - src/lingtai/tools/ANATOMY.md
  - src/lingtai/services/LICC_NOTIFICATION_CONTRACT.md
  - src/lingtai/tools/notification/__init__.py
  - src/lingtai/tools/notification/plugin.py
  - src/lingtai/tools/notification/schema.py
  - src/lingtai/tools/_plugin.py
  - src/lingtai/tools/_manual.py
  - src/lingtai/tools/tool_family/ANATOMY.md
  - src/lingtai/tools/registry.py
  - src/lingtai/kernel/notifications.py
  - src/lingtai/kernel/base_agent/turn.py
  - src/lingtai/kernel/tool_result_summary.py
  - src/lingtai/agent.py
  - src/lingtai/intrinsic_skills/system-manual/SKILL.md
  - src/lingtai/tools/notification/manual/SKILL.md
  - src/lingtai/tools/notification/manual/reference/channel-model/SKILL.md
  - src/lingtai/tools/notification/manual/reference/dismissal-safety/SKILL.md
  - tests/test_notification_tool.py
  - tests/test_intrinsic_tool_plugin_package.py
  - tests/test_notification_delay_alarm.py
  - tests/test_daemon_attention_delay.py
  - tests/test_system_dismiss.py
  - src/lingtai/tools/notification/glossary-en.md
  - src/lingtai/tools/notification/glossary-zh.md
  - src/lingtai/tools/notification/glossary-wen.md
maintenance: |
  tool_family is generic optional infrastructure this package composes onto;
  notification's own per-call family construction, null-stripping, and manual
  presentation adapter remain here.
  Keep related_files repo-relative, duplicate-free, and linked to real files.
  Keep this component's ANATOMY.md and CONTRACT.md reciprocal and keep
  parent/child anatomy links bidirectional. Code is the structural source of
  truth: update this anatomy in the same change that moves files, symbols,
  connections, composition, or state. Verify every changed citation and run the
  architecture-document validation before merge.
  Follow the root Anatomy/Contract pairing rule, report mismatches, and do not duplicate or auto-fix the rule here.
  Capability mentions in any document require explicit bidirectional
  related_files mapping to the implementing code (see root ## Maintenance).
---
# Notification Tool Anatomy

`src/lingtai/tools/notification/` is the mandatory agent-callable notification
surface. It composes ten actions: four hook-registry actions (`add`, `drop`,
`edit`, `list`), `check`, three atomic dismissal actions, consumer-only `delay`,
and the strictly read-only `manual` action. Notification Core owns mirror guards and Store use;
the tool owns only schema composition, envelope dispatch, the check
placeholder, argument adaptation, hook-manifest forwarding, and installed-manual
presentation.

The package is a **plugin-style package**: it ships the tool code, the
`manual/` skill tree it owns, and the descriptor that binds them
(`plugin.py`). `NOTIFICATION_PLUGIN` states the public name, the summary the
model description opens with, the packaged skill's catalog name, and the nine
actions the package declares; the reserved `manual` action is appended by
`lingtai.tools._plugin.IntrinsicToolPlugin`, never declared here. The
descriptor is declarative: `registry.INTRINSICS` remains the runtime source the
kernel reads, and `Agent._install_intrinsic_manuals()` remains the code that
mounts the manual.

Since the LTP v2 migration the public model-facing shape is the closed
`action` + `input` + `reasoning` + `summarize` envelope, with each action's
arguments in its own strict `input` object. Schema composition and envelope
dispatch delegate to the generic `tool_family` infrastructure; this package
retains ownership of the action implementations, the per-action schemas, and
the manual presentation shape. The public tool name and the five pre-existing
action values are unchanged; the four hook-registry actions are new.

## Components

- `plugin.py` is this package's identity: `NOTIFICATION_PLUGIN` (name,
  package, summary, packaged skill name) and `NOTIFICATION_DECLARED_ACTIONS`,
  the nine actions the package owns, with `manual` deliberately absent;
  `NOTIFICATION_ACTIONS` is the plugin-composed public list
  (`src/lingtai/tools/notification/plugin.py:23-55`). The packaged
  `manual/SKILL.md` is read and its frontmatter `name` checked when the
  descriptor is constructed, so a lost or renamed manual fails at import
  instead of degrading for every agent.
- `manual/` is the package-owned skill tree — the router `SKILL.md` plus the
  `channel-model` and `dismissal-safety` reference sub-skills.
  `Agent._install_intrinsic_manuals()` copies it to
  `.library/intrinsic/capabilities/notification/`, the plugin's declared
  `mount_name`, which is the path the reserved `manual` child reads.
- `schema.py` is data only: `DECLARED_INPUT_SCHEMAS` holds each declared
  action's own strict `input` schema, with optional dismiss fields in the
  provider-compatible nullable representation; `ACTION_ENUM_DESCRIPTION` and
  `get_description()` hold the canonical-English prose, the latter composed
  from the plugin's summary so the opening line has one owner
  (`src/lingtai/tools/notification/schema.py:36-313`). It declares no `manual`
  schema and deliberately defines no `get_schema`.
- `ACTION_ORDER` / `INPUT_SCHEMAS` in `__init__.py` are the plugin-composed
  public action order and per-action schema map — declared data plus the
  reserved `manual` appended from the one shared
  `tool_family.manual.MANUAL_INPUT_SCHEMA`
  (`src/lingtai/tools/notification/__init__.py:81-92`).
- `_schema_only_family()` / `_FAMILY` build the import-time `ToolFamily` used
  only to compose the schema; constructing it at import proves the fixed
  ten-child registry has no duplicate or reserved-`manual` collision
  (`src/lingtai/tools/notification/__init__.py:108-141`).
- `get_schema()` returns the composed family schema and substitutes
  notification's own action prose for the generic composer's neutral
  placeholder (`src/lingtai/tools/notification/__init__.py:144-159`).
- `_build_family()` builds the per-call dispatching `ToolFamily` with handlers
  bound to the calling `agent` via `NOTIFICATION_PLUGIN.build_family(...,
  agent=agent)`, so the `manual` child is appended by the plugin — bound to the
  package's own installed skill, never to an entry in the handler map — and
  stays unwrapped (`src/lingtai/tools/notification/__init__.py:383-432`).
- `handle()` strips kernel-injected `_tc_id`, delegates envelope validation and
  dispatch to that family, adapts the `manual` child result, and normalizes the
  generic `ACTION_REQUIRED` error back to the pinned unknown-action shape
  (`src/lingtai/tools/notification/__init__.py:434-473`).
- `_strip_nulls()` converts explicit `null` optionals back to absent so the
  handlers' `args.get(..., default)` defaulting is preserved
  (`src/lingtai/tools/notification/__init__.py:162-172`).
- `_check()` returns the dict-shaped placeholder onto which the turn loop can
  stamp the current notification payload
  (`src/lingtai/tools/notification/__init__.py:175-180`).
- `_adapt_manual_result()` flattens the shared ManualTool child's canonical
  `content`/`structuredContent` result to notification's pinned public
  `status`/`notification_manual`/`manual_path` shape and forwards the loader's
  degraded sentence unchanged: the mount name is now the tool name, so the
  loader already produces the contract-pinned text
  (`src/lingtai/tools/notification/__init__.py:183-213`).
- `_dismiss_channel()` adapts a whole-channel request and retains the inner
  event/ref rejection as defense in depth behind the envelope's earlier,
  no-I/O rejection (`src/lingtai/tools/notification/__init__.py:216-258`).
- `_dismiss_event()` and `_dismiss_ref()` adapt targeted system-event removal
  while defaulting the channel to `system`
  (`src/lingtai/tools/notification/__init__.py:261-304`).
- `_delay()` delegates to `notifications.delay_notification_channel()`, which
  persists one active private `.notification/.delay_state.json` record, arms a
  request-id-guarded process timer, and never mutates the target producer file.
- `_add_hook()`, `_drop_hook()`, `_edit_hook()`, and `_list_hooks()` adapt the
  hook-registry actions and delegate to
  `lingtai.kernel.notifications.add_hook` / `drop_hook` / `edit_hook` /
  `list_hooks`, which validate manifests, enforce name/channel uniqueness, and
  write `.notification/hooks.json` through Store family 8
  (`src/lingtai/tools/notification/__init__.py:312-380`).
- `registry.INTRINSICS` registers `notification` as a mandatory intrinsic next
  to email, system, context, psyche, and soul
  (`src/lingtai/tools/registry.py:70-77`). That shipped record must equal
  `NOTIFICATION_PLUGIN.intrinsic_declaration()`; the registry module, not the
  descriptor, is what the kernel actually reads.

## Connections

- `BaseAgent._wire_intrinsics()` binds every registered intrinsic module's
  `handle()` into the agent tool surface
  (`src/lingtai/kernel/base_agent/__init__.py:783-796`).
- The turn loop calls `attach_active_notifications()` after ordinary tool
  results so `check` receives the canonical `_meta.agent_meta.notifications.attention` and
  `_meta.agent_meta.guidance.transient` stamp
  (`src/lingtai/kernel/base_agent/turn.py:1748-1764`;
  `src/lingtai/kernel/meta_block.py:2944`).
- All three dismissal handlers delegate to
  `lingtai.kernel.notifications.dismiss_channel(...,
  invoked_by="notification")`; Core owns allowlists, producer guards,
  stale-version checks, protected channels, post-molt acknowledgement, and
  targeted event/ref removal (`src/lingtai/kernel/notifications.py:923`).
  The four hook-registry handlers delegate to Core's
  `add_hook`/`drop_hook`/`edit_hook`/`list_hooks`, which own manifest
  validation, uniqueness, and the family-8 Store writes
  (`src/lingtai/kernel/notifications.py:358-512`).
- `Agent._install_intrinsic_manuals()` copies this package's own `manual/`
  tree into `.library/intrinsic/capabilities/notification/` — the same
  `install_from` path every other tool-owned manual uses — and the `manual`
  child reads it back through `tool_family.manual.build_manual_child` and the
  shared `tools/_manual.py::load_installed_manual` loader.
  `tools/_manual.py::installed_manual_path` is the one definition of that path,
  which `IntrinsicToolPlugin.installed_manual_path()` publishes as the mount
  point so loader and descriptor cannot disagree (`src/lingtai/agent.py:551-640`).
- `src/lingtai/tools/_plugin.py` supplies the shared `IntrinsicToolPlugin`
  descriptor: identity validation, packaged-skill loading, the plugin-owned
  reserved `manual` child, `actions()`/`action_input_schemas()`/`build_family()`,
  and the `intrinsic_declaration()`/`tool_manifest()` host records. It
  discovers, imports, activates, and registers nothing — notification is the
  one package wired through it today.
- `base_agent.tools._dispatch_tool()` injects `_tc_id` into every intrinsic's
  args; only `context.molt` consumes it, so `handle()` strips it before the
  closed envelope is validated (`src/lingtai/kernel/base_agent/tools.py:28-35`).
- `kernel/tool_result_summary.py::_LTP_V2_MIGRATED_FAMILIES` lists
  `notification`, so the advertised root `summarize` boolean is actually
  honored as the a-priori summary control rather than silently ignored
  (`src/lingtai/kernel/tool_result_summary.py:150-183`).
- The notification manual is the progressive-disclosure router for procedures;
  its channel-model and dismissal-safety children hold protocol and safety
  depth. The paired Contract defines the normative tool Port and invariants.

## Composition

- **Parent:** `src/lingtai/tools/` (see `src/lingtai/tools/ANATOMY.md`).
- **Generic infrastructure:** `src/lingtai/tools/tool_family/` supplies
  `ChildTool`/`ToolFamily` schema composition and envelope dispatch plus the
  reserved `manual` child. It is optional infrastructure this package composes
  onto, not a base class it inherits from; unlike `web`, which owns a
  per-Agent manager, this intrinsic builds its dispatching family per call
  because `agent` only arrives per call.
- **Core dependency:** `src/lingtai/kernel/notifications.py` and the notification
  Store behind it. `delay` uses the same native mutation lock directly for its
  private dotfile plus `delay-alarm` mirror, without widening the Store Port. The four hook-registry actions (`add`/`drop`/`edit`/`list`)
  mutate the Store's family-8 hook-manifest registry
  (`load_hook_manifests`/`update_hook_manifests`/`stat_hook_registry`,
  `.notification/hooks.json`);
  the read and dismiss actions add no Store operation.
- **Turn-loop adapter:** `src/lingtai/kernel/base_agent/turn.py` completes the
  `check` placeholder with model-visible state.
- **Installed-resource adapter:** `src/lingtai/agent.py` installs the intrinsic
  skill tree consumed by `manual`.
- **Sibling ownership:** `system` retains `summarize`; producer tools retain
  their own canonical read/dismiss operations.

## State

- `_check()` is in-memory and write-free.
- The `manual` child reads one fixed installed text file and does not inspect or
  mutate `.notification/`, Notification Store state, producer state,
  fingerprints, acknowledgements, or notification logs.
- Envelope validation runs before any handler, so an unknown action, an unknown
  root field, or an `input` key belonging to another action fails with no
  notification I/O at all.
- Dismiss handlers own no state directly. Through notification Core they clear
  notification mirrors or remove targeted system events while leaving producer
  canonical state untouched.
- Delay owns no producer state. Core atomically records its private delay state
  under the Store-native lock, suppresses only the active target in
  `coherent_attention_read` (`src/lingtai/kernel/notifications.py:1013`), and at
  timer/heartbeat expiry writes a stable high-priority `delay-alarm` mirror
  before re-exposing the target. Corrupt or unreadable state is ignored
  (visible, not silent). A `daemon` target is masked rather than hidden there:
  the aggregate payload and raw version stay in the read and only the daemon
  attention entry becomes `DAEMON_DELAYED_ATTENTION_TOKEN`
  (`src/lingtai/kernel/notifications.py:911`), reusing the alarm-threshold mask
  seam `apply_daemon_attention_mask`
  (`src/lingtai/kernel/notifications.py:945`).
- Hook-registry handlers own no state directly either. Through notification
  Core they read/mutate `.notification/hooks.json` (Store family 8) and refresh
  the module-level registered-hook channel mirror that widens the allow
  predicate for THIS agent's workdir (hook channels are per-agent, not
  process-global); `drop` revokes the channel and `edit` moves it. The mirror is
  serialized under `_HOOK_REGISTRY_LOCK` and re-seeded by `sync_hook_registry`
  whenever the registry's `(st_mtime_ns, st_size)` stat changes (cross-process),
  with a workdir marked seeded only after a successful load. Read-only `list`
  never mutates.

## Notes

- There is no aggregate `dismiss`, no `summarize` action, no source-checkout
  fallback, and no `system` notification/dismiss compatibility alias. The
  shared manual loader is now deliberately used (via the reserved `manual`
  child), replacing this package's former private path construction.
- The kernel may synthesize the same `notification(action="check")` call/result
  shape at an idle boundary; that delivery plumbing is not another agent-callable
  action (`src/lingtai/kernel/base_agent/__init__.py:1255-1461`;
  `src/lingtai/kernel/base_agent/__init__.py:1582-1844`). Because that pair is
  deliberately byte-shape-identical to a voluntary read, its synthesized call
  args carry the same minimal LTP v2 envelope (`action`, `input: {}`, and a
  `reasoning` string); the optional public `summarize` control is valid but
  absent here. No `injection_seq` or other internal freshness field is admitted,
  since a provider/model can copy assistant-turn call args verbatim into a new
  real call, and `_ROOT_FIELDS` rejects keys outside the public root allowlist
  with `INVALID_ARGUMENT: unsupported notification argument`. Freshness/novelty
  against byte-equality is carried on the result side (`content`/`metadata`)
  instead, which is never fed back as call args.
- Large tool results are ranked and compacted through
  `context(action="summarize")`. Notification dismissal retains only the legacy
  reminder escape hatch described by the manual.
- Changes to notification read/dismiss semantics must also check
  `src/lingtai/services/LICC_NOTIFICATION_CONTRACT.md`; changes to Port behavior
  must update the paired Contract and focused tests in the same PR.
