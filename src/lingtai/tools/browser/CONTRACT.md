---
name: browser
contract_version: 2
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
  - src/lingtai/tools/browser/__init__.py
  - src/lingtai/tools/browser/manual/SKILL.md
  - tests/test_browser_capability.py
  - tests/test_browser_policy_cursor_edges.py
  - tests/test_browser_transport.py
maintenance: |
  This component contract is governed by the root CONTRACT.md. Keep
  related_files complete and repo-relative, including the paired Anatomy,
  Core-owned Port, production Adapter, exports, tests, and manual. Update the
  Port, Adapter, tests, and this contract together when a boundary or normative
  behavior changes; update the paired Anatomy when structure changes. Follow the
  root Anatomy/Contract pairing and ownership rules, report mismatches, and do
  not duplicate or auto-fix the rule here.
---
# Browser capability

## Purpose

`browser` is an opt-in, static public-page capability. It is deliberately
separate from `web_search`: it reads a caller-named HTTP(S) URL or a link
reference minted by the same live Agent and returns bounded, untrusted page
data.

## Behavior

The tool exposes `action="browse"` and `action="manual"`. Browse requires
exactly one `url` or `link_ref`; continuation also requires that caller-named
target and a cursor bound to its snapshot and `extract="article"` mode. The
manual route performs no network request and has a distinct manual response.

A successful browse is a structured `{status: "ok"}` result with requested and
final URL provenance, HTTP status/content type, static render identity, source
SHA-256, snapshot ID, stable ordered blocks and links, bounded pagination,
actual initial timings, warnings, and `untrusted_content: true`. Page text is
data, never instructions.

All failures are `{status: "failed", request_id, stage, error_code, message,
retryable, recommended_action, partial}` with sanitized bounded messages. There
is no search, dynamic renderer, PDF, session/cookie/auth, persistence, forms,
robots, credential, proxy, or hidden fallback behavior.

## Port

`BrowserPort` is a Core-owned technology-neutral outbound Port. `resolve`
returns every address answer for a hostname and accepts the remaining
end-to-end `timeout_s` supplied by Core. Core rejects unsafe answers before
calling `request`; the Adapter receives the exact `ResolvedTarget` and must
connect to one vetted IP without resolving again. `request` is one bounded GET,
with `max_bytes` in bytes and the remaining `timeout_s` in seconds, and never
follows a redirect. Calls are one-shot and have no cancellation, cookie,
credential, or persistent-client state in this slice. A retryable
`DNS_RESOLUTION_TIMEOUT` is distinct from DNS failure when the bounded resolver
wait expires.

## Adapters

`src/lingtai/adapters/browser_transport.py` is the production Adapter. It uses
stdlib HTTP(S), disables proxy environment behavior by using direct connections,
keeps the original hostname for Host and HTTPS SNI/certificate validation, and
pins the socket to the Core-vetted address. Browser package import does not
import this Adapter; `browser.setup()` is the sole composition seam. Tests may
inject a fake Port.

## Contract rules

- Only `http` and `https` public destinations are allowed. Userinfo,
  malformed ports, literal private/loopback/link-local/multicast/reserved/
  metadata/CGNAT/6to4 addresses, and any unsafe DNS answer fail before connect.
- Every redirect is resolved, SSRF-checked, and pinned before the next hop;
  redirects are capped and 4xx/5xx never become success. 429 and 5xx failures
  are retryable; ordinary client failures are not. DNS resolution, each
  redirect hop, connect, and body read all consume one 15-second end-to-end
  deadline; the stdlib Adapter permits at most one in-flight resolver lookup
  per transport instance and does not queue unbounded work.
- Download bytes, redirects, connections, timeout, extracted page size, link
  count, snapshot count, and reference count are bounded by fixed capability
  policy. Returned links are capped at 256 items and 24,000 characters total
  across returned link text plus URL fields (with 512-character text and
  2,048-character URL slices); exceeding either cap emits `LINKS_TRUNCATED`.
  The snapshot link target retains the full canonical URL; each returned ref is
  re-minted from it on every success response. `max_chars` is an
  actual integer in `[1, 100000]` and limits block text only; oversized blocks
  split losslessly at deterministic character offsets and do not consume the
  link budget.
- Cursor HMAC keys, snapshots, and link references live only for this Agent and
  process/task lifetime. Bounded LRU eviction fails loudly with a typed stale
  cursor/reference error; continuation re-mints its links from the snapshot's
  canonical targets without refetching or substituting another snapshot.
- HTML and plain-text decoding honors a bounded, declared Content-Type charset
  using Python text codecs only. UTF-8 is the default; malformed, unsupported,
  and decoding-error declarations fall back deterministically with stable
  warnings. Container-only `div`, `article`, `section`, `main`, and `body`
  text is emitted once in DOM order while semantic block kinds and skip-tag
  exclusions remain meaningful.
- Refresh or Agent reconstruction creates new state and invalidates old cursors
  and references. No filesystem snapshots, persistence, sessions, cookies,
  uploads, credentials, dynamic rendering, PDF, search, or configuration flags
  are part of this compatibility promise.

## Contract tests

`tests/test_browser_capability.py` covers schema, fake-Port policy/fetch,
extraction, provenance, source hashing, links, cursor continuation, stale state,
error sanitation, manual routing, and the real Agent registration/prompt gate.
`tests/test_browser_policy_cursor_edges.py` covers DOM-order containers,
declared charset fallback, and ref refresh after independent LRU eviction.
`tests/test_browser_transport.py` covers socket-level vetted-IP pinning,
body truncation, DNS failure/timeout/empty answers, Host/SNI preservation,
proxy-environment isolation, and bounded transport errors. The shared fake-Port
tests use no live network; the adapter tests use only hermetic local sockets or
mocked resolver/socket seams.

## Maintenance

Keep this Contract and `ANATOMY.md` reciprocal. A Port, Adapter, error,
ordering, state, or unsupported-capability change requires synchronized code,
tests, and contract updates. A structural move also updates Anatomy. Preserve
the manual edge on both owner twins and keep browser independent of the
unchanged `web_search` Contract and provider behavior.
