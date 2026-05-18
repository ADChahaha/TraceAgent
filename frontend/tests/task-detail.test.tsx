import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import {
  getTaskAudit,
  getTaskResult,
  getTaskSummary,
  getTaskTrace,
  loadTaskDetail
} from "@/lib/api";
import { TaskDetail } from "@/components/task-detail";
import type {
  ReviewField,
  ReviewSubmitPayload,
  TaskDetailData,
  TaskReplay,
  TaskResult,
  TaskSummary
} from "@/lib/types";

const waitingReviewSummary: TaskSummary = {
  task_id: "task-001",
  status: "waiting_review",
  stage: "review",
  route: "review",
  route_reason: "关键字段证据较弱，需要人工确认",
  has_result: true,
  has_trace: true,
  needs_review: true,
  stream: {
    state: "running",
    last_event_seq: 8
  }
};

const baseReplay: TaskReplay = {
  task_id: "task-001",
  status: "waiting_review",
  stage: "review",
  documents: [{ document_id: "doc-1", filename: "sample.pdf" }],
  display_html: '<h1 id="p001_b000">文明寝室名单</h1><p id="p001_b001">1-101、1-102 被列为文明寝室</p>',
  outline_tree: [
    {
      id: "p001_b000",
      type: "TITLE",
      text: "文明寝室名单",
      children: []
    }
  ],
  broad_plan: { plan: ["读取文明寝室名单"] },
  actions: [
    {
      tool_name: "write_field",
      reason: "候选证据支持字段值",
      args: {
        field_id: "room_numbers",
        value: "1-101,1-102",
        final_evidence: [
          {
            path: "/001-sample/001-Notice.md",
            sentences: ["S001"]
          }
        ],
        status: "resolved"
      },
      result: {
        ok: true,
        field: {
          field_id: "room_numbers",
          status: "resolved",
          value: "1-101,1-102",
          evidence: [
            {
              path: "/001-sample/001-Notice.md",
              sentences: ["S001"]
            }
          ],
          evidence_texts: [
            {
              path: "/001-sample/001-Notice.md",
              selector: "S001",
              text: "1-101、1-102 被列为文明寝室"
            }
          ],
          reason: "候选证据支持字段值"
        }
      }
    }
  ],
  result: { room_numbers: "1-101,1-102" },
  field_states: {},
  audit: { route: "review", route_reason: "关键字段证据较弱，需要人工确认" }
};

const reviewResult: TaskResult = {
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
};

const reviewFields: ReviewField[] = [
  {
    field_name: "room_numbers",
    display_name: "文明寝室房间号",
    agent_value: "1-101,1-102",
    field_status: "resolved",
    needs_review: true,
    review_reason: "字段需要人工确认",
    evidence_texts: [],
    evidence_refs: [],
    actions: [],
    reason: "候选证据支持字段值",
    failure_reason: null,
    agent_process: null
  }
];

const detailData: TaskDetailData = {
  summary: waitingReviewSummary,
  result: reviewResult,
  trace: null,
  replay: baseReplay,
  review: {
    task_id: "task-001",
    status: "waiting_review",
    route: "review",
    route_reason: "关键字段证据较弱，需要人工确认",
    fields: reviewFields
  },
  audit: null
};

const recentTaskSummaries: TaskSummary[] = [
  waitingReviewSummary,
  {
    task_id: "task-002",
    status: "processing",
    stage: "extraction",
    route: null,
    route_reason: null,
    has_result: false,
    has_trace: true,
    needs_review: false,
    created_at: "2026-05-18T09:00:00Z"
  }
];

beforeEach(() => {
  window.localStorage.clear();
  jest.restoreAllMocks();
});

function jsonResponse(payload: unknown) {
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    text: async () => JSON.stringify(payload)
  } as Response;
}

function renderTaskDetail(
  data: TaskDetailData = detailData,
  options: {
    loadTaskDetail?: (taskId: string) => Promise<TaskDetailData>;
    listTasks?: () => Promise<TaskSummary[]>;
    submitReview?: (taskId: string, payload: ReviewSubmitPayload) => Promise<TaskSummary>;
  } = {}
) {
  const loadTaskDetailImpl = options.loadTaskDetail ?? (async () => data);
  const listTasksImpl = options.listTasks ?? (async () => recentTaskSummaries);
  const submitReviewImpl =
    options.submitReview ??
    (async () =>
      ({
        ...data.summary,
        status: "completed",
        stage: "done",
        needs_review: false
      }) as TaskSummary);

  const injectedLoadTaskDetail = jest.fn(loadTaskDetailImpl) as jest.MockedFunction<
    (taskId: string) => Promise<TaskDetailData>
  >;
  const listTasks = jest.fn(listTasksImpl) as jest.MockedFunction<() => Promise<TaskSummary[]>>;
  const submitReview = jest.fn(submitReviewImpl) as jest.MockedFunction<
    (taskId: string, payload: ReviewSubmitPayload) => Promise<TaskSummary>
  >;

  render(
    <TaskDetail
      taskId="task-001"
      initialSummary={data.summary}
      loadTaskDetail={injectedLoadTaskDetail}
      listTasks={listTasks}
      submitReview={submitReview}
    />
  );

  return { injectedLoadTaskDetail, listTasks, submitReview };
}

