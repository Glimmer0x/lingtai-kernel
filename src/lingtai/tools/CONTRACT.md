---
name: lingtai-tool-protocol
contract_version: 2
root_contract: CONTRACT.md
related_files:
  - src/lingtai/tools/ANATOMY.md
  - src/lingtai/tools/registry.py
  - src/lingtai/kernel/base_agent/tools.py
  - src/lingtai/kernel/tool_executor.py
  - src/lingtai/tools/web_search/CONTRACT.md
  - src/lingtai/tools/web_search/__init__.py
  - src/lingtai/tools/knowledge/CONTRACT.md
  - src/lingtai/tools/knowledge/__init__.py
  - src/lingtai/tools/file/CONTRACT.md
  - src/lingtai/tools/file/__init__.py
  - src/lingtai/tools/task_card/CONTRACT.md
  - src/lingtai/tools/task_card/__init__.py
  - src/lingtai/tools/avatar/CONTRACT.md
  - src/lingtai/tools/avatar/__init__.py
  - src/lingtai/tools/soul/CONTRACT.md
  - src/lingtai/tools/soul/__init__.py
  - src/lingtai/tools/skills/CONTRACT.md
  - src/lingtai/tools/skills/__init__.py
  - src/lingtai/tools/tool_family/CONTRACT.md
  - src/lingtai/kernel/tool_result_summary.py
  - src/lingtai/tools/notification/CONTRACT.md
  - src/lingtai/tools/system/CONTRACT.md
  - src/lingtai/tools/daemon/CONTRACT.md
  - src/lingtai/tools/email/CONTRACT.md
  - src/lingtai/tools/email/__init__.py
  - src/lingtai/tools/context/CONTRACT.md
  - src/lingtai/tools/pad/CONTRACT.md
  - src/lingtai/tools/lingtai/CONTRACT.md
  - src/lingtai/tools/psyche/CONTRACT.md
  - tests/test_browser_capability.py
  - tests/test_wire_tool_description.py
maintenance: |
  This component contract is governed by the root CONTRACT.md and owns the
  LingTai Tool Protocol (LTP). Keep the paired tools Anatomy and cross-contract
  links reciprocal. Update Agent schema composition, ToolExecutor normalization,
  each migrated family, the `_LTP_V2_MIGRATED_FAMILIES` allowlist, and this
  contract together when the canonical call boundary changes. LTP alignment is documentary — this pair is the source of
  truth, not a central validator. Migrate one real family at a time; do not
  claim legacy tools already conform.
---
# LingTai Tool Protocol (LTP)

## Purpose

Define the **LingTai Tool Protocol (LTP)**: the future canonical public interface
for LingTai-owned model-facing tools. LTP covers public addressing, ownership,
boundaries, and the semantics of the envelope, actions, `manual`, and settings.

LTP is LingTai-owned. "Enhanced MCP-like" is a useful mental model, but LTP is
**not** an MCP extension: it does not rewrite arbitrary MCP schemas and reserves
nothing in them.

LTP standardizes the public interface only. It does **not** standardize
implementations, readers, schemas, or lifecycles. This file defines no family,
compiler, dispatcher, base class, port class, adapter class, handler, or result
type, and changes no runtime behavior by itself. It is a migration target applied
one family at a time.

## Behavior

A public LingTai tool is a **logical tool family**: one model-facing name that
groups cohesive capabilities sharing a domain, an authority, and a state scope.
Once a family is explicitly migrated, its final Agent-built model-facing argument
schema is a closed object whose root properties are exactly:

- `action` — selects one named action port within the family;
- `input` — the one strict input object for the selected action;
- `reasoning` — the top-level rationale for this tool call; and
- `summarize` — the root boolean opting this call's result into
  post-processing.

`action` and `input` are the family/action contract. `reasoning` and `summarize`
are cross-cutting envelope controls, not action arguments. The set is
provider-neutral and closed: there is no other public block, and `reasoning` and
`summarize` are never nested under `input`.

## Port

The provider-neutral boundary is the final `FunctionSchema` assembled by the
Agent. A migrated family owns `action` plus the strict per-action `input`
branches; Agent schema composition owns the standard top-level `reasoning`
field. Each action is one named port with one strict input schema.

