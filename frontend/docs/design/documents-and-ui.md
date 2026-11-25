# 文档引用、组件布局、代理与验证

返回 [Frontend 设计](../DESIGN.md)。

## 来源面板与数字引用

- `SessionDocuments` 在左栏互斥切换 Sources 与阅读视图：无选中引用时只显示图标化的来源列表（不展示文档下拉框、不预加载正文，保留搜索框与 `+` 补传入口，每行提供点击阅读文件名及下载/删除图标）；点击引用或文件名后阅读器替换整个 Sources 区，顶部保留紧凑文档切换与关闭按钮，选中的段落以钢蓝柔光块（`rgba(57, 120, 200, 0.13)` + 左侧贴边 3px `#3978C8` 直竖条，右侧圆角无弯钩）高亮并保留前后章节。
- `SourceReader` 定位引用段落时仅操作左侧文档滚动容器的 `scrollTo`（目标段已在可视范围内时不重复拉扯），绝不调用 `scrollIntoView` 拉扯整页。
- Dark 模式下左侧打开的原始文档纸面（`.sourcePaper`）恒定保持 `#FAFAFA` 白纸黑字（外围 8px `#141414` 暗槽），保障长文档阅读对比度。
- `/documents` 返回成员目录按一级目录归为整篇文档；`/documents/full?key=...` 一次取回整篇所有 Markdown 块并保留每块 `key`，`SourceReader` 按目录层级输出章节标题并在同一 `article` 内连续渲染段落、列表与表格。
- `MarkdownEvidence` 接管 `[label](documents/...)` 与证据链接：同文档切引用只更新 `data-evidence-selected` 与当前激活角标 `data-active="true"`，跨文档才加载新全文；按 documents 资源 ID 与 location 判版本，5 秒空闲同步不重载正文、不反复滚动，忽略异步迟到结果，缺失引用显式提示而不高亮其他段落。
- 数字引用样式采用沉静钢蓝小圆标（常态浅钢蓝底配 `#3978C8` 字，悬停与激活态实心钢蓝白字），按节点位置分配编号并在 StrictMode 下复用；对含空格的 Markdown key 先编码链接目标（代码示例保持原文）。
- 引用路径经查询参数编码，绝对或越界路径不作证据，旧数字 selector 无法映射时给出提示；仅历史和已完成的无工具 assistant 消息启用数字引用，原文直接用 Markdown 渲染，不依赖旧 `display_html` / `source_selectors`。

## 组件边界与布局

| 模块 | 职责 |
| --- | --- |
| `upload-workbench.tsx` | TraceAgent 单聚焦居中首页、一体化输入框、回形针附件入口、行内逐文件状态与自动跳转 |
| `use-file-uploads.ts`、`session/upload-status.tsx` | 单文件串行上传队列、重试/删除与来源行状态 |
| `task-detail.tsx` | 组合会话 hook、文件操作、会话标题透传与证据选择（无冗余副顶栏） |
| `session/workspace-shell.tsx` | 44px 极简顶栏（左侧最近会话抽屉、`+` 新建、TraceAgent 品牌与当前会话标题，右侧状态与主题切换）、最近会话抽屉、自由拖拽来源分栏 |
| `session/conversation.tsx`、`composer.tsx`、`documents.tsx`、`source-reader.tsx` | 对话流与合并式 `trace-mini` 极简工具折叠行（经 `lib/tool-labels.ts` 映射友好英文动作名）、输入与发送/暂停、来源列表与白纸原文阅读器 |
| `session-types.ts`、`session-state.ts`、`session-stream.ts`、`use-session.ts`、`tool-labels.ts` | 纯类型定义（含 `DocumentSelection`）、纯状态合并、SSE 解析、连接生命周期与工具英文动作名映射 |

- 首页采用单聚焦居中舞台（无左侧空栏与快捷提示卡）；详情页宽屏采用无缝 1px 分割线的左右双栏（默认左文件 36% / 右对话 64%，允许自由拖拽至宽范围，且点击引用或切回 Sources 列表绝不重置用户拖拽后的宽度）；色彩对齐中性色阶（Light 左 `#FAFAFA` / 分割线 `#E6E6E6` / 右 `#FFFFFF` / 钢蓝 `#3978C8`，Dark 顶栏与左栏 `#141414` / 右对话 `#181818` / 气泡与输入 `#222222` / 钢蓝 `#4E8EE0`）；样式拆分为 `workspace.module.css`、`home.module.css`、`sources.module.css` 与 `conversation.module.css`。
- 拖动条显式设为 `inline-flex`；800px 以下切换 Documents/Chat（点引用自动进原文）；最近会话抽屉展示可读会话标题并支持遮罩和 Escape 关闭，动效遵循 `prefers-reduced-motion`。历史未接入的旧 replay 组件与死样式已彻底删除。

## 代理与验证

- `backend-proxy` 原样透传 multipart/JSON 与流响应，保留 `Content-Disposition`，透传 `AbortSignal` 释放后端订阅；Next.js 代理上限 40mb，覆盖后端 32 MiB 内容与 multipart 开销。
- 测试命令：`pnpm --dir frontend exec jest --runInBand`、`pnpm --dir frontend lint`、`pnpm --dir frontend build`（说明在 `frontend/tests/docs/`）。本地默认通过根目录 `scripts/start.sh` 启动并共用 `backend/backend.sqlite3` 与 `storage/data`；旧 `backend/backend/backend.sqlite3` 不自动迁移。
