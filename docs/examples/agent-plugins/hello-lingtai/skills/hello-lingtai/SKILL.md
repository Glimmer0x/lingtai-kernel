---
name: hello-lingtai
description: >
  The example Agent Plugin's one skill. Reach for it only to confirm that plugin
  registration worked: if this skill is in your skills catalog with a location
  inside docs/examples/agent-plugins/hello-lingtai/, then the kernel mounted a
  declared plugin's skills/ directory correctly. It teaches nothing else and
  covers no real task.
version: 1.0.0
related_files:
  - docs/examples/agent-plugins/hello-lingtai/plugin.json
  - docs/examples/agent-plugins/hello-lingtai/mcp.json
  - docs/examples/agent-plugins/hello-lingtai/server.py
  - src/lingtai/tools/plugin/manual/SKILL.md
maintenance: |
  This skill exists to be observed, not to be followed. Keep it minimal — its
  value is that a human or agent can look at the skills catalog and see it, so
  anything that makes it longer makes it worse. Update it only if the plugin
  registration flow it demonstrates changes.
---

# hello-lingtai

You are reading the one Agent Skill bundled by the `hello-lingtai` example
plugin (`docs/examples/agent-plugins/hello-lingtai/`).

Its presence in your skills catalog is the assertion. The kernel did **not**
copy this file into `.library/`; it composed this skill's own directory
into the catalog scan, so the `location` you see for this entry still points
inside the plugin directory. That is what makes uninstall work by deletion of a
declaration rather than deletion of files: drop the plugin from
`manifest.plugins` in `init.json`, refresh, and this entry disappears while the
plugin directory stays exactly as it was.

The plugin also declares one stdio MCP server, also named `hello-lingtai`, with
a single `hello` tool. Registration gave that server a record in
`mcp_registry.jsonl` with `source="plugin:hello-lingtai"` — registered, not
running. To actually call it, add a matching entry under the top-level `mcp`
key in `init.json` and `system(action="refresh")`, exactly as for any curated
addon.