"Action port" names a separation of concerns, not a class or module. The
contract standardizes the wire interface; how a family realizes its actions
behind that interface is not constrained here.

## Adapters

Provider adapters wrap the same schema in their protocol-native envelope.
OpenAI's outer `parameters`, Anthropic's `input_schema`, and the internal
`FunctionSchema.parameters` attribute are transport or implementation names and
remain unchanged; none creates a public LingTai block named `parameters`.
ToolExecutor removes public `reasoning` before handler dispatch and may preserve
it as internal `_reasoning` metadata. `_reasoning` must never appear in the
model-facing schema or nested `input`.

## Contract rules

### Envelope

- The final migrated root property set MUST be exactly `action`, `input`,
  `reasoning`, and `summarize`, with `additionalProperties: false`. The
  family-required set is `action` and `input`; standard Agent composition adds
  top-level `reasoning`.
- `input` MUST be one object selected by `action`. Action branches are closed;
  declared optional fields use the provider-compatible nullable representation.
- Nested `input` MUST NOT contain `reasoning`, `_reasoning`, or `summarize`.
- `reasoning` is root-only cross-cutting metadata and is never part of an
  action's independent implementation input.
- `summarize` is a root-only boolean, absent or false by default. It is universal
  cross-cutting result post-processing for every migrated family, not an action
  implementation argument. A family MUST NOT read `summarize` as action input.
- The envelope MUST retain the root boolean through result post-processing, on
  both the single and the parallel call path, and MUST strip it before action
  implementation dispatch. No action handler or use case receives `summarize` as
  implementation input. This is interface semantics: it constrains what crosses
  the boundary, and requires no compiler, dispatcher, base class, or shared
  implementation to satisfy.
- Raw output MUST be durably recorded before any visible summary replacement, and
  tool errors MUST remain exact and unmodified. Summarization replaces what the
  model sees; it never replaces what was recorded and never rewrites an error.
- The prohibition above is on the result-summarization **control**, identified by
  role and not by spelling. This contract reserves no name inside `input`: an
  action MAY declare a domain field named `summary` when that field is genuine
  action input rather than a post-processing control. The `context` molt
  retrospective (`input.summary`, a string the agent writes for the next
  session) is such a field and remains legitimate. Note that `context` also
  carries an ACTION named `summarize`; that too is a domain operation, distinct
  from the root control, and no `context` child declares a `summarize` field. The test is role: a
  boolean asking the runtime to post-process this call's result belongs at root
  as `summarize`; a value the action itself consumes belongs in `input` under
  whatever name the domain calls it.
- No public `parameters`, `parameter`, `arguments`, `payload`, or compatibility
  alias is admitted after migration. Provider envelope names are not aliases.
- Internal `_reasoning` is metadata only: handlers may admit it after
  ToolExecutor normalization but MUST NOT treat it as action input.

### Dispatch and actions

- A migrated family MUST validate action/input correspondence at dispatch and
  reject keys belonging to another action's branch; schema conformance alone is
  not the authorization or safety boundary. This PR does not implement that
  dispatcher.
- Every LingTai-owned family MUST offer a `manual` action returning exact
  guidance for that family. Agents SHOULD call it before complex or unfamiliar
  use. Manual content stays progressive-disclosure material; schemas MUST NOT be
  bloated to carry it.
- A migrated family's `manual` MUST explain root `summarize` honestly for that
  family, selecting one shared guidance profile rather than restating the whole
  rule. The profiles are:
  - **bulky-result** — the family or action has predictably large output. Its
    manual says when `summarize=true` helps, and when exact raw text, IDs, or
    paths mean it should stay false.
  - **short-result** — output is normally small. Its manual says `summarize` is
    available but normally unnecessary, and to leave it false.
  A family whose actions differ MAY assign profiles per action. Calls to `manual`
  itself normally use `summarize=false`, so exact procedure and critical
  constraints are not summarized away; each manual SHOULD say so.