it("loadTaskDetail 只拉 replay 所需数据，不再加载 trace 和 audit", async () => {
  global.fetch = jest.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/tasks/task-001")) {
      return jsonResponse(waitingReviewSummary);
    }
    if (url.endsWith("/tasks/task-001/result")) {
      return jsonResponse(reviewResult);
    }
    if (url.endsWith("/tasks/task-001/replay")) {
      return jsonResponse(baseReplay);
    }
    if (url.endsWith("/tasks/task-001/review")) {
      return jsonResponse(detailData.review);
    }
    throw new Error(`unexpected fetch: ${url}`);
  });

  const loaded = await loadTaskDetail("task-001");

  expect(loaded.summary).toEqual(waitingReviewSummary);
  expect(loaded.result).toEqual(reviewResult);
  expect(loaded.replay).toEqual(baseReplay);
  expect(loaded.review).toEqual(detailData.review);
  expect(loaded.trace).toBeNull();
  expect(loaded.audit).toBeNull();
  expect(global.fetch).not.toHaveBeenCalledWith(expect.stringContaining("/trace"), expect.anything());
  expect(global.fetch).not.toHaveBeenCalledWith(expect.stringContaining("/audit"), expect.anything());
});

it("低层 API 仍保留 trace 和 audit 读取能力", async () => {
  global.fetch = jest.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/tasks/task-001")) {
      return jsonResponse(waitingReviewSummary);
    }
    if (url.endsWith("/tasks/task-001/result")) {
      return jsonResponse(reviewResult);
    }
    if (url.endsWith("/tasks/task-001/trace")) {
      return jsonResponse({ task_id: "task-001", fields: [] });
    }
    if (url.endsWith("/tasks/task-001/audit")) {
      return jsonResponse({ task_id: "task-001", status: "completed", field_commits: [] });
    }
    throw new Error(`unexpected fetch: ${url}`);
  });

  await expect(getTaskSummary("task-001")).resolves.toEqual(waitingReviewSummary);
  await expect(getTaskResult("task-001")).resolves.toEqual(reviewResult);
  await expect(getTaskTrace("task-001")).resolves.toEqual({ task_id: "task-001", fields: [] });
  await expect(getTaskAudit("task-001")).resolves.toEqual({
    task_id: "task-001",
    status: "completed",
    field_commits: []
  });
});

it("任务详情默认显示左任务栏和 Agent 工作区，不显示 Progress", async () => {
  renderTaskDetail();

  expect(await screen.findByLabelText("任务工作台左侧任务栏")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "关闭任务栏" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "新任务" })).toHaveAttribute("href", "/");
  expect(screen.getByRole("link", { name: /task-001/ })).toHaveAttribute("href", "/tasks/task-001");
  expect(screen.getByRole("link", { name: /task-002/ })).toHaveAttribute("href", "/tasks/task-002");
  expect(screen.getByLabelText("Agent 中间工作区")).toBeInTheDocument();
  expect(screen.getByText("候选证据支持字段值")).toBeInTheDocument();
  expect(screen.getByLabelText("Agent 对话输入框")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "添加文件" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "发送消息" })).toBeInTheDocument();
  expect(screen.queryByLabelText("任务进度面板")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("证据 Review 面板")).not.toBeInTheDocument();
});

it("关闭左任务栏后显示 Progress，重新打开左栏后隐藏 Progress", async () => {
  const user = userEvent.setup();
  renderTaskDetail();

  expect(await screen.findByLabelText("任务工作台左侧任务栏")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "关闭任务栏" }));

  expect(screen.queryByLabelText("任务工作台左侧任务栏")).not.toBeInTheDocument();
  const progress = screen.getByLabelText("任务进度面板");
  expect(progress).toBeInTheDocument();
  expect(within(progress).getByText("last seq 8")).toBeInTheDocument();
  expect(within(progress).getByText("running")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "打开任务栏" }));

  expect(screen.getByLabelText("任务工作台左侧任务栏")).toBeInTheDocument();
  expect(screen.queryByLabelText("任务进度面板")).not.toBeInTheDocument();
});

