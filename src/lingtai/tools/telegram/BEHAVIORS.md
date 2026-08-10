---
name: telegram-behavior-tests
behavior_version: 1
labt_version: 1
---

related_files:
  - src/lingtai/tools/telegram/manager.py
  - src/lingtai/tools/telegram/SKILL.md
  - src/lingtai/mcp_servers/telegram/task_card/CONTRACT.md
  - src/lingtai/mcp_servers/telegram/task_card/ANATOMY.md
  - src/lingtai/tools/feishu/_family.py
  - src/lingtai/tools/feishu/manager.py
  - src/lingtai/tools/web_search/CONTRACT.md
  - src/lingtai/tools/web_search/__init__.py
  - src/lingtai/tools/file/CONTRACT.md
  - src/lingtai/tools/file/_read.py
  - src/lingtai/tools/CONTRACT.md
  - tests/test_telegram_task_card_last_message.py
  - tests/test_telegram_reaction_states.py
  - tests/test_web_canonical_provider_routing.py
  - tests/test_read_continuation.py
  - tests/test_feishu_toolfamily_ltpv2.py
maintenance:
  migrated: 2026-08
  migration: CONVERT_BEHAVIOR from the five legacy test files listed above
  note: src/lingtai/tools/telegram has no sibling CONTRACT.md yet; the Telegram
    task-card contract lives at src/lingtai/mcp_servers/telegram/task_card/CONTRACT.md
    and Telegram reaction semantics are guarded by src/lingtai/tools/telegram/SKILL.md
---

# LABT v1 behaviors — comms/channels family

This file captures agent-observable behaviors for the comms/channels tool family in
lingtai-kernel, converted from the five CONVERT_BEHAVIOR test files listed in the
frontmatter. Every behavior below pins exact paths, tool names, commands, and expected
values so a test harness can reproduce it verbatim. C001 covers the
Telegram task-card projection, C002 covers Telegram reaction states, C003–C004 cover web
canonical provider routing (search→browse), C005 covers file read continuation, and
C006 covers the Feishu tool family LTP v2 envelope.

## Behavior C001 — Telegram task card: edit-in-place vs supersede by last message

- **LABT id**: C001
- **Title**: Telegram task-card last-message semantics (edit-in-place, rotation, failure paths)
- **Guards**: test only runs with the telegram task-card fake transport; no network.
- **Supersedes**: tests/test_telegram_task_card_last_message.py (CONVERT_BEHAVIOR)
- **Runner**: pytest tests/test_telegram_task_card_last_message.py
- **Prerequisites**: repo checkout with src/lingtai/mcp_servers/telegram/task_card.
- **Estimate**: 20 minutes.

### Steps

1. Start from a cold state (no resident task-card message).
2. Update the task card with `taskcard_update(draft="old text")`; note the resulting
   resident message id (compound id `mybot:55:100`).
3. Update again with `taskcard_update(draft="new text")` while the previous message is
   still the last one the bot sent.
4. Send a user message (user msg id `200`), then update the card again.
5. Force the bot to send an unrelated message (bot reply id `101`), then update again.
6. Rotate the resident card to a fresh message id (`mybot:55:201`), then update again.
7. Run the cold-state and failure-path scenarios below.

### Expected evidence

- **Edit-in-place**: when the resident task-card message is still the last message, the
  update result is `{status: ok, message_id: <same id>}` and exactly **1 send, 0 delete**
  transport calls occur.
- **Supersede by user message**: a user message after the resident card means the card is
  no longer "last"; the update rotates the card — the old resident message (`mybot:55:100`)
  is deleted and a new card is sent.

- **Rotation call order** (user msg id `200` case): transport sees exactly
  `edit(55, 100, <committed old text>)` → `delete(55, 100)` → `send(55, 201, <new text>)`
  with compound ids `mybot:55:100` / `mybot:55:201`; the rotation happens **before** the
  new send, so the card is never duplicated.