- The profiles exist so this guidance is maintained once and referenced, not
  copied verbatim into every manual. This PR defines the obligation only; it
  writes no manual and implements no manual machinery.
- Family boundaries follow shared domain, authority, state, and cohesion — not
  superficial implementation similarity. A family exists because its actions
  belong to one thing, not because their code looks alike.

### Settings

LTP defines two optional settings levels under the Agent settings root. Both are
addresses and ownership rules, not a file format or a reader.

`<agent-dir>` is the filesystem working-directory root owned by the Agent
instance whose LingTai-owned family is invoked. Its LTP settings root is the
direct child `<agent-dir>/settings/`. This names an address only: it imposes no
reader, loader, lifecycle, or other runtime requirement.

- `<agent-dir>/settings/<family>.json` — **family-owned** generic settings.
- `<agent-dir>/settings/<family>.<action>.json` — **action-owned** settings.

Illustratively: `web.json`, `web.search.json`, `web.browse.json`.

- **Grammar.** The two addresses MUST stay unambiguous. Neither a family name nor
  an action name may contain `.`; the first `.` in the stem therefore separates
  family from action. A stem with no `.` is the family file; a stem with exactly
  one `.` is that action's file. No stem carries more than one `.`.
- **Orthogonal scopes.** A family file MUST NOT embed action blocks, and an
  action file MUST NOT embed family or generic blocks. There is no include,
  inherit, overlay, fallback, or override; there is no precedence and no merged
  settings object. One semantic setting has exactly one owner.
- **Reading boundary.** One call may be affected by both levels: the family
  envelope reads and consumes only `<family>.json`, and the selected action reads
  and consumes only `<family>.<action>.json`. Neither reads the other's file.
- **Optionality.** A scope that supports no settings has no file. A supported but
  absent file means the owner's documented defaults apply. A present but invalid
  file MUST fail loudly at that owner's boundary and MUST NOT be silently
  ignored.
- **Per-owner authority.** Every family and action owns its own settings schema,
  version, and migration; whether it reads hot, at boot, or cached; its cache
  invalidation; and its error vocabulary. Internal helpers are allowed, but LTP
  MUST NOT depend on a central reader.
- **Discovery via `manual`.** A migrated family's `manual` is the settings
  discovery surface: it states the exact supported files, their schema and
  defaults, their lifecycle, and what an invalid file does. Where no settings
  surface exists, the manual says so explicitly rather than staying silent.
- **Reading is not writing.** Owning the read of a settings file grants no
  authority to mutate configuration.

### Implementation independence

Action implementations stay maximally independent. This contract MUST NOT be
read as requiring any of the following, and a future migration MUST NOT
introduce them merely to satisfy this file:

- inheritance from a shared base or port class;
- a shared handler or shared business logic;
- a common module layout or file consolidation;
- common boot, state, or dependency wiring;
- common internal request or result types;
- a universal domain result shape.

Two actions in one family may share nothing but the family name and the wire
envelope. That is a conforming implementation.

### Scope

- Scope is LingTai-owned tool families only. Arbitrary and MCP-provided tool
  schemas are out of scope and untouched; this contract reserves no field name
  in them and MUST NOT overwrite MCP fields.
- Migration is one family at a time in later PRs, vertically: code, contract, and
  manual together, with the evidence that migration's reviewer asks for. Legacy
  tools are neither mass-renamed nor declared migrated without their own
  implementation and documented alignment.
- Until a family is migrated, its existing runtime and schema are unchanged.
  Adopting this contract by itself causes no wire or runtime behavior change.

### Non-goals

This contract does not introduce, and the PR that adopted it did not implement:
a central LTP validator, registry, schema compiler, or universal conformance
harness; the old result-summarization control nested as `input.summary`; a
shared settings or `_settings` foundation; runtime schema injection;
ToolExecutor changes; a provider adapter envelope; or MCP migration.

The `file` family was also a non-goal of that adopting PR. It has since been
migrated on its own, vertically and with its own evidence, exactly as the
"one family at a time" rule requires — see `### Relationship to current
runtime` below and `src/lingtai/tools/file/CONTRACT.md`. Migrating it did not
relax any rule in this file.

