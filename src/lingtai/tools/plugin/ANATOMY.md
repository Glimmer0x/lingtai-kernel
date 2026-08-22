---
related_files:
  - src/lingtai/tools/ANATOMY.md
  - src/lingtai/tools/plugin/BEHAVIORS.md
  - src/lingtai/tools/plugin/__init__.py
  - src/lingtai/tools/plugin/plugin.py
  - src/lingtai/tools/_plugin.py
  - src/lingtai/tools/plugin/CONTRACT.md
  - src/lingtai/tools/plugin/manual/SKILL.md
  - src/lingtai/tools/plugin/glossary-en.md
  - src/lingtai/tools/plugin/glossary-zh.md
  - src/lingtai/tools/plugin/glossary-wen.md
  - src/lingtai/services/plugin_registry.py
  - src/lingtai/services/mcp_registry.py
  - src/lingtai/services/ANATOMY.md
  - src/lingtai/tools/mcp/ANATOMY.md
  - src/lingtai/tools/skills/__init__.py
  - src/lingtai/tools/tool_family/ANATOMY.md
  - src/lingtai/tools/registry.py
  - src/lingtai/agent.py
  - src/lingtai/init_schema.py
  - tests/test_plugin_tool.py
  - tests/test_tool_plugin_package.py
  - docs/examples/agent-plugins/hello-lingtai/plugin.json
  - docs/examples/agent-plugins/hello-lingtai/mcp.json
  - docs/examples/agent-plugins/hello-lingtai/server.py
  - docs/examples/agent-plugins/hello-lingtai/skills/hello-lingtai/SKILL.md
