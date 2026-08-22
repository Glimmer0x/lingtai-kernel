---
related_files:
  - reports/ANATOMY.md
  - src/lingtai/tools/_plugin.py
  - src/lingtai/tools/plugin/plugin.py
  - src/lingtai/tools/plugin/__init__.py
  - src/lingtai/tools/plugin/ANATOMY.md
  - src/lingtai/tools/plugin/CONTRACT.md
  - src/lingtai/tools/plugin/manual/SKILL.md
  - src/lingtai/tools/ANATOMY.md
  - src/lingtai/tools/registry.py
  - src/lingtai/agent.py
  - src/lingtai/ANATOMY.md
  - src/lingtai/services/plugin_registry.py
  - src/lingtai/mcp_servers/_plugin.py
  - src/lingtai/mcp_servers/telegram/plugin.py
  - tests/test_tool_plugin_package.py
  - tests/test_plugin_tool.py
maintenance: |
  Append-only record of one real-Plugin conversion run, written against base
  c0ce8c98 on branch feat/plugin-real-plugin-20260822. Do not rewrite it to
  match later code; if the tool-plugin packaging, the manual mount contract, or
  the tool-plugin/Agent-Plugin boundary changes, record that in a new report and
  update the owning ANATOMY/CONTRACT documents instead. Capability mentions here
  map bidirectionally to the implementing code via related_files above.
---

# Real Plugin conversion — the `plugin` model-facing tool

Base: `c0ce8c98`. Branch: `feat/plugin-real-plugin-20260822`.
Reference studied: `telegram-curated-mcp-plugin-20260821`
(`src/lingtai/mcp_servers/_plugin.py`, `src/lingtai/mcp_servers/telegram/plugin.py`,
`tests/test_curated_mcp_plugin_package.py`).

## What "real Plugin" had to mean here

The Telegram reference converts a curated MCP into a plugin-style *package*: one
folder that ships the server code, the bundled `SKILL.md`, and the declaration
the runtime catalog publishes — bound by a frozen descriptor that owns the
reserved `manual` action and refuses to let the package declare it. Three parts,
all load-bearing:

1. **Package + manifest.** `CuratedMcpPlugin` holds the identity and emits
   `mcp_declaration()`, the record `mcp_catalog.json` must equal.
2. **Manual as an owned skill.** The bundled `SKILL.md` is loaded and
   name-checked at construction; the `manual` child closes over it and no longer
   routes through the package's business manager.
3. **Runtime discovery/mount contract.** The declaration is what the catalog
   publishes and what the host's validator accepts; composition (`actions()`,
   `build_family()`) is the package's single public surface.

The conversion is real because the package's *actual* wiring — schema, dispatch,
server identity — was moved onto the descriptor. A descriptor module added
beside unchanged wiring would have been packaging theater. That is the bar this
run held itself to, and it is why the sibling "local tool descriptor seam"
attempts were not sufficient: they added a file without changing what composes
the tool.

Transposed to a model-facing tool, the three parts map onto: the tool package
plus its `BUILTIN_TOOLS`/`CORE_DEFAULTS` entry; `manual/SKILL.md` as the skill
the package owns; and `Agent._install_intrinsic_manuals` as the mount step.

## What was implemented

**`src/lingtai/tools/_plugin.py` (new)** — `ToolPlugin`, the tools-layer twin of
`CuratedMcpPlugin`:

- loads the package's `manual/SKILL.md` at construction, checks the frontmatter
  `name` against the declared `skill_name`, and rejects an empty or renamed one;
- owns the reserved `manual` child — `actions()`, `action_input_schemas()`, and
  `build_family()` append it and raise `ToolPluginError` if a package declares,
  re-schemas, or rebinds it; `build_family(agent=None)` yields the schema-only
  twin so the module-level and dispatching families declare identical children;
- emits `capability_declaration()`, the registry-shaped record
  (`name`, `module`, `summary`, `manual_destination`, `default_on`,
  `default_kwargs`) the built-in registry entries must agree with;
- bounds the schema's `manual` catalog line, because a capability manual's
  frontmatter is a multi-paragraph router and this line ships in the always-on
  tool schema on every turn;
- provides the mount lookup — `iter_tool_plugins()` scans `lingtai/tools/` for
  `<pkg>/plugin.py` and imports only packages that declare a descriptor;
  `declared_manual_destinations()` reduces that to the mapping the host reads.

**`src/lingtai/tools/plugin/plugin.py` (new)** — this package's `TOOL_PLUGIN`
descriptor, `PLUGIN_DECLARED_ACTIONS = ("info",)`, and the composed
`PLUGIN_ACTIONS = ("info", "manual")`.

**`src/lingtai/tools/plugin/__init__.py`** — rewired, not decorated. The family
is composed by `TOOL_PLUGIN.build_family()`; the tool registers under
`TOOL_PLUGIN.name`; the schema's `manual` action line comes from the packaged
skill's frontmatter instead of a hand-copied sentence; the unknown-action
envelope renders its action list from `PLUGIN_ACTIONS`. The literal `"plugin"`
skill-destination argument that used to sit at the `build_manual_child` call site
is gone — the package declares it once.

**`src/lingtai/agent.py`** — `_install_intrinsic_manuals` now reads a tool
plugin's declared `manual_destination` instead of inferring one from the
directory name. The retained `bash` → `shell` and `web_search` → `web` mappings
are untouched for packages without a descriptor, and the lookup is lazy and
failure-tolerant: a broken descriptor loses its declaration, never boot.

