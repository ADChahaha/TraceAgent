import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { TaskDetail } from "@/components/task-detail";
import type { TaskDetailData, TaskSummary } from "@/lib/types";

const waitingReviewSummary: TaskSummary = {
  task_id: "task-001",
  status: "waiting_review",
  stage: "review",
  route: "review",
  route_reason: "关键字段证据较弱，需要人工确认",
  has_result: true,
  has_trace: true,
  needs_review: true
};

const agentEvidence = {
  status: "model_resolved",
  notes: ["broad evidence 命中文明寝室表格"],
  texts: [
    "### 文明寝室名单\n\n| 房间 | 结论 | | --- | --- | | 1-101 | 通过 | | 1-102 | **文明寝室** |"
  ],
  refs: [{ document_id: "doc-1", page: 2, block_id: "doc-1:p2:b3" }]
};

const agentActions = [
  {
    action_type: "field_reference",
    message: "模型请求参考字段 building",
    used_in_final_decision: false,
    metadata: { requested_field_name: "building", returned_to_model: true }
  },
  {
    action_type: "global_lookup",
    message: "补查文明寝室名单",
    used_in_final_decision: true,
    metadata: { lookup_hints: ["文明寝室"], returned_block_ids: ["doc-1:p2:b3"] }
  },
  {
    action_type: "validation_rule",
    message: "校正房间号列表",
    used_in_final_decision: true
  }
];

const agentProcess = {
  field_name: "room_numbers",
  status: "resolved",
  value: "1-101,1-102",
  evidence: agentEvidence,
  related_fields: ["building"],
  actions: agentActions,
  process_steps: [
    {
      stage: "broad_extraction",
      title: "第一步 broad extraction",
      status: "model_resolved",
      evidence: agentEvidence
    },
    {
      stage: "field_resolution",
      title: "第二步 resolution / tool",
      status: "used",
      related_fields: ["building"],
      actions: agentActions
    },
    {
      stage: "final_result",
      title: "第三步 final result",
      status: "resolved",
      value: "1-101,1-102",
      reason: "模型定案后经过规则校正",
      failure_reason: null
    }
  ],
  reason: "模型定案后经过规则校正",
  failure_reason: null
};

const detailData: TaskDetailData = {
  summary: waitingReviewSummary,
  result: {
    task_id: "task-001",
    status: "waiting_review",
    route: "review",
    fields: [
      {
        field_name: "room_numbers",
        display_name: "文明寝室房间号",
        agent_value: "1-101,1-102",
        review_value: null,
        final_value: null,
        field_status: "resolved",
        route: "review",
        source: null,
        committed: false
      }
    ]
  },
  trace: {
    task_id: "task-001",
    agent_status: "completed",
    steps: [
      {
        stage: "document_processing",
        agent: "document_processor",
        status: "completed",
        summary: {
          document_count: 2,
          block_count: 2,
          warning_count: 0
        },
        documents: [
          {
            document_id: "doc-1",
            filename: "sample.pdf",
            file_type: "pdf",
            block_count: 1
          },
          {
            document_id: "doc-2",
            filename: "supplement.docx",
            file_type: "docx",
            block_count: 1
          }
        ]
      },
      {
        stage: "extraction",
        agent: "file_extraction_agent",
        status: "completed",
        summary: {
          field_count: 1,
          resolved_count: 1,
          failed_count: 0,
          warning_count: 0
        },
        field_decisions: [agentProcess]
      },
      {
        stage: "route_policy",
        agent: "route_policy_agent",
        status: "completed",
        summary: {
          field_count: 1,
          routes: {
            accept: 0,
            review: 1,
            reject: 0
          }
        },
        routes: [
          {
            field_name: "room_numbers",
            route: "review",
            needs_review: true,
            route_reason: "关键字段证据较弱，需要人工确认"
          }
        ]
      }
    ],
    agent_trace: [
      {
        id: "stage-run-1",
        sequence: 1,
        stage: "document_processing",
        agent: "document_processor",
        status: "completed",
        request: {
          filename: "sample.pdf",
          file_type: "pdf",
          upload_size_bytes: 12
        },
        response: {
          markdown: "1-101、1-102 被列为文明寝室"
        },
        trace: {
          warnings: []
        }
      },
      {
        id: "stage-run-2",
        sequence: 2,
        stage: "extraction",
        agent: "file_extraction_agent",
        status: "completed",
        request: {
          task_spec: { task_name: "civilized_dormitory" },
          metadata: { document_ids: ["doc-1"] }
        },
        response: {
          trace: { fields: [{ field_name: "room_numbers" }] }
        },
        trace: {
          fields: [{ field_name: "room_numbers" }]
        }
      }
    ],
    fields: [
      {
        field_name: "room_numbers",
        status: "resolved",
        evidence: {
          texts: [
            "### 文明寝室名单\n\n| 房间 | 结论 | | --- | --- | | 1-101 | 通过 | | 1-102 | **文明寝室** |"
          ],
          refs: [{ document_id: "doc-1", page: 2, block_id: "doc-1:p2:b3" }]
        },
        actions: agentProcess.actions,
        reason: "模型定案后经过规则校正"
      }
    ]
  },
  review: {
    task_id: "task-001",
    status: "waiting_review",
    route: "review",
    route_reason: "关键字段证据较弱，需要人工确认",
    fields: [
      {
        field_name: "room_numbers",
        display_name: "文明寝室房间号",
        agent_value: "1-101,1-102",
        field_status: "resolved",
        needs_review: true,
        review_reason: "字段需要人工确认",
        evidence_texts: [
          "### 文明寝室名单\n\n| 房间 | 结论 | | --- | --- | | 1-101 | 通过 | | 1-102 | **文明寝室** |"
        ],
        evidence_refs: [{ document_id: "doc-1", page: 2, block_id: "doc-1:p2:b3" }],
        actions: ["field_reference", "global_lookup", "validation_rule"],
        reason: "模型定案后经过规则校正",
        agent_process: agentProcess
      }
    ]
  },
  audit: {
    task_id: "task-001",
    status: "waiting_review",
    field_commits: []
  }
};