- **Supersede by bot message**: a bot reply (`mybot:55:101`) between the card and the
  update also rotates: `delete(55, 100)` → `send(55, 301, <new text>)`.
- **Rotation failure paths** (each returns `{status: ok, taskcard: false}` and a distinct
  marker): old resident already gone → `old_resident_deleted`; delete raises →
  `stale_delete_failed`; send raises after rotation → `indeterminate_send`; persist of
  the new resident fails → `resident_persist_failed`. Suppressed updates return
  `{status: ok, suppressed: true, taskcard: false}`.
- **Malformed send ids** (e.g. `no-colon-id`, `just:one`) are never adopted as the new
  resident; the update is suppressed.
- **Concurrency**: the task-card manager serializes rotation; only one in-flight rotation
  is allowed (`max_active == 1`).

### Pass / Fail

PASS when all evidence above holds; FAIL on any extra send/delete, any wrong id, or any
missing failure marker.

## Behavior C002 — Telegram reaction states (received → seen → replied)

- **LABT id**: C002
- **Title**: Telegram reaction state transitions and reply-vs-send semantics
- **Guards**: fake telegram transport; reactions never hit the network.
- **Supersedes**: tests/test_telegram_reaction_states.py (CONVERT_BEHAVIOR)
- **Runner**: pytest tests/test_telegram_reaction_states.py
- **Prerequisites**: src/lingtai/tools/telegram/SKILL.md section `#reply-vs-send`
  (the guard for reply-vs-send until a telegram root contract exists).
- **Estimate**: 15 minutes.

### Steps

1. Deliver a user message with `message_id=12345` that mentions a tool call with
   `reply_to_message_id=8`.
2. Let the handler run the received → seen → replied state machine.

### Expected evidence

- `REACTION_RECEIVED` is `[{type: "emoji", emoji: "👍"}]`; `REACTION_SEEN` is `"👀"`;
  `REACTION_REPLIED` is `"✍️"`; `REACTION_DONE` equals `REACTION_REPLIED`.
- The transport receives exactly the reaction sequence
  `[(12345, 8, "👍"), (12345, 8, "👀")]` — received and seen both react to
  `message_id=12345`, `reply_to_message_id=8`.
- If seen-reaction delivery fails, the seen step is **skipped** (no retry, no crash)
  and the sequence stays `[(12345, 8, "👍")]`.
- On reply, the state machine reacts `(12345, 8, "✍️")` — it reacts to the message
  whose id is `_reply_to_message_id` (8), not to a separately sent message.

### Pass / Fail

PASS when the reaction sequence and skip-on-delivery-failure match exactly; FAIL on any
missing reaction, extra reaction, or a reply that sends instead of reacting.

## Behavior C003 — Web canonical provider routing: default selection and hot config

- **LABT id**: C003
- **Title**: web search→browse canonical provider selection and hot-read settings
- **Guards**: provider factories are stubbed; no network; env vars are managed per-case.
- **Supersedes**: tests/test_web_canonical_provider_routing.py (CONVERT_BEHAVIOR)
- **Runner**: pytest tests/test_web_canonical_provider_routing.py
- **Prerequisites**: src/lingtai/tools/web_search/CONTRACT.md section
  `#provider-ownership-and-routing`; tool name `web` per web_search CONTRACT.md.
- **Estimate**: 30 minutes.

### Steps

1. Clear all provider env vars, then set `OPENAI_API_KEY` and call the `web` tool's
   search provider selection.
2. Clear `OPENAI_API_KEY` too, so no keys exist; select again.
3. Set only `ANTHROPIC_API_KEY` (or `GEMINI_API_KEY`); select again.
4. Write `settings/web.search.json` with `{"schema_version": 1, "engine": ...}` and
   select again without restarting.

### Expected evidence

- With `OPENAI_API_KEY` set and nothing else: `engine == "openai"`,
  `source == "built_in_default"`, and the factory tuple is
  `("openai", api_key=<env value>, model=None)`.