The `input.summary` non-goal bans one thing: carrying the result-summarization
*control* below root. It does not reserve the word `summary`, and it does not ban
an unrelated domain field that happens to be named `summary` — see
`### Envelope`.

### Relationship to current runtime

Nothing here describes shipped behavior beyond what each migrated family already
documents. `web` (`search | browse | manual`) is the first family migrated to
this contract: its final model-facing root is exactly `action`, `input`,
`reasoning`, and `summarize`; its `search` action reads the action-owned
`settings/web.search.json` (see `src/lingtai/tools/web_search/CONTRACT.md`).
`knowledge` (`info | manual`) is the third: the migration is envelope-only —
its public tool name and both public action values are unchanged, both children
take the canonical strict-empty `input`, and it supports no settings file (see
`src/lingtai/tools/knowledge/CONTRACT.md`). It remains a signpost capability
with no authoring, search, or edit action.

`file` (`read | write | edit | glob | grep | manual`) is the fourth family
migrated to this contract, and the first aggregation of several former public
roots into one: its final model-facing root is exactly `action`, `input`,
`reasoning`, and `summarize`. The migration was a clean break rather than an
adapter layer — the five old model-facing roots, their implementation packages,
their per-operation contracts and glossaries, and their capability names were
all deleted, with the behavior folded into the single `lingtai.tools.file`
owner. Those five capability names are now unknown and fail loudly; `file`
surfaces no settings file at either level and says so in its manual (see
`src/lingtai/tools/file/CONTRACT.md`).

`vision` (`analyze | manual`) is the fifth: it keeps its public tool name and
both public action values while moving to the same root envelope, with
`analyze` owning the direct current-preset image request and `manual` the
family-owned reserved child (see `src/lingtai/tools/vision/CONTRACT.md`). It
owns no settings file, so the two-level settings addressing rules do not apply
to it.

`avatar` (`spawn | rules | manual`) is the sixth family migrated, keeping its
public name and action values unchanged (see
`src/lingtai/tools/avatar/CONTRACT.md`, contract_version 4). It owns no
settings file at either level, and its manual says so explicitly. Two
avatar-specific facts are worth naming here because they are envelope
consequences, not local details: its `spawn` mission brief is root `reasoning`
(never an `input` property, per "Envelope"), and its `rules` action is
karma-gated while `spawn` and `manual` are not — a family must not hide a
stronger child action behind a weaker family posture.

`shell` (`run | poll | cancel | manual`) is the eighth: its final model-facing
root is likewise exactly `action`, `input`, `reasoning`, and `summarize`, its
run-only fields live only in `run`'s `input` and `job_id` only in
`poll`/`cancel`'s, and its unchanged `ShellManager` engine — sync execution,
the working-directory sandbox, the durable async lifecycle, cancellation, and
terminal receipts — keeps its historical flat shape as a purely internal
interface (see `src/lingtai/tools/bash/CONTRACT.md`).

`skills` (`info | manual`) is the ninth: it keeps its public tool name and both
public action values, adopts the same closed root, declares the canonical
strict-empty `input` object for both actions, and supports no settings file at
all — its manual says so explicitly (see
`src/lingtai/tools/skills/CONTRACT.md`). Family boundaries here follow the
shared-domain rule above: `info` and `manual` are two actions of one skill-
catalogue authority, not two related tools grouped for convenience.

`notification` (`check | dismiss_channel | dismiss_event | dismiss_ref |
manual`) is the tenth: its final model-facing root is likewise exactly
`action`, `input`, `reasoning`, and `summarize`, each action's arguments live
only in that action's own strict `input` (so `channel` belongs to
`dismiss_channel`, `event_id` only to `dismiss_event`, and `ref_id` only to
`dismiss_ref`), and it is the second migrated *intrinsic* — it therefore
composes its dispatching family per call rather than owning a per-Agent
manager (see `src/lingtai/tools/notification/CONTRACT.md`).

