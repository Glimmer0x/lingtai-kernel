---
name: notification-tool
contract_version: 2
root_contract: CONTRACT.md
related_files:
  - src/lingtai/tools/notification/ANATOMY.md
  - src/lingtai/tools/notification/__init__.py
  - src/lingtai/tools/notification/schema.py
  - src/lingtai/tools/_settings.py
  - src/lingtai/tools/registry.py
  - src/lingtai/kernel/notifications.py
  - src/lingtai/kernel/base_agent/__init__.py
  - src/lingtai/kernel/base_agent/turn.py
  - src/lingtai/agent.py
  - tests/test_notification_tool.py
  - tests/test_system_dismiss.py
  - tests/test_tools_package_data.py
  - src/lingtai/tools/notification/glossary-en.md
  - src/lingtai/tools/notification/glossary-zh.md
  - src/lingtai/tools/notification/glossary-wen.md
  - src/lingtai/intrinsic_skills/notification-manual/SKILL.md
  - src/lingtai/intrinsic_skills/notification-manual/reference/channel-model/SKILL.md
  - src/lingtai/intrinsic_skills/notification-manual/reference/dismissal-safety/SKILL.md
maintenance: |
  <!-- CANONICAL-MAINTENANCE v2 BEGIN -->
  This component contract is governed by the root CONTRACT.md. Keep
  related_files complete and repo-relative: the paired ANATOMY.md, Port, every
  production Adapter, contract tests, and directly relevant component contracts
  belong here. Re-read this contract whenever a linked boundary changes. Update
  the Port, affected Adapters, contract tests, and this contract in the same
  change; update the paired Anatomy when structure or composition also changes;
  bump contract_version for a breaking Port-contract change. If code and
  contract disagree, treat the disagreement as a defect. Follow the root
  Anatomy/Contract pairing rule and report drift rather than silently fixing it.
  <!-- CANONICAL-MAINTENANCE END -->
---
# Notification Tool Contract

## Purpose

The mandatory `notification` tool is the sole agent-callable notification
surface. It exposes four operational actions for reading or atomically clearing
notification mirrors plus one strictly read-only `manual` action for progressive
disclosure. It owns no producer state and introduces no Notification Store
operation.

## Public call boundary

The raw `get_schema()` is a closed object whose required root properties are
exactly `action` and `input`:

```text
notification(action="check", input={})
notification(action="dismiss_channel", input={"channel": "soul"})
notification(action="dismiss_event", input={"event_id": "evt-1"})
notification(action="dismiss_ref", input={"ref_id": "producer-1"})
notification(action="manual", input={})
```

The action domain, in order, is `check`, `dismiss_channel`, `dismiss_event`,
`dismiss_ref`, `manual`. The root is closed (`additionalProperties: false`),
`input` is required, and its `anyOf` consists of five closed action-owned object
branches. `check` and `manual` intentionally have separate empty titled
branches. `dismiss_channel` owns `channel`, `force`, and `reason`; it requires
`channel`. `dismiss_event` owns `event_id`, optional `channel`, `force`, and
`reason`; it requires `event_id`. `dismiss_ref` is the corresponding `ref_id`
branch. Cross-action fields, flat fields, omitted action, and compatibility
aliases are not accepted.

The raw schema does not own `reasoning`. BaseAgent alone adds optional root
`reasoning` to the Agent-facing FunctionSchema; an executor may carry it as
internal `_reasoning`. Reasoning is never nested in `input`. Provider envelope
names and shapes remain unchanged: Chat and Responses use the FunctionSchema
parameters, Anthropic uses `input_schema`, and the common wire description is
unchanged.

## Behavior

Agents MUST use `manual` only to retrieve installed guidance, `check` to request
current notification state, and the narrowest producer-specific or atomic
dismiss action after handling a notification. They MUST NOT treat generic
dismissal as mutation of producer canonical state, bypass protected channels, or
route large-result compaction through this tool.

Observable action contracts are:

- `check` returns `{_notification_placeholder: true, message}`; the turn-loop
  adapter may stamp `_meta.agent_meta.notifications.attention` and
  `_meta.agent_meta.guidance.transient` onto that same dict.
- `dismiss_channel` requires `channel`, rejects event/ref targets, and delegates
  a whole-mirror clear to notification Core.
- `dismiss_event` requires `event_id`; `dismiss_ref` requires `ref_id`; each
  defaults `channel` to `system` and delegates targeted removal to Core.
- `manual` reads only
  `<agent>/.library/intrinsic/capabilities/notification-manual/SKILL.md`.
  Success retains the established `{status: "ok", notification_manual,
  manual_path}` envelope; absence retains the degraded empty-body envelope.
- Every success and error also carries fresh `current_setting` evidence from
  the Agent-owned `settings/notification.json` placeholder. The only valid
  settings file is the evidence-only v1 object `{"schema_version": 1}`. Missing,
  valid, byte-distinct, and invalid files never change notification behavior.

Malformed root/input mappings, non-string or odd keys, cross-action fields, and
wrong action-input value types fail before any notification read, write, or
Core/Store dismissal seam. Service, installed-manual, and filesystem
exceptions use bounded non-private error envelopes; no exception detail,
secret, or absolute settings path is model-visible.

There is no aggregate `dismiss`, no `summarize`, no `items` property, no source
checkout fallback, and no compatibility alias. `system` owns `summarize` and
exposes no notification/dismiss alias.

## Adapters and safety

`lingtai.tools.registry.INTRINSICS` registers `notification` as a mandatory
intrinsic. `handle()` validates and dispatches the five actions. The turn-loop
notification post-hook completes `check` with the single canonical model-visible
payload. The three dismiss handlers adapt nested input into
`lingtai.kernel.notifications.dismiss_channel(..., invoked_by="notification")`,
where Core owns allowlists, producer guards, stale-version checks, protected
channels, acknowledgement policy, and targeted event/ref removal.

Agent initialization installs the bundled notification-manual skill tree into the
per-Agent intrinsic library. `manual` reads that initialized resource only and
never reads or mutates `.notification/`, Notification Store state, producer
state, fingerprints, or acknowledgement state.

Dismissal affects notification mirrors only. Producer guards, non-force stale
refusal, protected-channel refusal, post-molt reasons, and unrelated-event
preservation remain in force. Legacy `large_tool_result` reminder escape-hatch
behavior remains unchanged.

## Contract tests and maintenance

Focused tests cover mandatory registration and wiring, the ordered five-action
raw schema, raw-versus-Agent-facing reasoning injection, canonical descriptions,
closed action branches, malformed input before notification seams, installed
manual equality/path and read-only behavior, settings states/evidence, all
atomic dismiss semantics, Core guards, exception sanitization, provider wires,
and absence of system compatibility aliases. Architecture, Anatomy drift,
glossary, i18n, compile, control-byte, and diff-check validators cover the
linked document and manual graphs.

Read the paired Anatomy for current symbol locations and composition. Keep
implementation, schema, registry wiring, focused tests, glossaries, and the
manual/reference graph synchronized. The action/input migration is a breaking
Port change, so `contract_version` is `2`.
