# Backend API Draft

## 说明

这份文档只定义当前阶段后端需要提供的最小 API 结构，用来先跑通：

- 文档提交
- agent 处理
- 路由判断
- 人工复核

这里暂时不展开字段级请求体和响应体设计，先把接口职责和基本流程固定下来。

## 服务边界

在当前拆分下：

- `backend` 负责文件上传、storage 管理、数据库记录、任务状态、policy 和 review
- `agent service` 负责 OCR、预处理、抽取和字段级 route policy

其中一个关键约束是：

- `agent service` 不直接查询 `backend` 的数据库
- `agent service` 不直接管理 `backend` 的 storage
- `agent service` 只通过 `backend` 暴露的内部 API 获取任务输入和文件内容

## 调用方

这套 API 不只给前端使用，也要允许脚本直接调用。

当前可以先按两类调用方理解：

- 前端页面
- 实验脚本或批处理脚本

其中：

- 前端主要使用任务创建、任务查询和人工复核相关接口
- 脚本主要使用任务创建和任务查询接口，用于批量提交、轮询结果和实验统计

这样可以保证系统在产品原型和实验场景下复用同一条后端链路。

## API 列表

### 对前端和脚本开放的 API

### `POST /tasks`

用途：

- 接收文档和输入参数
- 创建处理任务
- 保存任务初始状态
- 调用 agent 服务开始处理

前端用途：

- 用户上传文档并发起一次新的处理任务
- 脚本批量提交任务时也可以复用这个接口

后端职责：

- 持久化原始输入
- 创建任务记录
- 调用 agent 服务
- 返回任务标识

### `GET /tasks/:task_id`

用途：

- 查询任务当前状态
- 查询当前处理阶段
- 查询是否已经产出结果
- 查询是否需要进入人工复核

前端用途：

- 在 agent 运行期间轮询任务状态
- 在处理完成后决定跳转到结果页还是 review 页
- 脚本也可以轮询这个接口获取任务状态和最终结果摘要

后端职责：

- 返回任务状态
- 返回当前阶段信息
- 返回摘要级结果信息
- 返回是否需要 review

### `GET /tasks/:task_id/review`

用途：

- 获取当前任务的人工复核数据包

前端用途：

- 当任务进入 review 状态后，拉取待复核内容并展示给用户

说明：

- 这个接口主要服务人工复核页面
- 实验脚本通常不直接调用这个接口，除非需要模拟 review 流程

后端职责：

- 返回待复核结果
- 返回 route 原因
- 返回需要展示给前端的处理上下文

### `POST /tasks/:task_id/review`

用途：

- 接收用户的人工复核结果
- 更新任务状态和最终结果
- 记录人工处理痕迹

前端用途：

- 用户在 review 页面提交审核决定

说明：

- 这个接口主要服务人工复核页面
- 如果后续实验需要代理人工审核，也可以由脚本调用

后端职责：

- 接收 review 决策
- 更新 review 记录
- 更新最终状态
- 在允许通过时写入最终数据
- 记录审计日志

### 供 Agent Service 使用的内部 API

### `GET /internal/tasks/:task_id/input`

用途：

- 给 `agent service` 提供任务输入
- 返回当前任务需要的处理参数和文档引用信息

说明：

- `agent service` 通过这个接口获取任务上下文
- 不直接读取 `backend` 数据库

### `GET /internal/documents/:document_id/file`

用途：

- 给 `agent service` 提供原始文件内容

说明：

- 文件本体由 `backend` 管理
- `agent service` 通过这个接口读取 `pdf`、`docx` 等原始文件
- 不直接访问底层 storage

### `POST /internal/tasks/:task_id/result`

用途：

- 接收 `agent service` 返回的处理结果

说明：

- `agent service` 处理完成后，将 OCR 结果、抽取结果或失败信息回传给 `backend`
- `backend` 收到结果后再进行入库、route 判断和后续状态更新

## 最小流程

### 1. 自动处理阶段

1. 前端调用 `POST /tasks` 创建任务。
2. 后端保存输入、文件和任务记录。
3. 后端调用 agent 服务开始处理。
4. agent 服务通过内部 API 获取任务输入和原始文件。
5. agent 返回处理结果给后端。
6. 后端保存 agent 输出。
7. 后端组装 `field_outputs + refs_with_text`，调用 agent service 的 route policy 接口判断 route。

### 2. 结果分流阶段

如果 route 为自动通过：

- 后端更新最终状态
- 后端写入正式数据

如果 route 为人工复核：

- 后端将任务标记为待复核
- 前端通过 `GET /tasks/:task_id` 感知该状态
- 前端再调用 `GET /tasks/:task_id/review` 获取复核内容

### 3. 人工复核阶段

1. 用户在前端完成 review。
2. 前端调用 `POST /tasks/:task_id/review` 提交结果。
3. 后端更新 review 记录、最终状态和日志。
4. 如果 review 允许通过，后端再写入正式数据。

## 脚本调用场景

为了支持实验，后端应允许脚本按同一套接口完成批量流程：

1. 脚本循环调用 `POST /tasks` 提交多份文档。
2. 脚本轮询 `GET /tasks/:task_id` 获取处理状态。
3. 对自动完成的任务直接收集结果。
4. 对进入 review 的任务，可以先统计数量，后续再决定是否由人工处理或代理规则处理。

第一版不必为了实验单独设计新接口，先保证单任务接口可以被脚本稳定调用即可。

如果后续实验规模变大，再考虑增加批量任务接口，例如：

- `POST /tasks/batch`
- `GET /tasks/batch/:batch_id`

## 建议任务状态

当前可以先保留一组简单状态：

- `pending`
- `processing`
- `completed`
- `waiting_review`
- `failed`

如果后续需要，再细分内部阶段状态。

## 设计原则

- agent 原始输出和最终入库结果分开保存
- review 结果不直接覆盖 agent 原始输出
- 前端只通过后端 API 获取任务、结果和 review 数据
- `agent service` 只通过内部 API 获取任务输入和文件，不直接查库
- 先保证最小闭环可跑通，再继续扩展接口细节
