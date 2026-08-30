---
kind: tool-glossary
schema_version: 1
tool_package: lingtai.tools.file
language: zh
related_files:
- docs.yaml
- src/lingtai/kernel/tool_glossary.py
- src/lingtai/tools/glossary_validator.py
- src/lingtai/tools/file/glossary-en.md
- src/lingtai/tools/file/glossary-wen.md
maintenance: |
  Simplified-Chinese (zh) glossary for the unified `file` tool family (lingtai.tools.file); body must stay non-empty. Update in lockstep with glossary-en.md/glossary-wen.md whenever the family's public action set or envelope changes.
  Body policy: maintain only a minimal term mapping plus at most one or two sentences of naming rationale; do not translate or duplicate the tool schema, parameters, action behavior, manual, contract, or anatomy.
---
**术语对照**

- `file`：统一的文件能力；一个公开 tool，按 `action` 选择其下的规范子操作。
- `action`：本次调用所选的子操作，取值为 `read`、`write`、`edit`、`glob`、`grep`、`settings`、`manual` 之一。
- `input`：该 `action` 自己的严格输入对象；不接受属于其他 action 的字段。
- `reasoning`：本次调用的理由，记入日记；属信封字段，非 action 输入。
- `summarize`：可选的根级布尔值，默认 false，控制本次结果是否被摘要替换；属信封字段，非 action 输入。`read`/`grep`/`glob` 输出可能很大，适合按需设为 true；`write`/`edit` 的回执须精确阅读，应保持 false。
- `settings`：家族保留的只读 SHOW action；仅接受空 `input`，按固定五字段显示完整 File 所有者策略，不提供 set/reset。
- `manual`：家族保留 action，返回已安装的 file-manual，不执行任何目标文件操作。

**各 action 的 input 字段**

- `read`：`file_path` 文件绝对路径；`offset` 起始行号（从 1 开始，默认 1）；`limit` 最大读取行数（默认 2000）；`max_chars` 单次读取字符预算（默认 100 000，超过不可配置的 runtime 硬上限者 clamp 到 200 000）。返回带行号的文本；仅支持文本文件，不能读取二进制、图片或音频。读取成功仍可能截断：检查 truncated、cap_chars、returned_chars、next_offset、remaining_lines_estimate、line_truncated，并用 next_offset 续读至结束。若 line_truncated=true，所示物理行只是前缀，next_offset 会跳到下一行，不能恢复该行隐藏尾部。
- `write`：`file_path` 文件绝对路径；`content` 要写入的内容。父目录自动创建；用于新建文件或完整重写，小修改用 `edit`。
- `edit`：`file_path` 文件绝对路径；`old_string` 要查找并替换的精确文本；`new_string` 替换后的文本；`replace_all` 是否替换所有匹配项（默认 false）。若 old_string 未找到或存在歧义则失败且不改动文件。
- `glob`：`pattern` glob 模式（如 '**/*.py'）；`path` 搜索目录（默认为 agent 工作目录）。返回排序后的匹配路径列表。
- `grep`：`pattern` 正则模式；`path` 搜索的文件或目录（默认为 agent 工作目录）；`glob` 文件过滤器（默认 '*' 即不过滤）；`max_matches` 最多返回的匹配数（默认 200）。返回匹配行及其文件路径与行号。
- `settings`：无字段（严格空对象）；返回 `key`、`current`、`default`、`configurable`、`comment`。
- `manual`：无字段（严格空对象）。

命名理由：`read`/`write`/`edit`/`glob`/`grep` 原为五个独立公开 tool，现收为一个 `file` 家族的规范子操作，名称即 action 值即分派键，不设映射层；其实现亦已并入 `lingtai.tools.file` 单一 package。
