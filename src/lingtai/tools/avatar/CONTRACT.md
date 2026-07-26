---
name: avatar-contract
tool: avatar
contract_version: 4
related_files:
  - src/lingtai/tools/avatar/__init__.py
  - src/lingtai/tools/avatar/_launcher.py
  - src/lingtai/tools/avatar/ANATOMY.md
  - src/lingtai/tools/avatar/manual/SKILL.md
  - src/lingtai/tools/_settings.py
  - src/lingtai/adapters/avatar_launcher.py
  - src/lingtai/adapters/posix/avatar_launcher.py
  - src/lingtai/adapters/windows/avatar_launcher.py
maintenance: |
  Keep related_files as repo-relative paths to real files. If behavior and this
  contract disagree, the code is the source of truth; fix both in the same
  change and bump contract_version on breaking public edits.
---

# Avatar capability contract

`avatar` is one public tool for independent peer-agent spawning, descendant
rules distribution, and installed-manual lookup. This document owns the avatar
surface only; sibling tools may be at different migration stages.

**contract_version 4** is the closed action/input migration. The raw public
parameters are a closed object requiring both root `action` and nested `input`.
The three action branches are `spawn`, `rules`, and `manual`. There is no
avatar-owned flat-argument or omitted-action compatibility path.

## Public calls

Every avatar-owned public example uses explicit root `action`, nested `input`,
and an Agent-injected root `reasoning` field:

```text
avatar(action="spawn", input={"name": "researcher"}, reasoning="...mission...")
avatar(action="spawn", input={"name": "clone", "type": "deep", "comment": "", "dry_run": true, "confirm": false}, reasoning="preview this reviewed mission")
avatar(action="rules", input={"rules_content": "Always report findings."}, reasoning="distribute the reviewed rule")
avatar(action="manual", input={}, reasoning="load avatar guidance")
```

`reasoning` is optional metadata injected at the root by `BaseAgent`; it is not
nested action input and is not part of `get_schema()`. The tool executor passes
it internally as `_reasoning`, where spawn uses it as the first-prompt mission.

The raw schema is:

- root `type: object`
- root properties exactly `action` and `input`
- root `required: ["action", "input"]`
- root `additionalProperties: false`
- `action` is the string enum `spawn | rules | manual`
- `input` is an `anyOf` of strict object branches, each with
  `additionalProperties: false`

`get_schema()` remains the raw action/input-only schema. `BaseAgent` adds
optional root `reasoning` when it constructs the Agent-facing
`FunctionSchema.parameters`; no reasoning field is added inside any input
branch. Provider envelope names remain unchanged: Chat uses
`function.parameters`, Responses uses flat function `parameters`, and
Anthropic uses `input_schema`.

## Action ownership

### `action="spawn"`

`input` requires `name` and owns only these fields:

- `name` (required string): one bare sibling-directory name, Unicode letters,
  digits, underscore, or hyphen; no dots, slashes, spaces, or leading dot; at
  most 64 characters.
- `type` (optional `shallow` or `deep`, default `shallow`)
- `comment` (optional persistent avatar system note)
- `dry_run` (optional boolean)
- `confirm` (optional boolean)

The spawn action never accepts `rules_content`. Its mission is the injected
root `reasoning` value. Empty, short (<20 characters), or debug/test-like
missions require `confirm=true` unless `dry_run=true`. A dry run validates and
returns a preview without writing a directory, ledger, signal, or process.
Normal success, duplicate/live-peer, gate, and boot-failure semantics remain
those implemented by `AvatarManager._spawn`.

### `action="rules"`

`input` requires `rules_content` and owns no spawn-only field. It requires an
admin privilege, writes the self `.rules` signal, and distributes the same
signal to live descendants discovered through the ledger tree. `name`, `type`,
`comment`, `dry_run`, and `confirm` are rejected for this action before any
rules service or filesystem side effect.

### `action="manual"`

