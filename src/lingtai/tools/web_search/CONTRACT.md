---
name: web
contract_version: 4
root_contract: CONTRACT.md
related_files:
  - src/lingtai/tools/web_search/ANATOMY.md
  - src/lingtai/tools/CONTRACT.md
  - src/lingtai/tools/web_search/__init__.py
  - src/lingtai/tools/web_search/settings.py
  - src/lingtai/tools/web_search/manual/SKILL.md
  - src/lingtai/tools/browser/core.py
  - src/lingtai/tools/browser/port.py
  - src/lingtai/adapters/browser_transport.py
  - src/lingtai/services/websearch/__init__.py
  - src/lingtai/services/websearch/openai.py
  - src/lingtai/services/websearch/anthropic.py
  - src/lingtai/services/websearch/gemini.py
  - src/lingtai/kernel/tool_result_summary.py
  - src/lingtai/tools/tool_family/CONTRACT.md
maintenance: |
  Keep this unified web Contract and its Anatomy reciprocal. Keep the manual
  edge on both owner twins. Update the Port, adapters, tests, and this Contract
  together when behavior or errors change; retain browser as an internal browse
  subcomponent rather than a second capability. web's schema composition and
  envelope dispatch build on the generic tool_family package; keep that link
  current when either side's boundary changes.
---
# Unified web capability

## Purpose

`web` is exactly one model-facing capability with explicit `search`, `browse`,
and metadata-only `manual` actions. It is implemented in the retained
`tools.web_search` composition owner; browser and SearchService are internal
subcomponents. `web` is the first family migrated to the LingTai Tool Protocol
v2 shape defined in `src/lingtai/tools/CONTRACT.md`, and the first family to
build its schema composition and envelope dispatch on the generic
`src/lingtai/tools/tool_family/` infrastructure (`ToolFamily`/`ChildTool`);
using it changed no observable promise in this file.

## Behavior

Search rereads the action-owned `settings/web.search.json` selector on every
call; browse and manual read no settings file. Search returns bounded
structured results and same-Agent `link_ref` handles. Browse consumes a URL or
a search/browse reference through the same BrowserEngine state. Manual returns
the installed web-manual without provider construction or network I/O. All
success and failure envelopes include `action` and a bounded secret-free
`current_setting` block. Explicit `engine` and irrelevant action fields fail
loudly. `web`'s own schema (via `ToolFamily.build_schema()`) declares a
top-level, REQUIRED `reasoning` string property — Host InvocationContext/
audit metadata — with the same description Agent schema composition also
re-injects into every tool's `properties` uniformly (that central injection
never touches `required`, so a family must declare `reasoning` required
itself). ToolExecutor preserves it only as internal `_reasoning` metadata,
which does not enter action input or change dispatch. `web`'s own schema owns
the root `summarize` boolean (LTP v2 is
migrated one family at a time, not by central injection); `handle()` delegates
to a per-instance `ToolFamily.handle()` (`tool_family/CONTRACT.md`), which
validates `summarize` is boolean and strips it before action dispatch — no action implementation
ever receives it.

## Port

Search uses the existing internal `SearchService.search(query)` boundary.
Browse uses the existing Core-owned `BrowserPort` implemented by the pinned
transport adapter. The public dispatcher never invokes search from browse or
browser transport from search.

## Provider ownership and routing

Built-in Search admits exactly four engines: canonical first-party OpenAI
Responses Web Search, canonical first-party Anthropic server-side Web Search,
canonical first-party Gemini Google Search grounding, and DuckDuckGo. MiniMax
and Zhipu are retired from built-in admission entirely (`_RETIRED_PROVIDERS`
in `web_search/__init__.py`). Their `SearchService` implementations were
deleted 2026-07-28 (Jason authorized the exact two-path deletion, issue
11114) — `src/lingtai/services/websearch/minimax.py` and `.../zhipu.py` no
longer exist, and `create_search_service()`'s factory branches for both were
removed with them, so an unrecognized `"minimax"`/`"zhipu"` name now raises
the factory's own documented `ValueError` like any other unknown provider,
never an uncaught `ModuleNotFoundError`. Wire either provider through a
third-party MCP server instead — see
`src/lingtai/tools/mcp/manual/reference/third-party-and-legacy.md`, the
skill-owned procedure route. Naming either via `provider=`, `default_engine=`,
or `engines={}` at `web` composition time raises `RetiredProviderError` — a
composition-time, actionable failure, never a silent DuckDuckGo substitution
and never reaching the factory at all. This is distinct from the pre-existing
`legacy_fallback_from`-tagged DuckDuckGo behavior, which remains in force
only for a genuinely unrecognized/inherited legacy provider name that was
never a deliberately-retired built-in.

