# `theme.test.ts`

这组测试锁定 `frontend/src/app/globals.css` 的 Codex 主题契约。它不跑页面，只读取样式文件本身，防止 light/dark 颜色和工作台面板被改回通用白灰主题。

## 测试链路

```text
读取 globals.css
  -> 检查 :root 的 light token
  -> 检查 html[data-theme="dark"] 的 dark token
  -> 检查 replay 工作台是否把面板、代码块和对话框背景统一交给主题变量
  -> 检查 Agent 每条 turn 内的上下间距是否更开、工具行和折叠 tool group 内部是否仍保持紧凑，以及 PDF chip 删除按钮尺寸
  -> 检查 evidence 文本链接是否扩大命中区域，避免跨行链接点击落到父级文字容器
  -> 检查 Replay stage 在窄视口也使用列布局，避免右侧 Review 原文栏掉到 Agent 下方
  -> 检查原文 iframe 是否去掉固定纸面宽度并改为 100% 宽铺满右侧框体
  -> 检查 Agent 阅读列是否使用 `1fr / max readable / 1fr`，保证宽度变窄时先压缩左右留白，再压缩正文宽度
  -> 失败时提示哪些 token 或 surface 又回退成了硬编码颜色
```

## 测试函数

- `Codex 主题使用统一的 light/dark token`：验证 light/dark 的关键颜色值是否收敛到 Codex 风格的白底、深灰和蓝色 accent。
- `工作台面板和代码块都复用主题表面变量`：验证 replay 工作台的主面板、工具面板、代码块和对话框背景都不再直接写死白底，而是跟随主题变量切换。
- `Agent turn 使用更开的上下间距，工具行内部保持紧凑`：验证每条 turn 内“对话内容 -> tool 行”的上下间隔更开（当前目标是 14px），同时工具行和折叠 tool group 内部保持紧凑横向间隔，且 PDF 删除按钮有明确点击尺寸。
- `evidence 文本链接扩大命中区域，跨行时仍能点击到链接本身`：验证 evidence 文本链接使用 inline-block 和细小内边距，让长链接换行后点击命中仍落在链接元素上。
- `Replay stage 在窄视口也使用左右栏列布局，不把 Review 原文栏堆到下方`：验证 `.replay-stage` 的基础样式就使用 `--replay-stage-columns`，保证 in-app browser 等窄视口下点击证据后右侧 Review 仍出现在右侧列。
- `完整原文 tab 填满右侧框体，不再强制固定纸面宽度或横向滚动`：验证 iframe 注入样式把 `html/body/main/page` 都限制在 100% 宽，并去掉 980px 纸面宽度和横向滚动。
- `Agent 阅读列先压缩弹性留白，再压缩正文宽度`：验证 Agent 中间文字框和输入框使用左右 `1fr` 弹性留白与 720px 阅读列上限，防止回退成固定 gutter 或阈值式突然取消留白。
