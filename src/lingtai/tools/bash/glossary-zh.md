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

- `shell`：执行指令，返 stdout/stderr。可运行系统上一切可用之程——脚本、git、curl、pip、数据管道等。返回 exit_code、stdout、stderr，并附 ok（布尔）与 command_status（'success'/'failed'）。要点：即便命令失败，顶层 status 仍为 'ok'——它仅表示 shell 已执行。务必检查 exit_code/ok 并阅读 warning 字段（标明非零退出、Python 回溯、缺失模块）；切勿仅凭 status 断定成功。避免大范围递归扫描（find … -name、rglob、os.walk、glob('**')）——易超时；优先用 `rg --files`。JSONL 须逐行解析，勿当作单个 JSON。支持异步：input.async=true 获取 job_id，再用 poll/cancel 查之。用此工具前，必先读 `shell-manual` 技能（涵盖定时任务、异步规范与进阶用法），无例外。
- `action`：必选。本族动作之一：'run' 执行命令，'poll' 查询异步任务状态，'cancel' 终止异步任务，'manual' 返回已安装的 shell-manual 技能。无默认值。
- `input`：必选。所选 action 专属的严格入参对象；各动作的字段互不相通，跨动作字段会在派发前被拒绝。
- `reasoning`：必选。简述调用本工具的缘由（记入日记）。属 Host 元数据，不会进入 action 入参。
- `summarize`：可选，默认 false。根层跨切面的结果后处理开关，非 action 入参。为 true 时，该 tool 照常执行，原始结果会完整保存到持久日志（可按 tool_call_id 取回），但在结果进入你的上下文之前，会被一段由你的 `reasoning` 字段驱动的 LLM 生成摘要替换——所以请在 `reasoning` 中明确说明要保留什么。仅当预期输出很大（>10k 字符）且你不需要精确原文时才设为 true。需要精确的行/文件/diff/stderr 原文时请保持 false。摘要非权威；若原始结果超过 500,000 字符则不生成摘要，你会收到一条指向已保存原始结果的拒绝信息。
- `input.command`（仅 run）：要执行的 shell 命令
- `input.timeout`（仅 run）：超时秒数，传 null 即用默认 30；仅同步执行时生效
- `input.working_dir`（仅 run）：命令的工作目录，传 null 或空字符串即使用 agent 工作目录。必须位于 agent 工作目录沙箱内；沙箱外路径会被拒绝。若要操作外部仓库/路径，请将 working_dir 保持为 agent 目录，并在 command 中显式 cd，例如 cd /absolute/path && ...
- `input.async`（仅 run）：后台运行命令并立即返回 job_id，传 null 即用默认 false
- `input.reminder`（仅 run）：兜底异步唤醒延迟秒数，传 null 即用默认 1800。仅在异步 run 中使用并校验。初始期限仅作崩溃兜底；有界的持久 return-handoff 会阻止第二个 manager 在首个 manager 尚未完成成功返回转换时提前发布旧期限。只有在守卫仍有效时原子写入 `returned_at + reminder`（或精确完成/失败已在有效守卫内落盘）才返回成功；过期后恢复的 owner 会携 `job_id/pid` 返回“仍可 poll”的显式错误，且保留崩溃兜底。若最终到期时任务仍非终态，则发布 system 通知提醒 poll。取消期间的持久 suppressing 状态同样有界，超时后可恢复提醒。精确完成会抑制这条过时的“仍可能运行”提醒，改由 shell completion 通知唤醒。
- `input.job_id`（仅 poll/cancel）：异步任务 ID（由异步 run 返回）
- `manual`：入参为严格空对象 `{}`，不执行任何 shell 操作，返回 shell-manual 全文与其宿主本地路径。
