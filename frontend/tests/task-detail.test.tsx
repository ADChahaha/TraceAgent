import { render, screen, waitFor, within } from "@testing-library/react";
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
  status: "candidate_resolved",
  notes: ["field decision referenced candidate_ids: c1"],
  texts: [
    "### 文明寝室名单\n\n| 房间 | 结论 | | --- | --- | | 1-101 | 通过 | | 1-102 | **文明寝室** |"
  ],
  blocks: [
    {
      document_id: "doc-1",
      block_id: "candidate-block-id-should-not-render",
      page: 2,
      text: "### 候选 block 原文\n\n| 房间 | 结论 | | --- | --- | | 1-101 | 通过 | | 1-102 | **文明寝室** |",
      kind: "text"
    }
  ],
  refs: [{ document_id: "doc-1", page: 2, block_id: "candidate-block-id-should-not-render" }]
};

const agentActions = [
  {
    action_type: "search_grep",
    message: "文明寝室 OR 房间号",
    used_in_final_decision: false,
    refs: [{ document_id: "doc-1", page: 2, span: "p:p1", block_id: "candidate-block-id-should-not-render" }],
    metadata: { stage: "broad", refs: ["doc-1:p2:b3:p:p1"] }
  },
  {
    action_type: "add_broad_candidate",
    message: "召回文明寝室房间号候选",
    used_in_final_decision: true,
    refs: [{ document_id: "doc-1", page: 2, span: "p:p1", block_id: "candidate-block-id-should-not-render" }],
    metadata: { stage: "broad", candidate_ids: ["c1"], refs: ["doc-1:p2:b3:p:p1"] }
  },
  {
    action_type: "finish_broad",
    message: "候选足够，结束 broad",
    used_in_final_decision: false,
    refs: [],
    metadata: { stage: "broad", candidate_ids: [], refs: [] }
  },
  {
    action_type: "final_decision",
    message: "候选证据支持字段值",
    used_in_final_decision: true,
    refs: [{ document_id: "doc-1", page: 2, span: "p:p1", block_id: "candidate-block-id-should-not-render" }],
    metadata: { stage: "resolution", candidate_ids: ["c1"], refs: ["doc-1:p2:b3:p:p1"] }
  }
];