`system` (`refresh | sleep | lull | interrupt | suspend | cpr | clear |
nirvana | presets | summarize | manual`) is the eleventh, and the third
migrated *intrinsic*: its final model-facing root is likewise exactly `action`,
`input`, `reasoning`, and `summarize`, and each action's arguments live only in
that action's own strict `input` — so `address` belongs to the six address
verbs, `preset`/`revert_preset` only to `refresh`, and `items`/`rebuild` only to
`summarize` (see `src/lingtai/tools/system/CONTRACT.md`). Two facts are worth
naming here because they are envelope consequences rather than local details.
First, the family's three privilege classes (self, karma, karma+nirvana) are
*per action*, so the closed per-action `input` is load-bearing for safety, not
just for tidiness: `address` is undeclared on `sleep`, which means the
always-authoritative dispatch layer rejects a smuggled target before any signal
file is written — the same "a family must not hide a stronger child action
behind a weaker family posture" rule `avatar` established, applied to
rejection rather than gating. Second, `sleep.force` was live and read by the
handler before this migration but never advertised in the flat schema; a strict
child `input` must declare every key its handler accepts, so declaring it
surfaces existing behavior rather than adding a capability. `system` owns no
settings file at either level and its manual says so.

`daemon` (`emanate | list | ask | check | reclaim | manual`) is the twelfth
family migrated to this contract, and the one with the largest retained engine.
Its final model-facing root is exactly `action`, `input`, `reasoning`, and
`summarize`, and each action's arguments live only in that action's own strict
`input`: `tasks`/`backend`/`max_turns`/`timeout` belong to `emanate`,
`contains`/`status`/`include_done` to `list`, `message` to `ask`, `truncate` to
`check`, while `reclaim` and `manual` take the canonical strict-empty `input`
(`id` is shared by `ask`/`check` and `last` by `list`/`check`, each declared in
both branches). It follows `shell`'s division: a dedicated
`daemon/_tool_family.py` owns the public schema and a `DaemonFamilyDispatcher`
that translates the envelope into `DaemonManager`'s unchanged legacy flat call
shape, so the emanation engine, backend routing, detached supervisor,
completion signaling, cancellation, timeouts, and terminal notifications are
untouched by the migration. Its pre-migration flat `summary` boolean is
replaced by the canonical root `summarize`, joining the allowlist below in the
same change. See `src/lingtai/tools/daemon/CONTRACT.md`.
`email` (`send | check | read | dismiss | reply | reply_all | search |
archive | delete | contacts | add_contact | remove_contact | edit_contact |
manual`) is the thirteenth family migrated to this contract, and the widest
child registry so far. Its final model-facing root is exactly `action`,
`input`, `reasoning`, and `summarize`; the public tool name and all fourteen
action values are unchanged, and each action's arguments now live only in that
action's own strict `input` (so `query` belongs to `search`, `filter`/`n` to
`check`, and `attachments`/`delay`/`mode` to `send`) instead of the one open
flat bag every action previously shared. It is the fourth migrated *intrinsic*,
so it composes its dispatching family per call and strips the kernel-injected
`_tc_id` at its own boundary. Two facts are envelope consequences worth naming
here: its `unread` action is kernel-synthesized digest state and is
deliberately **not** a public child, keeping its own exact pre-migration
rejection rendered before dispatch; and `EmailManager`'s historical flat
argument shape is retained unchanged as a purely internal interface, exactly
as `shell` kept `ShellManager`'s. It owns no settings file at either level.
See `src/lingtai/tools/email/CONTRACT.md` (contract_version 2).

`psyche` (`lingtai_update | lingtai_load | pad_edit | pad_load | pad_append |
context_molt | name_set | name_nickname | manual`) is the fourteenth, and the
fifth migrated *intrinsic*. It is the first migration to fold a **two-key**
public surface into this envelope: psyche was addressed as an
`(object, action)` matrix, and each pair became exactly one flat action, the
same collapse `notification` made for its atomic dismiss verbs. The operation
inventory is preserved exactly — nothing added, dropped, renamed, or merged —
and every operation-level success payload and error, every log event, and every
persistence path is unchanged; only the argument shape and the envelope layer
around it moved. Envelope validation and its errors are necessarily new under
this contract, and psyche's former two-key unknown-object/invalid-action guards
became one unknown-action error (see
`src/lingtai/tools/context/CONTRACT.md`). It
owns no settings file at either level and its manual says so.

