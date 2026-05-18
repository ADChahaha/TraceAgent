# `theme.test.ts`

这组测试锁定 `frontend/src/app/globals.css` 的 Codex 主题契约。它不跑页面，只读取样式文件本身，防止 light/dark 颜色和工作台面板被改回通用白灰主题。

## 测试链路

```text
读取 globals.css
  -> 检查 :root 的 light token
  -> 检查 html[data-theme="dark"] 的 dark token
  -> 检查 replay 工作台是否把面板、代码块和对话框背景统一交给主题变量
  -> 失败时提示哪些 token 或 surface 又回退成了硬编码颜色
```

## 测试函数

- `Codex 主题使用统一的 light/dark token`：验证 light/dark 的关键颜色值是否收敛到 Codex 风格的白底、深灰和蓝色 accent。
- `工作台面板和代码块都复用主题表面变量`：验证 replay 工作台的主面板、工具面板、代码块和对话框背景都不再直接写死白底，而是跟随主题变量切换。