- With **no** keys: `engine == "duckduckgo"` (built-in default fallback).
- With only anthropic/gemini keys: the corresponding engine is **available but
  unselected**; `PROVIDERS["providers"]` is exactly
  `{"duckduckgo", "gemini", "anthropic", "openai"}`.
- Settings file present: selection re-reads it hot — `engine` matches the file, and
  `source == "settings/web.search.json"` (relative to the working dir).
- `minimax` and `zhipu` are retired: composing either raises `RetiredProviderError`
  before any factory runs.

## Behavior C004 — Web routing constraints, typed errors, and fallback

- **LABT id**: C004
- **Title**: settings-only/backend-gated providers, typed failures, DDG fallback,
  link_ref extraction, browse independence
- **Guards**: same as C003 (stubbed factories, managed env).
- **Supersedes**: tests/test_web_canonical_provider_routing.py (CONVERT_BEHAVIOR)
- **Runner**: pytest tests/test_web_canonical_provider_routing.py
- **Prerequisites**: web_search CONTRACT.md `#provider-ownership-and-routing`.
- **Estimate**: 30 minutes.

### Steps

1. Select anthropic/gemini via `settings/web.search.json` while the active backend is a
   non-canonical one (`claude-code`, `openai`, `openrouter`, `custom`, or `codex`).
2. Force each typed failure below and inspect the error envelope.
3. Make OpenAI-only search fail, then fall back; inspect the fallback result.
4. Call `web` browse with a URL and with an empty URL.

### Expected evidence

- **Backend-gated**: settings-selected anthropic/gemini on the non-canonical backends
  listed above is refused with `error_code == "PROVIDER_BACKEND_INELIGIBLE"` (distinct
  from `SettingsOnlyProviderError`).
- **Typed errors**: provider failures surface as `error_code == "SEARCH_FAILED"` with a
  `provider_failure_class` field carrying the provider's exception class; a non-provider
  `TypeError` is **not** classified as `SEARCH_FAILED` and triggers **no** fallback.
- **OpenAI-only DDG fallback**: when the sole configured provider (openai) fails, the
  result is `actual_engine == "duckduckgo"` with `openai_failure_class` set; the result
  contains no API keys or secrets.
- **link_ref**: an item's `link_ref` is truthy iff its `url` is non-empty; items with an
  empty URL are discarded, not returned with empty link_ref.
- **manual**: `web` manual reports `current_setting.source == "not_applicable"` and an
  `error_code` that is not `PROVIDER_BACKEND_INELIGIBLE`.
- **Browse independence**: `web` browse does its own fetch and succeeds regardless of
  provider selection or provider state.

### Pass / Fail

PASS when error codes, fallback engine, secrets-free results, link_ref, and browse
independence all hold; FAIL on any wrong error code, secret leakage, or browse that
inherits provider state.

## Behavior C005 — File read continuation via next_offset pagination

- **LABT id**: C005
- **Title**: `file` read-only continuation, truncation caps, and next_offset semantics
- **Guards**: operates on fixture files under tests/fixtures; never writes.
- **Supersedes**: tests/test_read_continuation.py (CONVERT_BEHAVIOR)
- **Runner**: pytest tests/test_read_continuation.py
- **Prerequisites**: src/lingtai/tools/file/CONTRACT.md section
  `#read-_readpy--read-only`; tool name `file-contract` per file CONTRACT.md.
- **Estimate**: 20 minutes.

### Steps

1. Read a file larger than one page: `file(action=read, file_path=<fixture>,
   offset=1, limit=null, max_chars=null)`.
2. Take `next_offset` from the result and call read again with
   `offset=<next_offset>, limit=null, max_chars=null`.
3. Repeat with explicit `offset`/`limit` and with `max_chars` smaller than the page.
4. Read a file containing one very long line.

### Expected evidence

- **Caps**: `DEFAULT_READ_CAP_CHARS == 100_000`, `READ_HARD_CAP_CHARS == 200_000`,
  `PREVENTIVE_MAX_CHARS == 200_000`.
