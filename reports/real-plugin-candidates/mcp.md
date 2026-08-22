---
related_files:
  - reports/ANATOMY.md
  - src/lingtai/tools/mcp/plugin.json
  - src/lingtai/tools/mcp/plugin.py
  - src/lingtai/tools/mcp/ANATOMY.md
  - src/lingtai/tools/mcp/CONTRACT.md
  - src/lingtai/tools/mcp/BEHAVIORS.md
  - src/lingtai/tools/_plugin.py
  - src/lingtai/tools/ANATOMY.md
  - src/lingtai/services/plugin_registry.py
  - src/lingtai/agent.py
  - tests/test_builtin_tool_plugin_package.py
maintenance: |
  Frozen record of the `mcp` model-facing tool's conversion into a real Agent
  Plugins v1.0.0 package on 2026-08-22, kept as the reference slice for the
  remaining built-in tools. Do not rewrite it to match later code; if the
  packaging contract changes, the living source of truth is
  src/lingtai/tools/mcp/CONTRACT.md § Packaging and src/lingtai/tools/_plugin.py.
  Add a sibling <tool>.md when another tool is converted.
---
# Real Plugin candidate — `mcp`

Conversion of the model-facing `mcp` tool into a **real** Agent Plugins v1.0.0
package. Reference slice for the remaining built-in tools.

- **Branch:** `feat/mcp-real-plugin-20260822`, base `c0ce8c98`.
- **Reference read first:** the Telegram curated-MCP plugin
  (`src/lingtai/mcp_servers/_plugin.py`, `telegram/plugin.py`, and
  `tests/test_curated_mcp_plugin_package.py`) — one package owning its
  declaration, its bundled skill, and the reserved `manual` action.

## What "real" had to mean here

An earlier attempt on this tool stopped at a descriptor plus a package-local
manual loader: a frozen dataclass in `tools/mcp/plugin.py` and a
`resources.files()` read. Nothing on disk changed shape, nothing validated it,
and no runtime path discovered it — the "plugin" existed only as Python that the
tool itself chose to import. That is not a plugin; it is a naming convention.

The kernel already ships a plugin standard and a plugin *reader*
(`lingtai/services/plugin_registry.py`, Agent Plugins v1.0.0), so a real
conversion had a concrete bar to clear: the package must be a directory the
kernel's own reader accepts, its manual must be an owned Agent Skill that reader
discovers, and a runtime path must mount it from the manifest.

## What was implemented

### 1. Plugin package and manifest

`src/lingtai/tools/mcp/plugin.json` — a real manifest: `$schema` (the v1.0.0
plugin schema this kernel understands), `name: mcp`, `version`, `description`,
`homepage`, `license`, `keywords`, and the reverse-domain client-extension
namespace §3 reserves:

```json
"extensions": { "ai.lingtai.tool": { "package": "lingtai.tools.mcp",
                                     "manual_skill": "mcp-manual" } }
```

`plugin_registry.validate_manifest` accepts it, and `read_plugin` returns
`{name: "mcp", version: "1.0.0", skills: ["mcp-manual"], mcp_servers: []}` with
`problems == []` — the same call, with the same §4.1 containment rule, that a
third-party plugin dropped on a configured path gets. `lingtai.tools` does not
re-implement any of that; `tests/test_builtin_tool_plugin_package.py` pins the
filename constants equal to the service's so the layer cannot fork the spec.

### 2. Manual as an owned skill

`git mv src/lingtai/tools/mcp/manual → src/lingtai/tools/mcp/skills/mcp-manual`
(`SKILL.md` plus its `reference/` and `scripts/` sidecars). The pre-plugin
`manual/` directory convention is gone from this package, and the manual is now
a skill the plugin owns and the plugin reader discovers. `MCP_TOOL_PLUGIN`
(`tools/mcp/plugin.py`) re-states the manifest's name, shipping package, and
owned manual skill, and `BuiltinToolPlugin` raises `BuiltinToolPluginError` at
import if any of the three disagrees with the file on disk — the same
anti-drift promise `CuratedMcpPlugin` enforces for the curated MCPs, and the
same reserved-`manual` rule: the package declares only `("info",)`, and the
plugin appends `manual`.

