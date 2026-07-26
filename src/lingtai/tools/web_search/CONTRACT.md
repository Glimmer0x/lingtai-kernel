---
name: web
contract_version: 2
root_contract: CONTRACT.md
related_files:
  - src/lingtai/tools/web_search/ANATOMY.md
  - src/lingtai/tools/web_search/__init__.py
  - src/lingtai/tools/web_search/settings.py
  - src/lingtai/tools/web_search/manual/SKILL.md
  - src/lingtai/tools/browser/core.py
  - src/lingtai/tools/browser/port.py
  - src/lingtai/adapters/browser_transport.py
  - src/lingtai/services/websearch/__init__.py
maintenance: |
  Keep this unified web Contract and its Anatomy reciprocal. Keep the manual
  edge on both owner twins. Update the Port, adapters, tests, and this Contract
  together when behavior or errors change; retain browser as an internal browse
  subcomponent rather than a second capability.
---
# Unified web capability

## Purpose

`web` is exactly one model-facing capability with explicit `search`, `browse`,
and metadata-only `manual` actions. It is implemented in the retained
`tools.web_search` composition owner; browser and SearchService are internal
subcomponents.

## Behavior

Every call rereads the Agent-owned `settings/web.json` selector. Search returns
bounded structured results and same-Agent `link_ref` handles. Browse consumes a
URL or a search/browse reference through the same BrowserEngine state. Manual
returns the installed web-manual without provider construction or network I/O.
All success and failure envelopes include `action` and a bounded secret-free
`current_setting` block. Explicit `engine` and irrelevant action fields fail
loudly; kernel-injected `reasoning` is ignored.

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
- `action` is required and is one of `search`, `browse`, or `manual`.
- Settings v1 is exactly `{"schema_version":1,"search":{"engine":"..."}}`.
  Only an operator-admitted engine name is permitted. Missing files use the
  operator/built-in default; malformed, unknown, disallowed, unavailable, or
  credential-missing selections fail search without substitution. Invalid settings
  use error code `WEB_SETTINGS_INVALID`; a selected or initialization-unavailable
  engine uses `SEARCH_ENGINE_UNAVAILABLE`. Browse and manual remain usable and
  report the settings error.
- Settings reads reject symlinks, non-regular files, unstable snapshots,
  oversize/wrong-UTF-8 data, unknown fields, duplicate fields, and wrong schema.
  Diagnostics contain source, selected engine/null, bounded available statuses,
  revision/hash, and the exact change hint `Edit settings/web.json; changes apply
  on the next web call; use web(action='manual') for schema.`; secrets and absolute
  paths never appear.
- Search results are bounded `{title,url,snippet,link_ref}` objects with count
  and actual engine. References are same-Agent handles accepted by browse.
- Browse remains static public HTTP(S) only with its existing SSRF/DNS,
  extraction, provenance, cursor, snapshot, deadline, and typed-failure rules.

## Contract tests

Focused direct checks cover canonical and legacy configuration normalization,
opaque dependency identity, schema/prompt/catalog uniqueness, lazy provider
construction, settings file states and revision changes, explicit argument
rejection, environment immutability, search-to-browse continuation, and manual
operation with invalid settings. Existing browser Core/Port and SearchService
contract tests remain applicable. A real fresh Agent startup must inspect
resident/batched prompts, tool schemas, and live chat tools.

## Maintenance

Keep this Contract and `ANATOMY.md` reciprocal and keep the web-manual edge on
both. Physical legacy modules, provider-native wire strings, and internal
browser files remain retained; they are not additional model-facing surfaces.