`RetiredProviderError` is reserved exactly for MiniMax/Zhipu. Anthropic and
Gemini are fully active, currently-admitted canonical providers — never
described as "retired" anywhere in code, docs, or error text — restricted only
to a settings-only selection route; naming either through a forbidden
composition route raises the distinct `SettingsOnlyProviderError` (see below).

The real no-config `setup(agent)` path (no `engines=`, `provider=`,
`default_engine=`, or `search_service=`) composes the true built-in spec set:
all four canonical providers, with `openai`/`anthropic`/`gemini` each reading
only their own standard, publicly-documented API-key environment variable
(`OPENAI_API_KEY`/`ANTHROPIC_API_KEY`/`GEMINI_API_KEY` — the same names each
provider's own first-party LLM adapter already trusts,
`src/lingtai/llm/{openai,anthropic,gemini}/defaults.py`) — never the current
Agent's own live `agent.service` credentials or any private LLM-adapter
attribute. The built-in default engine is resolved live, per call: canonical
OpenAI when its standard credential is genuinely present, else DuckDuckGo.
Anthropic and Gemini are present in this spec set (so their status is
honestly reported in `current_setting`) but are never the *selected* default;
only a valid `settings/web.search.json` selection can select them.

Anthropic and Gemini are explicit opt-in **only** through a valid hot-read
`settings/web.search.json` selection. A composition-time `default_engine=`/
`provider=` naming either one is rejected outright with
`SettingsOnlyProviderError` at `setup()` time (an `engines={}` mapping may
still declare a bounded spec for one of them — credential/service injection
for tests/integration — without that composition selecting it as the
default). Once selected through settings, the call fails loudly with
`PROVIDER_BACKEND_INELIGIBLE` — no provider construction, no search call —
unless the current Agent's own live LLM backend truthfully IS that same
canonical provider, per the module-private `_same_provider_identity()`
predicate in `web_search/__init__.py` (exact match against
`agent.service.provider`; Claude Code, `custom`, `openrouter`, and every
other aliased/wire-compatible provider name are never treated as canonical
Anthropic/Gemini identity, regardless of API compatibility). This predicate
is private to `web` — no cross-tool identity API was created for one policy.
A runtime failure of an explicitly selected Anthropic/Gemini engine reports
`SEARCH_FAILED`; it is never silently substituted with DuckDuckGo or any
other engine — see the error hierarchy below for exactly how each provider's
own adapter reports that failure.

**Provider error hierarchy.** `src/lingtai/services/websearch/__init__.py`
defines `SearchProviderError(provider, failure_class)`, a shared, narrow base
raised by all three canonical adapters on a runtime failure — bounded to a
provider name and a failure class, never raw SDK exception text, request
bodies, or credentials in the message, logs, or any returned structure. Each
adapter's own subclass carries the same shape: `OpenAISearchError`,
`AnthropicSearchError`, `GeminiSearchError`. None of the three ever swallows
a genuine SDK/HTTP failure to `[]` — `[]` is reserved for a genuine
successful provider response with no content/result. `AnthropicSearchService`
additionally detects Anthropic's official in-body HTTP-200
`web_search_tool_result_error` (the API can return `status_code=200` while
the web search tool itself failed — evidence doc: "the Claude API still
returns a 200 (success) response") and raises `AnthropicSearchError`
carrying only the bounded `error_code`, never the raw block or any other
response content.

OpenAI is the sole engine with an automatic runtime fallback, and only for
the exact `OpenAISearchError` subclass (timeout, rate limit, HTTP/SDK
error). On that specific exception type, `web` executes exactly one
DuckDuckGo search and returns `status: "ok"` with `engine: "openai"`
(selected) and `actual_engine: "duckduckgo"` (actual), a top-level `comment`
line stating that OpenAI failed and DuckDuckGo was used, and bounded,
secret-free `openai_failure_class`/`duckduckgo_failure_class` provenance. If
the DuckDuckGo fallback also fails, the call fails with `SEARCH_FAILED` and
both bounded failure classes; there is no second retry and no recursive
fallback. A typed `AnthropicSearchError`/`GeminiSearchError` (or any other
`SearchProviderError` on a non-OpenAI engine) fails with `SEARCH_FAILED` and
a bounded `provider_failure_class`, never touching DuckDuckGo. Any non-typed
exception (a manager/programming defect — a `TypeError` or `AttributeError`
from malformed data, never raised by the adapters themselves) fails normally
with `SEARCH_FAILED` and no provenance field, and also never touches
DuckDuckGo. No engine other than OpenAI has an automatic fallback.

Each canonical provider's `SearchService` extracts real, official per-source
citation URLs from its own provider response — OpenAI's Responses `output[]`
message `annotations[].url_citation`, Anthropic's `web_search_result_location`
text citations (falling back to raw `web_search_tool_result` items), and
Gemini's `grounding_metadata.grounding_chunks[].web` (field names verified
2026-07-28 read-only against the installed `google-genai` 2.10.0 package
source, `google/genai/types.py`) — never an invented URL. When a provider
genuinely returns a nonempty search-grounded narrative with no citation (a
legally valid response shape for all three official APIs), exactly
one bounded narrative `SearchResult` with `url=""` is preserved rather than
silently discarded; `WebManager` never fabricates a `link_ref` for it
(`link_ref: null` in that one case only — every other result with a real URL
gets a real `link_ref`).