it("waiting_review 任务会展示证据并提交 revise_and_approve 后刷新详情", async () => {
  const user = userEvent.setup();
  window.localStorage.clear();
  window.localStorage.setItem(
    "agent-gate.recent-tasks",
    JSON.stringify([
      {
        task_id: "task-001",
        status: "waiting_review",
        stage: "review",
        created_at: "2026-04-29T08:00:00Z"
      }
    ])
  );
  const refreshedSummary: TaskSummary = {
    ...waitingReviewSummary,
    status: "completed",
    stage: "done",
    needs_review: false
  };
  const completedDetail: TaskDetailData = {
    ...detailData,
    summary: refreshedSummary,
    result: detailData.result
      ? {
          ...detailData.result,
          status: "completed",
          fields: detailData.result.fields.map((field) => ({
            ...field,
            final_value: "1-101,1-102,1-103",
            source: "human",
            committed: true
          }))
        }
      : null,
    review: null,
    audit: {
      task_id: "task-001",
      status: "completed",
      field_commits: []
    }
  };
  const loadTaskDetail = jest
    .fn<Promise<TaskDetailData>, [string]>()
    .mockResolvedValueOnce(detailData)
    .mockResolvedValueOnce(completedDetail);
  const submitReview = jest.fn(async () => refreshedSummary);

  render(
    <TaskDetail
      taskId="task-001"
      initialSummary={waitingReviewSummary}
      loadTaskDetail={loadTaskDetail}
      submitReview={submitReview}
    />
  );

  expect(await screen.findByRole("heading", { name: "文明寝室名单" })).toBeInTheDocument();
  expect(screen.getByRole("table")).toBeInTheDocument();
  expect(screen.getAllByText("文明寝室房间号").length).toBeGreaterThan(0);
  expect(screen.queryByText("room_numbers")).not.toBeInTheDocument();
  expect(screen.getByText("1-101")).toBeInTheDocument();
  expect(screen.getByText("1-102")).toBeInTheDocument();
  expect(screen.getByText("文明寝室")).toBeInTheDocument();
  expect(screen.getByText("Agent 决策过程")).toBeInTheDocument();
  expect(screen.getByText("第一步 broad extraction")).toBeInTheDocument();
  expect(screen.getByText("第二步 resolution / tool")).toBeInTheDocument();
  expect(screen.getByText("第三步 final result")).toBeInTheDocument();
  expect(screen.getByText("模型请求参考字段 building")).toBeInTheDocument();
  expect(screen.getByText("补查文明寝室名单")).toBeInTheDocument();
  expect(screen.queryByText("### 文明寝室名单")).not.toBeInTheDocument();
  expect(screen.queryByText("| 房间 | 结论 |")).not.toBeInTheDocument();

  await user.click(screen.getByRole("tab", { name: "证据" }));
  expect(screen.getByText("Agent 执行过程")).toBeInTheDocument();
  expect(screen.getByText("字段决策过程")).toBeInTheDocument();
  expect(screen.getAllByText("第一步 broad extraction").length).toBeGreaterThan(0);
  expect(screen.getAllByText("第二步 resolution / tool").length).toBeGreaterThan(0);
  expect(screen.getAllByText("第三步 final result").length).toBeGreaterThan(0);
  expect(screen.getByText("document_processor")).toBeInTheDocument();
  expect(screen.getByText("file_extraction_agent")).toBeInTheDocument();
  expect(screen.getByText("route_policy_agent")).toBeInTheDocument();
  expect(screen.getByText("sample.pdf")).toBeInTheDocument();
  expect(screen.getByText("supplement.docx")).toBeInTheDocument();
  expect(screen.getByText("review: 1")).toBeInTheDocument();
  expect(screen.getAllByText("validation_rule").length).toBeGreaterThan(0);
  expect(screen.getByText("Agent 原始 trace")).toBeInTheDocument();
  expect(screen.getByText("document_processor / document_processing")).toBeInTheDocument();
  expect(screen.getByText("file_extraction_agent / extraction")).toBeInTheDocument();
  expect(screen.getByText("request: filename, file_type, upload_size_bytes")).toBeInTheDocument();
  expect(screen.getByText("response: markdown")).toBeInTheDocument();

  await user.click(screen.getByRole("tab", { name: "复核" }));
  await user.clear(screen.getByLabelText("文明寝室房间号 复核值"));
  await user.type(screen.getByLabelText("文明寝室房间号 复核值"), "1-101,1-102,1-103");
  await user.type(screen.getByLabelText("复核备注"), "人工补充遗漏房间");
  await user.click(screen.getByRole("button", { name: "提交修正并通过" }));

  await waitFor(() => expect(submitReview).toHaveBeenCalledTimes(1));
  expect(submitReview).toHaveBeenCalledWith("task-001", {
    decision: "revise_and_approve",
    fields: [
      {
        field_name: "room_numbers",
        review_value: "1-101,1-102,1-103"
      }
    ],
    comment: "人工补充遗漏房间",
    reviewer: "frontend"
  });
  await waitFor(() => expect(loadTaskDetail).toHaveBeenCalledTimes(2));
  const recentTasks = JSON.parse(window.localStorage.getItem("agent-gate.recent-tasks") ?? "[]");
  expect(recentTasks[0]).toMatchObject({
    task_id: "task-001",
    status: "completed",
    stage: "done"
  });
  expect(recentTasks[0].created_at).toBe("2026-04-29T08:00:00Z");
});

