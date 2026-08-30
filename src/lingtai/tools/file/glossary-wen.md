---
kind: tool-glossary
schema_version: 1
tool_package: lingtai.tools.file
language: wen
related_files:
- docs.yaml
- src/lingtai/kernel/tool_glossary.py
- src/lingtai/tools/glossary_validator.py
- src/lingtai/tools/file/glossary-en.md
- src/lingtai/tools/file/glossary-zh.md
maintenance: |
  Classical-Chinese (wen) glossary for the unified `file` tool family (lingtai.tools.file); body must stay non-empty and distinct from glossary-zh.md. Update in lockstep with glossary-en.md/glossary-zh.md whenever the family's public action set or envelope changes.
  Body policy: maintain only a minimal term mapping plus at most one or two sentences of naming rationale; do not translate or duplicate the tool schema, parameters, action behavior, manual, contract, or anatomy.
---
**名相对照**

- `file`：统摄文卷之能；唯一公器，以 `action` 择其下正名之子事。
- `action`：此召所择之子事，唯 `read`、`write`、`edit`、`glob`、`grep`、`settings`、`manual` 七者之一。
- `input`：该 action 自有之严整输入；他事之字段，一概不纳。
- `reasoning`：此召之由，录于日记；乃信封之属，非子事之输入。
- `summarize`：可选根级布尔，默为 false，主此召之果是否以摘要代之；亦信封之属，非子事之输入。`read`、`grep`、`glob` 之出或巨，可酌设 true；`write`、`edit` 之回执须精读，宜留 false。
- `settings`：家族所留之只阅 SHOW 事；唯纳空 `input`，以五字段尽陈 File 主家之策，不设 set/reset。
- `manual`：家族所留之事，返已装之 file-manual，不动目标文卷分毫。

**各 action 之 input 名相**

- `read`：`file_path` 文卷之绝对路径；`offset` 起始行号（自一起算，默十）；`limit` 至多读取之行数（默二千）；`max_chars` 此召字符之额（默十万，逾 runtime 不可配置之硬限者裁至二十万）。返带行号之文；唯文本可读，二进制、图像、音声不可。阅之虽成，犹或截断：当察 truncated、cap_chars、returned_chars、next_offset、remaining_lines_estimate、line_truncated，以 next_offset 续阅至尽。若 line_truncated=true，所示物理行唯前缀，next_offset 越至下行，不复其隐尾。
- `write`：`file_path` 文卷之绝对路径；`content` 欲写入之内容。父目录自动创建；用于新建文卷或完整重写，小改当用 `edit`。
- `edit`：`file_path` 文卷之绝对路径；`old_string` 欲查且替之精确文字；`new_string` 替换后之文字；`replace_all` 是否尽替所有匹配（默 false）。若 old_string 未见或有歧义则不成，且文卷不动分毫。
- `glob`：`pattern` glob 之式（如 '**/*.py'）；`path` 搜寻之目录（默为 agent 之工作目录）。返排序后之匹配路径。
- `grep`：`pattern` 欲搜之正则式；`path` 欲搜之文卷或目录（默为 agent 之工作目录）；`glob` 文卷过滤之式（默 '*' 即不滤）；`max_matches` 至多返回之匹配数（默二百）。返匹配之行及其文卷路径与行号。
- `settings`：无字段（严整空器）；返 `key`、`current`、`default`、`configurable`、`comment`。
- `manual`：无字段（严整空器）。

命名之由：`read`、`write`、`edit`、`glob`、`grep` 昔为五器各立，今敛为一 `file` 家族之正名子事；名即 action 之值，亦即分派之键，中无映射之层；其实亦并入 `lingtai.tools.file` 一 package 之内。
