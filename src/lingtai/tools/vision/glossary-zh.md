---
kind: tool-glossary
schema_version: 1
tool_package: lingtai.tools.vision
language: zh
related_files:
- docs.yaml
- src/lingtai/kernel/tool_glossary.py
- src/lingtai/tools/glossary_validator.py
- src/lingtai/tools/vision/glossary-en.md
- src/lingtai/tools/vision/glossary-wen.md
maintenance: |
  Simplified-Chinese (zh) glossary for the `vision` tool package (lingtai.tools.vision); body must stay non-empty. Update in lockstep with glossary-en.md/glossary-wen.md whenever vision's public tool schema changes.
  Body policy: maintain only a minimal term mapping plus at most one or two sentences of naming rationale; do not translate or duplicate the tool schema, parameters, action behavior, manual, contract, or anatomy.
---
**术语对照**

- `vision`：使用 LLM 的视觉能力分析图像。支持 JPEG、PNG 和 WebP。可以对图像提出任何问题——描述内容、识别文字、解读图表、识别物体、评估风格或氛围。结合 draw 可以先生成图像再分析。
- `action`：所选子 Tool 名，`analyze` 直接分析，`manual` 仅返回只读指引
- `input`：所选 action 自身的严格输入
- `image_path`：`analyze` 输入中的图像文件路径
- `question`：`analyze` 输入中关于图像的问题，`null` 表示使用默认提问
- `reasoning`：Host 审计元数据，不进入 action 输入
- `summarize`：Host 呈现层的可选后处理开关，不进入 action 输入
- `manual`：族属保留子 Tool 名，返回安装手册全文与路径；引导 agent 查看当前 preset 身份并在自身 skill catalog 中查找匹配手册；不自动调用 MCP
