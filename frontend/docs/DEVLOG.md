# Frontend Devlog

last updated: 2026-09-19

## 2026-09-19

### 选文件立即处理与实际数据库恢复

首页不再等提问后批量上传。选择文件后复用一次创建的会话，按文件串行请求处理接口；每行分别展示排队、右侧旋转图标、就绪或失败重试。详情补传复用同一队列，失败不阻塞后续文件。处理中禁止提问，发送首问不重复上传；删除已处理文件调用后端，删除刚补传文件清理本地占位。文件完成后可直接 Open workspace 查看资源。

TDD 先复现选择文件后没有请求、没有独立状态及补传批量提交等失败；实现后再用删除回归测试复现并修复残留就绪占位。最终前端 60 项测试、ESLint、TypeScript 和生产构建通过。

停止上一轮指向 /tmp 的服务，改用 scripts/start.sh 正常启动，后端进程实际打开 backend/backend.sqlite3，存储使用 storage/data，前端入口为 127.0.0.1:3000。旧 backend/backend/backend.sqlite3 保留，其旧 tasks 表不会自动迁移。浏览器上传两份合成 DOCX，未输入问题即看到各自处理状态并完成；实际库有 2 个 raw、1 个 documents、1 个 index，chat_turns 数量为 0。通过 Open workspace 打开会话 b7ed5846d57a4bdab816499d7d4e4678 查看资源。

### 真实后端联调补验

启动独立 storage、document、agent 和 backend 服务，前端通过 3105 端口代理访问 8000。使用合成 orion-pilot.docx、独立临时数据库和存储目录，从浏览器执行上传、模型流式问答、生成中刷新、完成后刷新、追问与取消；下载的 DOCX 与原文件逐字节一致。

实际发现并修复：Agent 接受空白最终消息导致下一轮输入校验失败；backend completion 首帧遗漏历史轮次；真实引用目录含空格而无法被 Markdown 解析；StrictMode 重复渲染使引用编号跳号。前两项在对应服务修复并补测试，前端在解析前仅编码文档链接目标的空格，代码示例不改写，引用编号按节点位置复用。

修复后会话 fcc0546d94ae4803b44e2d39d2c86c06 完成预算回答 $48,000、取消一轮、再完成最终评审日期 November 25, 2026 的追问；两处数字引用均实际点击并核对原文，提交新轮时历史继续保留。模型曾超时重试，不能据此声称模型服务稳定；本轮未验证 PDF OCR。

验证结果：Agent 213 项、backend 94 项、前端 56 项测试通过；前端 ESLint、TypeScript 和生产构建通过。所有修复均先用失败测试复现，再实现并回归。

### 资料工作台界面收尾

按参考图改为顶部导航、左侧来源和右侧主内容的双栏布局，保留 Agent Gate 品牌。首页显示文件列表、文档概览和底部提问框；最近会话移入按需展开的抽屉。详情页把文件操作和原文阅读合并到来源栏，聊天区保留固定输入区域。样式放在工作台 CSS Module 中，避免影响未接入的旧 replay 页面。

新增来源搜索和可编辑问题建议。搜索仅过滤文件列表，阅读中的原文不会消失；摘要、关键问题和比较建议先填入草稿，不隐式创建轮次。未添加没有后端能力的音频或分享按钮。

先增加首页概览与建议、来源搜索测试，确认两项因缺少目标行为失败，再实现。全部 11 个套件、53 项测试通过，ESLint、TypeScript 和生产构建通过。浏览器检查桌面 1440x960 与窄屏 390x844 的首页布局，并实际验证问题建议填入和 Documents/Chat 切换。本轮未重新执行真实模型全链路，接口行为通过现有迁移回归测试验证。

### 会话 API 迁移

前端从旧 `/qa/tasks` 迁移为独立会话与文件 API。首页先创建会话、上传文件，再等待 POST completion 的首帧确认后跳转；详情用 resume 快照替换历史，再按消息和工具 ID 合并增量。断线只 GET 恢复，取消明确传 session_id 和 turn_id。最近会话只保存在本机导航缓存，因为后端没有会话列表接口。

把原 1591 行详情组件拆成连接 hook、纯状态合并器、SSE 解码器，以及工作台、对话、输入和文档组件。补齐文件下载、补传、删除和 documents 路径引用查看；原文改从 document API 读取 Markdown。窄窗口收起侧栏并在文档和聊天之间切换，引用点击自动打开原文。所有本次新增或修改的代码文件均不超过 300 行。

代理响应改为二进制/流原样转发并保留下载文件名，传递订阅取消信号；代理上传容量由 10mb 提升到 40mb，覆盖后端 32 MiB 配额及 multipart 开销。取消的历史轮次仅显示取消状态，不重复显示错误警告。

