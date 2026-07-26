---
related_files:
  - src/lingtai/tools/ANATOMY.md
  - src/lingtai/tools/browser/CONTRACT.md
  - src/lingtai/tools/browser/__init__.py
  - src/lingtai/tools/browser/core.py
  - src/lingtai/tools/browser/port.py
  - src/lingtai/tools/browser/netpolicy.py
  - src/lingtai/tools/browser/fetcher.py
  - src/lingtai/tools/browser/extractor.py
  - src/lingtai/tools/browser/cursor.py
  - src/lingtai/tools/browser/snapshots.py
  - src/lingtai/tools/browser/refstore.py
  - src/lingtai/tools/browser/manual/SKILL.md
  - src/lingtai/adapters/browser_transport.py
  - src/lingtai/ANATOMY.md
  - tests/test_browser_capability.py
  - tests/test_browser_policy_cursor_edges.py
  - tests/test_browser_transport.py
maintenance: |
  Keep related_files repo-relative, duplicate-free, and linked to real files.
  Keep this Anatomy and its paired Contract reciprocal, keep the parent/child
  anatomy links bidirectional, and retain the manual edge on both owner twins.
  Code is the structural source of truth: update this map when files, symbols,
  connections, composition, or state change. Verify citations and run the
  architecture-document validation before merge. Follow the root pairing rule,
  report mismatches, and do not duplicate or auto-fix it.
---
# Browser capability Anatomy

The browser package is the driving tool adapter plus the Core-owned static
browse use case. Its Port and policy stay technology-neutral; the concrete
socket transport lives outside this package and is selected only by `setup()`.

## Components

- `BrowserManager`, `setup()`, `get_schema()` — model-facing route, registration, and lazy composition (`src/lingtai/tools/browser/__init__.py:38-108`).
- `BrowserEngine` — per-Agent orchestration for target validation, deadline-aware fetch/extract, provenance, pagination, bounded links, and typed results (`src/lingtai/tools/browser/core.py:116-339`).
- `BrowserFailure` — sanitized failure envelope with an optional numeric HTTP status when the fetch/extract stage knows it (`src/lingtai/tools/browser/core.py:26-67`).
- `BrowserPort`, `ResolvedTarget`, `TransportResponse`, `TransportError` — Core-owned outbound boundary, remaining DNS deadline, and typed Adapter errors (`src/lingtai/tools/browser/port.py:14-64`).
- `resolve_and_check()` and redirect helpers — scheme, userinfo, malformed URL, deadline-aware DNS-answer and SSRF policy (`src/lingtai/tools/browser/netpolicy.py:43-224`).
- `fetch()` — one end-to-end-deadline bounded one-hop Port call and manual redirect loop (`src/lingtai/tools/browser/fetcher.py:56-136`).
- `extract_html()` / `extract_plain_text()` — declared-codec decoding plus deterministic semantic/container blocks and links using the stdlib parser (`src/lingtai/tools/browser/extractor.py:145-220`).
- `CursorCodec` / `paginate_blocks()` — HMAC snapshot/mode cursors and lossless bounded pages; oversized next blocks use the remaining page budget at deterministic character offsets (`src/lingtai/tools/browser/cursor.py:22-143`).
- `InMemorySnapshotStore` / `RefStore` — bounded per-Agent LRU snapshots and independently evictable refs; snapshot links retain full canonical targets (`src/lingtai/tools/browser/snapshots.py:33-86`, `src/lingtai/tools/browser/refstore.py:8-37`).
- `VettedHttpTransport` — outside production Adapter for pinned HTTP(S) requests and single-in-flight bounded DNS lookup (`src/lingtai/adapters/browser_transport.py:17-165`).

## Connections

`Agent` reaches `setup_capability()` in `src/lingtai/tools/registry.py`, which
lazily imports this package. `setup()` registers the manager through generic
`Agent.add_tool()` and imports the production Adapter only when no fake Port is
injected. Core calls only `BrowserPort`; the Adapter depends inward on Port.
The manual loader reads the installed browser manual without invoking Core or
networking.

## Composition

The parent [`src/lingtai/tools/ANATOMY.md`](../ANATOMY.md) owns the built-in
registry and lazy tools DAG. The wrapper [`src/lingtai/ANATOMY.md`](../../ANATOMY.md)
owns Agent composition; the external Adapter is a navigation edge to this
owner, not a second browser Contract. The paired [`CONTRACT.md`](CONTRACT.md)
owns all browser promises, including the Port and manual behavior.

## State

`BrowserEngine` owns an HMAC key, bounded snapshot LRU, bounded link-reference
store, and fixed fetch policy for one Agent/process/task lifetime. Snapshot link
items retain a full canonical target plus bounded display fields; `_success`
re-mints refs from those targets because the RefStore may evict independently.
The production Adapter owns only its lock-guarded single in-flight resolver job;
no module mutable state, filesystem snapshot, cookie jar, credential, cache, or
cross-Agent ref/cursor state exists. Agent refresh/reconstruction makes a new
engine and invalidates old refs and cursors.

## Notes

All fetched text, title, snippets, and links are untrusted data. The current
slice is static HTTP(S) GET only; search remains in `web_search`, and dynamic
rendering, PDF, authentication, sessions, forms, persistence, and robots are
not hidden in fallback paths.
