---
kind: tool-glossary
schema_version: 1
tool_package: lingtai.tools.read
language: wen
related_files:
- docs.yaml
- src/lingtai/kernel/tool_glossary.py
- src/lingtai/tools/glossary_validator.py
- src/lingtai/tools/read/glossary-en.md
- src/lingtai/tools/read/glossary-zh.md
maintenance: |
  Classical-Chinese (wen) glossary for the `read` tool package (lingtai.tools.read); body must stay non-empty and distinct from glossary-zh.md. Update when read's public action/input schema or user-visible terminology changes.
  Body policy: maintain only a minimal term mapping plus at most one or two sentences of naming rationale; do not translate or duplicate the tool schema, parameters, action behavior, manual, contract, or anatomy.
---
**名相對照**

- `action`：所行之名；唯 `read`、`manual` 二值
- `input`：封閉之行參；`manual` 之參必空
- `summary`：`input` 中之精確布爾摘要控，默 false，且不改閱卷之行
- `current_setting`：每召所附之嚴格設定快照，惟作證據而不改閱卷

`file_path`、`offset`、`limit`、`max_chars`、`next_offset`、`line_truncated` 皆守英文名相；不設省略 `action`、扁平參數或兼容別名。