maintenance: |
  Keep related_files as repo-relative paths to real files. Include neighboring
  ANATOMY.md files so the anatomy graph stays connected rather than isolated;
  anatomy links must be bidirectional. If you create a new ANATOMY.md, copy this
  maintenance field. If you notice drift between this anatomy and the code,
  report it. The mcp sibling is the pattern this package mirrors — when mcp's
  family composition, manual adaptation, or unknown-action envelope changes,
  re-check this one; when its addon decompression changes, re-check the
  registration half here, which mirrors it. See lingtai-dev-guide for details.
  Capability mentions in any document require explicit bidirectional
  related_files mapping to the implementing code (see root ## Maintenance).
---
# lingtai/tools/plugin + lingtai/services/plugin_registry (split)

Plugin capability — the per-agent **Agent Plugins** (agent-plugins.org, v1.0.0)
catalog and registration. It scans the configured plugin paths, validates each
`plugin.json`, mounts what was declared, and renders the result as XML into the
system prompt. It is the structural twin of `src/lingtai/tools/mcp/ANATOMY.md` —
same two-child LTP v2 family, same tool/service split, same lazy back-edge — and
its registration half mirrors that package's addon decompression.

**Two tiers, and the line between them is a security boundary.** A plugin
*declared* in `init.json` `manifest.plugins` (or its alias
`manifest.capabilities.plugin.paths`) is **registered**: each of its validated
skill directories is
composed into the skills-catalog scan and its `mcp.json` servers become
`mcp_registry.jsonl` records stamped `source="plugin:<name>"`. A plugin merely
found on an inherited `manifest.capabilities.skills.paths` directory is
**discovered**: listed, nothing mounted. Dropping a directory somewhere must
never silently register a third party's MCP server.

**The tool is still read-only.** Mounting happens once, in `register_plugins`,
called by `Agent` before capability setup — no model-facing action can reach it,
which is what keeps the capability safe in `CORE_DEFAULTS`. Registration is also
registry-level only: a registered server is registered, never running.

## Components

- `plugin/__init__.py` — the tool slice (~351 lines). One model-facing LTP v2
  family: public tool name `plugin`, public actions `info`/`manual`, carried in
  the canonical `action` + `input` + `reasoning` + `summarize` envelope composed
  by the generic `lingtai.tools.tool_family` infrastructure
  (`src/lingtai/tools/tool_family/ANATOMY.md`).
  `get_description` (`src/lingtai/tools/plugin/__init__.py:287`),
  `get_schema` (`src/lingtai/tools/plugin/__init__.py:291`) returns
  `ToolFamily.build_schema()` with the family's own `action` description
  substituted, and `_build_family`
  (`src/lingtai/tools/plugin/__init__.py:250`) is the single source of the
  two-child registry — called with `None` at import for the module-level
  schema-only family `_FAMILY` (`src/lingtai/tools/plugin/__init__.py:284`),
  which fails loudly on a duplicate/reserved-name collision and never
  dispatches, and called with the agent from `setup`
  (`src/lingtai/tools/plugin/__init__.py:300`) for the real dispatching family
  whose `manual` child comes straight from
  `tool_family.manual.build_manual_child`. Both children share the one
  `_EMPTY_INPUT` literal (`src/lingtai/tools/plugin/__init__.py:237`)
  re-exported from `tool_family.manual.MANUAL_INPUT_SCHEMA`, so the advertised
  and validated shapes cannot drift. `_reconcile`
  (`src/lingtai/tools/plugin/__init__.py:144`) backs the `info` child: it reads
  the boot snapshot off `agent._plugin_registration`, re-scans discovery live,
  splits the result into the registered and discovered tiers, and renders both.
  It never registers — that is what makes `info` safe to call.
  `_registered_entries` (`src/lingtai/tools/plugin/__init__.py:123`) projects the
  snapshot, consulting `_skills_enabled`
  (`src/lingtai/tools/plugin/__init__.py:113`) so a plugin whose skills could not
  be composed says so in `skipped` rather than claiming a mount that did not
  happen. `_catalog_entry` (`src/lingtai/tools/plugin/__init__.py:98`) projects a
  discovered record down to catalog facts. `_collect_paths`
  (`src/lingtai/tools/plugin/__init__.py:63`) is where this capability differs
  from mcp — it unions its own configured `manifest.capabilities.plugin.paths`,
  the snapshot's declared paths (the canonical `manifest.plugins`, which does not
  otherwise reach this capability), and the skills capability's
  `manifest.capabilities.skills.paths` read off `agent._capabilities`, in that
  order and de-duplicated. `_flatten_manual_result`
  (`src/lingtai/tools/plugin/__init__.py:182`) is the Host-owned adapter that
  turns the manual child's canonical `content`/`structuredContent` result back
  into the flat `plugin_manual` public shape strictly *after* dispatch (no
  double wrap), and `handle_plugin`
  (`src/lingtai/tools/plugin/__init__.py:318`) owns the unknown-action envelope —
  including the missing-action empty-string default and unhashable `action`
  values (issue #513), routed by tuple membership against `child_names`, which
  compares by `==` and never hashes — before delegating to `ToolFamily.handle`.
  Both actions declare a strict-empty `input`, so any extra input field fails
  before the paths are re-scanned or the manual is loaded.
- `plugin/manual/` — the `plugin-manual` skill (`SKILL.md`). Installed to
  `.library/intrinsic/capabilities/plugin/SKILL.md` by the Agent initializer's
  generic `install_from(tools_pkg, "capabilities")` sweep, which picks up any
  tool package carrying a `manual/` directory — no per-package wiring.
- The service lives at `src/lingtai/services/plugin_registry.py` and splits in
  two halves. **Discovery:** `resolve_contained`
  (`src/lingtai/services/plugin_registry.py:110`) is the §4.1 path-containment
  gate — `./` prefix required syntactically, containment checked *after*
  `Path.resolve()` so a symlink escape is rejected exactly like a literal `../`
  escape; `validate_manifest`
  (`src/lingtai/services/plugin_registry.py:145`) enforces the two required
  manifest fields against the pinned `PLUGIN_SCHEMA_URL`
  (`src/lingtai/services/plugin_registry.py:58`) and the transcribed v1.0.0
  `name` grammar `_NAME_RE` (`src/lingtai/services/plugin_registry.py:69`);
  `_scan_skills` (`src/lingtai/services/plugin_registry.py:273`) enumerates the
  plugin's skills through `_walk_skills`
  (`src/lingtai/services/plugin_registry.py:195`), whose traversal deliberately
  mirrors `tools._catalog._scan_recursive` so the reported set is the mounted set
  and each skill directory is contained-checked individually — it returns the
  per-skill validated paths, which is what registration composes, never the
  parent `skills/` (whose symlink-following scan would re-admit a reject); and
  `_scan_mcp_servers`
  (`src/lingtai/services/plugin_registry.py:412`) reads `mcp.json` into validated
  `{name, spec}` entries, each applying the per-component failure boundary.
  Every server passes through the one gate `resolve_server_spec`
  (`src/lingtai/services/plugin_registry.py:344`), which validates the transport
  and resolves each plugin-relative `command`/`cwd`/`args` value via
  `_expand_plugin_path` (`src/lingtai/services/plugin_registry.py:300`) — which
  also normalizes any relative value carrying a `..` segment through the same
  gate, so `../x` cannot slip past by omitting the `./` — so
  discovery and registration cannot disagree about what is acceptable, and a path
  smuggled through an argument is checked exactly like one in `command`.
  `read_plugin` (`src/lingtai/services/plugin_registry.py:473`) applies the
  whole-plugin boundary; `resolve_path`
  (`src/lingtai/services/plugin_registry.py:535`) mirrors the skills capability's
  path resolution; `scan_plugin_root`
  (`src/lingtai/services/plugin_registry.py:547`) treats a configured path as a
  collection directory unless it carries `plugin.json` itself; `read_plugins`
  (`src/lingtai/services/plugin_registry.py:580`) is the multi-path entry point
  returning `(records, problems, report)` with duplicate names flagged
  first-wins. **Registration:** `declared_plugin_paths`
  (`src/lingtai/services/plugin_registry.py:629`) resolves the canonical key and
  its alias into one ordered, de-duplicated list; `to_registry_record`
  (`src/lingtai/services/plugin_registry.py:665`) translates one resolved server
  into a registry record through `mcp_registry.validate_record` — the exact
  validator the addon path uses, so a plugin cannot introduce a shape the
  registry would reject; `prune_plugin_records`
  (`src/lingtai/services/plugin_registry.py:725`) is the uninstall mechanism,
  dropping only `source="plugin:*"` lines that the current declaration no longer
  implies and preserving blank, unparseable, and foreign-source lines byte for
  byte; `register_plugins`
  (`src/lingtai/services/plugin_registry.py:779`) is the one mutation point,
  pruning first and appending second so a changed spec is replaced rather than
  duplicated. **Render:** `_plugin_xml`
  (`src/lingtai/services/plugin_registry.py:935`) stamps each plugin with its
  `<mount>` tier and `_build_registry_xml`
  (`src/lingtai/services/plugin_registry.py:963`) renders the
  `<registered_plugin>` section whose preamble states the two-tier contract in
  the same words as the tool description.
- Boot wiring lives in `src/lingtai/agent.py`: `_register_declared_plugins`
  (`src/lingtai/agent.py:468`) runs on both boot paths immediately after addon
  decompression and before capability setup, and records `_plugin_skill_paths`
  and `_plugin_registration` on the agent. It runs with an empty declaration list
  too — that empty run *is* the uninstall path. `__init__` calls it only when it
  was given `capabilities=` or `plugins=`, though: the CLI's minimal construction
  declares neither and defers to `_setup_from_init`, which always calls it, so
  the boot flow registers once instead of pruning and re-appending every record.
- The skills side of the mount is `_compose_paths`
  (`src/lingtai/tools/skills/__init__.py:105`), which unions the declared Tier-1
  paths with `_plugin_skill_paths` — per-skill directories, each scanned by
  `_scan_one_skill` (`src/lingtai/tools/skills/__init__.py:88`). Because it reads off the agent, all three of
  that capability's reconcile entry points (setup, the post-manual-install
  re-reconcile, and full-context reconstruction) pick plugin skills up for free.
