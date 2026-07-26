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
  - src/lingtai/tools/email/CONTRACT.md
  - src/lingtai/tools/email/__init__.py
  - tests/test_browser_capability.py
  - tests/test_wire_tool_description.py
maintenance: |
  This component contract is governed by the root CONTRACT.md. Keep the paired
  tools Anatomy and cross-contract links reciprocal. Update Agent schema
  composition, ToolExecutor normalization, the migrated capability, wire tests,
  and this contract together when the canonical call boundary changes. Migrate
  one real vertical slice at a time; do not claim legacy tools already conform.
---
# Model-facing tool call contract

## Purpose

Define LingTai's future canonical public argument shape for model-facing tools:
exactly three root blocks named `action`, `input`, and `reasoning`. This is a
migration target applied capability by capability, not a silent reinterpretation
of every existing tool. Unified `web` is the first real wire-tested implementation.

## Behavior

Once a capability is explicitly migrated, its final Agent-built model-facing
argument schema is a closed object whose root properties are exactly:

- `action`: the operation selector;
- `input`: the one strict action-specific payload object; and
- `reasoning`: the top-level rationale for this tool call.

There is no fourth public metadata block. Existing tools retain their current
explicit schemas until a scoped migration changes their code, tests, manual, and
contract together.

### A-priori summary transition

The shared kernel summary predicate uses the presence of the `input` key as the
mode discriminator. A canonical call requests a summary only when `input` is a
Mapping/object and `input.summary` is exactly the boolean `true`; once `input` is
present, root `summary` is ignored and is never a fallback, even when `input` is
malformed, missing `summary`, or carries a false/non-boolean value. No truthy
coercion, flattening, or argument mutation is permitted. A call with no `input`
key remains in legacy mode and requests only when root `summary` is exactly
`true`.

This is a transitional compatibility rule, not a second public schema: migrated
capabilities that support a-priori summary advertise that flag only as nested
`input.summary`, while unmigrated legacy advertisers retain their root flag until
their own vertical migration. Tool errors continue to bypass summarization. The
raw result is durably recorded before either nested or legacy summary control is
applied; generated, refusal, and fail-closed no-gateway replacements are
model-visible substitutes with the
existing raw locator and metadata.

The root-summary branch may be removed only in the commit that migrates the last
currently legacy root-summary advertiser (including shell's historical `bash`
rolling alias and daemon), and only after a registry-wide test proves that no
provider-facing schema advertises root `summary`, no migrated handler accepts
flat fields, and no supported pending legacy call relies on the root shape. Until
that final removal gate, root lookup is permitted solely when `input` is absent.

## Port

The provider-neutral boundary is the final `FunctionSchema` assembled by the
Agent. A migrated capability owns `action` plus strict nested `input`; Agent
schema composition owns the standard top-level `reasoning` field. The capability
dispatcher validates that `input` matches `action` before invoking its use case.

## Adapters

Provider adapters wrap the same schema in their protocol-native envelope.
OpenAI's outer `parameters`, Anthropic's `input_schema`, and the internal
`FunctionSchema.parameters` attribute are transport or implementation names and
remain unchanged; none creates a public LingTai block named `parameters`.
ToolExecutor removes public `reasoning` before handler dispatch and may preserve
it as internal `_reasoning` metadata. `_reasoning` must never appear in the
model-facing schema or nested `input`.

## Contract rules

- The final migrated root property set is exactly `action`, `input`, and
  `reasoning`, with `additionalProperties: false`. The capability-required set
  is `action` and `input`; standard Agent composition adds top-level `reasoning`
  without moving it into action input.
- `input` is one object selected by `action`. Strict action branches are closed;
  declared optional fields use the provider-compatible nullable representation.
- Nested `input` contains neither `reasoning` nor `_reasoning`.
- A migrated capability validates action/input correspondence again at dispatch;
  schema conformance alone is not the authorization or safety boundary.
- No public `parameters`, `parameter`, `arguments`, `payload`, or compatibility
  alias is admitted after migration. Provider envelope names are not aliases.
- Internal `_reasoning` is metadata only: handlers may admit it after
  ToolExecutor normalization but must not treat it as action input.
- Migration is vertical and explicit. Legacy tools are neither mass-renamed nor
  declared conforming without their own implementation, docs, and wire evidence.
- Unified `web` is the first conforming implementation and the proving ground for
  the contract; its component contract owns web-specific behavior.

## Contract tests

A migrated capability must prove: exact final Agent root properties, capability-
required `action` / `input`, closed strict input branches; absence of reasoning fields below root; successful
internal `_reasoning` dispatch; unchanged provider envelope semantics; Chat and
Responses serialization; a hermetic fresh Agent startup and complete prompt
build; and a real model-facing call after refresh when runtime wiring changes.
Web's focused capability and wire tests are the first conformance suite.

## Maintenance

Keep this shared contract directional and concise. Add a capability only after a
real scoped migration has code, contract/manual updates, provider-wire tests, and
runtime evidence. Do not use this file to mass-normalize legacy schemas or rename
external provider protocol fields.
