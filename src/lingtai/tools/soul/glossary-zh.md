---
kind: tool-glossary
schema_version: 1
tool_package: lingtai.tools.soul
language: zh
related_files:
- docs.yaml
- src/lingtai/kernel/tool_glossary.py
- src/lingtai/tools/glossary_validator.py
- src/lingtai/tools/soul/glossary-en.md
- src/lingtai/tools/soul/glossary-wen.md
maintenance: |
  Simplified-Chinese (zh) glossary for the `soul` tool package (lingtai.tools.soul); body must stay non-empty. Update in lockstep with glossary-en.md/glossary-wen.md whenever soul's public tool schema changes.
  Body policy: maintain only a minimal term mapping plus at most one or two sentences of naming rationale; do not translate or duplicate the tool schema, parameters, action behavior, manual, contract, or anatomy.
---
**术语对照**

- `soul`：你的内心之声。flow 默认关闭、需显式启用：仅当运维设置环境变量 LINGTAI_SOUL_FLOW_ENABLED=1（随后 refresh）时才运行。关闭时，soul(action='flow', input={}) 返回 status='disabled'（这是预期状态，不是错误，请勿反复重试）；inquiry/config/voice/dismiss/manual 仍可用。启用后，flow 每 soul_delay 秒于 IDLE 时自动触发——M=1+K 次并行 LLM 调用（1 次对当前对话的退步阅读 + K 次过去快照之声），以非自愿的 soul(action='flow', input={}, reasoning=...) 对出现在历史中（该合成对与当前信封同形，可直接照此调用）。delay_seconds 只是启用后的节奏，并非开关。inquiry：向自身深拷贝提问，答案在工具结果中返回。config：运行时调整心流旋钮（delay_seconds、consultation_past_count），但不会启用 flow。dismiss：消除当前心流通知。详见 soul-manual skill。
- `set`：切换到哪个声音预设。属于 action='voice' 的 input。内置：'inner'（极简——「你是灵魂，以内心之声说话」）或 'observer'（结构化的退后一步、钩之框架）。或 'custom'，需附上 'prompt' 字段写入你自己的系统提示词文本。不传 'set' 即读取当前声音和已解析的提示词，不做任何改动。
- `prompt`：心流之声的自定义系统提示词。属于 action='voice' 的 input；set='custom' 时必填，其他情况下忽略。长度上限 4000 字符。以灵魂之身向自己说话——描述你希望阅读自己日记时被如何框定。同一个提示词同时用于 insights（当下之我）与 past（凝蜕前的旧我）两类咨询；每次触发的提示文本会区分你正在读谁的日记。
- `input`：所选 action 独有的严格输入对象。每个 action 各自拥有一份封闭的 input：inquiry 只收 `inquiry`；config 只收 `delay_seconds`/`consultation_past_count`；voice 只收 `set`/`prompt`；flow、dismiss、manual 收空对象。跨 action 传参（如 action='inquiry' 却给 delay_seconds）在任何处理之前即被拒绝。
- `reasoning`：调用本工具的简短理由，记入日记。属于信封根层的必填项，不属于任何 action 的 input。
- `summarize`：根层的结果后处理开关，默认缺省或 false。不是 action 的输入。soul 的结果都很小，通常保持 false；读 manual 时尤应保持 false，以免摘要略去确切步骤。
- `manual`：返回已安装的 soul-manual skill，不执行任何 soul 操作（不动定时器、锁、咨询、配置、声音或通知状态）。