- The canonical config key is declared in `src/lingtai/init_schema.py`
  (`MANIFEST_OPTIONAL["plugins"]`), with a shape-only warning for malformed
  entries; per-plugin validation happens at registration.
- A minimal working plugin ships at
  `docs/examples/agent-plugins/hello-lingtai/` — one skill, one stdio MCP server
  (stdlib only, so it stands in for genuinely third-party code), pinned by
  `tests/test_plugin_tool.py::test_the_shipped_example_plugin_registers_end_to_end`.

## Public API

The `plugin` tool exposes two read-only actions, called through the LTP v2
envelope `plugin(action=..., input={}, reasoning="...")` (both actions take a
strict-empty `input`; `summarize` is the optional root presentation control):

| Action | Description |
|--------|-------------|
| `info` | Re-scan the configured plugin paths and return the boot registration snapshot: `declared`, `registered_count`, `registered` (per plugin: name, version, summary, source, skills, skill_count, skills_mounted, mcp_servers, mcp_server_count, mcp_registered, skipped), `discovered_count`, `discovered`, `mcp_appended`, `mcp_pruned`, a per-path `paths` report, and `problems`. No manual body, and no mounting. |
| `manual` | Return the `plugin-manual` skill body on demand, with no scan or mutation. |

Installing and uninstalling are not actions: both are edits to
`manifest.plugins` followed by `system(action="refresh")`.

