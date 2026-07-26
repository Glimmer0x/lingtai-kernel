---
kind: tool-glossary
schema_version: 1
tool_package: lingtai.tools.bash
language: wen
related_files:
- docs.yaml
- src/lingtai/kernel/tool_glossary.py
- src/lingtai/tools/glossary_validator.py
- src/lingtai/tools/bash/glossary-en.md
- src/lingtai/tools/bash/glossary-zh.md
maintenance: |
  Classical-Chinese (wen) glossary for the canonical `shell` tool (retained implementation package lingtai.tools.bash); body must stay non-empty and distinct from glossary-zh.md. Update in lockstep with glossary-en.md/glossary-zh.md whenever shell's public tool schema changes.
  Body policy: maintain only a minimal term mapping plus at most one or two sentences of naming rationale; do not translate or duplicate the tool schema, parameters, action behavior, manual, contract, or anatomy.
---
**名相对照**

- `shell`：执行指令，返 stdout/stderr。可运行系统上一切可用之程——脚本、git、curl、pip、数据管道等。返 exit_code、stdout、stderr，兼附 ok（真伪）与 command_status（'success'/'failed'）。须知：命令虽败，顶层 status 仍作 'ok'——此仅言 shell 已运，非言命令已成。必察 exit_code/ok，且阅 warning 一字（标非零之退、Python 之回溯、缺失之模块）；勿独凭 status 而断其成。忌大范围递归之扫（find … -name、rglob、os.walk、glob('**')）——易致超时；宜先用 `rg --files`。JSONL 当逐行而解，勿混作一 JSON。支持异步：设 action='run' 且 input.async=true 取 job_id，后以 action='poll'/'cancel' 与 input.job_id 查之。用此器前，必先读 `shell-manual` 一技（含定时之设、异步之规、进阶之用），无所例外。
- `action`：必明择所行之事：'run' 执行指令，'poll' 查异步任务之状，'cancel' 斩异步任务，'manual' 读已装手册
- `command`：欲执行之指令
- `timeout`：超时秒数（默认：30，唯同步执行时生效）
- `working_dir`：居于 input 对象；命令之工作目录（可选），留空即用 agent 工作目录，须在沙箱之内。
- `async`：居于 run 之 input；后台运行指令，立即返 job_id（默认 false）。
- `reminder`：居于 run 之 input；异步兜底唤醒延迟（默认 1800），仅 async run 校验使用；poll/cancel 不受此字段。
- `job_id`：居于 poll/cancel 之 input；异步任务之号（由异步 run 所返）。
- `input.summary`：可选。默认 false。设 true 时，此 tool 照常运行，原始结果完存于持久日志（可凭 tool_call_id 取回）；然结果入尔上下文前，先以尔 `reasoning` 字段所驱之 LLM 摘要代之——故 `reasoning` 当明言所欲存者。唯料输出甚巨（逾一万字符）且无需精确原文时，方设 true。需精确之行/文件/diff/stderr 原文者，留 false。摘要非权威；原始结果逾五十万字符，则不生摘要，尔得一拒辞，指向所存之原始结果。
