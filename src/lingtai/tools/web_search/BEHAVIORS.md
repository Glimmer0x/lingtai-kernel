---
name: web-search-behavior-tests
behavior_version: 1
labt_version: 2
contract: CONTRACT.md
anatomy: ANATOMY.md
related_files:
  - src/lingtai/tools/web_search/CONTRACT.md
  - src/lingtai/tools/web_search/ANATOMY.md
  - src/lingtai/tools/web_search/__init__.py
  - src/lingtai/tools/web_search/settings.py
  - src/lingtai/tools/web_search/manual/SKILL.md
  - src/lingtai/tools/CONTRACT.md
  - tests/test_web_canonical_provider_routing.py
  - tests/test_web_settings_action.py
maintenance: |
  LABT v2, migrated 2026-08 from tests/test_web_canonical_provider_routing.py
  (previously filed as C003/C004 under src/lingtai/tools/telegram/BEHAVIORS.md;
  re-homed here so web_search owns its own behavior tests). Keep guards pointed
  at real `web` contract clauses (frontmatter name `web`): § Provider ownership
  and routing for default selection / backend eligibility / error hierarchy /
  DDG fallback, § Settings ownership for five-field SHOW/redaction, and §
  Contract rules for link_ref and browse independence.
  Update the matching LABT here in the same change as the contract clause; keep
  the paired ANATOMY.md reciprocal.
---
# Web Search Behavior Tests

LABT v2. Self-contained agent-executable behavioral tests for the `web`
capability (`src/lingtai/tools/web_search/`): W001 covers canonical provider
default selection and hot settings, W002 covers routing constraints, typed
failures, and DuckDuckGo fallback, and W003 covers the settings owner. All three
guard clauses in
`src/lingtai/tools/web_search/CONTRACT.md` (frontmatter name `web`).

## Behavior W001 — Web canonical provider routing: default selection and hot config

