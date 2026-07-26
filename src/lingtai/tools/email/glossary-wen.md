---
kind: tool-glossary
schema_version: 1
tool_package: lingtai.tools.email
language: wen
related_files:
- docs.yaml
- src/lingtai/kernel/tool_glossary.py
- src/lingtai/tools/glossary_validator.py
- src/lingtai/tools/email/glossary-en.md
- src/lingtai/tools/email/glossary-zh.md
maintenance: |
  Classical-Chinese (wen) glossary for the `email` tool package (lingtai.tools.email); body must stay non-empty and distinct from glossary-zh.md. Update in lockstep with glossary-en.md/glossary-zh.md whenever email's public tool schema changes.
  Body policy: maintain only a minimal term mapping plus at most one or two sentences of naming rationale; do not translate or duplicate the tool schema, parameters, action behavior, manual, contract, or anatomy.
---
**名相对照**

- `email`：原 locale catalog 未载 model-facing 本地名；召名、`action` 枚举、`input` 之分支与字段皆仍书 canonical English。
- `reasoning`：惟 BaseAgent 所加之 root metadata；不得入 `input`，亦不得作 flat 参名。
