# `theme.test.ts`

这组测试锁定 `frontend/src/app/globals.css` 的 Codex 主题契约。它不跑页面，只读取样式文件本身，防止 light/dark 颜色和工作台面板被改回通用白灰主题。

## 测试链路

```text
读取 globals.css
  -> 检查 :root 的 light token
  -> 检查 html[data-theme="dark"] 的 dark token
  -> 检查 replay 工作台是否把面板、代码块和对话框背景统一交给主题变量
  -> 检查 Agent 每条 turn 内的上下间距是否更开、工具行和折叠 tool group 内部是否仍保持紧凑，折叠 group 是否带可旋转箭头且展开明细不额外左缩进，以及 PDF chip 删除按钮尺寸
  -> 检查 Agent 正文、evidence 链接、tool 摘要和折叠 tool group 摘要在窄宽度下使用换行，而不是 nowrap + hidden 裁剪
  -> 检查 Replay stage 在窄视口也使用列布局，避免右侧 Review 原文栏掉到 Agent 下方
  -> 检查 Agent 对话流和底部输入框在 centered/full 两种内容模式下都铺满当前 Agent slot，并共用同一个水平 inset，避免正文和 composer 左右边距不一致
  -> 检查 Contents 面板列表是否自身纵向滚动、隐藏横向溢出，并让长标题和值多行换行，不用 ellipsis 裁剪
  -> 检查首页首屏是否固定在视口内，左侧栏隐藏溢出，只允许左侧 Tasks 列表作为剩余高度区域自己纵向滚动，并且首页左侧栏宽度使用统一的 `--replay-left-panel-width`
  -> 检查首页打开左侧栏时在窄视口仍保留 `sidebar / resize handle / main` 三列，只在关闭左栏时隐藏 sidebar 和 handle
  -> 失败时提示哪些 token 或 surface 又回退成了硬编码颜色
```

## 测试函数

- `Codex 主题使用统一的 light/dark token`：验证 light/dark 的关键颜色值是否收敛到 Codex 风格的白底、深灰和蓝色 accent。
- `工作台面板和代码块都复用主题表面变量`：验证 replay 工作台的主面板、工具面板、代码块和对话框背景都不再直接写死白底，而是跟随主题变量切换。
- `Agent turn 使用更开的上下间距，工具行内部保持紧凑`：验证每条 turn 内“对话内容 -> tool 行”的上下间隔更开（当前目标是 14px），同时工具行和折叠 tool group 内部保持紧凑横向间隔；折叠 group 使用 `icon / summary / chevron` 三列，箭头展开时旋转，展开明细不额外左缩进，PDF 删除按钮也有明确点击尺寸。
- `Agent 文本和工具摘要在窄宽度下换行，不用隐藏省略裁剪`：验证 Agent 正文、evidence 链接、tool 摘要和折叠 tool group 摘要都允许在窄列中换行，防止压缩侧栏或打开 Review 后文字被 ellipsis/overflow hidden 截断。
- `Replay stage 在窄视口也使用左右栏列布局，不把 Review 原文栏堆到下方`：验证 `.replay-stage` 的基础样式就使用 `--replay-stage-columns`，保证 in-app browser 等窄视口下点击证据后右侧 Review 仍出现在右侧列。
- `Agent 对话流和 composer 使用同一套左右 inset 铺满中间 panel`：验证 Agent 正文流和底部输入框在 centered/full 两种内容模式下都使用 `0 / minmax(0, 1fr) / 0`，实际宽度由外层统一水平 inset 控制，防止正文窄列和 composer 宽度不一致。
- `Contents 面板保留可读宽度、纵向滚动和多行文本`：验证 Contents 列表有 `min-height: 0` 和纵向滚动，横向溢出被收住，outline 标题和值都允许多行换行而不是隐藏省略。
- `首页首屏只让 Tasks 列表成为滚动容器，整页工作台不滚动`：验证首页 workbench 以 fixed/inset 固定到 viewport，stage 和左侧栏隐藏整体溢出，真正可滚动的是占据剩余高度的 `.replay-task-list`，且首页和详情页复用同一个左侧栏宽度变量。
- `首页打开左侧栏时窄视口仍保留侧栏和拖拽手柄`：验证首页打开左栏时不会被 900px 响应式规则改成单列，也不会隐藏 `.replay-task-sidebar` 或 `.replay-panel-resize-handle`；关闭左栏时才隐藏这两个元素。