it("点击 evidence 链接打开右侧 Review，Review 遮住 Progress 并可与左栏共存", async () => {
  const user = userEvent.setup();
  const evidenceDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      actions: [
        {
          tool_name: "read",
          reason: "查看 [文明寝室证据](evidence://task-001/p001_b001)",
          args: {
            path: "/001-sample/001-Notice.md"
          },
          result: {
            ok: true,
            path: "/001-sample/001-Notice.md",
            kind: "paragraph",
            text: "1-101、1-102 被列为文明寝室"
          }
        }
      ]
    }
  };
  renderTaskDetail(evidenceDetail);

  expect(await screen.findByLabelText("任务工作台左侧任务栏")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "关闭任务栏" }));
  expect(screen.getByLabelText("任务进度面板")).toBeInTheDocument();

  await user.click(screen.getByRole("link", { name: "文明寝室证据" }));

  const review = screen.getByLabelText("证据 Review 面板");
  expect(review).toBeInTheDocument();
  expect(within(review).getByText("evidence://task-001/p001_b001")).toBeInTheDocument();
  expect(screen.queryByLabelText("任务进度面板")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("任务工作台左侧任务栏")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "打开任务栏" }));

  expect(screen.getByLabelText("任务工作台左侧任务栏")).toBeInTheDocument();
  expect(screen.getByLabelText("证据 Review 面板")).toBeInTheDocument();
  expect(screen.queryByLabelText("任务进度面板")).not.toBeInTheDocument();
});

it("关闭 Review 后按左栏状态恢复 Progress 或仅保留左栏 Agent", async () => {
  const user = userEvent.setup();
  const evidenceDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      actions: [
        {
          tool_name: "read",
          reason: "查看 [文明寝室证据](evidence://task-001/p001_b001)",
          args: { path: "/001-sample/001-Notice.md" },
          result: { ok: true, path: "/001-sample/001-Notice.md", kind: "paragraph", text: "1-101" }
        }
      ]
    }
  };
  renderTaskDetail(evidenceDetail);

  expect(await screen.findByLabelText("任务工作台左侧任务栏")).toBeInTheDocument();
  await user.click(screen.getByRole("link", { name: "文明寝室证据" }));
  expect(screen.getByLabelText("任务工作台左侧任务栏")).toBeInTheDocument();
  expect(screen.getByLabelText("证据 Review 面板")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "关闭 Review" }));

  expect(screen.getByLabelText("任务工作台左侧任务栏")).toBeInTheDocument();
  expect(screen.queryByLabelText("证据 Review 面板")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("任务进度面板")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "关闭任务栏" }));
  expect(screen.getByLabelText("任务进度面板")).toBeInTheDocument();

  await user.click(screen.getByRole("link", { name: "文明寝室证据" }));
  expect(screen.getByLabelText("证据 Review 面板")).toBeInTheDocument();
  expect(screen.queryByLabelText("任务进度面板")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "关闭 Review" }));
  expect(screen.queryByLabelText("证据 Review 面板")).not.toBeInTheDocument();
  expect(screen.getByLabelText("任务进度面板")).toBeInTheDocument();
});

it("waiting_review 字段复核提交 revise_and_approve 并刷新最近任务", async () => {
  const user = userEvent.setup();
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
    result: {
      ...reviewResult,
      status: "completed",
      fields: reviewResult.fields.map((field) => ({
        ...field,
        final_value: "1-101,1-102,1-103",
        source: "human",
        committed: true
      }))
    },
    review: null
  };
  const injectedLoadTaskDetail = jest
    .fn<Promise<TaskDetailData>, [string]>()
    .mockResolvedValueOnce(detailData)
    .mockResolvedValueOnce(completedDetail);
  const submitReview = jest.fn(async () => refreshedSummary);

  renderTaskDetail(detailData, {
    loadTaskDetail: injectedLoadTaskDetail,
    submitReview
  });

  expect(await screen.findByText("写入字段：文明寝室房间号")).toBeInTheDocument();
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
  await waitFor(() => expect(injectedLoadTaskDetail).toHaveBeenCalledTimes(2));
  const recentTasks = JSON.parse(window.localStorage.getItem("agent-gate.recent-tasks") ?? "[]");
  expect(recentTasks[0]).toMatchObject({
    task_id: "task-001",
    status: "completed",
    stage: "done"
  });
  expect(recentTasks[0].created_at).toBe("2026-04-29T08:00:00Z");
});

