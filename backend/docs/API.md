# Backend API 设计

这份文档定义毕业设计原型阶段 `backend` 对前端和实验脚本暴露的 API。后端负责上传、任务状态、route 输出保存、人工审核、最终结果和审计；`agent service` 负责文档标准化、字段抽取和字段级 route policy，不直接写库。

## 基本链路

后端 API 围绕一次文档治理任务展开：

```text
前端或脚本上传一个或多个 PDF / DOCX 和任务参数
  -> POST /tasks 创建任务
  -> 后端逐个调用 document_processor，把上传文件转成 markdown + blocks
  -> 后端为每个文件保存 markdown / blocks，不保存用户上传的原始文件
  -> 后端合并多个文件的 markdown、md_list 和 blocks
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
- `trace` 表示 Agent 执行层如何得到字段结果，包括三段 agent 执行过程、证据、定位、补查、validation action 和失败原因。
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

- `files`：必填，上传的一个或多个 PDF / DOCX；multipart 中可以重复传入多个 `files` 字段。
- `task_type`：必填，调用方定义的任务类型标识，例如 `civilized_dormitory`。
- `task_spec`：必填，显式字段 schema；后端不提供默认 task spec，也不按 `task_type` 兜底选择 schema。
- `metadata`：可选，前端或脚本传入的补充信息。

兼容说明：旧版单文件字段名 `file` 仍可使用；新版前端应统一使用重复 `files` 字段。

请求示例：

```bash
curl -X POST "http://localhost:8000/tasks" \
  -F "files=@sample.pdf" \
  -F "files=@supplement.docx" \
  -F "task_type=civilized_dormitory" \
  -F 'task_spec={"task_name":"civilized_dormitory","fields":[{"field_name":"room_numbers","display_name":"文明寝室房间号","type":"string","required":true,"critical":true}]}'
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
上传一个或多个 files、task_type、task_spec 和 metadata
  -> 校验至少存在一个文件，逐个从 filename 推断 pdf/docx
  -> 校验 task_spec 必须是 JSON object
  -> 创建 task 记录，状态设为 pending / uploaded
  -> 在当前请求中读取每个上传文件 bytes
  -> 对每个文件调用 document_processor 生成 markdown、md_list 和 blocks
  -> 每个文件生成一个 document_id 并保存标准化结果，不保存原始文件
  -> 合并所有文件的 markdown、md_list 和 blocks
  -> 调用 file_extraction_agent，并在 metadata 中传入 document_ids
  -> 保存 result 和 trace
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
`needs_review` 以任务当前 `status` 为准：只有 `status=waiting_review` 时才为 `true`；人工复核提交后即使历史 route 仍为 `review`，任务 summary 也会返回 `completed / done / needs_review=false`。

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
  "steps": [
    {
      "stage": "document_processing",
      "agent": "document_processor",
      "status": "completed",
      "started_at": "2026-04-28T10:00:01Z",
      "finished_at": "2026-04-28T10:00:08Z",
      "summary": {
        "document_count": 2,
        "block_count": 24,
        "warning_count": 0
      },
      "documents": [
        {
          "document_id": "doc-1",
          "filename": "sample.pdf",
          "file_type": "pdf",
          "block_count": 12,
          "markdown_chars": 3200,
          "warning_count": 0
        },
        {
          "document_id": "doc-2",
          "filename": "supplement.docx",
          "file_type": "docx",
          "block_count": 12,
          "markdown_chars": 2800,
          "warning_count": 0
        }
      ]
    },
    {
      "stage": "extraction",
      "agent": "file_extraction_agent",
      "status": "completed",
      "started_at": "2026-04-28T10:00:08Z",
      "finished_at": "2026-04-28T10:00:20Z",
      "failure_reason": null,
      "summary": {
        "field_count": 1,
        "resolved_count": 1,
        "failed_count": 0,
        "warning_count": 0
      },
      "field_decisions": [
        {
          "field_name": "room_numbers",
          "status": "resolved",
          "value": "1-101,1-102",
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
              "action_type": "global_lookup",
              "message": "补查文明寝室名单",
              "used_in_final_decision": true,
              "metadata": {
                "lookup_hints": ["文明寝室"],
                "returned_block_ids": ["doc-1:p2:b3"]
              }
            },
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
      "warnings": [],
      "metadata": {}
    },
    {
      "stage": "route_policy",
      "agent": "route_policy_agent",
      "status": "completed",
      "started_at": "2026-04-28T10:00:20Z",
      "finished_at": "2026-04-28T10:00:21Z",
      "summary": {
        "field_count": 1,
        "routes": {
          "accept": 0,
          "review": 1,
          "reject": 0
        }
      },
      "routes": [
        {
          "field_name": "room_numbers",
          "route": "review",
          "needs_review": true,
          "route_reason": "关键字段证据较弱，需要人工确认"
        }
      ]
    }
  ],
  "agent_trace": [
    {
      "id": "stage_run_001",
      "sequence": 1,
      "stage": "document_processing",
      "agent": "document_processor",
      "status": "completed",
      "failure_reason": null,
      "request": {
        "document_id": "doc-1",
        "filename": "sample.pdf",
        "file_type": "pdf",
        "content_type": "application/pdf",
        "upload_size_bytes": 20480,
        "upload_sha256": "..."
      },
      "response": {
        "markdown": "1-101、1-102 被列为文明寝室",
        "md_list": ["1-101、1-102 被列为文明寝室"],
        "blocks": []
      },
      "trace": {
        "meta_info": {},
        "warnings": []
      },
      "started_at": "2026-04-28T10:00:01Z",
      "finished_at": "2026-04-28T10:00:08Z"
    }
  ],
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

`steps` 按 backend 实际调用顺序返回：

```text
documents 表中的标准化结果
  -> document_processor 步骤，返回每个文件的 filename/file_type/block_count/warning_count
  -> agent_runs 中的 result_json/trace_json
  -> file_extraction_agent 步骤，返回字段数、resolved/failed 统计、warning 数和 field_decisions
  -> field_routes 表中的 route 结果
  -> route_policy_agent 步骤，返回 accept/review/reject 计数和每个字段的 route_reason
```

`field_decisions` 来自 `agent_runs.trace_json` 和 `agent_runs.result_json`，用于把 file_extraction_agent 的字段定案过程透给前端。它包含字段值、证据摘要、跨字段参考、global lookup、validation rule、reason、failure_reason 和 `process_steps`。当前 agent 契约不保存 raw prompt 或 raw model response，因此 backend 也不会在 trace 中伪造这类原始内容。

`process_steps` 是 backend 从现有字段 trace 派生的展示链路，不新增数据库字段：

```text
field evidence + actions + agent value
  -> broad_extraction：候选证据 block、文本、refs 和 notes
  -> field_resolution：field_reference / global_lookup / validation_rule 等动作
  -> final_result：最终 status、agent value、reason 或 failure_reason
```

`agent_trace` 来自 `agent_stage_runs`，按每次 HTTP 调用单独保存并返回：

```text
document_processor 每个文件一次记录
  -> request 保存 document_id、filename、file_type、content_type、upload_size_bytes、upload_sha256，不保存 file_bytes
  -> response 保存 agent service 返回的完整 JSON
  -> trace 保存 response.trace；没有 trace 时保存 meta_info/warnings

file_extraction_agent 一次记录
  -> request 保存 blocks、markdown、md_list、task_spec、metadata、run_options
  -> response 保存 ExtractionResult 完整 JSON
  -> trace 保存 ExtractionResult.trace

route_policy_agent 一次记录
  -> request 保存 task_spec、field_outputs、refs_with_text、metadata、policy_options
  -> response 保存 RoutePolicyResult 完整 JSON
  -> trace 保存 response.trace；没有 trace 时保存 field_routes/warnings/metadata 摘要
```

`trace.steps` 是给工作台展示的摘要视图；`agent_trace` 是更接近原始 agent 调用过程的调试视图。两者都只包含 agent service 已经返回给 backend 的内容，不包含 agent service 未暴露的 raw prompt 或 raw model response。

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
      "failure_reason": null,
      "agent_process": {
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
            "action_type": "global_lookup",
            "message": "补查文明寝室名单",
            "used_in_final_decision": true,
            "metadata": {
              "lookup_hints": ["文明寝室"],
              "returned_block_ids": ["doc-1:p2:b3"]
            }
          }
        ],
        "reason": "模型定案后经过表格规则校正",
        "failure_reason": null
      }
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
  -> 合并字段值、证据、定位、route 原因和 agent_process
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
      "committed_at": "2026-04-28T10:05:00Z",
      "agent_process": {
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
            "action_type": "global_lookup",
            "message": "补查文明寝室名单",
            "used_in_final_decision": true,
            "metadata": {
              "lookup_hints": ["文明寝室"],
              "returned_block_ids": ["doc-1:p2:b3"]
            }
          }
        ],
        "reason": "模型定案后经过表格规则校正",
        "failure_reason": null
      }
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
  "task_types": [],
  "routes": ["accept", "review", "reject"],
  "review_decisions": ["approve", "revise_and_approve", "reject"],
  "features": {
    "trace": true,
    "review": true,
    "audit": true,
    "external_task_spec": true,
    "multiple_files": true
  }
}
```

## 错误语义

第一版保持简单：

- 请求体或文件缺失：FastAPI 参数校验返回 `422`
- 文件类型不支持、`task_spec` 缺失或 JSON 非法：`422`
- `task_id` 不存在：`404`
- 当前任务状态不允许执行该操作：`409`
- agent HTTP 调用或后端流程异常：`502`，如果任务已经创建则同步更新为 `failed / done`

如果 agent 本身返回 `ExtractionResult.status="failed"` 或 route policy 返回失败状态，后端保存失败结果并让任务进入 `failed / done`。