## Agent Plugins v1.0.0 shape

```
my-plugin/
├── plugin.json          # required: $schema + name
├── skills/<name>/SKILL.md   # optional — composed into the skills catalog when declared
├── mcp.json             # optional — becomes registry records when declared
└── com.example.client/  # optional reverse-domain extension namespace (ignored)
```

```json
{
  "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
  "name": "my-plugin",
  "version": "1.0.0",
  "description": "one-line summary rendered as <summary>"
}
```

## Internal Module Layout

```
plugin/plugin.py
  └── TOOL_PLUGIN                   — this package's ToolPlugin descriptor: name,
      PLUGIN_DECLARED_ACTIONS         module, summary, packaged skill, manual
      PLUGIN_ACTIONS                  destination, default kwargs; ('info',) and
                                      ('info', 'manual') respectively

plugin/__init__.py
  ├── Path collection
  │   └── _collect_paths()          — own ∪ declared ∪ skills paths, in that order, deduped
  │
  ├── Reconciliation
  │   ├── _catalog_entry()          — one discovered record → the catalog facts
  │   ├── _skills_enabled()         — is there a catalog to compose plugin skills into?
  │   ├── _registered_entries()     — boot snapshot → the registered tier
  │   └── _reconcile()              — report snapshot + re-scan discovery + render prompt
  │
  ├── Manual adaptation
  │   └── _flatten_manual_result()  — canonical child result → flat plugin_manual shape
  │
  └── Tool surface
      ├── _build_family()           — declares `info`; TOOL_PLUGIN appends `manual`
      ├── _ACTION_DESCRIPTION       — declared line + the descriptor's manual catalog line
      ├── _SUPPORTED_ACTIONS        — the unknown-action envelope, from PLUGIN_ACTIONS
      ├── get_description/schema()  — module-level, backed by the schema-only _FAMILY
      └── setup()                   — registers TOOL_PLUGIN.name, runs initial _reconcile

services/plugin_registry.py
  ├── §4.1 containment
  │   └── resolve_contained()       — './' prefix + post-resolve containment (symlinks followed)
  │
  ├── Manifest validation
  │   └── validate_manifest()       — required $schema + name, typed optional fields
  │
  ├── Component discovery
  │   ├── _scan_skills()            — immediate skills/<name>/SKILL.md subdirs
  │   ├── _expand_plugin_path()     — './' and ${PLUGIN_ROOT}/ → absolute, containment-checked
  │   ├── resolve_server_spec()     — the one gate: transport + every referenced path
  │   └── _scan_mcp_servers()       — mcp.json mcpServers → [{name, spec}]
  │
  ├── Plugin / path scan
  │   ├── read_plugin()             — one plugin dir → (record | None, problems)
  │   ├── resolve_path()            — tilde / absolute / working-dir-relative
  │   ├── scan_plugin_root()        — collection dir, or single plugin if it has plugin.json
  │   └── read_plugins()            — all configured paths → (records, problems, report)
  │
  ├── Declaration + registration
  │   ├── declared_plugin_paths()   — manifest.plugins ∪ capabilities.plugin.paths alias
  │   ├── plugin_source()           — the "plugin:<name>" ownership stamp
  │   ├── to_registry_record()      — resolved server → record, via mcp_registry.validate_record
  │   ├── prune_plugin_records()    — drop owned records the declaration no longer implies
  │   └── register_plugins()        — the one mutation point: prune, then append
  │
  └── XML builder
      ├── _escape_xml()             — XML entity escaping
      ├── _plugin_xml()             — one <plugin> element, stamped with its <mount> tier
      └── _build_registry_xml()     — both tiers → <registered_plugin> prompt section
```

## Key Invariants

- **A tool plugin is not an Agent Plugin.** This package is packaged as a *tool
  plugin* (`lingtai/tools/_plugin.py`) — a kernel-shipped Python package that
  owns its capability declaration and its `manual/SKILL.md`. It is emphatically
  not an *Agent Plugin*, the third-party directory standard it reports. It ships
  no `plugin.json` (`ToolPlugin` rejects a package that does, at import),
  `read_plugins` pointed at `lingtai/tools/` finds nothing, the tool never
  appears in its own `info` snapshot, and no `source="plugin:plugin"` record
  exists. Without that line the reporter would have to be mounted before it
  could report, and uninstalling "plugin" would mean pruning a kernel capability.