按 TDD 先复现旧接口、正文重复合并风险、代理二进制损坏、断流恢复、窄窗口引用不可见等目标行为，再逐层实现。验证结果：前端 11 个测试套件、51 项测试通过，TypeScript、ESLint 和生产构建通过。

使用临时数据库与 storage 目录，在真实浏览器完成 DOCX 上传、首问跳转、模型流式回答、引用原文查看、刷新恢复、追问和取消。数据库保存一轮 completed 与一轮 cancelled；通过前端代理下载的 DOCX 与原文件逐字节一致。真实模型出现过一次缺少结束信号的尝试，现有后端重试后完成。PDF 解析及模型服务稳定性不属于本次前端验证结论。

## 2026-05-23 04:15:14

### 已完成工作

- 前端切换到 QA-only API：`/qa/tasks`、`/inputs`、`/events`、`/cancel`。
- 首页创建流程改为“上传 PDF + 首轮问题”，不再提交 `task_spec`、`task_type` 或字段 schema。
- 任务详情页改为 SSE 事件驱动的多轮 QA 工作台，直接渲染用户消息、模型过程消息、工具过程和 inline evidence link。
- 运行中右下角发送按钮切换为暂停按钮，点击后调用当前 task 的 cancel 接口。
- 同步更新 `frontend/docs/DESIGN.md` 和前端测试说明文档。

### 验证

- `npm test -- --runInBand`，结果 `6 suites / 29 tests passed`。
- `npm run lint` 通过。
- `npm run build` 通过。
- 浏览器打开 `http://127.0.0.1:3000` 检查首页上传与 QA 输入；backend 未启动时详情页能展示后端不可用错误。

## 2026-05-05 15:21:45

### 已完成工作

- 修复 replay 全屏模式下长字段值把人工复核区顶出视口的问题。
- `ReplayReview` 在存在字段写入卡时给根节点增加 `has-field-write` 布局状态，让全屏样式为底部字段卡和复核区预留更高空间。
- 字段写入卡内部改为字段内容区独立滚动，复核 textarea 和提交按钮固定留在卡片底部。
- 同步更新设计文档和任务详情测试说明，补充全屏长字段 review 的回归测试。

### 验证

- `pnpm --dir frontend test -- task-detail.test.tsx --runInBand`，结果 `20 passed`。

## 2026-05-04 02:20:00

### 已完成工作

- 新增 Review replay 动画界面，直接消费 backend 的 `actions + display_html + outline_tree + result`。
- Review 主体采用文档视图布局：左侧可展开 outline，中间 iframe 渲染 document_processor 的原始 display HTML，右侧显示 plan 进度，底部对话框显示模型每一步 reason。
- 支持 auto 播放、速度控制、对话框左键下一步、对话框上滚进入 backlog、右键退出 backlog、浏览器全屏视图。
- 每个 action 会定位相关 DOM id：outline 逐层展开并显示鼠标点击动画，文档区域滚动到 evidence，paragraph 做逐行阅读高亮，table/list 做块级高亮。
- `set_field` 时在文档证据处做写入强调，并在对话框展示字段值和 evidence chip；evidence chip 点击可暂停 replay 并跳转到对应证据。
- 人工 review 入口保留在 replay 下方：需要人工接管时，用户可以边看动画边填写需要修正的字段。
- 前端显示层隐藏内部 id：header 显示 `Header: 标题内容`，表格显示 `某 header 下面的表格`，表格行显示 `某 header 下面的表格第 N 行`；原始 id 仍用于定位和高亮。
- 修复直接进入 `/tasks/{task_id}` 或 failed task 时 replay 不加载的问题，只要 summary 有 trace/result 就拉取 replay。

### 当前进展

- 真实立命馆任务的 replay 页面已经能展示 `52` 步 actions，并可用于观察模型如何查找、读取、查询表格和写入字段。
- 当前可视化效果已经能体现可追踪性，但 plan 文本仍受模型 prompt 影响，偶尔会显得过度自信或过度规划。

### 验证

- `npm test -- --runInBand tests/task-detail.test.tsx tests/backend-proxy.test.ts`
- `npm run build`
- 手动打开 `http://localhost:3010/tasks/task_fc1c4d34a48742c9b7785f13f497ced8` 检查 replay 面板、outline、文档高亮、对话框、plan 和 evidence chip。

### 遇到的问题

- 初版 auto timer 和动画 timer 分离，导致对话框文字可能比鼠标/高亮快一条；已改为当前 action 动画结束后再推进 index。
- 用户手动滚动文档或点击 outline 后，自动动画不能强行把视图拉回；已在用户检查时暂停 replay。
- 原始 evidence id 可读性差，已改为显示标签层转换，不影响内部定位。

### 下一步

- 后续单独调 file_extraction_agent prompt：让模型 reason 更短、更贴近当前动作，让 plan 更适合前端逐项划掉展示。
