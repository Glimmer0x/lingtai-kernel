---
name: browser-internal
contract_version: 3
root_contract: CONTRACT.md
related_files:
  - src/lingtai/tools/browser/ANATOMY.md
  - src/lingtai/tools/browser/port.py
  - src/lingtai/tools/browser/core.py
  - src/lingtai/tools/browser/fetcher.py
  - src/lingtai/tools/browser/netpolicy.py
  - src/lingtai/tools/browser/extractor.py
  - src/lingtai/tools/browser/cursor.py
  - src/lingtai/tools/browser/snapshots.py
  - src/lingtai/tools/browser/refstore.py
  - src/lingtai/adapters/browser_transport.py
  - src/lingtai/tools/web_search/CONTRACT.md
  - tests/test_browser_capability.py
maintenance: |
  This is the internal browse-subcomponent Contract owned by unified web.
  Keep its Anatomy reciprocal and preserve the Core Port, adapter, SSRF,
  provenance, cursor, snapshot, reference, deadline, and typed-failure rules.
  It is not a public capability and must not acquire a registry, schema, prompt,
  catalog, or manual entry of its own.
---
# Internal browse subcomponent

## Purpose

This package is the bounded static browse Core/Port used by the public `web`
capability. It is retained as a technology-neutral child, not a separate
model-facing browser tool.

## Behavior

`BrowserEngine.handle` accepts browse arguments and returns the existing
structured success or typed failure payload, including provenance, source hash,
SSRF-safe redirects, snapshots, cursors, refs, bounded extraction, and
`untrusted_content`. The unified parent adds public `action` and setting
metadata. Manual loading belongs to the parent web manager.

## Port

`BrowserPort.resolve` and `request` remain the Core-owned outbound boundary.
The production pinned HTTP(S) transport is outside this package and receives
vetted targets and remaining end-to-end deadlines.

## Adapters

`src/lingtai/adapters/browser_transport.py` is the production adapter. Tests
inject a fake BrowserPort. No adapter registers a model-facing tool.

## Contract rules

Only public HTTP(S) destinations are accepted. Existing DNS/SSRF, redirect,
content, charset, byte, link, snapshot, ref, cursor, timeout, and typed-error
bounds remain normative. SearchService is not imported or called by this Core.
Refresh/reconstruction must use fresh per-Agent state; no filesystem snapshot,
credential, cookie, or hidden fallback is part of this subcomponent.

## Contract tests

The existing browser capability, policy/cursor-edge, and transport tests cover
this child. Unified web checks additionally prove search result references use
this same live engine without causing a second public registration.

## Maintenance

Keep this internal Contract paired with its Anatomy and linked from the parent
web Contract as an implementation boundary. Do not expose `browser` as a
capability name or install its retained manual bundle.
