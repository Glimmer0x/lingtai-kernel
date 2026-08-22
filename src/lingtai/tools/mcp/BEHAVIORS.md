---
name: mcp-behavior-tests
behavior_version: 2
labt_version: 2
contract: CONTRACT.md
anatomy: ANATOMY.md
related_files:
  - src/lingtai/tools/mcp/CONTRACT.md
  - src/lingtai/tools/mcp/ANATOMY.md
  - src/lingtai/tools/mcp/__init__.py
  - src/lingtai/mcp_catalog.json
  - src/lingtai/tools/mcp/plugin.json
  - src/lingtai/tools/mcp/plugin.py
  - src/lingtai/tools/_plugin.py
maintenance: |
  Created during the every-contract-needs-behaviors sweep. Keep this file
  reciprocal with CONTRACT.md and ANATOMY.md (tridirectional loop): when an mcp
  tool behavior clause changes, update the guarding LABT here in the same
  change. MC002 guards the CONTRACT's Packaging section; if the Agent Plugins
  layout, the manifest's ai.lingtai.tool extension, or the no-mcp.json rule
  changes, update MC002 in the same change.
---
# MCP Capability Behavior Tests

Self-contained agent behavior tasks guarding the observable behavior clauses of
`src/lingtai/tools/mcp/CONTRACT.md` (info/manual only, strict-empty input,
identity surfaced only when present, degraded manual shape). Pinned pytest
commands must run from the repo root with the project's Python.

## Behavior MC001 — info is read-only and any input field fails before the registry is re-read

- **id**: MC001
- **title**: info is read-only and any input field fails before the registry is re-read
- **guards**: `mcp-contract` § Tool surface
- **runner**: any LingTai agent with `shell` and `file` access to this repository
- **prerequisites**: a clean checkout of `<repo>`; a scratch agent working directory `<scratch>` with an `mcp_registry.jsonl`
- **estimate**: ≈ 15 minutes

### Steps
1. From `<repo>`, run `python -m pytest tests/test_mcp_capability.py tests/test_mcp_skill_manuals.py -q` and capture the outcome.
2. Call `mcp(action="info", input={}, reasoning="probe")` and record the result; confirm it reconciles the registry, re-injects prompt XML, and returns `{status, registry_path, registered_count, registered, problems}`.
3. Call `mcp(action="info", input={"extra": 1}, reasoning="probe")` and confirm rejection happens before the registry is re-read or the manual is loaded.

### Expected evidence
- [ ] Step 1: the mcp capability and skill-manual suites pass, pinning envelope validation, dispatch, and the canonical manual shape.
- [ ] Step 2: `info` returns the health/registry result; each `registered` entry carries `identity` only when a matching identity record with non-empty `accounts` exists.
- [ ] Step 3: any extra `input` key yields `INVALID_ARGUMENT` (`unsupported mcp input field`) before registry I/O; unknown actions render the exact Host-owned pre-migration envelope.

### Pass / Fail
Pass when the suites pass and the read-only/no-input observations hold. Fail on an accepted input field, on identity leaking without a matching record, or on a mutating `info`; record the evidence trail in the task report.

## Behavior MC002 — the tool ships as a real Agent Plugin whose packaging grants it no new power

- **id**: MC002
- **title**: the tool ships as a real Agent Plugin whose packaging grants it no new power
- **guards**: `mcp-contract` § Packaging
- **runner**: any LingTai agent with `shell` and `file` access to this repository
- **prerequisites**: a clean checkout of `<repo>`; the project's Python on `PATH`
- **estimate**: ≈ 20 minutes

### Steps
1. From `<repo>`, run `python -m pytest tests/test_builtin_tool_plugin_package.py -q` and capture the outcome.
2. Read `src/lingtai/tools/mcp/plugin.json` and list `src/lingtai/tools/mcp/`; confirm the manifest declares `$schema`, `name: mcp`, and the `ai.lingtai.tool` extension, that the manual lives at `skills/mcp-manual/SKILL.md`, and that no `mcp.json` and no `manual/` directory exist beside them.
3. Read the package through the host's own reader — `python -c "from pathlib import Path; from lingtai.services.plugin_registry import read_plugin; print(read_plugin(Path('src/lingtai/tools/mcp')))"` — and record the returned record and problems.
4. Boot a scratch agent with the `mcp` capability into `<scratch>`, then compare `<scratch>/.library/intrinsic/capabilities/mcp/SKILL.md` with `src/lingtai/tools/mcp/skills/mcp-manual/SKILL.md`, and read every line of `<scratch>/mcp_registry.jsonl`.

### Expected evidence
- [ ] Step 1: the built-in tool plugin suite passes, pinning the manifest, the owned skill, the mount, and the reserved `manual`.
- [ ] Step 2: the manifest and the `skills/mcp-manual/` skill are present; there is no `mcp.json` and no leftover `manual/` directory.
- [ ] Step 3: `read_plugin` returns `problems == []` and a record with `name == "mcp"`, `skills == ["mcp-manual"]`, and `mcp_servers == []` — validation is the host's, not a private copy.
- [ ] Step 4: the mounted `SKILL.md` is byte-identical to the packaged owned skill (with its `reference/` and `scripts/` sidecars present), and no registry line carries `source == "plugin:mcp"`.

### Pass / Fail
Pass when the suite passes, the manifest-declared skill is what got mounted, and the registry is untouched by the mount. Fail on a package that ships an `mcp.json`, on a `source="plugin:mcp"` record appearing from a plain boot, on a mounted manual that differs from the packaged one, or on `read_plugin` reporting problems; record the evidence trail in the task report.
