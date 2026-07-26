---
kind: tool-glossary
schema_version: 1
tool_package: lingtai.tools.email
language: zh
related_files:
- docs.yaml
- src/lingtai/kernel/tool_glossary.py
- src/lingtai/tools/glossary_validator.py
- src/lingtai/tools/email/glossary-en.md
- src/lingtai/tools/email/glossary-wen.md
maintenance: |
  Simplified-Chinese (zh) glossary for the `email` tool package (lingtai.tools.email); body must stay non-empty. Update in lockstep with glossary-en.md/glossary-wen.md whenever email's public tool schema changes.
  Body policy: maintain only a minimal term mapping plus at most one or two sentences of naming rationale; do not translate or duplicate the tool schema, parameters, action behavior, manual, contract, or anatomy.
---
**术语对照**

- `email`：原 locale catalog 未定义 model-facing 本地化别名；调用名、`action` 枚举值、`input` 分支和字段名均保持 canonical English。
- `reasoning`：仅为 BaseAgent 注入的 root metadata；不得移入 `input`，亦不得以 flat 字段调用。
