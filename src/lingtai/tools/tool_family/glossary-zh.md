---
kind: tool-glossary
schema_version: 1
tool_package: lingtai.tools.tool_family
language: zh
related_files:
- docs.yaml
- src/lingtai/kernel/tool_glossary.py
- src/lingtai/tools/glossary_validator.py
- src/lingtai/tools/tool_family/glossary-en.md
- src/lingtai/tools/tool_family/glossary-wen.md
maintenance: |
  简体中文 glossary for the internal tool_family infrastructure package; keep a minimal mapping of immutable identifiers and update it with the English and wen files. Body policy: maintain only a minimal term mapping plus at most one or two sentences of naming rationale; do not translate or duplicate the tool schema, parameters, action behavior, manual, contract, or anatomy.
---
**术语对照**

- `ToolFamily`：一族聚合工具的内部子 Tool 注册表与 schema 组合器
- `ChildTool`：一个子 Tool 的名称、`input_schema`、handler 描述符
- `action`：模型选择的子 Tool 名，等同注册表键
- `input`：所选 action 自身的严格输入
- `reasoning`：Host 审计元数据，不进入子 Tool 输入
- `summarize`：Host 呈现层的可选后处理开关，不进入子 Tool 输入
- `manual`：族属保留子 Tool 名，返回安装手册全文与路径
