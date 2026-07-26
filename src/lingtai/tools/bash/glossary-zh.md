---
kind: tool-glossary
schema_version: 1
tool_package: lingtai.tools.bash
language: zh
related_files:
- docs.yaml
- src/lingtai/kernel/tool_glossary.py
- src/lingtai/tools/glossary_validator.py
- src/lingtai/tools/bash/glossary-en.md
- src/lingtai/tools/bash/glossary-wen.md
maintenance: |
  Simplified-Chinese (zh) glossary for the canonical `shell` tool (retained implementation package lingtai.tools.bash); body must stay non-empty. Update in lockstep with glossary-en.md/glossary-wen.md whenever shell's public tool schema changes.
  Body policy: maintain only a minimal term mapping plus at most one or two sentences of naming rationale; do not translate or duplicate the tool schema, parameters, action behavior, manual, contract, or anatomy.
---
**术语对照**

- `shell`：执行指令，返 stdout/stderr。可运行系统上一切可用之程——脚本、git、curl、pip、数据管道等。返回 exit_code、stdout、stderr，并附 ok（布尔）与 command_status（'success'/'failed'）。要点：即便命令失败，顶层 status 仍为 'ok'——它仅表示 shell 已执行。务必检查 exit_code/ok 并阅读 warning 字段（标明非零退出、Python 回溯、缺失模块）；切勿仅凭 status 断定成功。避免大范围递归扫描（find … -name、rglob、os.walk、glob('**')）——易超时；优先用 `rg --files`。JSONL 须逐行解析，勿当作单个 JSON。支持异步：action='run' 且 input.async=true 获取 job_id，再用 action='poll'/'cancel' 与 input.job_id 查之。用此工具前，必先读 `shell-manual` 技能（涵盖定时任务、异步规范与进阶用法），无例外。
- `action`：必填且必须显式选择：'run' 执行命令，'poll' 查询异步任务状态，'cancel' 终止异步任务，'manual' 读取已安装手册
- `command`：要执行的 shell 命令
- `timeout`：超时秒数（默认：30，仅同步执行时生效）
- `working_dir`：位于 input 对象内；命令工作目录（可选），留空即使用 agent 工作目录，必须在沙箱内。
- `async`：位于 run 的 input 内；后台运行命令并立即返回 job_id（默认 false）。
- `reminder`：位于 run 的 input 内；异步兜底唤醒延迟（默认 1800），仅 async run 校验和使用；poll/cancel 不接受此字段。
- `job_id`：位于 poll/cancel 的 input 内；异步任务 ID（由异步 run 返回）。
- `input.summary`：可选。默认 false。为 true 时，该 tool 照常执行，原始结果会完整保存到持久日志（可按 tool_call_id 取回），但在结果进入你的上下文之前，会被一段由你的 `reasoning` 字段驱动的 LLM 生成摘要替换——所以请在 `reasoning` 中明确说明要保留什么。仅当预期输出很大（>10k 字符）且你不需要精确原文时才设为 true。需要精确的行/文件/diff/stderr 原文时请保持 false。摘要非权威；若原始结果超过 500,000 字符则不生成摘要，你会收到一条指向已保存原始结果的拒绝信息。