- **`manual` is descriptor-owned:** `__init__.py` declares only `info`;
  `TOOL_PLUGIN.build_family()` appends the reserved `manual` bound to this
  package's declared skill, and raises `ToolPluginError` if the package tries to
  declare, re-schema, or rebind it. The child still answers from the per-agent
  *installed* copy, so the public `manual_path` contract is unchanged — what the
  descriptor owns is *which* skill it is and *where* it mounts.
- **Declaration gates mounting:** an inherited skills path is scanned and listed
  but never registers anything. Only `manifest.plugins` and its alias mount.
- **No model-facing mutation:** no action registers, unregisters, copies, or
  spawns anything. `register_plugins` is boot/refresh-only and unreachable from
  the tool surface, which is why default-on is safe.
- **Registration never executes:** a registered MCP server holds a registry
  record and nothing more, exactly as a decompressed addon does. Running it
  still requires an `init.json` top-level `mcp` entry.
- **Skills are composed, never copied:** a registered plugin's skill keeps a
  `location` inside the plugin. Nothing is written under `.library/`, which is
  why uninstall needs no file deletion.
- **Registration owns only its own stamp:** a name already held by a
  hand-written or addon record skips the plugin's server rather than
  overwriting it; between two plugins, first declared wins. Pruning likewise
  touches only `source="plugin:*"` lines and leaves blank, unparseable, and
  foreign-source lines byte for byte.
- **Idempotent and convergent:** running registration twice leaves the same
  registry as once, and the registry converges on the current declaration —
  removed plugins, removed servers, and changed specs all resolve.
- **Path containment (§4.1):** every plugin-relative path MUST begin with `./`
  (or the equivalent `${PLUGIN_ROOT}/` form) and MUST resolve inside the
  filesystem-resolved plugin root — `command`, `cwd`, and every entry of `args`
  alike. Because containment is checked after `Path.resolve()`, a `./symlink`
  pointing outside is rejected identically to `./../escape`, and it is enforced
  at registration, so an escaping server never reaches the registry.
- **Two failure boundaries:** an unreadable or invalid `plugin.json` rejects the
  whole plugin (absent from the catalog, registers nothing, reason in
  `problems`); an individual escaping or malformed skill directory / MCP server
  is skipped while the rest of the plugin still mounts, with the reason in that
  plugin's `skipped` list.
- **`$schema` is a local identifier, never a fetch:** the pinned v1.0.0 URLs are
  compared as opaque strings; the kernel makes no network call during a scan.
- **Duplicate names are first-wins:** a second plugin with an already-seen name
  is dropped with a problem entry, mirroring the mcp registry's duplicate
  handling.
- **Paths are inherited, not duplicated:** the skills capability's configured
  paths are scanned for plugins too, so operators declare a directory once for
  discovery — but inheritance never mounts.

## Dependencies

- `lingtai.tools.tool_family` — `ChildTool` / `ToolFamily` / `build_manual_child`
- `lingtai.services.plugin_registry` — lazily imported inside `_reconcile`
  (the `lingtai.tools → lingtai` back-edge)
- `lingtai.services.mcp_registry` — lazily imported inside the registration
  functions for `validate_record` / `read_registry` / `_append_record` /
  `_registry_path`, so plugin-sourced records pass the same gate as addons
- `lingtai.kernel.base_agent.BaseAgent` — agent type (TYPE_CHECKING only)
- stdlib only in the service (`json`, `re`, `logging`, `pathlib`)

## Composition

- **Parent:** `src/lingtai/tools/` (tool slice); the service sibling lives in
  `src/lingtai/services/`.
- **Siblings:** `mcp/` (the pattern this package mirrors, on both the family and
  the decompression sides), `skills/` (whose configured paths this capability
  inherits and whose catalog scan registration composes into), `knowledge/`,
  `daemon/`.
- **Manual:** `plugin/manual/SKILL.md` — the `plugin-manual` router.
- **Kernel hooks:** `setup()` is called during capability initialization from
  `src/lingtai/tools/registry.py`; boot-time registration is called earlier, by
  `Agent._register_declared_plugins` on both the constructor and
  `_setup_from_init` paths, alongside addon decompression.
