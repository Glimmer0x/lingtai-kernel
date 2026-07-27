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

## Adapters

Operator setup supplies immutable per-Agent engine specs, optional injected
SearchService instances, and browser ports. Provider construction is lazy and
cached per selected engine. The settings file is not a credential/configuration
channel and no request mutates `os.environ`. Existing browser SSRF, deadline,
provenance, source-hash, cursor, snapshot, reference, and typed-failure rules
remain in force.

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
  initialization-unavailable engine uses `SEARCH_ENGINE_UNAVAILABLE`. Browse
  and manual remain fully usable — including when `settings/web.search.json`
  is invalid — and never construct a search provider.
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
tests remain applicable. A real fresh Agent startup must prove exactly
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
