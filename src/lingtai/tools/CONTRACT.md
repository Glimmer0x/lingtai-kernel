---
name: model-facing-tool-call
contract_version: 1
root_contract: CONTRACT.md
related_files:
  - src/lingtai/tools/ANATOMY.md
  - src/lingtai/tools/registry.py
  - src/lingtai/kernel/base_agent/tools.py
  - src/lingtai/kernel/tool_executor.py
  - src/lingtai/tools/web_search/CONTRACT.md
  - src/lingtai/tools/web_search/__init__.py
  - tests/test_browser_capability.py
  - tests/test_wire_tool_description.py
maintenance: |
  This component contract is governed by the root CONTRACT.md. Keep the paired
  tools Anatomy and cross-contract links reciprocal. Update Agent schema
  composition, ToolExecutor normalization, the migrated family, wire tests,
  and this contract together when the canonical call boundary changes. Migrate
  one real family at a time; do not claim legacy tools already conform.
---
# Model-facing tool call contract

## Purpose

Define the future canonical public argument shape for LingTai-owned model-facing
tools: a **tool family envelope** with the four root blocks `action`, `input`,
`reasoning`, and `summarize`. This file is normative for the wire interface only.
It defines no family, compiler, dispatcher, base class, port class, adapter
class, handler, or result type, and it changes no runtime behavior by itself. It
is a migration target applied one family at a time.

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
- `summarize` is a root-only boolean, absent or false by default. It denotes
  result post-processing, not an action implementation argument. A family MUST
  NOT read `summarize` as action input.
- The prohibition above is on the result-summarization **control**, identified by
  role and not by spelling. This contract reserves no name inside `input`: an
  action MAY declare a domain field named `summary` when that field is genuine
  action input rather than a post-processing control. Today's psyche molt
  retrospective (`input.summary`, a string the agent writes for the next session)
  is such a field and stays legitimate after migration. The test is role: a
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
- Family boundaries follow shared domain, authority, state, and cohesion — not
  superficial implementation similarity. A family exists because its actions
  belong to one thing, not because their code looks alike.

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
- Migration is one family at a time in later PRs, vertically: code, contract,
  manual, and wire evidence together. Legacy tools are neither mass-renamed nor
  declared conforming without their own implementation and evidence.
- Until a family is migrated, its existing runtime and schema are unchanged.
  Adopting this contract by itself causes no wire or runtime behavior change.

## Relationship to current runtime

Nothing here describes shipped behavior beyond what each migrated family already
proves. In particular, the current a-priori result-summarization flag is read at
runtime under the literal key `summary`
(`src/lingtai/kernel/tool_result_summary.py:159`); this contract names the future
envelope field `summarize`. Reconciling the two is per-family migration work, not
a claim about today's wire. Unified `web` is the existing conceptual family shape
— `search | browse | manual` under one name — and is not changed by this file.
`web` is not yet a migrated family: it exposes no root `summarize` and has not
been proved against this contract.

Non-normative future illustration: `file` may later become one family with
actions `read | write | edit | glob | grep | manual`, while all six
implementations remain fully independent. That migration is not implemented, not
scheduled here, and not claimed.

## Contract tests

A migrated family must prove: exact final Agent root properties; family-required
`action` / `input`; closed strict input branches; absence of `reasoning`,
`_reasoning`, and `summarize` below root; rejection of wrong-branch input keys;
successful internal `_reasoning` dispatch; unchanged provider envelope semantics;
Chat and Responses serialization; a hermetic fresh Agent startup and complete
prompt build; and a real model-facing call after refresh when runtime wiring
changes. Because root `summarize` is required of every migrated family, every
migrated family must also prove that a `summarize` call preserves and logs the
raw output before summarization and leaves error results exact.

Web's existing focused capability and wire tests are starting evidence for the
family/action shape only: they cover `action` / `input` / `manual`, and `web`
does not yet expose the root `summarize` field. They are not a full conformance
suite. Full conformance for any family, `web` included, awaits that family's
explicit migration and its own `summarize` proof.

## Non-goals

This contract does not introduce, and this PR does not implement: the old
result-summarization control nested as `input.summary`; a shared settings or
`_settings` foundation; runtime schema injection; ToolExecutor changes; test or
manual rewrites; a provider adapter envelope; MCP migration; or the `file`
family.

This non-goal bans one thing: carrying the result-summarization *control* below
root. It does not reserve the word `summary`, and it does not ban an unrelated
domain field that happens to be named `summary` — see `### Envelope`.

## Maintenance

Keep this shared contract directional and concise. Add a family only after a real
scoped migration has code, contract/manual updates, provider-wire tests, and
runtime evidence. Do not use this file to mass-normalize legacy schemas, to
justify a shared implementation framework, or to rename external provider
protocol fields.