`input` must be exactly `{}`. The action is read-only and loads the real
installed `avatar` manual at:

```text
<agent>/.library/intrinsic/capabilities/avatar/SKILL.md
```

It does not read the source-package manual as a substitute and does not spawn,
write rules, or append a ledger event.

## Validation and settings evidence

Every handler call first rereads the Agent-owned `settings/avatar.json` through
the strict shared v1 placeholder reader. Missing, valid, byte-distinct hot
revision, and invalid files are evidence only: `current_setting` never selects
or changes avatar behavior. The file is reread on every call, including
malformed, manual, and service-error paths.

Every returned result contains a fresh secret-free `current_setting` block with
`configurable: false`, `placeholder: "no-op"`, source, revision, bounded hash,
and a no-op change hint. Invalid settings may add a bounded `settings_error`;
raw bytes, secret sentinels, and host paths are never returned. Settings
behavior and prompt text are invariant across missing/valid/revised/invalid
snapshots.

Root and nested mappings are checked strictly before dispatch. Non-mapping
arguments, missing root keys, unsupported root keys, non-string/unhashable
keys, non-string or unsupported action values, non-mapping input, non-string
nested keys, missing action-required fields, and action-crossed fields return a
bounded error with `current_setting` and make zero avatar service calls.

## State and side effects

All paths are relative to the parent agent directory and its network root:

```text
<parent>/delegates/ledger.jsonl
<parent>/.rules
<network-root>/<avatar-name>/
```

A real spawn is a detached process and may copy/write files, launch a child,
and distribute existing rules. A real rules call writes signals. Validation,
manual, and dry-run paths do not perform those live side effects. Tests and
harnesses must inject a deterministic launcher/service seam; never call the
public tool against a live network or real avatar process.

The launch Port remains responsible for platform mechanics. Spawn keeps the
existing exact argv, boot heartbeat, ledger, deep-copy, path-scope, and
cross-platform launcher semantics described by the source and adapter
contracts.

## Preserved runtime and platform invariants

This schema migration does not move platform mechanics into the core manager or
weaken the existing launch contract:

- avatar names remain one safe sibling segment and the resolved destination must
  stay directly under the network root;
- shallow spawn copies the parent configuration through the existing composition
  and identity-stripping path; deep spawn also copies the durable roots selected
  by the existing implementation and starts with fresh conversation history;
- `dry_run` performs validation and returns the existing preview without creating
  the avatar directory, launching a process, or appending a success ledger row;
- the manager prepares a `LaunchRequest`, calls the injected launcher Port, waits
  for the existing heartbeat/boot condition, and releases the opaque process
  handle after the boot decision;
- POSIX and Windows process/session details remain owned by their adapter
  launchers. Core code must not branch on platform-specific process APIs;
- successful spawn registration and rules propagation continue through
  `delegates/ledger.jsonl` and the existing `.rules` signal protocol. Failed
  launch/boot paths must not be reported as successful registrations;
- confirmation, duplicate/liveness, admin, and boot-failure outputs keep their
  established machine-readable shapes; this migration only nests public inputs
  and adds settings evidence.

The cross-platform and state invariants remain mechanically anchored by
`tests/test_layers_avatar.py`, `tests/test_avatar_rules.py`, the platform
launcher test suites, and `tests/test_avatar_action_input_candidate.py`. Tests
for this public migration must patch candidate-owned launch/boot/rules seams and
must never start a real descendant process or distribute rules to a live
network.

## Documentation and glossary ownership

`get_description()`, this contract, `ANATOMY.md`, and the installed manual must
keep avatar-owned public examples in root-action/nested-input/reasoning form.
Do not rewrite sibling-tool prose merely because it still shows another shape.
Canonical identifiers (`avatar`, `action`, `input`, `spawn`, `rules`, `manual`,
`name`, `type`, `comment`, `dry_run`, `confirm`, `rules_content`, and
`reasoning`) remain English literals. The zh/wen glossaries map terms only and
do not invent aliases or options.