## The recursion this had to avoid, and how

`plugin` is the one tool where "package the tool as a plugin" is a trap: it is
the tool that *reports* Agent Plugins (agent-plugins.org v1.0.0). Two different
things are called plugin, and the conversion is only safe if they stay apart:

| | Tool plugin | Agent Plugin |
|---|---|---|
| What | kernel-shipped Python package under `lingtai/tools/` | third-party directory carrying `plugin.json` |
| Declared by | `lingtai/tools/registry.py` | `init.json` `manifest.plugins` |
| Discovered by | `iter_tool_plugins()` (this wheel) | `services.plugin_registry.read_plugins` (operator paths) |
| Mounted by | `Agent._install_intrinsic_manuals` | `Agent._register_declared_plugins` |
| Registry stamp | none | `source="plugin:<name>"` |

Had they shared machinery, boot would have to mount the reporter before it could
report, `plugin(action="info")` would list itself, and uninstalling "plugin"
would mean pruning a kernel capability. The separation is enforced rather than
documented: `ToolPlugin.__post_init__` raises if the package ships a
`plugin.json`, so a tool package can never become discoverable as an Agent
Plugin. Discovery is a scan of the kernel's own wheel and is never routed
through the Agent Plugins scanner.

Self-bootstrapping was avoided the same way the registry already avoids it:
`lingtai.tools.registry` still resolves capability modules with `importlib`
*inside* `setup_capability`, and `_plugin.py`'s discovery is never called at
registry-import time, so importing the registry still does not import every
tool. Declaring a descriptor is therefore a promise that the package's
`__init__` stays import-cheap — stated in `_plugin.py` and pinned by test.

## Boundaries preserved

- **Discovery.** Agent Plugins discovery is untouched: `read_plugins`,
  `scan_plugin_root`, the two-tier declared/inherited split, and the per-path
  health report are byte-identical.
- **Mount.** `Agent` still owns the copy into `.library/intrinsic/`. The package
  gained a *declaration*, not the ability to install itself.
- **Security.** §4.1 path containment, `$schema` version gating, and the
  ownership-stamp/pruning rules are unchanged; the new code writes no file, spawns
  no process, and reads no configuration.
- **Config.** `init.json` handling, `manifest.plugins`, the
  `capabilities.plugin.paths` alias, and `apply_core_defaults` are unchanged.
- **Registry.** `BUILTIN_TOOLS`/`CORE_DEFAULTS` remain the runtime source the
  host reads; the descriptor is what they must agree with, proven by test rather
  than generated at runtime.
- **Lifecycle.** Registration stays boot/refresh-only and unreachable from any
  action, which is what keeps the capability safe in `CORE_DEFAULTS`.
- **Public surface.** The action enum, branch titles, strict-empty inputs,
  `manual_path`, the flat `plugin_manual` result, and the unknown-action envelope
  text are all unchanged; `tests/test_plugin_tool.py` passes untouched.

## Verification

Run with `PYTHONPATH=src python3 -m pytest -p no:cacheprovider` (cache-safe, no
`.pytest_cache` written into the worktree).

| Suite | Result |
|---|---|
| `tests/test_tool_plugin_package.py` (new, 23 tests) | pass |
| `tests/test_plugin_tool.py` | pass |
| `tests/test_tool_family_manual_contract.py`, `tests/test_tool_family_mcp_migration_parity.py`, `tests/test_intrinsic_manual_actions.py` | pass |
| `tests/test_agent_capabilities.py`, `tests/test_skills.py`, `tests/test_mcp_capability.py`, `tests/test_override_intrinsic.py`, `tests/test_prompt_section_definitions.py` | pass except the pre-existing failures below |
| `tests/test_lingtai_facade.py`, `tests/test_i18n.py`, `tests/test_kernel_isolation.py` | pass except the pre-existing failure below |
| `tests/test_docs_governance.py`, `tests/test_anatomy_drift_checker.py` | pass except the pre-existing failures below |

Pre-existing failures on the clean base, confirmed by stashing this change and
re-running them at `c0ce8c98`; none is caused by or related to this work:

- `test_kernel_isolation.py::test_kernel_has_no_lingtai_submodules` —
  `kernel/notifications.py` imports `lingtai.adapters.notification_store_lock`.
- `test_mcp_capability.py::test_curated_mcp_modules_ship_inside_lingtai_distribution`
  and `test_docs_governance.py::test_all_four_notification_managers_preserve_exact_runtime_body`
  — the installed `mcp` package does not export `ServerRequestContext`.
- `test_skills.py::test_lingtai_owned_skill_frontmatter_has_last_changed_at` —
  same import failure reached through the skills scan.
- `test_docs_governance.py::test_every_in_scope_doc_has_required_fields` —
  frontmatter gaps in `IMPLEMENTATION_REPORT.md`,
  `src/lingtai/kernel/llm/ANATOMY.md`, and three
  `src/lingtai/mcp_servers/feishu/reference/*.md` files.

## Follow-on candidates

`plugin` is the first tool plugin and deliberately the hardest one, since it is
the case where the packaging could have eaten itself. The remaining built-in
tools with a `manual/` bundle can adopt `ToolPlugin` one at a time; `shell` and
`web` are the interesting next slices, because their implementation directory
and public name differ and their declared `manual_destination` would replace the
last two hardcoded mappings in `Agent._install_intrinsic_manuals`.
