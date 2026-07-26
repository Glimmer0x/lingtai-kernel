---
related_files:
  - src/lingtai/tools/ANATOMY.md
  - src/lingtai/tools/CONTRACT.md
  - src/lingtai/tools/notification/CONTRACT.md
  - src/lingtai/tools/notification/__init__.py
  - src/lingtai/tools/notification/schema.py
  - src/lingtai/tools/_settings.py
  - src/lingtai/tools/registry.py
  - src/lingtai/services/LICC_NOTIFICATION_CONTRACT.md
  - src/lingtai/kernel/notifications.py
  - src/lingtai/kernel/base_agent/__init__.py
  - src/lingtai/kernel/base_agent/turn.py
  - src/lingtai/agent.py
  - src/lingtai/intrinsic_skills/notification-manual/SKILL.md
  - src/lingtai/intrinsic_skills/notification-manual/reference/channel-model/SKILL.md
  - src/lingtai/intrinsic_skills/notification-manual/reference/dismissal-safety/SKILL.md
  - tests/test_notification_tool.py
  - tests/test_system_dismiss.py
  - tests/test_tools_package_data.py
  - src/lingtai/tools/notification/glossary-en.md
  - src/lingtai/tools/notification/glossary-zh.md
  - src/lingtai/tools/notification/glossary-wen.md
maintenance: |
  Keep related_files repo-relative, duplicate-free, and linked to real files.
  Keep this component's ANATOMY.md and CONTRACT.md reciprocal and keep
  parent/child anatomy links bidirectional. Code is the structural source of
  truth: update this anatomy in the same change that moves files, symbols,
  connections, composition, or state. Verify every changed citation and run
  architecture-document validation before merge.
---
# Notification Tool Anatomy

`src/lingtai/tools/notification/` is the mandatory agent-callable notification
surface. It composes five actions: `check`, three atomic dismissal actions, and
the strictly read-only `manual` action. Notification Core owns mirror guards and
Store use; the tool owns only the closed action/input schema, dispatch, the check
placeholder, argument adaptation, settings evidence, and installed-manual
retrieval.

## Components

- `schema.py` defines canonical-English registration prose, the ordered five
  action domain, a closed root, and strict action-owned `input.anyOf` branches.
  The check and manual branches are separate empty titled objects. The raw
  schema owns no reasoning.
- `__init__.py` defines `_ACTION_FIELDS`, mapping-key and type validation,
  settings evidence, `handle()`, the check placeholder, manual retrieval, and
  the three Core adapters. Public validation occurs before any notification
  Core/Store seam; every result receives fresh `current_setting` evidence.
- `_settings.py` supplies the shared Agent-owned no-op placeholder reader for
  `settings/notification.json`.
- `registry.INTRINSICS` registers `notification` as a mandatory intrinsic next
  to email, system, psyche, and soul.
- `CONTRACT.md` is the normative public Port and invariant document.

## Connections

- `BaseAgent._wire_intrinsics()` binds every registered intrinsic module's
  `handle()` into the agent tool surface. `_build_tool_schemas()` copies the raw
  notification schema and alone injects optional root `reasoning`.
- The turn loop and notification meta-block call the notification post-hook
  after ordinary tool results so `check` receives the canonical notification
  payload on the same result.
- Kernel notification Core owns allowlists, producer guards, stale-version
  checks, protected channels, post-molt acknowledgement, and targeted event/ref
  removal. All dismiss adapters call the Core helper with
  `invoked_by="notification"`.
- `Agent._install_intrinsic_manuals()` copies the kernel-shipped
  notification-manual skill tree into the per-Agent intrinsic library that
  `_manual()` reads.
- The notification manual is the progressive-disclosure router for procedures;
  channel-model and dismissal-safety children hold protocol and safety depth.

## Composition

- **Parent:** `src/lingtai/tools/`.
- **Core dependency:** `src/lingtai/kernel/notifications.py` and the injected
  Notification Store Port. This tool adds no Store operation.
- **Turn-loop adapter:** the notification post-hook completes the check
  placeholder with model-visible state.
- **Installed-resource adapter:** `src/lingtai/agent.py` installs the manual
  tree consumed by `manual`.
- **Sibling ownership:** `system` retains `summarize`; producer tools retain
  their own canonical read/dismiss operations.

## Public boundary

The raw root is exactly required `action` and required `input`, with
`additionalProperties: false`. `input` is a strict action-specific `anyOf`; no
flat fields, omitted action, nested reasoning, or compatibility alias is
accepted. Agent-facing schemas add only optional root reasoning. Synthetic
kernel check pairs use the same `{"action": "check", "input": {}}` call shape;
freshness stays in result content/metadata.

The handler rereads `settings/notification.json` on every call. The only valid
settings value is `{"schema_version": 1}` and it is evidence-only; settings
never selects or changes notification behavior. Missing, valid, rewritten, and
invalid states are represented by bounded, secret-free `current_setting` data.

`check` is in-memory and write-free. `manual` reads one fixed installed text
file and does not inspect or mutate `.notification/`, Notification Store state,
producer state, fingerprints, acknowledgements, or notification logs. Dismiss
handlers own no state directly: Core clears notification mirrors or removes
selected system events while preserving producer canonical state and unrelated
events.

There is no aggregate `dismiss`, `summarize`, source-checkout fallback, shared
manual compatibility route, or `system` notification/dismiss alias. Large-result
reminder and stale/force behavior remains in Core and is not duplicated here.
