# frontend/src/components 关键决策

归属 [Frontend 设计](../../docs/DESIGN.md)，记录工作台组件布局、流式交互、文件入口与原文引用渲染的长期取舍。

## 1. 详情页文件补传收口到 Sources，左栏互斥切换列表与阅读器

- 决定：详情页补传统一走 Sources 面板的 `Add files`，聊天输入区不放附件按钮，也不展示无后端接口的建议问题/音频/分享按钮；左栏互斥切换 Sources 列表与阅读视图，无选中引用时不预加载正文。
- 原因：避免多入口导致文件状态与问答提交冲突，去掉不必要的预加载开销和无后端支撑的装饰控件。
- 排除：在对话输入框重复放置附件上传入口；无选中引用时预加载文档正文或展示文档下拉框。

## 2. 否决 PDF 页图加 bbox overlay，原文审阅统一走白纸连续 Markdown DOM 与钢蓝柔光块

- 决定：撤回并禁止"后端渲染 PDF 页图加前端百分比 bbox 叠加高亮框"方案；原文阅读器统一由 `SourceReader` 直接渲染整篇文档的连续 Markdown 块 DOM，在 Light 与 Dark 模式下原始文档纸面恒定保持 `#FAFAFA` 白纸黑字（Dark 模式外围仅留 8px `#141414` 暗槽）；通过 `data-evidence-selected` 使用沉静钢蓝柔光块（`rgba(57, 120, 200, 0.13)` + 左侧贴边 3px `#3978C8` 直竖条，右侧圆角无弯钩）高亮目标段，并仅操作左侧滚动容器 `scrollTo`（目标段已在可视范围内时不重复拉扯），绝不使用 `scrollIntoView` 拉扯整页。
- 原因：实测 PDF 页图叠加 bbox 存在无法顺畅上下连续滚动与定位偏移问题；原黄色荧光高亮在长文与暗色下刺眼或发脏，且 `scrollIntoView` 会把外层顶栏与整页上下拉扯；恒定白纸黑字配钢蓝柔光块兼顾双主题阅读舒适度与清晰证据焦点。
- 排除：后端渲染每页 PDF 为 PNG base64 返回并由前端叠放 bbox 高亮框；黄色荧光块或行内划词高亮；在 Dark 模式下把原始文档正文反色为深灰底白字；继续调用 `scrollIntoView` 定位段落。

## 3. 采用 `react-markdown` + `remark-gfm` 渲染正文，区分过程内联链接与最终句末角标

- 决定：放弃手写 Markdown 块解析器，改用 `react-markdown` + `remark-gfm` 渲染嵌套列表与表格（经 `normalizeMarkdown` 展开紧凑表格并对含空格的 `documents/...` 目标编码，跳过代码块），默认不执行原始 HTML；仅对已完成且无 `tool_calls` 的最终回答启用 `citation` 模式渲染句末数字角标，并通过 `splitTrailingSourcesSection` 剥离模型尾随生成的 `Sources` 汇总段；过程叙述保持 `inline` 可读链接。
- 原因：手写行解析器易拆裂嵌套列表与 GFM 表格；终稿用句末数字角标并去尾随来源列表能保持正文阅读连贯。
- 排除：继续修补手写块解析器；在最终回答段下或文末单开 Sources 列表；把过程叙述中的证据链接也压成纯数字角标。

## 4. 流式交互保持主按钮 DOM 稳定、单条极简工具折叠组、友好英文动作名、智能跟底与窄列折行