### 3. Runtime discovery and mount contract

`src/lingtai/tools/_plugin.py` is the tools-layer analogue of
`mcp_servers/_plugin.py`: `BuiltinToolPlugin` (identity + family composition)
and `discover_tool_plugin(root)` (manifest → mount plan, validated by
`read_plugin`). `Agent._install_intrinsic_manuals` now branches per package:

- a package carrying `plugin.json` is read as a plugin and its manifest-declared
  owned skill is mounted at `.library/intrinsic/capabilities/<name>/`;
- a package without one keeps the legacy `manual/` convention, so the remaining
  tools are unaffected and can convert one at a time.

Both layouts land at the same destination, so the model sees no change: the
reserved `manual` action still serves
`<agent>/.library/intrinsic/capabilities/mcp/SKILL.md`, which is now a
byte-identical mount of a skill the plugin owns.

### 4. Packaging

`pyproject.toml` gained the `*/skills/**/*` package-data glob and `MANIFEST.in`
grafts `src/lingtai/tools/mcp/skills`; the manifest itself rides the existing
`*/*.json` glob. Without these the wheel would install a `plugin.json` declaring
a `skills/` directory that is not in the archive.

## Boundaries deliberately preserved

| Boundary | Status |
| --- | --- |
| Registry | The package ships **no** `mcp.json`. Mounting writes no `mcp_registry.jsonl` record — in particular no `source="plugin:mcp"` record. |
| Activation | Unchanged: an explicit `init.json` top-level `mcp` entry. Packaging a tool grants no activation. |
| Registration | `register_plugins` still owns operator-declared external plugins. `mcp` is neither declared nor discovered as an Agent Plugin; it ships inside the wheel. |
| Transport / credentials | Untouched. Nothing here spawns a process, opens a connection, or reads a secret. |
| Security | A tool plugin that *did* carry an `mcp.json` is reported as a packaging problem by `discover_tool_plugin` and its servers stay unregistered — the mount plan has no registry write to reach. |
| Public surface | Unchanged: action enum `["info", "manual"]`, branch titles `["info input", "manual input"]`, the flat `mcp_manual` result shape, the signpost descriptions, and the degraded-manual error text. |

## Verification

`python3 -m pytest -q -p no:cacheprovider` (repo root, `PYTHONDONTWRITEBYTECODE=1`):

- `tests/test_builtin_tool_plugin_package.py` — **30 passed** (new).
- `tests/test_mcp_capability.py tests/test_tool_family_mcp_migration_parity.py
  tests/test_signpost_tool_descriptions.py tests/test_plugin_tool.py` —
  **166 passed, 1 failed**.

The single failure is
`test_mcp_capability.py::test_curated_mcp_modules_ship_inside_lingtai_distribution`,
an environmental import error (`cannot import name 'ServerRequestContext' from
'mcp.server'` — the installed `mcp` package predates the API `mcp_servers/*/
server.py` uses). It reproduces on the untouched base commit and is unrelated to
this change. `tests/test_labt_validation.py` and the docs-governance /
architecture-document suites likewise carry pre-existing failures on the base
(`daemon/BEHAVIORS.md` id `D008:`, `kernel/llm/ANATOMY.md` duplicate
`related_files`, four documents with no frontmatter fence); none of them names a
file this change touches.

## Next candidates

The mount path is generic — `install_tool_plugin` reads any tool package's
manifest — so the remaining conversions are per-package moves plus a
`plugin.json`. Two wrinkles a converter will meet that `mcp` did not:

- **Name ≠ directory.** `bash` mounts as `shell` and `web_search` as `web`. The
  manifest `name` is the model-facing name, and the Agent Plugins name grammar
  forbids `_`, so those packages should declare `name: shell` / `name: web` and
  let the alias table in `install_from` retire with them.
- **More than one owned skill.** `daemon` and `web_search` ship nested manual
  trees. `discover_tool_plugin` mounts the manifest-declared manual skill under
  the plugin name and any further owned skill under its own catalog label; a
  converter should check that against the tool's existing installed layout
  before moving files.
