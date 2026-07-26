---
kind: tool-glossary
schema_version: 1
tool_package: lingtai.tools.mcp
language: zh
related_files:
- docs.yaml
- src/lingtai/tools/mcp/CONTRACT.md
- src/lingtai/kernel/tool_glossary.py
- src/lingtai/tools/glossary_validator.py
- src/lingtai/tools/mcp/glossary-en.md
- src/lingtai/tools/mcp/glossary-wen.md
maintenance: |
  Simplified-Chinese (zh) glossary for the `mcp` tool package (lingtai.tools.mcp); body must stay non-empty. Update in lockstep with glossary-en.md/glossary-wen.md whenever mcp's public tool schema changes.
  Body policy: maintain only a minimal term mapping plus at most one or two sentences of naming rationale; do not translate or duplicate the tool schema, parameters, action behavior, manual, contract, or anatomy.
---
**术语对照**

- `mcp`：原 locale catalog 未定义 model-facing 本地化别名；调用名、`action`、`input`、`reasoning` 与 `current_setting` 均保持 canonical English。
- `info`、`manual`：皆须配空 `input`；本词表只记 canonical 名相，不提供扁平调用别名。
