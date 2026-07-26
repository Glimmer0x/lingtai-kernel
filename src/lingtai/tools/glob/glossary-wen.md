---
kind: tool-glossary
schema_version: 1
tool_package: lingtai.tools.glob
language: wen
related_files:
- docs.yaml
- src/lingtai/kernel/tool_glossary.py
- src/lingtai/tools/glossary_validator.py
- src/lingtai/tools/glob/glossary-en.md
- src/lingtai/tools/glob/glossary-zh.md
maintenance: |
  Classical-Chinese (wen) glossary for the `glob` tool package (lingtai.tools.glob); body must stay non-empty and distinct from glossary-zh.md. Update in lockstep with glossary-en.md/glossary-zh.md whenever glob's public tool schema changes.
  Body policy: maintain only a minimal term mapping plus at most one or two sentences of naming rationale; do not translate or duplicate the tool schema, parameters, action behavior, manual, contract, or anatomy.
---
**名相对照**

- `action`：所择之行；惟 `glob`、`manual` 二值。
- `input`：内嵌而封闭之输入；搜卷时载 `pattern`，求手册则为空。
- `pattern`：Glob 之式。
- `path`：搜卷之目录；无则用 Agent 工作目录。
- `summary`：精确布尔之先验摘要控，不改搜卷所得。
