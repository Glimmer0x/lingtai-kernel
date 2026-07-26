---
kind: tool-glossary
schema_version: 1
tool_package: lingtai.tools.glob
language: zh
related_files:
- docs.yaml
- src/lingtai/kernel/tool_glossary.py
- src/lingtai/tools/glossary_validator.py
- src/lingtai/tools/glob/glossary-en.md
- src/lingtai/tools/glob/glossary-wen.md
maintenance: |
  Simplified-Chinese (zh) glossary for the `glob` tool package (lingtai.tools.glob); body must stay non-empty. Update in lockstep with glossary-en.md/glossary-wen.md whenever glob's public tool schema changes.
  Body policy: maintain only a minimal term mapping plus at most one or two sentences of naming rationale; do not translate or duplicate the tool schema, parameters, action behavior, manual, contract, or anatomy.
---
**术语对照**

- `action`：操作选择；取 `glob` 或 `manual`。
- `input`：封闭的嵌套输入对象；普通搜索含 `pattern`，手册操作为空对象。
- `pattern`：Glob 匹配模式。
- `path`：搜索目录；缺省为 Agent 工作目录。
- `summary`：精确布尔的先验摘要控制，不改变匹配。
