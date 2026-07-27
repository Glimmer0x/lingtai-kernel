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
  - tests/test_browser_capability.py
  - tests/test_wire_tool_description.py
maintenance: |
  This component contract is governed by the root CONTRACT.md and owns the
  LingTai Tool Protocol (LTP). Keep the paired tools Anatomy and cross-contract
  links reciprocal. Update Agent schema composition, ToolExecutor normalization,
  the migrated family, and this contract together when the canonical call
  boundary changes. LTP alignment is documentary — this pair is the source of
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

This contract does not introduce, and this PR does not implement: a central LTP
validator, registry, schema compiler, or universal conformance harness; the old
result-summarization control nested as `input.summary`; a shared settings or
`_settings` foundation; runtime schema injection; ToolExecutor changes; test or
manual rewrites; a provider adapter envelope; MCP migration; or the `file`
family.

The `input.summary` non-goal bans one thing: carrying the result-summarization
*control* below root. It does not reserve the word `summary`, and it does not ban
an unrelated domain field that happens to be named `summary` — see
`### Envelope`.

### Relationship to current runtime

Nothing here describes shipped behavior beyond what each migrated family already
documents. In particular, the current a-priori result-summarization flag is read at
runtime under the literal key `summary`
(`src/lingtai/kernel/tool_result_summary.py:159`); this contract names the future
envelope field `summarize`. Reconciling the two is per-family migration work, not
a claim about today's wire. Unified `web` is the existing conceptual family shape
— `search | browse | manual` under one name — and is not changed by this file.
`web` is not yet a migrated family: it exposes no root `summarize`, has no LTP
settings surface, and has not been aligned to this contract.

Non-normative future illustration: `file` may later become one family with
actions `read | write | edit | glob | grep | manual`, while all six
implementations remain fully independent. That migration is not implemented, not
scheduled here, and not claimed.

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

Web's existing focused capability and wire tests are starting evidence for the
family/action shape only: they cover `action` / `input` / `manual`, and `web`
does not yet expose the root `summarize` field or an LTP settings surface. They
are not a conformance suite, and no such suite is required to exist.

## Maintenance

Keep this shared contract directional and concise. Add a family only after a real
scoped migration has code, contract/manual updates, and reviewed evidence that it
meets these rules. LTP alignment is maintained by keeping this contract and the
paired `ANATOMY.md` honest and current, not by a central validator; do not add
one here. Do not use this file to mass-normalize legacy schemas, to justify a
shared implementation framework, or to rename external provider protocol fields.
