# 文档引用、组件布局、代理与验证

本页属 [Frontend 设计](../DESIGN.md)，说明原文阅读器、数字引用高亮、组件分工、代理与验证口径。

## 来源面板与数字引用

- `SessionDocuments` 在左栏互斥切换 Sources 与阅读视图：无选中引用时仅显示来源列表（不展示文档下拉框、不预加载正文）；点击引用后阅读器替换整个 Sources 区，顶部保留文档切换与 `Close document` 按钮，选中块淡黄色强调并保留前后章节。
- 来源列表展示 `raw` 资源并提供下载/删除；文件变更与提问提交在页面互斥。
- `/documents` 返回成员目录按一级目录归为整篇文档；`/documents/full?key=...` 一次取回整篇所有 Markdown 块并保留每块 `key`，`SourceReader` 按目录层级输出章节标题并在同一 `article` 内连续渲染段落、列表与表格。
- `MarkdownEvidence` 接管 `[label](documents/...)` 与证据链接：同文档切引用仅更新 `data-evidence-selected` 并滚动定位，跨文档才加载新全文；按 documents 资源 ID 与 location 判版本，5 秒空闲同步不重载正文、不反复滚动；忽略异步迟到结果，缺失引用显式提示不高亮其他段落。
- 数字引用为 14px 黑底白字小圆标（9px 字号），悬浮微变灰加细轮廓；对含空格的 Markdown key 先编码链接目标（代码示例保持原文），按节点位置分配编号且 StrictMode 复用；路径经查询参数编码，绝对或越界路径不作证据，旧数字 selector 无法映射时明确提示。仅历史和已完成的无工具 assistant 消息启用数字引用；原文使用 Markdown 渲染，不依赖旧 `display_html`/`source_selectors`。

## 组件边界与布局

| 模块 | 职责 |
| --- | --- |
| `upload-workbench.tsx` | 首页文件选择即处理、逐文件状态、创建会话与首问确认 |
| `use-file-uploads.ts`、`session/upload-status.tsx` | 单文件串行上传队列、重试/删除与来源行状态 |
| `task-detail.tsx` | 组合会话 hook、文件操作与证据选择 |
| `session/workspace-shell.tsx` | 顶部品牌与主题、最近会话抽屉、可调宽度来源分栏 |
| `session/workspace-overview.tsx` | 首页概览及摘要/关键问题草稿快捷入口（仅填草稿） |
| `session/conversation.tsx`、`composer.tsx`、`documents.tsx` | 对话流与工具组、输入与发送/暂停、来源列表与原文阅读 |
| `session-types.ts`、`session-state.ts`、`session-stream.ts`、`use-session.ts` | 契约、纯状态合并、SSE 解析与连接生命周期 |

- 宽屏为左来源右内容双栏，顶栏仅显 `Agent Gate`；输入框下方不放建议问题按钮，不展示无后端的音频/分享按钮；来源搜索按文件名忽略大小写过滤。
- 拖动条显式 `inline-flex`；800px 以下切换 Documents/Chat（点引用自动进原文）；最近会话抽屉支持遮罩和 Escape 关闭，动效遵循 `prefers-reduced-motion`。新增/修改代码模块控制在 300 行内，旧 replay 组件不接入现行链路。

## 代理与验证

- `backend-proxy` 原样透传 multipart/JSON 与流响应，保留 `Content-Disposition`，透传 `AbortSignal` 释放后端订阅；Next.js 代理上限 40mb，覆盖后端 32 MiB 内容与 multipart 开销。
- 测试运行：`pnpm --dir frontend exec jest --runInBand`、`pnpm --dir frontend lint`、`pnpm --dir frontend build`（说明在 `frontend/tests/docs/`）。本地默认运行由根目录 `scripts/start.sh` 启动并共用 `backend/backend.sqlite3` 与 `storage/data`；旧 `backend/backend/backend.sqlite3` 不自动迁移。
