---
kind: tool-glossary
schema_version: 1
tool_package: lingtai.tools.grep
language: zh
related_files:
- docs.yaml
- src/lingtai/kernel/tool_glossary.py
- src/lingtai/tools/glossary_validator.py
- src/lingtai/tools/grep/glossary-en.md
- src/lingtai/tools/grep/glossary-wen.md
maintenance: |
  Simplified-Chinese (zh) glossary for the `grep` tool package (lingtai.tools.grep); body must stay non-empty. Update in lockstep with glossary-en.md/glossary-wen.md whenever grep's public tool schema changes.
  Body policy: maintain only a minimal term mapping plus at most one or two sentences of naming rationale; do not translate or duplicate the tool schema, parameters, action behavior, manual, contract, or anatomy.
---
**术语对照**

- `grep`：在文件内容中搜索匹配正则表达式的行；其公开调用采用严格的 `action` 与嵌套 `input`。
- `action`：选择 `grep` 普通搜索或 `manual` 已安装手册。
- `input`：拥有 `pattern`、`path`、`glob`、`max_matches` 与嵌套 `summary` 的普通输入对象。
- `reasoning`：由 Agent 注入的根级调用理由；不属于 `input`，也不送入 FileIO。
- `pattern`：要搜索的正则表达式模式
- `path`：要搜索的文件或目录
- `glob`：文件 glob 过滤器（例如 '*.py'）
- `max_matches`：最大返回匹配数
- `summary`：`input` 内的精确布尔摘要控制；默认 false。
