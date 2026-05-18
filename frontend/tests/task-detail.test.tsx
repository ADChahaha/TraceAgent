import { render, screen, waitFor, within } from "@testing-library/react";
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

function createMultiFieldDetail(taskId = "task-001"): TaskDetailData {
  return {
    ...detailData,
    summary: {
      ...waitingReviewSummary,
      task_id: taskId
    },
    result: {
      ...reviewResult,
      task_id: taskId,
      fields: [
        reviewResult.fields[0],
        {
          field_name: "building_name",
          display_name: "楼栋名称",
          agent_value: "一号楼",
          review_value: null,
          final_value: null,
          field_status: "resolved",
          route: "accept",
          route_reason: "证据充分",
          source: null,
          committed: false
        },
        {
          field_name: "invalid_room",
          display_name: "无效房间",
          agent_value: "9-999",
          review_value: null,
          final_value: null,
          field_status: "rejected",
          route: "reject",
          route_reason: "证据不足，拒绝写入",
          source: null,
          committed: false
        }
      ]
    },
    replay: {
      ...baseReplay,
      task_id: taskId,
      actions: [
        ...baseReplay.actions,
        {
          tool_name: "write_field",
          reason: "楼栋证据充分",
          args: {
            field_id: "building_name",
            value: "一号楼",
            final_evidence: [
              {
                path: "/001-sample/001-Notice.md",
                sentences: ["S002"]
              }
            ],
            status: "resolved"
          },
          result: {
            ok: true,
            field: {
              field_id: "building_name",
              status: "resolved",
              value: "一号楼",
              evidence: [
                {
                  path: "/001-sample/001-Notice.md",
                  sentences: ["S002"]
                }
              ],
              evidence_texts: [
                {
                  path: "/001-sample/001-Notice.md",
                  selector: "S002",
                  text: "一号楼包含文明寝室"
                }
              ],
              reason: "楼栋证据充分"
            }
          }
        },
        {
          tool_name: "write_field",
          reason: "无效房间证据不足",
          args: {
            field_id: "invalid_room",
            value: "9-999",
            final_evidence: [
              {
                path: "/001-sample/001-Notice.md",
                sentences: ["S003"]
              }
            ],
            status: "rejected"
          },
          result: {
            ok: true,
            field: {
              field_id: "invalid_room",
              status: "rejected",
              value: "9-999",
              evidence: [
                {
                  path: "/001-sample/001-Notice.md",
                  sentences: ["S003"]
                }
              ],
              evidence_texts: [
                {
                  path: "/001-sample/001-Notice.md",
                  selector: "S003",
                  text: "9-999 不在文明寝室名单中"
                }
              ],
              reason: "无效房间证据不足"
            }
          }
        }
      ]
    }
  };
}

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
    taskId?: string;
    loadTaskDetail?: (taskId: string) => Promise<TaskDetailData>;
    listTasks?: () => Promise<TaskSummary[]>;
    submitReview?: (taskId: string, payload: ReviewSubmitPayload) => Promise<TaskSummary>;
  } = {}
) {
  const taskId = options.taskId ?? data.summary.task_id;
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

  const renderResult = render(
    <TaskDetail
      taskId={taskId}
      initialSummary={data.summary}
      loadTaskDetail={injectedLoadTaskDetail}
      listTasks={listTasks}
      submitReview={submitReview}
    />
  );

  return { injectedLoadTaskDetail, listTasks, submitReview, ...renderResult };
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

it("任务详情默认显示左任务栏、Agent 工作区，不显示字段 Progress 或 evidence Review", async () => {
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
  expect(screen.queryByLabelText("字段进度面板")).not.toBeInTheDocument();
  expect(within(screen.getByLabelText("Agent 中间工作区")).queryByText("写入字段：文明寝室房间号")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Review 面板")).not.toBeInTheDocument();
});

it("Agent 流直接显示完整文字和工具行，不再暴露 replay 播放控制", async () => {
  const directStreamDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      actions: [
        {
          tool_name: "read",
          reason: "读取 [文明寝室证据](evidence://task-001/p001_b001)",
          args: { path: "/001-sample/001-Notice.md" },
          result: { ok: true, path: "/001-sample/001-Notice.md", kind: "paragraph" }
        },
        {
          tool_name: "write_field",
          reason: "写入文明寝室字段",
          args: {
            field_id: "room_numbers",
            value: "1-101,1-102",
            final_evidence: []
          },
          result: {
            ok: true,
            field: {
              field_id: "room_numbers",
              status: "resolved",
              value: "1-101,1-102",
              evidence: [],
              reason: "写入文明寝室字段"
            }
          }
        }
      ]
    }
  };
  renderTaskDetail(directStreamDetail);

  const agentArea = await screen.findByLabelText("Agent 中间工作区");
  expect(within(agentArea).getAllByText((_, element) => element?.textContent === "读取 文明寝室证据").length).toBeGreaterThan(0);
  expect(screen.getByRole("link", { name: "文明寝室证据" })).toBeInTheDocument();
  expect(screen.getByText("写入文明寝室字段")).toBeInTheDocument();
  expect(screen.getByText(/Read paragraph Notice/)).toBeInTheDocument();
  expect(screen.getByText(/Wrote room_numbers/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "自动播放" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "暂停自动播放" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "下一步" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "播放速度" })).not.toBeInTheDocument();
  expect(screen.queryByRole("slider")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /只播放第/ })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /tool read/ })).not.toBeInTheDocument();
});