## Adapters

Operator setup supplies immutable per-Agent engine specs, optional injected
SearchService instances, and browser ports. Provider construction is lazy and
cached per selected engine. The settings file is not a credential/configuration
channel and no request mutates `os.environ`. Existing browser SSRF, deadline,
provenance, source-hash, cursor, snapshot, reference, and typed-failure rules
remain in force. `OpenAISearchService` uses the canonical Responses API
(`client.responses.create(tools=[{"type": "web_search"}])`), not the retired
Chat Completions `gpt-4o-search-preview` route, and raises `OpenAISearchError`
(a bounded failure-class carrier, never raw SDK exception text) on failure
instead of swallowing to an empty result — the one provider adapter whose
failure the Web use-case policy must observe to drive the DuckDuckGo fallback
above.

## Contract rules

- The public name is `web`; no browser or web_search registry, schema, prompt,
  check-caps, catalog, or installed manual entry exists.
- `web` is the first real implementation of the shared LTP v2 contract in
  `src/lingtai/tools/CONTRACT.md`: the final model-facing root is exactly
  `action`, `input`, `reasoning`, and `summarize`. There is no public
  `parameters`, `parameter`, `summary`, or other compatibility alias;
  `_reasoning` is internal only.
- `action`, nested `input`, and top-level `reasoning` are required by the
  capability schema (`required: [action, input, reasoning]`). `action` is
  one of `search`, `browse`, or `manual`; `input` uses strict action-specific
  object branches. Each branch is closed, every declared branch field is
  required, and browse optionals use JSON null, matching OpenAI strict-object
  conventions. No branch admits `reasoning`, `_reasoning`, or `summarize`.
- `summarize` is a root-only optional boolean, absent or false by default. It
  is envelope metadata, not action input: `handle()` validates its type
  (non-boolean fails loudly with `INVALID_ARGUMENT`) and strips it before
  dispatching to `search`/`browse`/`manual`. `src/lingtai/kernel/
  tool_result_summary.py` recognizes canonical root `summarize=true` for
  `web` specifically (scoped by tool name, alongside the legacy literal
  `summary` flag it preserves for genuinely unmigrated callers) and treats
  `web`'s own canonical `status: "failed"` envelope as an unsummarizable error
  result, exactly like the kernel-wide `status: "error"` convention — scoped
  to migrated LTP v2 families so an unrelated tool's non-error `"failed"`-named
  domain value is never reinterpreted.
- Settings v1 is the direct, action-owned strict schema
  `{"schema_version":1,"engine":"<admitted-name>"}`, read from
  `settings/web.search.json` (a direct child of `<agent-dir>/settings/`; no
  nested `search` object). There is no family-owned `settings/web.json`, no
  `settings/web.browse.json` or `settings/web.manual.json`, no cross-read of
  any old or sibling settings path, and no compatibility fallback, overlay, or
  merge. Only an operator-admitted engine name is permitted. Missing files use
  the operator/built-in default; malformed, unknown, disallowed, unavailable,
  or credential-missing selections fail search without substitution. Invalid
  settings use error code `WEB_SETTINGS_INVALID`; a selected or
  initialization-unavailable engine uses `SEARCH_ENGINE_UNAVAILABLE`; a
  selected Anthropic/Gemini engine on a non-canonical backend uses
  `PROVIDER_BACKEND_INELIGIBLE`. Browse and manual remain fully usable —
  including when `settings/web.search.json` is invalid — and never construct
  a search provider.
- Settings reads reject symlinks, non-regular files, unstable snapshots,
  oversize/wrong-UTF-8 data, unknown fields, duplicate fields, and wrong
  schema. A changed file is observed on the next call (hot-read, no caching).
  Diagnostics contain source, selected engine/null, bounded available statuses,
  revision/hash, and the exact change hint `Edit settings/web.search.json;
  changes apply on the next web call; use web(action='manual', input={},
  reasoning='load web guidance') for schema.`; secrets and absolute paths never
  appear.
