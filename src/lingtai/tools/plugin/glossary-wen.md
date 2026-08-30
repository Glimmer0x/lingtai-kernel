---
kind: tool-glossary
schema_version: 1
tool_package: lingtai.tools.plugin
language: wen
related_files:
- docs.yaml
- src/lingtai/kernel/tool_glossary.py
- src/lingtai/tools/glossary_validator.py
- src/lingtai/tools/plugin/glossary-en.md
- src/lingtai/tools/plugin/glossary-zh.md
maintenance: |
  Classical-Chinese (wen) glossary for the `plugin` tool package (lingtai.tools.plugin); body must stay non-empty and distinct from glossary-zh.md. Update in lockstep with glossary-en.md/glossary-zh.md whenever plugin's public tool schema changes.
  Body policy: maintain only a minimal term mapping plus at most one or two sentences of naming rationale; do not translate or duplicate the tool schema, parameters, action behavior, manual, contract, or anatomy.
---
**名相对照**

- `plugin`：Agent Plugins（agent-plugins.org v1.0.0）之标准名也，原 locale catalog 未载 model-facing 本地名；召名、action 枚举之值与参名皆仍书上文 canonical English。
- `action`、`input`、`reasoning`、`summarize`：LTP v2 封函四名，literal 不译；`info`、`settings`、`manual` 三 action 之值亦仍书 canonical English。
- `plugin.json`、`mcp.json`、`skills/`：皆 Agent Plugins 规约所定之文名、目名，literal 也，不译。