it("Agent 文字流和底部输入框在中间内容框内居中，单侧栏时动态补旁侧留白", async () => {
  const user = userEvent.setup();
  renderTaskDetail();

  const agentArea = await screen.findByLabelText("Agent 中间工作区");
  expect(agentArea).toHaveAttribute("data-agent-balance-side", "right");
  expect(agentArea).toHaveAttribute("data-agent-gutter", "compact");
  expect(within(agentArea).getByLabelText("Agent 居中文字流内容")).toHaveClass("replay-agent-centered-content");
  expect(within(agentArea).getByLabelText("Agent 居中输入区")).toHaveClass("replay-agent-composer-balance-row");
  expect(within(agentArea).getByLabelText("Agent 中间文字框")).toHaveClass("replay-agent-content-frame");
  expect(within(agentArea).getByLabelText("Agent 中间输入框")).toHaveClass("replay-agent-composer-frame");
  expect(within(agentArea).getByLabelText("Agent 中间文字框")).toContainElement(
    within(agentArea).getByLabelText("Agent 阅读列"),
  );
  expect(within(agentArea).getByLabelText("Agent 中间输入框")).toContainElement(
    within(agentArea).getByLabelText("Agent 输入阅读列"),
  );
  expect(agentArea).toHaveAttribute("data-agent-content-mode", "centered");
  expect(agentArea.querySelector('[data-agent-balance-spacer="right"]')).toHaveAttribute("data-active", "true");
  expect(agentArea.querySelector('[data-agent-balance-spacer="left"]')).toHaveAttribute("data-active", "true");

  await user.click(screen.getByRole("button", { name: "关闭任务栏" }));

  expect(agentArea).toHaveAttribute("data-agent-balance-side", "left");
  expect(agentArea).toHaveAttribute("data-agent-content-mode", "centered");
  expect(agentArea.querySelector('[data-agent-balance-spacer="left"]')).toHaveAttribute("data-active", "true");
  expect(agentArea.querySelector('[data-agent-balance-spacer="right"]')).toHaveAttribute("data-active", "true");

  await user.click(screen.getByRole("button", { name: "打开 evidence Review" }));

  expect(agentArea).toHaveAttribute("data-agent-balance-side", "none");
  expect(agentArea).toHaveAttribute("data-agent-content-mode", "full");
  expect(agentArea.querySelector('[data-agent-balance-spacer="left"]')).toHaveAttribute("data-active", "false");
  expect(agentArea.querySelector('[data-agent-balance-spacer="right"]')).toHaveAttribute("data-active", "false");
});

it("关闭左任务栏后自动显示字段 Progress", async () => {
  const user = userEvent.setup();
  renderTaskDetail();

  expect(await screen.findByLabelText("任务工作台左侧任务栏")).toBeInTheDocument();
  expect(screen.queryByLabelText("字段进度面板")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "关闭任务栏" }));

  expect(screen.queryByLabelText("任务工作台左侧任务栏")).not.toBeInTheDocument();
  const progress = screen.getByLabelText("字段进度面板");
  expect(progress).toBeInTheDocument();
  expect(within(progress).getAllByText("resolved").length).toBeGreaterThan(0);
  expect(within(progress).getAllByText("review").length).toBeGreaterThan(0);
  expect(within(progress).getByRole("button", { name: /文明寝室房间号/ })).toBeInTheDocument();
  expect(within(progress).queryByLabelText("字段展开详情")).not.toBeInTheDocument();
  expect(within(progress).queryByText("字段需要人工确认")).not.toBeInTheDocument();
  expect(within(progress).queryByText("last seq 8")).not.toBeInTheDocument();
  expect(within(progress).queryByText("running")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "打开任务栏" }));

  expect(screen.getByLabelText("任务工作台左侧任务栏")).toBeInTheDocument();
  expect(screen.queryByLabelText("字段进度面板")).not.toBeInTheDocument();
});