- **First page**: when the file exceeds the cap, the result is truncated and reports
  `next_offset == last_returned_line + 1`, plus `remaining_lines_estimate`,
  `total_lines`, and `lines_shown`.
- **Continuation**: reading with `offset == next_offset` starts exactly at that line
  (no overlap, no gap) and again returns its own `next_offset` for the next page.
- **Offset/limit**: explicit `offset` and `limit` are honored; a per-call `max_chars`
  returns `cap_chars == <requested>` and `returned_chars <= cap_chars`.
- **Single long line**: the line is truncated with `line_truncated: true`,
  `last_returned_line == 1`, and `next_offset == 2`.
- **Schema/description**: the read result schema mentions `max_chars`, `read-manual`,
  `truncated`, `next_offset`, and `line_truncated`, and the limits are documented as
  `100 000` and `200 000` (spaced thousands) in the tool description.

### Pass / Fail

PASS when pagination is gap-free and overlap-free, caps hold, and the long-line case
reports exactly `last_returned_line == 1` / `next_offset == 2`; FAIL on any skipped or
repeated line.

## Behavior C006 — Feishu tool family LTP v2 envelope

- **LABT id**: C006
- **Title**: feishu LTP v2 envelope validation, child schemas, and flat dispatch
- **Guards**: the feishu manager is a recording stub; no network; identity path is
  `/tmp/identities.json`.
- **Supersedes**: tests/test_feishu_toolfamily_ltpv2.py (CONVERT_BEHAVIOR)
- **Runner**: pytest tests/test_feishu_toolfamily_ltpv2.py
- **Prerequisites**: src/lingtai/tools/CONTRACT.md section `#envelope`;
  src/lingtai/tools/feishu/_family.py and src/lingtai/tools/feishu/manager.py.
- **Estimate**: 30 minutes.

### Steps

1. Call the feishu tool with 9 invalid envelope shapes (missing/unknown `action`,
   wrong `payload` type, etc.).
2. Call `feishu(action="accounts")` on a cold identity path.
3. Exercise `send` (receive_id/text/body combinations), `remove_contact`, `manual`,
   and each empty-input action.
4. Inspect the generated child tool schemas for the family.

### Expected evidence

- **Actions**: `FEISHU_ACTIONS` is exactly
  `("send", "check", "read", "reply", "react", "search", "delete", "edit",
  "contacts", "add_contact", "remove_contact", "accounts", "manual")` — 13 actions.
- **Envelope validation**: each of the 9 invalid shapes returns a `failed`-status result
  **before** any manager I/O (the stub records zero calls for those inputs).
- **accounts**: the valid call makes the manager receive exactly
  `{"action": "accounts"}` and returns `{status: ok, accounts: [main], details, ...}`
  with `identity_path == "/tmp/identities.json"`; the ltpv2 flat result equals the
  family handle result.
- **send**: requires `receive_id` with **text XOR content** (body); a payload with both
  or neither is rejected.
- **remove_contact**: accepts **exactly one** of `alias` / `open_id`; both or neither
  is rejected.
- **manual**: echoes the input verbatim or returns
  `{status: ok, skill: "feishu-mcp-manual", manual: <str>}`.
- **Child schemas**: `input` uses `anyOf` (not `oneOf`); `reasoning`/`summarize` never
  appear in child schemas or handlers; scrub preserves `required`, the `action` enum,
  `anyOf`/`allOf`, an `allOf` length of 13, and `additionalProperties: false`.
- **Empty-input branches**: exactly `{check, contacts, accounts, manual}` succeed with
  an empty payload.

### Pass / Fail

PASS when validation short-circuits before manager I/O, flat==ltpv2 for accounts, and
child schemas match the scrub rules; FAIL on any manager call for invalid input, any
schema drift (`oneOf`, leaked `reasoning`/`summarize`), or a wrong action count.