- Search results are bounded `{title,url,snippet,link_ref}` objects with count
  and actual engine. References are same-Agent handles accepted by browse.
  `link_ref` is `null` only for the one bounded citation-free narrative
  result a canonical provider may legally return; every result with a real
  `url` gets a real `link_ref`, never a fabricated one for an empty `url`.
- Composing `web` with a retired provider (`minimax`, `zhipu`) via
  `provider=`, `default_engine=`, or `engines={}` raises
  `RetiredProviderError` at `setup()` time. Composing with a settings-only
  provider (`anthropic`, `gemini`) via `provider=` or `default_engine=`
  raises the distinct `SettingsOnlyProviderError` instead — both are
  composition-time, actionable Python exceptions, not a runtime search
  result; the two classes are never conflated, since Anthropic/Gemini are
  active canonical providers and MiniMax/Zhipu are not. `engines={}` may
  still declare a bounded spec for `anthropic`/`gemini` (credential/service
  injection) without that composition selecting either as the default.
- Browse remains static public HTTP(S) only with its existing SSRF/DNS,
  extraction, provenance, cursor, snapshot, deadline, and typed-failure rules,
  and stays provider/network independent of the search settings file.

## Contract tests

Focused direct checks cover canonical and legacy configuration normalization,
opaque dependency identity, schema/prompt/catalog uniqueness, lazy provider
construction, action-owned settings file states (missing, valid, malformed,
wrong schema, unknown/duplicate fields, disallowed selector, symlink/non-
regular file, changed-file-observed-next-call), no old-path cross-read,
explicit argument rejection, environment immutability, search-to-browse
continuation, and manual/browse operation with invalid settings and no
provider construction. Existing browser Core/Port and SearchService contract
tests remain applicable. Provider ownership/routing checks cover: the real
no-config `setup(agent)` path composes all four canonical specs and
genuinely selects OpenAI via its standard `OPENAI_API_KEY` env var when set
(proved with real environment isolation, not a test-only injected `engines=`
set standing in for the default), else DuckDuckGo, without overriding an
explicit operator default; MiniMax/Zhipu are absent from `PROVIDERS` and
raise `RetiredProviderError` from the flat-`provider=`, `default_engine=`,
and map-shaped `engines={}` composition paths alike — never a DuckDuckGo
substitution — while a genuinely unrecognized/inherited legacy provider name
keeps the pre-existing `legacy_fallback_from` DuckDuckGo behavior; a
composition-time `default_engine=`/`provider=` naming `anthropic`/`gemini`
raises the distinct `SettingsOnlyProviderError` (never `RetiredProviderError`
— both are still active canonical providers), and only a valid hot-read
`settings/web.search.json` selection (live-changed, no refresh required) can
select either, subject to canonical-backend eligibility that succeeds for a
truthfully-canonical backend and fails `PROVIDER_BACKEND_INELIGIBLE` (no
provider construction, no search call) on every non-canonical backend
including Claude Code and `custom`/aliased providers; a settings-selected
Anthropic/Gemini runtime failure raises the adapter's own typed
`AnthropicSearchError`/`GeminiSearchError` (including Anthropic's official
in-body `web_search_tool_result_error`) and reports `SEARCH_FAILED` with a
bounded `provider_failure_class`, proved end-to-end through the real adapter
class plus `WebManager`, never invoking DuckDuckGo; an OpenAI runtime
failure raising the typed `OpenAISearchError` falls back to exactly one
DuckDuckGo search with a comment line and bounded dual failure-class
provenance, a non-`OpenAISearchError` exception (a programming defect) fails
normally without touching DuckDuckGo, and a non-OpenAI engine's runtime
failure never triggers that fallback; all three canonical providers'
`SearchService.search()` are proved, using provider-shaped fake Responses/
Anthropic/Gemini objects passed through the real extraction code, to return
nonempty results with real link refs when official citations/grounding
chunks/result blocks are present, and exactly one bounded narrative
result with `link_ref: null` (never a fabricated one) when the official API
legally returns a citation-free grounded narrative. A real
fresh Agent startup must prove exactly
`action` / `input` / `reasoning` / `summarize` at the root, no cross-cutting
field in any nested input branch, internal `_reasoning` dispatch,
resident/batched prompts, and both Chat and Responses tool wires. Executor-
level evidence proves the raw result is durably logged before any visible
`summarize=true` replacement on both the sequential and a controlled-parallel
path, and that search/browse `status: "failed"` results stay byte/content
exact and unsummarized under `summarize=true`.

## Maintenance

Keep this Contract and `ANATOMY.md` reciprocal and keep the web-manual edge on
both. Physical legacy modules, provider-native wire strings, and internal
browser files remain retained; they are not additional model-facing surfaces.