it("字段 Progress 只做紧凑列表，点击字段会在最右侧 Review 打开详情", async () => {
  const user = userEvent.setup();
  renderTaskDetail(createMultiFieldDetail());

  await user.click(await screen.findByRole("button", { name: "关闭任务栏" }));

  const progress = screen.getByLabelText("字段进度面板");
  expect(within(progress).getByRole("button", { name: /文明寝室房间号/ })).toBeInTheDocument();
  expect(within(progress).getByRole("button", { name: /楼栋名称/ })).toBeInTheDocument();
  expect(within(progress).queryByLabelText("字段展开详情")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Review 面板")).not.toBeInTheDocument();
  expect(within(progress).queryByText("楼栋证据充分")).not.toBeInTheDocument();

  await user.click(within(progress).getByRole("button", { name: /楼栋名称/ }));

  const review = screen.getByLabelText("Review 面板");
  expect(within(progress).queryByLabelText("字段展开详情")).not.toBeInTheDocument();
  expect(within(progress).queryByText("证据充分")).not.toBeInTheDocument();
  expect(within(review).getByLabelText("字段展开详情")).toBeInTheDocument();
  expect(within(review).getByText("写入字段：楼栋名称")).toBeInTheDocument();
  expect(within(review).getByText("证据充分")).toBeInTheDocument();
  expect(screen.queryByLabelText("文明寝室房间号 复核值")).not.toBeInTheDocument();
});

it("字段 Progress 按 review、reject、accept 分组展示", async () => {
  const user = userEvent.setup();
  renderTaskDetail(createMultiFieldDetail());

  await user.click(await screen.findByRole("button", { name: "关闭任务栏" }));

  const progress = screen.getByLabelText("字段进度面板");
  const groupHeadings = within(progress).getAllByRole("heading", { level: 3 });
  expect(groupHeadings.map((heading) => heading.textContent)).toEqual(["Review", "Reject", "Accept"]);

  const reviewGroup = within(progress).getByLabelText("Review 字段分组");
  const rejectGroup = within(progress).getByLabelText("Reject 字段分组");
  const acceptGroup = within(progress).getByLabelText("Accept 字段分组");
  expect(within(reviewGroup).getByRole("button", { name: /文明寝室房间号/ })).toBeInTheDocument();
  expect(within(rejectGroup).getByRole("button", { name: /无效房间/ })).toBeInTheDocument();
  expect(within(acceptGroup).getByRole("button", { name: /楼栋名称/ })).toBeInTheDocument();

  const reviewTop = reviewGroup.compareDocumentPosition(rejectGroup);
  const rejectTop = rejectGroup.compareDocumentPosition(acceptGroup);
  expect(reviewTop & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(rejectTop & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

it("Review toggle 打开最右侧 evidence Review 空态，不影响字段 Progress", async () => {
  const user = userEvent.setup();
  renderTaskDetail();

  await user.click(await screen.findByRole("button", { name: "关闭任务栏" }));
  await user.click(screen.getByRole("button", { name: "打开 evidence Review" }));

  expect(screen.getByLabelText("字段进度面板")).toBeInTheDocument();
  const review = screen.getByLabelText("Review 面板");
  expect(review).toBeInTheDocument();
  expect(within(review).getByText("选择一个字段或 evidence 链接查看详情")).toBeInTheDocument();
});

it("点击 evidence 链接打开最右侧 Review，字段 Progress 和 evidence Review 是两个竖栏", async () => {
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
  expect(screen.getByLabelText("字段进度面板")).toBeInTheDocument();

  await user.click(screen.getByRole("link", { name: "文明寝室证据" }));

  const review = screen.getByLabelText("Review 面板");
  expect(review).toBeInTheDocument();
  expect(within(review).getByRole("tab", { name: "文明寝室证据" })).toBeInTheDocument();
  expect(within(review).getByRole("tabpanel")).toHaveTextContent("evidence://task-001/p001_b001");
  expect(within(review).getByText("evidence://task-001/p001_b001")).toBeInTheDocument();
  const progress = screen.getByLabelText("字段进度面板");
  expect(progress).toBeInTheDocument();
  expect(progress).not.toContainElement(review);
  expect(review).not.toContainElement(progress);
  expect(screen.queryByLabelText("任务工作台左侧任务栏")).not.toBeInTheDocument();
});

it("不同 evidence 会在最右侧 Review 内打开 tab", async () => {
  const user = userEvent.setup();
  const evidenceDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      actions: [
        {
          tool_name: "read",
          reason: "查看 [第一条证据](evidence://task-001/p001_b001) 和 [第二条证据](evidence://task-001/p001_b002)",
          args: { path: "/001-sample/001-Notice.md" },
          result: { ok: true, path: "/001-sample/001-Notice.md", kind: "paragraph", text: "1-101、1-102 被列为文明寝室" }
        }
      ]
    }
  };
  renderTaskDetail(evidenceDetail);

  await user.click(await screen.findByRole("button", { name: "关闭任务栏" }));
  await user.click(screen.getByRole("link", { name: "第一条证据" }));
  await user.click(screen.getByRole("link", { name: "第二条证据" }));

  const review = screen.getByLabelText("Review 面板");
  expect(within(review).getByRole("tab", { name: "第一条证据" })).toBeInTheDocument();
  expect(within(review).getByRole("tab", { name: "第二条证据" })).toBeInTheDocument();
  expect(within(review).getByRole("tabpanel")).toHaveTextContent("evidence://task-001/p001_b002");
});

it("evidence Review tabs 按 task 隔离，不同任务不共享 tab", async () => {
  const user = userEvent.setup();
  const firstTaskDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      actions: [
        {
          tool_name: "read",
          reason: "查看 [任务一证据](evidence://task-001/p001_b001)",
          args: { path: "/001-sample/001-Notice.md" },
          result: { ok: true, path: "/001-sample/001-Notice.md", kind: "paragraph", text: "task one evidence" }
        }
      ]
    }
  };
  const secondTaskDetail: TaskDetailData = {
    ...createMultiFieldDetail("task-002"),
    summary: {
      ...waitingReviewSummary,
      task_id: "task-002"
    },
    replay: {
      ...baseReplay,
      task_id: "task-002",
      actions: [
        {
          tool_name: "read",
          reason: "查看 [任务二证据](evidence://task-002/p001_b010)",
          args: { path: "/002-sample/Notice.md" },
          result: { ok: true, path: "/002-sample/Notice.md", kind: "paragraph", text: "task two evidence" }
        }
      ]
    }
  };
  const injectedLoadTaskDetail = jest
    .fn<Promise<TaskDetailData>, [string]>()
    .mockResolvedValueOnce(firstTaskDetail)
    .mockResolvedValueOnce(secondTaskDetail);

  const { rerender, listTasks, submitReview } = renderTaskDetail(firstTaskDetail, {
    loadTaskDetail: injectedLoadTaskDetail,
    listTasks: async () => [firstTaskDetail.summary, secondTaskDetail.summary]
  });

  await user.click(await screen.findByRole("button", { name: "关闭任务栏" }));
  await user.click(screen.getByRole("link", { name: "任务一证据" }));
  expect(screen.getByRole("tab", { name: "任务一证据" })).toBeInTheDocument();

  rerender(
    <TaskDetail
      taskId="task-002"
      initialSummary={secondTaskDetail.summary}
      loadTaskDetail={injectedLoadTaskDetail}
      listTasks={listTasks}
      submitReview={submitReview}
    />
  );

  expect(await screen.findByRole("link", { name: "任务二证据" })).toHaveAttribute(
    "href",
    "evidence://task-002/p001_b010"
  );
  expect(screen.queryByRole("tab", { name: "任务一证据" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "打开 evidence Review" }));
  expect(screen.getByText("选择一个字段或 evidence 链接查看详情")).toBeInTheDocument();
});

it("打开左栏会自动关闭字段 Progress，但不会关闭最右侧 evidence Review", async () => {
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
  await user.click(screen.getByRole("button", { name: "关闭任务栏" }));
  await user.click(screen.getByRole("link", { name: "文明寝室证据" }));
  expect(screen.queryByLabelText("任务工作台左侧任务栏")).not.toBeInTheDocument();
  expect(screen.getByLabelText("字段进度面板")).toBeInTheDocument();
  expect(screen.getByLabelText("Review 面板")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "打开任务栏" }));

  expect(screen.getByLabelText("任务工作台左侧任务栏")).toBeInTheDocument();
  expect(screen.queryByLabelText("字段进度面板")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Review 面板")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "关闭 Review" }));

  expect(screen.getByLabelText("任务工作台左侧任务栏")).toBeInTheDocument();
  expect(screen.queryByLabelText("字段进度面板")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Review 面板")).not.toBeInTheDocument();
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

  await user.click(await screen.findByRole("button", { name: "关闭任务栏" }));
  await user.click(screen.getByRole("button", { name: /文明寝室房间号/ }));
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

  await user.click(await screen.findByRole("button", { name: "关闭任务栏" }));
  await user.click(screen.getByRole("button", { name: /保密义务判断/ }));
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

  await userEvent.click(await screen.findByRole("button", { name: "关闭任务栏" }));
  await userEvent.click(screen.getByRole("button", { name: /文明寝室房间号/ }));
  expect(await screen.findByText("写入字段：文明寝室房间号")).toBeInTheDocument();
  expect(screen.getAllByText("reject").length).toBeGreaterThan(0);
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
