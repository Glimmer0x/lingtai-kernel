---
kind: tool-glossary
schema_version: 1
tool_package: lingtai.tools.pad
language: zh
related_files:
- docs.yaml
- src/lingtai/kernel/tool_glossary.py
- src/lingtai/tools/glossary_validator.py
- src/lingtai/tools/pad/glossary-en.md
- src/lingtai/tools/pad/glossary-wen.md
maintenance: |
  Simplified-Chinese (zh) glossary for the `pad` tool package (lingtai.tools.pad); body must stay non-empty. Update in lockstep with glossary-en.md/glossary-wen.md whenever pad's public tool schema changes.
  Body policy: maintain only a minimal term mapping plus at most one or two sentences of naming rationale; do not translate or duplicate the tool schema, parameters, action behavior, manual, contract, or anatomy.
---
**术语对照**

- `pad`：提示板固定引用清单；调用名保持 canonical English。
- `append`：校验并持久化固定引用，但不热加载当前提示词；`manual`：返回操作指南。
