---
kind: tool-glossary
schema_version: 1
tool_package: lingtai.tools.context
language: wen
related_files:
- docs.yaml
- src/lingtai/kernel/tool_glossary.py
- src/lingtai/tools/glossary_validator.py
- src/lingtai/tools/context/glossary-en.md
- src/lingtai/tools/context/glossary-zh.md
maintenance: |
  Classical-Chinese (wen) glossary for the `context` tool package (lingtai.tools.context); body must stay non-empty and distinct from glossary-zh.md. Update in lockstep with glossary-en.md/glossary-zh.md whenever context's public tool schema changes.
  Body policy: maintain only a minimal term mapping plus at most one or two sentences of naming rationale; do not translate or duplicate the tool schema, parameters, action behavior, manual, contract, or anatomy.
---
**名相对照**

- `context`：原 locale catalog 未载 model-facing 本地名；召名、action 枚举之值与参名皆仍书上文 canonical English。
