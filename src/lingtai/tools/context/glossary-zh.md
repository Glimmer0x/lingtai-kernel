---
kind: tool-glossary
schema_version: 1
tool_package: lingtai.tools.context
language: zh
related_files:
- docs.yaml
- src/lingtai/kernel/tool_glossary.py
- src/lingtai/tools/glossary_validator.py
- src/lingtai/tools/context/glossary-en.md
- src/lingtai/tools/context/glossary-wen.md
maintenance: |
  Simplified-Chinese (zh) glossary for the `context` tool package (lingtai.tools.context); body must stay non-empty. Update in lockstep with glossary-en.md/glossary-wen.md whenever context's public tool schema changes.
  Body policy: maintain only a minimal term mapping plus at most one or two sentences of naming rationale; do not translate or duplicate the tool schema, parameters, action behavior, manual, contract, or anatomy.
---
**术语对照**

- `context`：上下文生命周期；调用名保持 canonical English。
- `rebuild`：先重组全部规范系统提示词来源，再应用摘要，最后请求 provider 重放。