it("enum 字段复核提交 tagged payload 而不是字符串", async () => {
  const user = userEvent.setup();
  const enumVariants = [
    { name: "Entailment", type: "null", description: "合同文本支持该判断" },
    { name: "Contradiction", type: "null", description: "合同文本否定该判断" },
    { name: "NotMentioned", type: "null", description: "合同文本没有提到该判断" }
  ];
  const enumValue = { variant: "Entailment", value: null };
  const enumDetail: TaskDetailData = {
    ...detailData,
    result: {
      ...reviewResult,
      fields: [
        {
          ...reviewResult.fields[0],
          field_name: "nda_disclosure",
          display_name: "保密义务判断",
          agent_value: enumValue,
          field_type: "enum",
          variants: enumVariants
        }
      ]
    },
    replay: {
      ...baseReplay,
      result: { nda_disclosure: enumValue },
      actions: [
        {
          tool_name: "write_field",
          reason: "合同文本支持保密义务判断",
          args: {
            field_id: "nda_disclosure",
            value: enumValue,
            final_evidence: []
          },
          result: {
            ok: true,
            field: {
              field_id: "nda_disclosure",
              status: "resolved",
              value: enumValue,
              evidence: [],
              reason: "合同文本支持保密义务判断"
            }
          }
        }
      ]
    },
    review: {
      ...detailData.review!,
      fields: [
        {
          ...reviewFields[0],
          field_name: "nda_disclosure",
          display_name: "保密义务判断",
          agent_value: enumValue,
          field_type: "enum",
          variants: enumVariants
        }
      ]
    }
  };
  const submitReview = jest.fn(async (): Promise<TaskSummary> => ({
    ...waitingReviewSummary,
    status: "completed",
    stage: "done",
    needs_review: false
  }));

  renderTaskDetail(enumDetail, { submitReview });

  expect(await screen.findByText("写入字段：保密义务判断")).toBeInTheDocument();
  expect(screen.getByLabelText("保密义务判断 枚举选项")).toHaveValue("Entailment");
  await user.selectOptions(screen.getByLabelText("保密义务判断 枚举选项"), "Contradiction");
  await user.click(screen.getByRole("button", { name: "提交修正并通过" }));

  await waitFor(() => expect(submitReview).toHaveBeenCalledTimes(1));
  expect(submitReview).toHaveBeenCalledWith("task-001", {
    decision: "revise_and_approve",
    fields: [
      {
        field_name: "nda_disclosure",
        review_value: { variant: "Contradiction", value: null }
      }
    ],
    comment: "",
    reviewer: "frontend"
  });
});

it("reject 字段只显示拒绝路由，不提供人工修改入口", async () => {
  const rejectedDetail: TaskDetailData = {
    ...detailData,
    summary: {
      ...waitingReviewSummary,
      status: "rejected",
      route: "reject",
      needs_review: false
    },
    result: {
      ...reviewResult,
      fields: [
        {
          ...reviewResult.fields[0],
          route: "reject",
          route_reason: "证据不足，拒绝写入"
        }
      ]
    },
    replay: {
      ...baseReplay,
      actions: [
        {
          tool_name: "write_field",
          reason: "证据不足",
          args: {
            field_id: "room_numbers",
            value: "1-101"
          },
          result: {
            ok: true,
            field: {
              field_id: "room_numbers",
              status: "rejected",
              value: "1-101",
              evidence: [],
              reason: "证据不足"
            }
          }
        }
      ]
    },
    review: null
  };

  renderTaskDetail(rejectedDetail);

  expect(await screen.findByText("写入字段：文明寝室房间号")).toBeInTheDocument();
  expect(screen.getByText("reject")).toBeInTheDocument();
  expect(screen.queryByLabelText("文明寝室房间号 复核值")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "提交修正并通过" })).not.toBeInTheDocument();
});

it("failed 任务会展示 backend 返回的失败原因", async () => {
  const failedSummary: TaskSummary = {
    task_id: "task-001",
    status: "failed",
    stage: "extraction",
    route: null,
    route_reason: null,
    has_result: false,
    has_trace: false,
    needs_review: false,
    error_message: "OCR worker crashed"
  };
  renderTaskDetail({
    summary: failedSummary,
    result: null,
    trace: null,
    replay: null,
    review: null,
    audit: null
  });

  expect(await screen.findByText("任务失败")).toBeInTheDocument();
  expect(screen.getByText("OCR worker crashed")).toBeInTheDocument();
  expect(screen.getByText("task-001 / no replay")).toBeInTheDocument();
});

it("failed 但已有 replay 的任务仍展示 Agent 工作区", async () => {
  const failedWithReplay: TaskDetailData = {
    ...detailData,
    summary: {
      ...waitingReviewSummary,
      status: "failed",
      stage: "route_policy",
      error_message: "字段提交失败"
    },
    review: null
  };

  renderTaskDetail(failedWithReplay);

  expect(await screen.findByText("任务失败")).toBeInTheDocument();
  expect(screen.getByText("字段提交失败")).toBeInTheDocument();
  expect(screen.getByLabelText("Agent 中间工作区")).toBeInTheDocument();
  expect(screen.getByLabelText("Agent 文字流")).toBeInTheDocument();
});