Three psyche facts are envelope consequences worth naming here. Its molt
retrospective is `input.summary` — the domain field this contract's "Envelope"
section explicitly permits, never the root `summarize` control. Its two
destructive full rewrites (`lingtai_update`, `pad_edit`) and its irreversible
`context_molt` make the "reject before dispatch" rule load-bearing rather than
merely tidy: a wrong-branch key must fail with nothing written and nothing
shed. And it is the first family that *consumes* the intrinsic-only `_tc_id`
rather than dropping it, so it strips that key at its own Host boundary and
threads it to the one action that needs it, instead of widening the shared
envelope.

**Current state (the paragraph above is migration history).** That family no
longer exists, and neither do the `pad`/`lingtai`/`knowledge`/`skills` public
roots that briefly succeeded it. The four durable domains are now taught by one
read-only root, `psyche` (`pad | lingtai | knowledge | skills | manual`,
`src/lingtai/tools/psyche/CONTRACT.md`, the equation
`pad + lingtai + knowledge + skills = psyche`): every action returns that domain's
manual and mutates nothing. Those four packages remain as private lifecycle
owners — Pad/LingTai composers and the Skills/Knowledge catalogs plus the
Knowledge legacy migration — and register no tool. Generic durable mutation
belongs to `file.write`/`file.edit`, which never hot-load prompt state; the
retired `pad.append`, `skills.info`, and `knowledge.info` actions have no
aliases. The
context lifecycle is `context` (`molt | summarize | rebuild | manual`,
`src/lingtai/tools/context/CONTRACT.md`): `summarize` records only, while
`rebuild` is the one active operation that first recomposes every canonical
prompt source, then applies pending/new summaries, then requests provider
replay; bare `{}` remains valid with zero pending summaries. Refresh and molt
invoke that same internal reconstruction contract as passive scenarios. Name
actions moved to `system`. There is no `psyche` root/module/alias and no public
`system(action='summarize')`. `context` alone consumes `_tc_id`; its action
named `summarize` remains unrelated to the root boolean control.

The legacy a-priori result-summarization flag under the literal key `summary`
(`src/lingtai/kernel/tool_result_summary.py:172`) remains honored for every
still-unmigrated caller; `src/lingtai/kernel/tool_result_summary.py` recognizes
the canonical `summarize` spelling only when the calling tool is a migrated LTP
v2 family (`_LTP_V2_MIGRATED_FAMILIES`, currently `web`, `mcp`, `knowledge`,
`file`, `vision`, `avatar`, `soul`, `shell`, `skills`, `notification`, `system`,
`daemon`, `email`, `pad`, `lingtai`, and `context`), so
an unmigrated tool's own field literally named `summarize` is never
reinterpreted as this control. A family adopting this envelope MUST join that
allowlist in the same change, or the root `summarize` it advertises to the
model would be silently ignored. Every other LingTai-owned family remains
unmigrated and keeps its existing schema and settings surface unchanged by
this file.

`mcp` is the second migrated family: public tool name `mcp`, actions `info |
manual`, both taking the canonical strict-empty `input`. The migration changed
its call envelope only — no action was added, removed, renamed, or given a new
capability; it remains signpost-only and read-only, and external MCP
registration (direct insertion into `mcp_registry.jsonl`) is untouched by it.
See `src/lingtai/tools/mcp/CONTRACT.md`.

`soul` (`inquiry | flow | config | voice | dismiss | manual`) is the seventh
family migrated to this contract, and the first migrated *intrinsic*. Its final
model-facing root is exactly `action`, `input`, `reasoning`, and `summarize`;
each action owns one strict closed `input` object, and its `summarize` guidance
profile is **short-result** for every action (see
`src/lingtai/tools/soul/CONTRACT.md`). `soul` supports no settings file at
either level and its manual says so explicitly. Being an intrinsic, it also
proves one boundary `web` could not: `base_agent._dispatch_tool` injects the
transport-only `_tc_id` into every intrinsic's args, so a migrated intrinsic
drops that key at its own Host boundary before the closed-root check rather
than widening the shared envelope's admitted root fields.

