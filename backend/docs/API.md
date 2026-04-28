# Backend API 设计

这份文档定义毕业设计原型阶段 `backend` 对前端和实验脚本暴露的 API。后端负责上传、任务状态、route 输出保存、人工审核、最终结果和审计；`agent service` 负责文档标准化、字段抽取和字段级 route policy，不直接写库。

## 基本链路

后端 API 围绕一次文档治理任务展开：

```text
前端或脚本上传 PDF / DOCX 和任务参数
  -> POST /tasks 创建任务
  -> 后端调用 document_processor，把上传文件转成 markdown + blocks
  -> 后端保存 markdown / blocks，不保存用户上传的原始文件
  -> 后端调用 file_extraction_agent 执行字段抽取
  -> agent 返回 ExtractionResult(result + trace)
  -> 后端组装 field_outputs + refs_with_text 并调用 route_policy_agent
  -> agent 返回 accept / review / reject 字段路由
  -> 如果 route=accept，生成最终字段结果和审计记录
  -> 如果 route=review，生成人工审核 handoff 包
  -> 人工审核提交 approve / revise_and_approve / reject
  -> 后端更新最终 result、任务状态和 audit
```

这里的核心边界是：

- `result` 表示后端治理后的最终字段结果，可以包含 agent 原值、人工修正值和最终值。
- `trace` 表示 Agent 执行层如何得到字段结果，包括证据、定位、补查、validation action 和失败原因。
- `review` 表示人工审核需要接管的信息包和人工提交的处理结论。
- `audit` 表示字段最终进入或未进入正式数据区的责任链路。

## API 列表

```text
POST /tasks
GET  /tasks/:task_id
GET  /tasks/:task_id/result
GET  /tasks/:task_id/trace
GET  /tasks/:task_id/review
POST /tasks/:task_id/review
GET  /tasks/:task_id/audit
GET  /capabilities
```

## 通用状态

任务状态 `status`：

```text
pending
processing
waiting_review
completed
rejected
failed
```

处理阶段 `stage`：

```text
uploaded
document_processing
extraction
route_policy
review
field_commit
done
```

route 决策 `route`：

```text
accept
review
reject
```

`route` 由 agent service 的 `route_policy_agent` 给出。backend 只提交任务/字段定义、字段输出和 `refs_with_text`，然后保存 `accept / review / reject` 输出并驱动状态流转。

人工审核结论 `review_decision`：

```text
approve
revise_and_approve
reject
```

## `POST /tasks`

创建一次文档治理任务。

请求类型建议使用 `multipart/form-data`：

- `file`：必填，上传的 PDF 或 DOCX。
- `task_type`：必填，任务类型，例如 `civilized_dormitory`。
- `task_spec`：可选，显式字段 schema；如果省略，后端按 `task_type` 选择默认 schema。
- `metadata`：可选，前端或脚本传入的补充信息。

请求示例：

```bash
curl -X POST "http://localhost:8000/tasks" \
  -F "file=@sample.pdf" \
  -F "task_type=civilized_dormitory"
```

响应示例：

```json
{
  "task_id": "task-001",
  "status": "completed",
  "stage": "done"
}
```

处理步骤：

```text
上传文件和任务参数
  -> 校验文件类型和任务类型
  -> 创建 task 记录，状态设为 pending / uploaded
  -> 在当前请求中读取上传文件 bytes，调用 document_processor 生成 markdown、md_list 和 blocks
  -> 保存文档标准化结果并生成 document_id，不保存原始文件
  -> 调用 file_extraction_agent，保存 result 和 trace
  -> 组装 field_outputs + refs_with_text 并调用 route_policy_agent
  -> 按 route 写入 final result、review 状态或 reject / failed 状态
  -> 返回 task_id 和当前 status/stage
```

第一版为同步处理模型，`POST /tasks` 会在同一个请求内完成 document processing、extraction 和 route policy。响应中的 `status/stage` 可能是：

- `completed / done`：字段已自动通过并写入 audit。
- `waiting_review / review`：至少一个字段需要人工复核。
- `rejected / done`：route policy 拒绝任务。
- `failed / done`：agent 调用或后端流程失败。

## `GET /tasks/:task_id`

查询任务当前状态和 route 摘要。这个接口用于前端轮询，不返回完整 result 或 trace。

响应示例：

```json
{
  "task_id": "task-001",
  "status": "waiting_review",
  "stage": "review",
  "route": "review",
  "route_reason": "关键字段经过补查后定案，需要人工确认",
  "has_result": true,
  "has_trace": true,
  "needs_review": true,
  "created_at": "2026-04-28T10:00:00Z",
  "updated_at": "2026-04-28T10:02:30Z"
}
```

## `GET /tasks/:task_id/result`

查询后端治理后的最终字段结果。

响应示例：

```json
{
  "task_id": "task-001",
  "status": "completed",
  "route": "accept",
  "fields": [
    {
      "field_name": "room_numbers",
      "display_name": "文明寝室房间号",
      "agent_value": "1-101,1-102",
      "review_value": null,
      "final_value": "1-101,1-102",
      "field_status": "resolved",
      "route": "accept",
      "source": "agent",
      "committed": true
    }
  ]
}
```

字段说明：

- `agent_value`：Agent 原始定案值。
- `review_value`：人工审核修正值；未人工修正时为 `null`。
- `final_value`：最终用于展示或写库的字段值。
- `source`：最终值来源，建议使用 `agent` 或 `human`。
- `committed`：该字段是否已经进入最终提交记录。

