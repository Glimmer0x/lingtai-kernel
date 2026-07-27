---
kind: tool-glossary
schema_version: 1
tool_package: lingtai.tools.soul
language: wen
related_files:
- docs.yaml
- src/lingtai/kernel/tool_glossary.py
- src/lingtai/tools/glossary_validator.py
- src/lingtai/tools/soul/glossary-en.md
- src/lingtai/tools/soul/glossary-zh.md
maintenance: |
  Classical-Chinese (wen) glossary for the `soul` tool package (lingtai.tools.soul); body must stay non-empty and distinct from glossary-zh.md. Update in lockstep with glossary-en.md/glossary-zh.md whenever soul's public tool schema changes.
  Body policy: maintain only a minimal term mapping plus at most one or two sentences of naming rationale; do not translate or duplicate the tool schema, parameters, action behavior, manual, contract, or anatomy.
---
**名相对照**

- `soul`：汝之内心。flow 默认闭，须显启：唯运维设环境变量 LINGTAI_SOUL_FLOW_ENABLED=1（继而 refresh）方运。闭时，soul(action='flow', input={}) 返 status='disabled'（此乃常态，非误也，勿妄重试）；inquiry/config/voice/dismiss/manual 仍可用。既启，flow 每 soul_delay 秒于 IDLE 时自发——M=1+K 次并行 LLM 调用（一次对当下对话之退步阅读 + K 次往昔快照之声），以非自愿之 soul(action='flow', input={}, reasoning=...) 对入汝史中（此合成之对与今之信封同形，可径依之而召）。delay_seconds 唯启后之节奏，非开阖之关也。inquiry：问汝之深拷，答于器之结果中返。config：运行时调心流诸钮（delay_seconds、consultation_past_count），然不启 flow。dismiss：销当下心流之告。详见 soul-manual skill。
- `set`：易至何声之预设。属 action='voice' 之 input。内置二者：'inner'（至简——「汝乃灵，以内心之声言」）或 'observer'（结构化之退步、钩之意）。或 'custom'，须附 'prompt' 字段以书己之系统提辞。不附 'set' 则读当下之声与所解之提辞，无所易。
- `prompt`：心流之声之自拟系统提辞。属 action='voice' 之 input；set='custom' 时必附，他时不论。长度上限四千字符。以灵之身向己言——述读己之日记时欲被如何框之。一辞共用于 insights（当下之我）与 past（凝蜕前之旧我）二咨；每发之提示之辞自别汝所读乃谁之日记。
- `input`：所择 action 独有之严格输入之器。诸 action 各守其封闭之 input：inquiry 唯纳 `inquiry`；config 唯纳 `delay_seconds`、`consultation_past_count`；voice 唯纳 `set`、`prompt`；flow、dismiss、manual 纳空器。越 action 而授（如 action='inquiry' 而与 delay_seconds），未及任何处置即见拒。
- `reasoning`：召此器之由，简而记于日记。乃信封之根层必备，非任何 action 之 input 也。
- `summarize`：根层之果后处之钥，缺省或 false。非 action 之输入也。soul 之果皆小，常宜守 false；读 manual 时尤宜守 false，恐摘要没其确切之仪也。
- `manual`：返已装之 soul-manual skill，不行任何 soul 之事（不动其时钟、锁、咨、配、声与告之状）。