`src/lingtai/tools/tool_family/` is optional, generic composition
infrastructure implementing this envelope (schema composition from a
`ChildTool` registry, dispatch-validation boilerplate, and a reusable
ManualTool builder) that a family MAY adopt instead of hand-writing the
equivalent code; `web` is its first consumer, using it for schema composition
and dispatch while retaining its own outer `handle()` for family-specific
diagnostics, `mcp` is its second, retaining its own outer `handle_mcp()`
for its exact pre-migration unknown-action envelope, `knowledge` is its
third, using it the same way with its own outer `handle()` preserving that
family's exact pre-migration unknown-action result, `file` is its fourth
(below), `vision` is its fifth, using it the same way while retaining
its own outer `handle()` for the family's flat manual/error result shapes,
`avatar` is its sixth, restoring its own pinned unknown-action error
envelope the same way, `soul` is its seventh, composing `get_schema()`
from a module-level schema-only family and building an agent-bound one per
`handle(agent, args)` call because an intrinsic module has no per-Agent
manager instance to hold one, `shell` is its eighth, using it the same
way while retaining a thin outer `handle()` that narrows the generic
unknown-action message to its own four actions, `skills` is its ninth,
using it the same way but returning its canonical envelope failures
verbatim, having no such diagnostics, `notification` is its tenth, using
it the same way while retaining a thin outer `handle()` that strips the
kernel-injected `_tc_id` every intrinsic receives, flattens the reserved
`manual` child's canonical result to its own pinned public shape, and
normalizes the generic unknown-action error to its own, and `context` is its
eleventh, using `soul`'s module-level composition shape while threading the
`_tc_id` it actually consumes to its `molt` child out-of-band rather
than widening the shared envelope. `avatar` reuses
`ToolFamily` but not `build_manual_child`, because its manual ships inside
its own package rather than the agent's installed `.library` catalog —
adopting part of the infrastructure is conforming. Using it is never
required — see its own
`src/lingtai/tools/tool_family/CONTRACT.md` "Implementation independence" is
binding on it exactly as it is on every family.

`file` is that illustration realized: one family with actions
`read | write | edit | glob | grep | manual` whose six implementations remain
fully independent, sharing nothing but the family name and the wire envelope —
co-located in one package as `_read.py`, `_write.py`, `_edit.py`, `_glob.py`,
and `_grep.py`, where none imports another. Single ownership is not shared
implementation.
It is also the worked example of the family-boundary rule above — the five
operations are one family because they act on one working tree through one
authority (the injected `FileIOService`) under one sandbox, not because their
code looks alike.

## Contract tests

**There is no universal LTP validator, registry, schema compiler, or machine-
enforced conformance suite, and this contract does not introduce one.** Alignment
to LTP is maintained through this contract and the paired `ANATOMY.md`, reviewed
per migration — not through a central programmatic gate.

Evidence for a migration is therefore documentary and reviewed: the migrating PR
shows its final model-facing schema, states which envelope and settings rules it
satisfies, and updates this contract's related documents where the promise
changes. A reviewer checks that against the rules above.

Individual families and actions MAY keep their own behavior tests as locally
chosen evidence, and are encouraged to where the risk warrants it — for example
around envelope root properties, closed input branches, wrong-branch rejection,
`summarize` retention and isolation on both the single and parallel call path,
raw output recorded before any visible replacement, exact error results,
`summarize` never reaching the action implementation, and loud failure on an
invalid settings file. LTP does not mandate one universal suite covering these,
and a family choosing a different local evidence set is not thereby
non-conforming.

Web's focused capability, wire, and executor tests are this contract's first
migration evidence: they cover the full closed root (`action` / `input` /
`reasoning` / `summarize`), closed input branches, wrong-branch and non-boolean
rejection, `summarize` retention and isolation on both the single and a
controlled-parallel call path, raw output recorded before any visible
replacement, exact `status: "failed"` results under `summarize=true`, and the
action-owned `settings/web.search.json` surface (see
`src/lingtai/tools/web_search/CONTRACT.md` Contract tests). They remain one
family's local evidence, not a conformance suite, and no such suite is required
to exist.

