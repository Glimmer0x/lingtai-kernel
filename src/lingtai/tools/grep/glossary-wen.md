---
kind: tool-glossary
schema_version: 1
tool_package: lingtai.tools.grep
language: wen
related_files:
- docs.yaml
- src/lingtai/kernel/tool_glossary.py
- src/lingtai/tools/glossary_validator.py
- src/lingtai/tools/grep/glossary-en.md
- src/lingtai/tools/grep/glossary-zh.md
maintenance: |
  Classical-Chinese (wen) glossary for the `grep` tool package (lingtai.tools.grep); body must stay non-empty and distinct from glossary-zh.md. Update in lockstep with glossary-en.md/glossary-zh.md whenever grep's public tool schema changes.
  Body policy: maintain only a minimal term mapping plus at most one or two sentences of naming rationale; do not translate or duplicate the tool schema, parameters, action behavior, manual, contract, or anatomy.
---
**名相对照**

- `grep`：以正则式搜寻文中之字；其公开调用以严整 `action` 与内嵌 `input` 为式。
- `action`：择 `grep` 普通搜寻，或 `manual` 已装之手册。
- `input`：普通输入之主，含 `pattern`、`path`、`glob`、`max_matches`，及内嵌 `summary`。
- `reasoning`：Agent 所注之根级调用理由；非 `input` 所有，亦不入 FileIO。
- `pattern`：欲搜之正则式
- `path`：欲搜之文卷或目录
- `glob`：文卷 glob 过滤器（如'*.py'）
- `max_matches`：至多返回之匹配数
- `summary`：`input` 中之精确布尔摘要控；默认 false。
