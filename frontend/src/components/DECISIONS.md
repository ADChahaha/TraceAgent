# frontend/src/components 关键决策

归属 [Frontend 设计](../../docs/DESIGN.md)，记录工作台组件布局、文件入口与原文引用交互的长期取舍。

## 1. 详情页文件补传收口到 Sources，引用基于 Markdown 块 key 直接渲染

- 决定：详情页补传统一走 Sources 面板的 `Add files`，聊天输入区不放附件按钮，也不展示无后端接口的建议问题/音频/分享按钮；左栏互斥切换 Sources 列表与阅读视图，无选中引用时不预加载正文；数字引用直接按 `documents/...` 块 key 渲染并高亮 Markdown 原文。
- 原因：避免多入口导致文件状态与问答提交冲突，去掉不必要的预加载开销和历史 HTML 选择器兼容负担。
- 排除：在对话输入框重复放置附件上传入口，或继续维护旧版 `display_html` / `source_selectors` 引用映射。