const agentProcess = {
  field_name: "room_numbers",
  status: "resolved",
  value: "1-101,1-102",
  evidence: agentEvidence,
  related_fields: [],
  actions: agentActions,
  process_steps: [
    {
      stage: "broad_extraction",
      title: "第一步 broad extraction",
      status: "candidate_resolved",
      evidence: agentEvidence,
      actions: [agentActions[0], agentActions[1], agentActions[2]]
    },
    {
      stage: "field_resolution",
      title: "第二步 resolution / tool",
      status: "used",
      related_fields: [],
      output_fields: [
        {
          field_name: "room_numbers",
          status: "resolved",
          value: "1-101,1-102",
          reason: "候选证据支持字段值"
        }
      ],
      notes: [
        "执行 final_decision：候选证据支持字段值，参与最终定案。"
      ],
      actions: [agentActions[3]]
    },
    {
      stage: "final_result",
      title: "第三步 agent result（route 前）",
      status: "resolved",
      value: "1-101,1-102",
      reason: "候选证据支持字段值",
      failure_reason: null
    },
    {
      stage: "route_validation",
      title: "第四步 route validation",
      status: "review",
      route: "review",
      needs_review: true,
      reason: "关键字段证据较弱，需要人工确认",
      notes: ["route_policy_agent 判定该字段需要人工复核。"]
    }
  ],
  reason: "候选证据支持字段值",
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
        reason: "候选证据支持字段值"
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
        actions: ["search_grep", "add_broad_candidate", "finish_broad", "final_decision"],
        reason: "候选证据支持字段值",
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
  expect(screen.getAllByRole("table").length).toBeGreaterThan(0);
  expect(screen.getAllByText("文明寝室房间号").length).toBeGreaterThan(0);
  expect(screen.queryByText("room_numbers")).not.toBeInTheDocument();
  expect(screen.getAllByText("1-101").length).toBeGreaterThan(0);
  expect(screen.getAllByText("1-102").length).toBeGreaterThan(0);
  expect(screen.getAllByText("文明寝室").length).toBeGreaterThan(0);
  const reviewEvidenceSummary = screen.getByText("证据文本（1）");
  const reviewEvidenceDetails = reviewEvidenceSummary.closest("details");
  expect(reviewEvidenceDetails).not.toBeNull();
  expect(reviewEvidenceDetails).not.toHaveAttribute("open");
  await user.click(reviewEvidenceSummary);
  expect(reviewEvidenceDetails).toHaveAttribute("open");
  expect(screen.getByText("Agent 决策过程")).toBeInTheDocument();
  expect(screen.getByText("第一步 broad extraction")).toBeInTheDocument();
  expect(screen.getAllByText("候选 blocks（1）").length).toBeGreaterThan(0);
  expect(screen.getAllByRole("heading", { name: "候选 block 原文" }).length).toBeGreaterThan(0);
  expect(screen.queryByText("candidate-block-id-should-not-render")).not.toBeInTheDocument();
  expect(screen.getByText("第二步 resolution / tool")).toBeInTheDocument();
  expect(screen.getByText("第三步 agent result（route 前）")).toBeInTheDocument();
  expect(screen.getByText("第四步 route validation")).toBeInTheDocument();
  expect(screen.getByText("文明寝室 OR 房间号")).toBeInTheDocument();
  expect(screen.getByText("召回文明寝室房间号候选")).toBeInTheDocument();
  expect(screen.getAllByText("引用 1 条").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Agent 输出字段（route 前）").length).toBeGreaterThan(0);
  expect(screen.getByText("Route 结论")).toBeInTheDocument();
  expect(screen.getAllByText("resolved").length).toBeGreaterThan(0);
  expect(screen.getByText("执行 final_decision：候选证据支持字段值，参与最终定案。")).toBeInTheDocument();
  expect(screen.queryByText("### 文明寝室名单")).not.toBeInTheDocument();
  expect(screen.queryByText("| 房间 | 结论 |")).not.toBeInTheDocument();

  await user.click(screen.getByRole("tab", { name: "证据" }));
  expect(screen.getByText("Agent 执行过程")).toBeInTheDocument();
  expect(screen.getByText("字段决策过程")).toBeInTheDocument();
  expect(screen.getAllByText("第一步 broad extraction").length).toBeGreaterThan(0);
  expect(screen.getAllByText("候选 blocks（1）").length).toBeGreaterThan(0);
  expect(screen.queryByText("candidate-block-id-should-not-render")).not.toBeInTheDocument();
  expect(screen.getAllByText("第二步 resolution / tool").length).toBeGreaterThan(0);
  expect(screen.getAllByText("第三步 agent result（route 前）").length).toBeGreaterThan(0);
  expect(screen.getAllByText("第四步 route validation").length).toBeGreaterThan(0);
  expect(screen.getByText("document_processor")).toBeInTheDocument();
  expect(screen.getByText("file_extraction_agent")).toBeInTheDocument();
  expect(screen.getByText("route_policy_agent")).toBeInTheDocument();
  expect(screen.getAllByText("sample.pdf").length).toBeGreaterThan(0);
  expect(screen.getAllByText("supplement.docx").length).toBeGreaterThan(0);
  expect(screen.getByText("review: 1")).toBeInTheDocument();
  expect(screen.getAllByText("final_decision").length).toBeGreaterThan(0);
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

it("failed 任务会展示 backend 返回的失败原因", async () => {
  const failedSummary: TaskSummary = {
    task_id: "task-failed",
    status: "failed",
    stage: "done",
    route: null,
    route_reason: null,
    has_result: false,
    has_trace: true,
    needs_review: false,
    error_message: "resolution 执行失败: lookup_blocks action exceeded limit"
  };
  const loadTaskDetail = jest.fn(async (): Promise<TaskDetailData> => ({
    summary: failedSummary,
    result: null,
    trace: null,
    review: null,
    audit: null
  }));

  render(
    <TaskDetail
      taskId="task-failed"
      initialSummary={failedSummary}
      loadTaskDetail={loadTaskDetail}
    />
  );

  expect(await screen.findByText("failed")).toBeInTheDocument();
  expect(screen.getByText("任务失败")).toBeInTheDocument();
  expect(screen.getByText("resolution 执行失败: lookup_blocks action exceeded limit")).toBeInTheDocument();
});

it("list 字段在结果页按条目分行展示", async () => {
  const completedSummary: TaskSummary = {
    ...waitingReviewSummary,
    task_id: "task-list",
    status: "completed",
    stage: "done",
    route: "accept",
    needs_review: false
  };
  const paperTitles = [
    "Cascading failures in multiple-to-multiple interdependent networks",
    "Multi-Model Synergistic Gaussian Splatting for Sparse View Synthesis"
  ];
  const loadTaskDetail = jest.fn(async (): Promise<TaskDetailData> => ({
    summary: completedSummary,
    result: {
      task_id: "task-list",
      status: "completed",
      route: "accept",
      fields: [
        {
          field_name: "academic_paper_titles",
          display_name: "学术论文名称",
          agent_value: paperTitles,
          review_value: null,
          final_value: paperTitles,
          field_status: "resolved",
          route: "accept",
          source: "agent",
          committed: true
        }
      ]
    },
    trace: null,
    review: null,
    audit: null
  }));

  render(
    <TaskDetail
      taskId="task-list"
      initialSummary={completedSummary}
      loadTaskDetail={loadTaskDetail}
    />
  );

  await screen.findByText("completed");
  const row = screen.getByRole("row", { name: /学术论文名称/ });
  const listItems = within(row).getAllByRole("listitem");
  expect(listItems.map((item) => item.textContent)).toEqual([
    paperTitles[0],
    paperTitles[1],
    paperTitles[0],
    paperTitles[1]
  ]);
  expect(within(row).queryByText(/\["Cascading failures/)).not.toBeInTheDocument();
});

it("action refs 同页同 span 但 block 不同时不会触发重复 key warning", async () => {
  const user = userEvent.setup();
  const consoleError = jest.spyOn(console, "error").mockImplementation(() => {});
  const duplicateRefAction = {
    action_type: "search_grep",
    message: "论文题目 OR 学术论文",
    used_in_final_decision: false,
    refs: [
      { document_id: "doc-1", page: 2, span: "r:r1", block_id: "doc-1:p2:b11" },
      { document_id: "doc-1", page: 2, span: "r:r1", block_id: "doc-1:p2:b12" }
    ],
    metadata: { stage: "broad", refs: ["doc-1:p2:b11:r:r1", "doc-1:p2:b12:r:r1"] }
  };
  const duplicateRefProcess = {
    ...agentProcess,
    actions: [duplicateRefAction],
    process_steps: agentProcess.process_steps.map((step) =>
      step.stage === "broad_extraction"
        ? { ...step, actions: [duplicateRefAction] }
        : { ...step, actions: [] }
    )
  };
  const completedSummary: TaskSummary = {
    ...waitingReviewSummary,
    status: "completed",
    stage: "done",
    route: "accept",
    needs_review: false
  };
  const loadTaskDetail = jest.fn(async (): Promise<TaskDetailData> => ({
    ...detailData,
    summary: completedSummary,
    trace: detailData.trace
      ? {
          ...detailData.trace,
          steps: detailData.trace.steps?.map((step) =>
            step.agent === "file_extraction_agent"
              ? { ...step, field_decisions: [duplicateRefProcess] }
              : step
          )
        }
      : null,
    review: null
  }));

  try {
    render(
      <TaskDetail
        taskId="task-duplicate-ref"
        initialSummary={completedSummary}
        loadTaskDetail={loadTaskDetail}
      />
    );

    await screen.findByText("completed");
    await user.click(screen.getByRole("tab", { name: "证据" }));
    expect(screen.getByText("引用 2 条")).toBeInTheDocument();
    expect(
      consoleError.mock.calls.some((call) =>
        call.some((item) => String(item).includes("Encountered two children with the same key"))
      )
    ).toBe(false);
  } finally {
    consoleError.mockRestore();
  }
});

it("trace 会直接展示 document_processor 返回的完整原始 Markdown", async () => {
  const user = userEvent.setup();
  const completedSummary: TaskSummary = {
    ...waitingReviewSummary,
    task_id: "task-markdown",
    status: "completed",
    stage: "done",
    route: "accept",
    needs_review: false
  };
  const rawMarkdown = [
    "## 2026届本科生科研作品替代毕业论文（设计）名单汇总表",
    "",
    "| 序号 | 作品类型 | 论文题目 |",
    "| --- | --- | --- |",
    "| 1 | 学术论文 | Cascading failures in multiple-to-multiple interdependent networks |"
  ].join("\n");
  const loadTaskDetail = jest.fn(async (): Promise<TaskDetailData> => ({
    summary: completedSummary,
    result: null,
    trace: {
      task_id: "task-markdown",
      agent_status: "completed",
      steps: [],
      agent_trace: [
        {
          id: "stage-run-markdown",
          sequence: 1,
          stage: "document_processing",
          agent: "document_processor",
          status: "completed",
          request: {
            filename: "academic-paper.pdf",
            file_type: "pdf"
          },
          response: {
            markdown: rawMarkdown
          },
          trace: {
            warnings: []
          }
        }
      ],
      fields: []
    },
    review: null,
    audit: null
  }));

  render(
    <TaskDetail
      taskId="task-markdown"
      initialSummary={completedSummary}
      loadTaskDetail={loadTaskDetail}
    />
  );

  await screen.findByText("completed");
  await user.click(screen.getByRole("tab", { name: "证据" }));
  const markdownRegion = screen.getByRole("region", { name: "academic-paper.pdf 原始 Markdown" });
  expect(within(markdownRegion).getByText("原始 Markdown")).toBeInTheDocument();
  expect(markdownRegion.querySelector("pre")?.textContent).toBe(rawMarkdown);
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
          used_global_lookup: false,
          used_validation_rule: false,
          action_types: ["search_grep", "add_broad_candidate", "finish_broad", "final_decision"],
          related_fields: [],
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
  expect(screen.getByText("文明寝室 OR 房间号")).toBeInTheDocument();
  expect(screen.getByText("召回文明寝室房间号候选")).toBeInTheDocument();
});

it("没有额外 tool/action 时不会把 resolution 显示成 skipped", async () => {
  const noToolProcess = {
    ...agentProcess,
    related_fields: [],
    actions: [],
    process_steps: agentProcess.process_steps.map((step) =>
      step.stage === "field_resolution"
        ? {
            stage: "field_resolution",
            title: "第二步 resolution / tool",
            status: "completed",
            related_fields: [],
            actions: [],
            output_fields: [
              {
                field_name: "room_numbers",
                status: "resolved",
                value: "1-101,1-102",
                reason: "候选证据支持字段值"
              }
            ],
            notes: ["未记录额外 tool/action；resolution 直接将候选证据定案为字段输出。"]
          }
        : step
    )
  };
  const loadTaskDetail = jest.fn(async (): Promise<TaskDetailData> => ({
    ...detailData,
    trace: detailData.trace
      ? {
          ...detailData.trace,
          steps: detailData.trace.steps?.map((step) =>
            step.agent === "file_extraction_agent"
              ? { ...step, field_decisions: [noToolProcess] }
              : step
          ),
          fields: [
            {
              field_name: "room_numbers",
              status: "resolved",
              evidence: agentEvidence,
              actions: [],
              reason: "字段由候选 block 直接定案",
              process_steps: noToolProcess.process_steps
            }
          ]
        }
      : null,
    review: null,
    audit: null
  }));

  render(
    <TaskDetail
      taskId="task-001"
      initialSummary={{ ...waitingReviewSummary, status: "completed", stage: "done", needs_review: false }}
      loadTaskDetail={loadTaskDetail}
    />
  );

  await screen.findByText("completed");
  await userEvent.click(screen.getByRole("tab", { name: "证据" }));

  expect(screen.getByText("第二步 resolution / tool")).toBeInTheDocument();
  expect(screen.getAllByText("未记录额外 tool/action；resolution 直接将候选证据定案为字段输出。").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Agent 输出字段（route 前）").length).toBeGreaterThan(0);
  expect(screen.queryByText("skipped")).not.toBeInTheDocument();
});
