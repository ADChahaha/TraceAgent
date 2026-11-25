# `theme.test.ts`

这组测试锁定 TraceAgent 工作台的样式契约，读取 `globals.css`、`workspace.module.css`、`sources.module.css` 与 `conversation.module.css`，防止 Light/Dark 中性色阶、暗色白纸文档、36%/64% 分栏比例、窄列折行与 `trace-mini` 工具折叠样式回退。

## 测试函数

- `TraceAgent 主题使用统一的 Antigravity / Codex 中性色阶、柔光高亮与暗色白纸文档`：验证 Light/Dark 中性色阶（`#FAFAFA`、`#E6E6E6`、`#FFFFFF`、`#3978C8` 与 `#141414`、`#181818`、`#222222`、`#4E8EE0`）、Dark 模式左侧文档纸面恒定保持 `#FAFAFA` 白纸黑字（8px 暗槽）及钢蓝柔光块无弯钩样式。
- `默认详情页左右分栏给右侧 Agent 对话区更大宽度，拖动条显式占位`：验证 `workspace.module.css` 默认左栏为 `36%`（右侧对话区 64%），且分栏拖动条显式设为 `inline-flex`。
- `Agent 正文和行内链接在窄宽度下完整折行，容器查询支持窄列模式`：验证 `.replay-agent-reason-text` 与 `.replay-evidence-link` 完整折行且容器查询保留窄列紧凑模式。
- `工具过程折叠条采用极简 trace-mini 布局并支持窄列换行`：验证 `conversation.module.css` 隐藏原生 disclosure marker、展开旋转箭头、左侧细竖线引导及步骤列表自动换行。