## `GET /tasks/:task_id/trace`

查询 Agent 执行层 trace，用于证据高亮、调试和论文展示。

响应示例：

```json
{
  "task_id": "task-001",
  "agent_status": "completed",
  "failure_reason": null,
  "fields": [
    {
      "field_name": "room_numbers",
      "status": "resolved",
      "evidence": {
        "block_ids": ["doc-1:p2:b3"],
        "texts": ["1-101、1-102 被列为文明寝室"],
        "refs": [
          {
            "document_id": "doc-1",
            "page": 2,
            "block_id": "doc-1:p2:b3"
          }
        ],
        "status": "model_resolved",
        "notes": ["按模型 used_block_ids 绑定证据"]
      },
      "related_fields": ["building"],
      "actions": [
        {
          "action_type": "validation_rule",
          "message": "按表格规则校正房间号列表",
          "used_in_final_decision": true
        }
      ],
      "reason": "模型定案后经过规则校正",
      "failure_reason": null
    }
  ],
  "metadata": {
    "failure_stage": null
  }
}
```

## `GET /tasks/:task_id/review`

获取人工审核 handoff 包。只有任务进入 `waiting_review` 时才需要调用。

响应示例：

```json
{
  "task_id": "task-001",
  "status": "waiting_review",
  "route": "review",
  "route_reason": "关键字段证据较弱，需要人工确认",
  "fields": [
    {
      "field_name": "room_numbers",
      "display_name": "文明寝室房间号",
      "agent_value": "1-101,1-102",
      "field_status": "resolved",
      "needs_review": true,
      "review_reason": "字段经过 global_lookup 后才定案",
      "evidence_texts": ["1-101、1-102 被列为文明寝室"],
      "evidence_refs": [
        {
          "document_id": "doc-1",
          "page": 2,
          "block_id": "doc-1:p2:b3"
        }
      ],
      "related_fields": ["building"],
      "actions": ["global_lookup", "validation_rule"],
      "reason": "模型定案后经过表格规则校正",
      "failure_reason": null
    }
  ]
}
```

处理步骤：

```text
task_id
  -> 读取 agent result + trace
  -> 读取 route policy 输出
  -> 只挑出需要人工接管或需要展示的字段
  -> 合并字段值、证据、定位和 route 原因
  -> 返回人工审核信息包
```

## `POST /tasks/:task_id/review`

提交人工审核结果。

请求示例：

```json
{
  "decision": "revise_and_approve",
  "fields": [
    {
      "field_name": "room_numbers",
      "review_value": "1-101,1-102,1-103"
    }
  ],
  "comment": "人工根据原文补充一个遗漏房间"
}
```

响应示例：

```json
{
  "task_id": "task-001",
  "status": "completed",
  "stage": "done",
  "review_decision": "revise_and_approve"
}
```

处理步骤：

```text
人工提交 decision、字段修正值和备注
  -> 校验任务必须处于 waiting_review
  -> 如果 decision=approve，沿用 agent_value 作为 final_value
  -> 如果 decision=revise_and_approve，使用 review_value 作为 final_value
  -> 如果 decision=reject，任务进入 rejected，不写入最终字段提交
  -> 记录人工处理痕迹
  -> 更新 result 和 audit
```

## `GET /tasks/:task_id/audit`

查询字段级提交与责任链路。这个接口用于论文中的可追责展示，也用于排查“某个字段为什么最终这样写入”。

响应示例：

```json
{
  "task_id": "task-001",
  "status": "completed",
  "field_commits": [
    {
      "field_name": "room_numbers",
      "final_value": "1-101,1-102,1-103",
      "route": "review",
      "reviewed": true,
      "review_decision": "revise_and_approve",
      "agent_value": "1-101,1-102",
      "review_value": "1-101,1-102,1-103",
      "evidence_refs": [
        {
          "document_id": "doc-1",
          "page": 2,
          "block_id": "doc-1:p2:b3"
        }
      ],
      "used_global_lookup": true,
      "used_validation_rule": true,
      "related_fields": ["building"],
      "committed_by": "human",
      "committed_at": "2026-04-28T10:05:00Z"
    }
  ]
}
```

## `GET /capabilities`

查询系统能力边界，供前端上传页和实验脚本使用。

响应示例：

```json
{
  "supported_file_types": ["pdf", "docx"],
  "task_types": [
    {
      "task_type": "civilized_dormitory",
      "display_name": "文明寝室通知抽取",
      "fields": [
        {
          "field_name": "room_numbers",
          "display_name": "文明寝室房间号",
          "type": "string",
          "required": true,
          "critical": true
        }
      ]
    }
  ],
  "routes": ["accept", "review", "reject"],
  "review_decisions": ["approve", "revise_and_approve", "reject"],
  "features": {
    "trace": true,
    "review": true,
    "audit": true
  }
}
```

## 错误语义

第一版保持简单：

- 请求体或文件缺失：FastAPI 参数校验返回 `422`
- 文件类型或任务类型不支持：`422`
- `task_id` 不存在：`404`
- 当前任务状态不允许执行该操作：`409`
- agent HTTP 调用或后端流程异常：`502`，如果任务已经创建则同步更新为 `failed / done`

如果 agent 本身返回 `ExtractionResult.status="failed"` 或 route policy 返回失败状态，后端保存失败结果并让任务进入 `failed / done`。
