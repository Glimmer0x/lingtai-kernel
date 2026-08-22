---
related_files:
  - src/lingtai/tools/context/manual/SKILL.md
  - src/lingtai/tools/context/manual/assets/molt-template.md
  - src/lingtai/tools/context/manual/assets/session-journal-entry-template.md
  - src/lingtai/tools/context/manual/reference/summarize-manual/SKILL.md
  - src/lingtai/tools/context/plugin.py
  - src/lingtai/tools/_plugin.py
  - src/lingtai/tools/registry.py
  - tests/test_intrinsic_tool_plugin_package.py
  - src/lingtai/tools/ANATOMY.md
  - src/lingtai/tools/CONTRACT.md
  - src/lingtai/tools/context/BEHAVIORS.md
  - src/lingtai/tools/context/CONTRACT.md
  - src/lingtai/tools/tool_family/ANATOMY.md
  - src/lingtai/tools/pad/ANATOMY.md
  - src/lingtai/tools/lingtai/ANATOMY.md
  - src/lingtai/tools/system/ANATOMY.md
  - src/lingtai/tools/system/summarize.py
  - src/lingtai/tools/context/__init__.py
  - src/lingtai/tools/context/_molt.py
  - src/lingtai/tools/context/_session_journal.py
  - src/lingtai/tools/context/_snapshots.py
  - src/lingtai/agent.py
  - src/lingtai/kernel/base_agent/prompt.py
  - src/lingtai/tools/context/glossary-en.md
  - src/lingtai/tools/context/glossary-wen.md
  - src/lingtai/tools/context/glossary-zh.md
maintenance: |
  Keep paths real, repo-relative, duplicate-free, and reciprocal with the paired
  Contract and connected anatomies. Update this graph with schema, lifecycle,
  composition-path, summary-engine, or state-ownership changes.
  Capability mentions in any document require explicit bidirectional
  related_files mapping to the implementing code (see root ## Maintenance).
---
# tools/context

Context lifecycle family with exact public actions
`molt | summarize | rebuild | manual`. `rebuild` is the sole active full
reconstruction operation; refresh and molt invoke the same internal contract as
passive lifecycle scenarios.

This package is also the model-facing reference slice for **intrinsic tool
plugin packaging** (`../_plugin.py`): one folder ships the tool code, the
`manual/` skill bundle the host installs, and the registration record
`registry.INTRINSICS` publishes — so the public action list, the manual, and the
registry entry cannot drift apart.

## Components

- `plugin.py` — this package's plugin descriptor. `CONTEXT_PLUGIN` states the
  registry name, the implementation module, the summary/homepage, and the
  packaged skill name `context-manual`; `CONTEXT_DECLARED_ACTIONS` lists
  Context's own three actions with `manual` deliberately absent, and
  `CONTEXT_ACTIONS` is the plugin-composed public list. Consumed by
  `__init__.py` for the root name, `ACTION_ORDER`, `_MANUAL_SKILL_NAME`, and
  family composition.
- `manual/` — the package-owned `context-manual` skill bundle: `SKILL.md`,
  `assets/molt-template.md`, `assets/session-journal-entry-template.md`, and the
  nested `reference/summarize-manual/SKILL.md` sub-skill. Mounted by
  `Agent._install_intrinsic_manuals` into
  `.library/intrinsic/capabilities/context-manual/`; the installed copy — not
  the wheel-internal one — is what `manual` reads and hands the model a path to.
- `__init__.py`
  - strict per-action schemas, including genuinely optional `rebuild.items` so
    bare `{}` is schema-valid;
  - `_summarize_action` pins record-only engine mode;
  - `_rebuild_action` calls `agent._reconstruct_context` before invoking the
    private summary engine, handles reconstruction failures as result dicts, and
    marks successful engine results `prompt_reconstructed: true`;
  - `_CHILD_SPECS`, `_build_declared_children`, `_FAMILY`, `get_schema`,
    `handle` provide single-registry schema/dispatch and isolate `_tc_id` to
    molt; `_CHILD_SPECS` is pinned against `CONTEXT_DECLARED_ACTIONS` at import
    so the registry and the descriptor stay one list, and every family is
    composed through `CONTEXT_PLUGIN.build_family`, which appends the reserved
    `manual` child itself;
  - manual adaptation resolves `context-manual` once after dispatch.
- `../system/summarize.py` — private history-summary engine. It records pending
  marker replacements, marks the applied set done, persists history, and only
  then calls `chat.request_history_rebuild`. It is not a public `system` action.
- `_molt.py` — agent and system molt implementations; shared
  `_select_keep_last_entries` atomically selects suffixes around complete
  single/parallel assistant tool-result batches; replay selection,
  archive/wipe, post-molt hook invocation before fresh-session creation, and
  post-molt notification publishing.
- `_session_journal.py` — fail-closed journal-path/frontmatter gate.
- `_snapshots.py` — atomic pre-molt snapshots and retrospective persistence.
- `agent.py`
  - `_reload_prompt_sections` is the authoritative all-source composer and
    reuses private `_lingtai_load`/`_pad_load`;
  - `_reconstruct_context` wraps that composer and performs the final full
    prompt flush;
  - `_setup_from_init` routes refresh through this method and registers exactly
    this method as the one post-molt hook;
  - `_install_intrinsic_manuals` is the discovery/mount half of the plugin
    contract: its `install_from` scan finds this package's `manual/` bundle and
    `_MANUAL_MOUNT_NAMES` maps `context` to the installed skill name
    `context-manual`. The host decides the mount; `CONTEXT_PLUGIN.manual_mount()`
    declares what it expects, and `tests/test_intrinsic_tool_plugin_package.py`
    pins the two against each other and against the real install.
- `kernel/base_agent/prompt.py::_flush_system_prompt` calls the virtual
  `agent._build_system_prompt`, preserving Agent-owned `base_prompt` and tool
  composition in the published/provider-visible prompt.

## Ordering and connections

Active rebuild flow:

```text
context.handle
  -> _rebuild_action
  -> Agent._reconstruct_context
     -> Agent._reload_prompt_sections
        -> private LingTai/Pad composers + every other canonical source
     -> virtual full prompt build/flush to disk and live interface
  -> private summary engine (new and/or pending summaries)
  -> chat.request_history_rebuild (provider replay)
```

Bare rebuild follows the same flow even when there are no pending markers.
Refresh supplies already-resolved init data and later rebuilds its session with
preserved history. Molt invokes the one registered `_reconstruct_context` hook
before `ensure_session`. Pad/LingTai boot functions only perform initial
composition; they do not register hooks.

## State and invariants

Context-owned persistent paths are `system/summaries/`, `history/snapshots/`,
`history/chat_history.jsonl`, `history/chat_history_archive.jsonl`, and the
post-molt notification. Pad and LingTai files are durable sources owned by their
families/file mutation, but the context reconstruction path composes them along
with base prompt, covenant, packaged layers, rules, brief, comment, guidance,
and current tool/meta sections.

`summarize` never reconstructs. `rebuild` always composes before history
mutation and provider request. `molt` retains refusal-before-shed and its distinct
archive/count/replay effects. No retired root or action is an alias.