`file`'s focused suite (`tests/test_file_tool_family.py`) is the second
migration's evidence, chosen for its own risks: exactly one public root with no
surviving old roots, the closed envelope, action/input correlation on both
wires, every child's schema/dispatch/result/error, cross-action rejection
before handler I/O, the no-I/O family manual with read pagination as a nested
reference, read continuation and line truncation, verbatim write/edit receipts,
and the `summarize` control and truthful mixed read/write risk posture. The
retained operations' own suites (`tests/test_layers_file.py`,
`tests/test_read_continuation.py`) continue to cover per-operation depth. This
is a different evidence set from web's, which is exactly what the paragraph
above permits.

`tests/test_tool_family_avatar_migration.py` is `avatar`'s own local evidence
for the same rules, chosen for that family's risk: the closed root, per-action
child inputs, root `allOf` correlation surviving both wires, cross-action and
unknown-root-field rejection *before* any handler I/O, `summarize` never
reaching a child handler and `avatar` actually being on the kernel allowlist,
the preserved unknown-action envelope, spawn's dry-run/mission-guard/identity
and path validation, the karma gate and distribution for `rules`, and `manual`
performing no spawn or rules I/O. Every test there builds its own isolated
temporary network and fakes the launcher Port, so it neither creates a live
avatar nor writes a live `.rules` signal.

`context`'s evidence (`tests/test_tool_family_context_migration.py`,
plus the updated `tests/test_context.py`, `tests/test_pad.py`,
`tests/test_eigen.py`, `tests/test_session_journal_gate.py`, and
`tests/test_intrinsic_manual_actions.py`) is likewise one family's local
evidence, chosen for a risk profile no earlier migration had: the irreversible
molt plus the record/apply pair that rewrites what the provider actually sees.
It covers the exact four-action inventory (`molt | summarize | rebuild |
manual`), the record-only-versus-applying split that replaced the former
`rebuild` boolean, the proof that no `psyche` root survives anywhere, the
closed root on both wires with the `allOf` correlation intact, per-action input
isolation, envelope and cross-branch rejection before any file write or context
shed, `_tc_id` isolation on the consume-rather-than-drop path, the molt
journal gate refusing before any shed, a full successful molt lifecycle in a
disposable workdir, the synthesized system-forced pair carrying the current
envelope, and the reserved `manual` child's no-double-wrap result.

`soul`'s migration evidence (`tests/test_tool_family_soul_migration.py`, plus
the updated `tests/test_soul.py`, `tests/test_soul_consultation.py`,
`tests/test_system_dismiss.py`, and `tests/test_intrinsic_manual_actions.py`)
is likewise one family's local evidence: it covers all six child schemas and
handlers, the closed root on both provider wires, wrong-branch rejection
before any handler I/O, `reasoning`/`_reasoning`/`summarize`/`_tc_id`
isolation from child input, the reserved `manual` child's
full-body/`manual_path` result with no double wrap and no soul operation, and
— specific to this family — that the opt-in `flow` env gate stays the only
enable path and that a disabled `flow` is a stable status rather than an
error.

`task_card` is a migrated intrinsic family as well, but with a narrower
producer-first boundary than the channel adapters that may consume it. Its local
evidence (`tests/test_task_card_controller.py`,
`tests/test_telegram_toolfamily_ltpv2.py`,
`tests/test_telegram_task_card_programmable.py`) covers the closed family root,
the exact agent-local file contract, activation/deactivation ordering, and the
fact that transport-specific projection semantics belong to the consuming
adapter rather than the intrinsic producer.

## Maintenance

Keep this shared contract directional and concise. Add a family only after a real
scoped migration has code, contract/manual updates, and reviewed evidence that it
meets these rules. LTP alignment is maintained by keeping this contract and the
paired `ANATOMY.md` honest and current, not by a central validator; do not add
one here. Do not use this file to mass-normalize legacy schemas, to justify a
shared implementation framework, or to rename external provider protocol fields.