it("审计记录会展示字段提交对应的 agent 决策过程", async () => {
  const user = userEvent.setup();
  const completedSummary: TaskSummary = {
    ...waitingReviewSummary,
    status: "completed",
    stage: "done",
    route: "accept",
    needs_review: false
  };
  const loadTaskDetail = jest.fn(async (): Promise<TaskDetailData> => ({
    summary: completedSummary,
    result: {
      task_id: "task-001",
      status: "completed",
      route: "accept",
      fields: [
        {
          field_name: "room_numbers",
          display_name: "文明寝室房间号",
          agent_value: "1-101,1-102",
          review_value: null,
          final_value: "1-101,1-102",
          field_status: "resolved",
          route: "accept",
          source: "agent",
          committed: true
        }
      ]
    },
    trace: null,
    review: null,
    audit: {
      task_id: "task-001",
      status: "completed",
      field_commits: [
        {
          field_name: "room_numbers",
          final_value: "1-101,1-102",
          route: "accept",
          reviewed: false,
          review_decision: null,
          agent_value: "1-101,1-102",
          review_value: null,
          evidence_refs: [{ document_id: "doc-1", page: 2, block_id: "doc-1:p2:b3" }],
          used_global_lookup: true,
          used_validation_rule: true,
          related_fields: ["building"],
          committed_by: "agent",
          committed_at: "2026-04-29T08:00:00Z",
          agent_process: agentProcess
        }
      ]
    }
  }));

  render(
    <TaskDetail
      taskId="task-001"
      initialSummary={completedSummary}
      loadTaskDetail={loadTaskDetail}
    />
  );

  await screen.findByText("completed");
  await user.click(screen.getByRole("tab", { name: "审计" }));

  expect(screen.getAllByText("文明寝室房间号").length).toBeGreaterThan(0);
  expect(screen.queryByText("room_numbers")).not.toBeInTheDocument();
  expect(screen.getByText("Agent 决策过程")).toBeInTheDocument();
  expect(screen.getByText("模型请求参考字段 building")).toBeInTheDocument();
  expect(screen.getByText("补查文明寝室名单")).toBeInTheDocument();
});