- **id**: W001
- **title**: web search→browse canonical provider selection and hot-read settings
- **guards**: `web` § Provider ownership and routing (built-in default engine resolved live per call; anthropic/gemini are settings-only opt-in; retired-provider composition errors) ([CONTRACT.md](CONTRACT.md#provider-ownership-and-routing))
- **supersedes**: tests/test_web_canonical_provider_routing.py (CONVERT_BEHAVIOR)
- **runner**: any LingTai agent with the `web` tool
- **prerequisites**: repo checkout with src/lingtai/tools/web_search; provider factories are stubbed/recording — no network; env vars are managed per-case (isolated and restored after each case); tool name is `web` per web_search CONTRACT.md; contract section `#provider-ownership-and-routing`.
- **estimate**: 30 minutes

### Steps

1. Clear all provider env vars, then set `OPENAI_API_KEY` and call the `web` tool's search provider selection.
2. Clear `OPENAI_API_KEY` too, so no keys exist; select again.
3. Set only `ANTHROPIC_API_KEY` (or `GEMINI_API_KEY`); select again.
4. Write `settings/web.search.json` with `{"schema_version": 1, "engine": ...}` and select again without restarting.

### Expected evidence

- [ ] With `OPENAI_API_KEY` set and nothing else: `engine == "openai"`, `source == "built_in_default"`, and the factory tuple is `("openai", api_key=<env value>, model=None)`.
- [ ] With **no** keys: `engine == "duckduckgo"` (built-in default fallback).
- [ ] With only anthropic/gemini keys: the corresponding engine is **available but unselected**; `PROVIDERS["providers"]` is exactly `{"duckduckgo", "gemini", "anthropic", "openai"}`.
- [ ] Settings file present: selection re-reads it hot — `engine` matches the file, and `source == "settings/web.search.json"` (relative to the working dir).
- [ ] `minimax` and `zhipu` are retired: composing either raises `RetiredProviderError` before any factory runs.

### Pass / Fail

PASS when the selected engine, source, provider set, hot-read settings, and retired-provider errors all match above; FAIL on any wrong engine/source, an unselected provider becoming selected, a non-hot settings read, or a retired provider reaching the factory.

## Behavior W002 — Web routing constraints, typed errors, and fallback

- **id**: W002
- **title**: settings-only/backend-gated providers, typed failures, DDG fallback, link_ref extraction, browse independence
- **guards**: `web` § Provider ownership and routing (backend eligibility, `SEARCH_FAILED` hierarchy, OpenAI-only DDG fallback) and § Contract rules (link_ref, browse independence) ([CONTRACT.md](CONTRACT.md#provider-ownership-and-routing))
- **supersedes**: tests/test_web_canonical_provider_routing.py (CONVERT_BEHAVIOR)
- **runner**: any LingTai agent with the `web` tool
- **prerequisites**: same as W001 (stubbed/recording provider factories, managed env, no network); contract sections `#provider-ownership-and-routing` and `#contract-rules`.
- **estimate**: 30 minutes

### Steps

1. Select anthropic/gemini via `settings/web.search.json` while the active backend is a non-canonical one (`claude-code`, `openai`, `openrouter`, `custom`, or `codex`).
2. Force each typed failure below and inspect the error envelope.
3. Make OpenAI-only search fail, then fall back; inspect the fallback result.
4. Call `web` browse with a URL and with an empty URL.

### Expected evidence

- [ ] **Backend-gated**: settings-selected anthropic/gemini on the non-canonical backends listed above is refused with `error_code == "PROVIDER_BACKEND_INELIGIBLE"` (distinct from `SettingsOnlyProviderError`).
- [ ] **Typed errors**: provider failures surface as `error_code == "SEARCH_FAILED"` with a `provider_failure_class` field carrying the provider's exception class; a non-provider `TypeError` is **not** classified as `SEARCH_FAILED` and triggers **no** fallback.
- [ ] **OpenAI-only DDG fallback**: when the sole configured provider (openai) fails, the result is `actual_engine == "duckduckgo"` with `openai_failure_class` set; the result contains no API keys or secrets.
- [ ] **link_ref**: an item's `link_ref` is truthy iff its `url` is non-empty; items with an empty URL are discarded, not returned with empty link_ref.
- [ ] **manual**: `web` manual reports `current_setting.source == "not_applicable"` and an `error_code` that is not `PROVIDER_BACKEND_INELIGIBLE`.
- [ ] **Browse independence**: `web` browse does its own fetch and succeeds regardless of provider selection or provider state.

### Pass / Fail

PASS when error codes, fallback engine, secrets-free results, link_ref, and browse independence all hold; FAIL on any wrong error code, secret leakage, or browse that inherits provider state.

## Behavior W003 — Web five-field settings SHOW and redaction

- **id**: W003
- **title**: web settings exposes truthful live facts without mutation
- **guards**: `web` § Settings ownership ([CONTRACT.md](CONTRACT.md#settings-ownership))
- **runner**: any LingTai agent with the `web` tool
- **prerequisites**: isolated workdir and process environment; admitted recording search services; no network; `tests/test_web_settings_action.py` is the bottom assertion.
- **estimate**: 15 minutes

### Steps

1. Call `web(action="settings", input={})` with no Web env or owner files.
2. Set valid owner env/file values and inventory again, then run one recording search.
3. Make each hot-read source invalid and inspect the settings result.
4. Attempt a non-empty settings input and inspect the workdir/environment afterward.
5. Inventory configured credentials containing sentinels and verify every `comment` target in `web-manual`.

### Expected evidence

- [ ] Public action order is `search`, `browse`, `settings`, `manual`; inventory has the exact nine ordered Web row keys and every row has only `key`, `current`, `default`, `configurable`, and `comment`.
- [ ] Hot env values shadow valid files while composed/50000 defaults remain truthful; invalid env/file truth yields fixed `SETTINGS_UNAVAILABLE` with no partial rows.
- [ ] Non-empty input fails and no file or process environment is changed; there is no set/reset/mutation result shape.
- [ ] Credential `current` and `default` are `<redacted>`; no sentinel, credential-env value, private flag, or absolute workdir path appears.
- [ ] Every comment names an existing `web-manual` heading containing meaning, accepted values, precedence/address, timing, authorization/sensitivity, and the real change procedure.
- [ ] The recording search still receives the query exactly once through the env-selected admitted engine.

### Pass / Fail

PASS when exact rows, defaults, manual targets, fail-closed inventory, no-write behavior, redaction, and ordinary search evidence all match; FAIL on extra projected fields, partial rows, a leaked credential/path, SHOW mutation, or search/browse regression.