- 决定：发送与暂停复用同一个 `<Button>` DOM 节点（内部图标以 `data-visible` 切换），生成期间保持 `<textarea>` 可编辑草稿；`groupItems` 跳过仅有 `tool_calls` 而无可见文本的空 `assistant` 消息，把连续工具调用合并为单个 `<details>` 极简折叠入口（放大镜图标 + 步骤数 + 箭头），以首条工具稳定 ID（`group[0].id`）作 React key 防止流式追加时重挂载收起，展开后通过 [tool-labels.ts](../lib/tool-labels.ts) 映射为友好英文动作名（`Browse files` / `Read passage` / `Keyword search` / `Semantic search`，未知兜底 `Document lookup`），不暴露 `ls`/`grep`/`read`/`search_embedding` 原始工具名，失败工具沿用中性配色不标红；对话流仅在距底 `<= 80px` 时自动跟底，上翻历史不强拉回底；窄列下正文与行内链接以 `display: inline` 与 `overflow-wrap: anywhere` 完整折行。
- 原因：避免空文本中间消息把一轮工具调用切碎为多行堆叠，隐藏内部实现函数名提升阅读清晰度，同时防止流式更新期间按钮闪烁、输入中断、工具折叠态复位、强制滚底打断阅读或窄屏文字截断。
- 排除：保留空消息分隔导致多行 `1 tool activity` 竖排堆叠；在界面直接展示 `ls`/`grep`/`read`/`search_embedding` 原始工具名；拆分为两个条件挂载按钮或在运行期禁用输入框；用数组长度或下标作工具组 key；给 `tool_failed` 加红色警示；流式到达无条件滚底；以单行省略裁剪链接。

## 5. 前端运行时全英文文案门禁与彻底隔离实验页面

- 决定：前端运行时 UI、可访问性标签、错误兜底与页面 metadata 统一使用英文，由 `frontend/tests/frontend-copy.test.ts` 机械门禁禁止 `frontend/src/**/*.ts(x)` 非注释代码中出现汉字字面量（匹配中文的正则改用 Unicode 转义）；产品路由彻底隔离实验数据页面与旧字段审核/`route` 徽标控件。
- 原因：防止界面出现中英文混杂，保持产品代码与离线评测数据及已废旧审核工作流彻底隔离。
- 排除：仅靠人工规范约束英文 UI 文案；在前端产品路由中内置实验数据展示页或保留字段审核控件。

## 6. 品牌统一为 `TraceAgent`，单聚焦首页、44px 极简顶栏（左侧 `+` 新建）与 36%/64% 默认自由拖拽分栏

- 决定：工作台品牌与页签元数据统一改为 `TraceAgent`；首页移除左侧空栏与 `Get a summary`/`Explore the details` 快捷提示卡（彻底删除 `workspace-overview.tsx` 及历史未接入的 `replay-review.tsx`/`outline-panel.tsx`/`task-store.ts`/`types.ts`/`json.ts` 与死样式），改为单聚焦居中舞台加一体化输入框、回形针附件入口与行内文件队列状态；顶栏收敛为 44px 极简图标栏，将 `+`（New workspace）置于左侧紧邻最近会话菜单按钮，右侧仅留状态、窄屏切换与主题切换按钮，并移除详情页冗余的 `Document conversation` 副顶栏；详情页采用中性色阶（Light 左 `#FAFAFA`/右 `#FFFFFF`，Dark 顶栏与左栏 `#141414`/右 `#181818`/浮起元素 `#222222`），默认按左文件 36% / 右对话 64% 展开，允许自由拖拽且点击引用或切回文件列表绝不重置用户设定的左右宽度；样式拆分为 `workspace.module.css`、`home.module.css`、`sources.module.css` 与 `conversation.module.css`，共享类型 `DocumentSelection` 迁入 `session-types.ts` 消除 `documents.tsx <-> source-reader.tsx` 循环引用。
- 原因：让默认进入工作台时 Agent 对话区明显宽于文件栏，把高频新建入口与历史会话抽屉收拢在左上角更符合直觉，同时按职责拆分 CSS 并彻底删除死代码满足全仓单文件 <= 300 行与无循环依赖门禁。
- 排除：继续保持 50%/50% 对半开屏；把 `+` 新建按钮放在顶栏右侧主题切换旁；保留 2500+ 行的旧 replay 死代码或 559 行单体 CSS；在点击引用时强行把左栏重置回固定宽度。
