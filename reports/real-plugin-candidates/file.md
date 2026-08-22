# Real Plugin conversion — `file` (model-facing tool)

- **Date:** 2026-08-22
- **Worktree:** `lingtai-kernel-worktrees/file-real-plugin-20260822`
- **Branch:** `feat/file-real-plugin-20260822`
- **Base:** `c0ce8c98` (`docs(daemon): discourage undersized max turns (#1438)`)
- **Reference slice:** `telegram-curated-mcp-plugin-20260821` @ `348c0bd1`
  (`feat(mcp): package Telegram as curated plugin`)

## What the Telegram reference actually is

Telegram's conversion is not a manual move and not an inventory descriptor. It
is three concrete things bound in one place:

1. **A plugin package.** `src/lingtai/mcp_servers/_plugin.py` defines
   `CuratedMcpPlugin`, a frozen descriptor that loads the package's bundled
   `SKILL.md` at construction and fails loudly if the frontmatter name, the
   package/module identity, or the body is wrong.
2. **A shipped manifest.** `mcp_declaration()` returns the *existing runtime
   record shape* (`mcp_catalog.json`'s stdio entry). The catalog file stays the
   file the host reads; the descriptor is what that entry must equal, proven by
   test rather than generated at runtime.
3. **Manual-as-owned-skill + a reserved-action promise.** The package declares
   only its own actions; `actions()`, `action_input_schemas()`, and
   `build_family()` append `manual` themselves and raise
   `CuratedMcpPluginError` if the package tries to declare, re-schema, or
   rebind it. `_family.py`, `server.py`, and `manager.py` all consume the
   descriptor rather than restating its facts.

## The equivalent contract for `file`

`file` is a built-in model-facing tool, not an MCP server, so its runtime
discovery/mount contract lives in different files — but it is the same three
facts:

| Telegram | File |
|---|---|
| `mcp_catalog.json` stdio record | `registry.BUILTIN_TOOLS["file"]` (module), `registry.CORE_DEFAULTS["file"]` (boot kwargs), `registry.get_all_providers()` (module `PROVIDERS`) |
| `python -m <package>` launcher | `registry.setup_capability` → `file.setup(agent)` → `agent.add_tool(...)` |
| bundled `<package>/SKILL.md` | bundled `<package>/manual/SKILL.md`, swept by `Agent._install_intrinsic_manuals` into `.library/intrinsic/capabilities/<name>/` |
| `CuratedMcpPlugin` | `ToolPlugin` (`src/lingtai/tools/_plugin.py`) |
| `telegram/plugin.py` → `TELEGRAM_PLUGIN` | `file/plugin.py` → `FILE_PLUGIN` |

Before this change `file` was the outlier among built-in tools: every other
tool with a manual (`email`, `bash`→`shell`, `web_search`→`web`, `daemon`,
`plugin`, `mcp`, `avatar`, `task_card`, `vision`, `knowledge`, `skills`) ships
its own `manual/` bundle, while `file`'s manual shipped as a *kernel-owned*
standalone bundle at `src/lingtai/intrinsic_skills/file-manual/`. The manual was
therefore not the package's to own, and nothing bound the capability's module,
defaults, providers, actions, and manual together.

## What was implemented

### 1. Plugin package + manifest — `src/lingtai/tools/_plugin.py` (new)

`ToolPlugin` / `ToolPluginError`, the `lingtai.tools` twin of
`mcp_servers/_plugin.py`, with the same deliberate limits stated in its
docstring: **declarative only** — no discovery, import-by-name, mounting,
registration, or config reading. It loads the package's `manual/SKILL.md` at
construction and raises on a missing bundle, a frontmatter `name` that is not
the declared `skill_name`, an empty body, a package whose last segment is not
its `module_dir`, a blank identity field, or a non-mapping
`defaults`/`providers`.

`capability_declaration()` is the manifest: `{name, module, defaults,
providers, manual_destination}` — the four facts the host already publishes
about a built-in tool, in one place. It registers and mounts nothing.

`manual_destination` is the *canonical capability name*, because that is
exactly what `_install_intrinsic_manuals` computes for a package's `manual/`
directory (it is stated separately from `module_dir` precisely because
`bash`→`shell` and `web_search`→`web` differ).

### 2. Manual-as-owned-skill

`src/lingtai/intrinsic_skills/file-manual/SKILL.md` →
`src/lingtai/tools/file/manual/SKILL.md` (`git mv`, frontmatter `name:
file-manual` unchanged, `related_files` gains `plugin.py`). The host installer
now discovers it in the same `install_from(tools_pkg, "capabilities")` sweep as
every other tool manual and mounts it at
`.library/intrinsic/capabilities/file/`.

`read-manual` deliberately stays a standalone kernel bundle: it is a nested
reference the file manual points at, not a second top-level manual action.

### 3. `file/plugin.py` (new) and real consumption in `file/__init__.py`

`FILE_PLUGIN` declares name/package/module_dir/summary/skill_name plus the
`defaults` and `providers` the registry publishes. `FILE_DECLARED_ACTIONS` is
`("read", "write", "edit", "glob", "grep")` — `manual` is absent by
construction; `FILE_ACTIONS` is the plugin-composed public list.

`file/__init__.py` now composes *through* the descriptor rather than restating
it:

- child order comes from `FILE_DECLARED_ACTIONS` (with an import-time
  `ToolPluginError` if the declared actions and the declared input schemas
  disagree);
- `ACTION_INPUT_SCHEMAS` comes from `FILE_PLUGIN.action_input_schemas(...)`;
- `_build_family()` declares only the five operations and hands them to
  `FILE_PLUGIN.build_family(children, agent)`, which appends the reserved
  `manual` child — `FileManager` no longer registers `manual` at all, so no
  manager change can drop or rebind it;
- `PROVIDERS = FILE_PLUGIN.providers_declaration()`;
- `FAMILY_MANUAL_SKILL = FILE_PLUGIN.manual_destination`;
- `get_description()` interpolates `FILE_PLUGIN.skill_name`;
- `setup()` mounts with `FILE_PLUGIN.name` and `FILE_PLUGIN.package`.

### 4. Runtime discovery/mount contract, documented and pinned

Following the reference exactly, the host tables stay the runtime source and
the descriptor is what they must agree with:

- `registry.py` carries the agreement note on the `file` row and explains why
  the table is *not* generated from the descriptor (resolving it there would
  eagerly import the tool and break the module's documented lazy-import
  discipline).
- `agent.py`'s `_install_intrinsic_manuals` comment now names the mount half of
  the contract.
- `tests/test_file_tool_plugin_package.py` (new, 26 tests) pins:
  declaration ↔ `BUILTIN_TOOLS`/`CORE_DEFAULTS`/`get_all_providers`; the
  packaged skill is the manual this plugin owns and no longer exists as a
  standalone kernel bundle; the host installs it byte-identically at the
  declared destination and `action="manual"` returns exactly that copy; the
  package cannot declare, re-schema, or rebind `manual`; descriptor defects
  raise at construction; and the public envelope, dispatch, and
  read/write/edit behavior are unchanged.

## Preserved behavior and host boundaries

- **Model-facing surface is byte-identical to base.** `get_schema()` and
  `get_description()` were dumped from base `c0ce8c98` and from the converted
  package and compared: identical.
- **Sandbox / read / write / edit unchanged.** Every operation still reaches
  the working tree only through the injected `agent._file_io` service via
  `_file_paths.resolve_workdir_path`; no operation module was touched.
- **Host boundary on the manual preserved.** The `manual` child is *built* by
  the plugin but still loads through the kernel-owned
  `tool_family.manual.build_manual_child`, so the body and the model-visible
  `manual_path` come from the agent's own installed
  `.library/intrinsic/capabilities/` tree — not from a package resource read.
  This is the one deliberate divergence from Telegram, whose MCP server has no
  installed-library boundary to respect.
- **Mounting stays the host's.** Nothing here activates a capability, writes a
  registry record, or spawns anything.

### The one intentional behavior change

The installed manual destination moves from
`.library/intrinsic/capabilities/file-manual/SKILL.md` to
`.library/intrinsic/capabilities/file/SKILL.md`. This is unavoidable and
correct: it is what makes the manual package-owned, and it aligns `file` with
every other tool whose manual destination is its canonical capability name. The
skills-catalog entry the model sees is unchanged (`- name: file-manual`, from
the frontmatter). Updated accordingly: `tests/test_file_tool_family.py`,
`tests/test_intrinsic_manual_actions.py`, `tests/test_skills.py`,
`tools/tool_family/BEHAVIORS.md`, `tools/file/ANATOMY.md`,
`tools/file/CONTRACT.md`, `intrinsic_skills/ANATOMY.md`,
`intrinsic_skills/read-manual/SKILL.md`.

## Validation (run in this worktree, cache-safe `-p no:cacheprovider`)

| Suite | Result |
|---|---|
| `tests/test_file_tool_plugin_package.py` | 26 passed |
| `tests/test_file_tool_family.py`, `test_intrinsic_manual_actions.py`, `test_tool_family_manual_contract.py`, `test_layers_file.py` | 70 passed |
| `tests/test_file_io_sidecar.py`, `test_services_file_io.py`, `test_read_continuation.py`, `test_plugin_tool.py` | 193 passed |
| `tests/test_tools_package_data.py` | 13 passed |
| `tests/test_skills.py`, `test_agent_capabilities.py` | 46 passed, 1 failed |
| `tests/test_architecture_documents.py`, `test_docs_governance.py`, `test_anatomy_drift_checker.py`, `test_kernel_isolation.py` | 84 passed, 4 failed |

**All 5 failures are pre-existing at base `c0ce8c98`**, verified by stashing the
change and re-running:

- `test_skills.py::test_lingtai_owned_skill_frontmatter_has_last_changed_at` —
  `intrinsic_skills/notification-manual/SKILL.md` has a date-only
  `last_changed_at`.
- `test_architecture_documents.py::test_every_tracked_file_climbs_the_anatomy_graph`,
  `test_docs_governance.py::test_every_in_scope_doc_has_required_fields`,
  `test_docs_governance.py::test_all_four_notification_managers_preserve_exact_runtime_body`,
  `test_kernel_isolation.py::test_kernel_has_no_lingtai_submodules`.

The anatomy-graph violation list was diffed before/after: **no new violations**.

Not run: `tests/test_mcp_skill_manuals.py` and
`tests/test_outbound_file_containment.py` fail to *collect* in this environment
(`ImportError: cannot import name 'ServerRequestContext' from 'mcp.server'` —
installed `mcp` SDK predates the v2 API). This is an environment limitation, not
a change effect; neither module touches the converted code paths.

## Files changed

New:
- `src/lingtai/tools/_plugin.py`
- `src/lingtai/tools/file/plugin.py`
- `tests/test_file_tool_plugin_package.py`
- `reports/real-plugin-candidates/file.md`

Moved:
- `src/lingtai/intrinsic_skills/file-manual/SKILL.md` → `src/lingtai/tools/file/manual/SKILL.md`

Modified:
- `src/lingtai/tools/file/__init__.py`, `src/lingtai/tools/file/ANATOMY.md`,
  `src/lingtai/tools/file/CONTRACT.md`
- `src/lingtai/tools/registry.py`, `src/lingtai/tools/ANATOMY.md`,
  `src/lingtai/tools/tool_family/BEHAVIORS.md`
- `src/lingtai/agent.py` (comment only)
- `src/lingtai/intrinsic_skills/ANATOMY.md`,
  `src/lingtai/intrinsic_skills/read-manual/SKILL.md`
- `tests/test_file_tool_family.py`, `tests/test_intrinsic_manual_actions.py`,
  `tests/test_skills.py`

No other worktree, shared config, or auth material was touched. No push, PR,
merge, delete, reset, or amend was performed.

## Follow-on candidates

`ToolPlugin` is generic. The next packages to convert are the ten other tools
that already own a `manual/` bundle and only need a descriptor plus the same
composition rewiring; `bash`→`shell` and `web_search`→`web` are the two that
exercise the `module_dir` ≠ `name` split the descriptor already models.
