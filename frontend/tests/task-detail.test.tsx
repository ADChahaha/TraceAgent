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
  TaskDetailData,
  TaskReplay,
  TaskResult,
  TaskSummary
} from "@/lib/types";

const completedSummary: TaskSummary = {
  task_id: "task-001",
  status: "completed",
  stage: "done",
  has_result: true,
  has_trace: true,
  stream: {
    state: "ended",
    last_event_seq: 8
  }
};

const baseReplay: TaskReplay = {
  task_id: "task-001",
  status: "completed",
  stage: "done",
  documents: [{ document_id: "doc-1", filename: "sample.pdf" }],
  display_html:
    '<h1 id="p001_b000">文明寝室名单</h1><p id="p001_b001">1-101、1-102 被列为文明寝室</p><p id="p001_b002">一号楼包含文明寝室</p>',
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
            sentences: ["p001_b001"]
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
              sentences: ["p001_b001"]
            }
          ],
          evidence_texts: [
            {
              path: "/001-sample/001-Notice.md",
              selector: "p001_b001",
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
  audit: {}
};

const encodedFilenameReplay: TaskReplay = {
  ...baseReplay,
  documents: [{ document_id: "doc-1", filename: "/contracts/Confidentiality%20and%20Non-Disclosure%20Agreement.pdf" }]
};

const completedResult: TaskResult = {
  task_id: "task-001",
  status: "completed",
  fields: [
    {
      field_name: "room_numbers",
      display_name: "文明寝室房间号",
      agent_value: "1-101,1-102",
      final_value: "1-101,1-102",
      field_status: "resolved",
      source: "agent",
      committed: true
    }
  ]
};

const processedDisplayHtml =
  '<!doctype html><html lang="en"><head><meta charset="utf-8"><style>body { margin: 0; background: #f3f4f6; } main { max-width: 980px; margin: 0 auto; padding: 24px; } .page { background: #fff; padding: 44px 56px; }</style><script>window.__sourceScriptRan = true;</script></head><body><main><section class="page"><h1 id="p001_b000">文明寝室名单</h1><p id="p001_b001">1-101、1-102 被列为文明寝室</p><p id="p001_b002">一号楼包含文明寝室</p></section></main></body></html>';

const detailData: TaskDetailData = {
  summary: completedSummary,
  result: completedResult,
  trace: null,
  replay: baseReplay,
  audit: null
};

const recentTaskSummaries: TaskSummary[] = [
  completedSummary,
  {
    task_id: "task-002",
    status: "processing",
    stage: "extraction",
    has_result: false,
    has_trace: true,
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
  } = {}
) {
  const taskId = options.taskId ?? data.summary.task_id;
  const loadTaskDetailImpl = options.loadTaskDetail ?? (async () => data);
  const listTasksImpl = options.listTasks ?? (async () => recentTaskSummaries);
  const injectedLoadTaskDetail = jest.fn(loadTaskDetailImpl) as jest.MockedFunction<
    (taskId: string) => Promise<TaskDetailData>
  >;
  const listTasks = jest.fn(listTasksImpl) as jest.MockedFunction<() => Promise<TaskSummary[]>>;

  const renderResult = render(
    <TaskDetail
      taskId={taskId}
      initialSummary={data.summary}
      loadTaskDetail={injectedLoadTaskDetail}
      listTasks={listTasks}
    />
  );

  return { injectedLoadTaskDetail, listTasks, ...renderResult };
}

function getSourceFrameHtml(sourceViewer: HTMLElement): string {
  const frame = within(sourceViewer).getByTitle("原文文档") as HTMLIFrameElement;
  return frame.getAttribute("srcdoc") ?? "";
}

function createMultiFieldDetail(taskId = "task-001"): TaskDetailData {
  return {
    ...detailData,
    summary: {
      ...completedSummary,
      task_id: taskId
    },
    result: {
      ...completedResult,
      task_id: taskId,
      fields: [
        completedResult.fields[0],
        {
          field_name: "building_name",
          display_name: "楼栋名称",
          agent_value: "一号楼",
          final_value: "一号楼",
          field_status: "resolved",
          source: "agent",
          committed: true
        },
        {
          field_name: "missing_required",
          display_name: "缺失字段",
          agent_value: null,
          final_value: null,
          field_status: "failed",
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
                sentences: ["p001_b002"]
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
                  sentences: ["p001_b002"]
                }
              ],
              evidence_texts: [
                {
                  path: "/001-sample/001-Notice.md",
                  selector: "p001_b002",
                  text: "一号楼包含文明寝室"
                }
              ],
              reason: "楼栋证据充分"
            }
          }
        }
      ]
    }
  };
}

it("loadTaskDetail 只拉 replay 所需数据，不再加载 trace 和 audit", async () => {
  global.fetch = jest.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/tasks/task-001")) {
      return jsonResponse(completedSummary);
    }
    if (url.endsWith("/tasks/task-001/result")) {
      return jsonResponse(completedResult);
    }
    if (url.endsWith("/tasks/task-001/replay")) {
      return jsonResponse(baseReplay);
    }
    throw new Error(`unexpected fetch: ${url}`);
  });

  const loaded = await loadTaskDetail("task-001");

  expect(loaded.summary).toEqual(completedSummary);
  expect(loaded.result).toEqual(completedResult);
  expect(loaded.replay).toEqual(baseReplay);
  expect(loaded.trace).toBeNull();
  expect(loaded.audit).toBeNull();
  expect(global.fetch).not.toHaveBeenCalledWith(expect.stringContaining("/trace"), expect.anything());
  expect(global.fetch).not.toHaveBeenCalledWith(expect.stringContaining("/audit"), expect.anything());
  expect(global.fetch).not.toHaveBeenCalledWith(expect.stringContaining("/review"), expect.anything());
});

it("低层 API 仍保留 trace 和 audit 读取能力", async () => {
  global.fetch = jest.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/tasks/task-001")) {
      return jsonResponse(completedSummary);
    }
    if (url.endsWith("/tasks/task-001/result")) {
      return jsonResponse(completedResult);
    }
    if (url.endsWith("/tasks/task-001/trace")) {
      return jsonResponse({ task_id: "task-001", fields: [] });
    }
    if (url.endsWith("/tasks/task-001/audit")) {
      return jsonResponse({ task_id: "task-001", status: "completed", field_commits: [] });
    }
    throw new Error(`unexpected fetch: ${url}`);
  });

  await expect(getTaskSummary("task-001")).resolves.toEqual(completedSummary);
  await expect(getTaskResult("task-001")).resolves.toEqual(completedResult);
  await expect(getTaskTrace("task-001")).resolves.toEqual({ task_id: "task-001", fields: [] });
  await expect(getTaskAudit("task-001")).resolves.toEqual({
    task_id: "task-001",
    status: "completed",
    field_commits: []
  });
});

it("任务详情默认显示左任务栏、Agent 工作区，不在全局顶栏显示 Review tab", async () => {
  renderTaskDetail();

  const topbar = await screen.findByLabelText("Replay 顶部工具栏");
  expect(within(topbar).queryByRole("tablist", { name: "右侧工作栏选项卡" })).not.toBeInTheDocument();
  expect(within(topbar).queryByRole("tab", { name: "Review" })).not.toBeInTheDocument();
  expect(within(topbar).getByText("task-001")).toHaveAttribute("title", "task-001");
  expect(within(topbar).queryByText("task-001 / sample.pdf")).not.toBeInTheDocument();
  expect(await screen.findByLabelText("任务工作台左侧任务栏")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "关闭任务栏" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "新任务" })).toHaveAttribute("href", "/");
  expect(screen.getByRole("link", { name: /task-001/ })).toHaveAttribute("href", "/tasks/task-001");
  expect(screen.getByRole("link", { name: /task-002/ })).toHaveAttribute("href", "/tasks/task-002");
  expect(screen.getByLabelText("Agent 中间工作区")).toBeInTheDocument();
  expect(screen.getByText("候选证据支持字段值")).toBeInTheDocument();
  expect(screen.getByLabelText("Agent 对话输入框")).toBeInTheDocument();
  expect(screen.queryByLabelText("字段进度面板")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("右侧 Review 工作栏")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Inspector 面板")).not.toBeInTheDocument();
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
  expect(screen.getByText("Read passage")).toBeInTheDocument();
  expect(screen.getByText("Filled room_numbers")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "自动播放" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "暂停自动播放" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "下一步" })).not.toBeInTheDocument();
  expect(screen.queryByRole("slider")).not.toBeInTheDocument();
});

it("Agent 工具行按真实工具显示英文摘要和语义图标", async () => {
  const user = userEvent.setup();
  const toolDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      actions: [
        {
          tool_name: "tree",
          reason: "",
          args: { path_id: "evidence://0000", depth: 3 },
          result: { ok: true, locator: "evidence://0000" }
        },
        {
          tool_name: "read",
          reason: "",
          args: { path_id: "evidence://0000.0001.0001.0001" },
          result: {
            ok: true,
            locator: "evidence://0000.0001.0001.0001",
            kind: "paragraph",
            text: "1-101、1-102 被列为文明寝室"
          }
        },
        {
          tool_name: "add_candidate_evidence",
          reason: "",
          args: { field_id: "room_numbers", path_id: "evidence://0000.0001.0001.0001" },
          result: { ok: true, field_id: "room_numbers", candidate_evidence: ["evidence://0000.0001.0001.0001"] }
        },
        {
          tool_name: "review_evidences",
          reason: "",
          args: { field_id: "room_numbers" },
          result: { ok: true, field_id: "room_numbers", evidence: ["evidence://0000.0001.0001.0001/S001"] }
        },
        {
          tool_name: "write_field",
          reason: "",
          args: { field_id: "room_numbers", value: "1-101,1-102", final_evidence: [] },
          result: {
            ok: true,
            field: {
              field_id: "room_numbers",
              status: "resolved",
              value: "1-101,1-102",
              evidence: []
            }
          }
        },
        {
          tool_name: "submit_result",
          reason: "",
          args: {},
          result: { ok: true }
        }
      ]
    }
  };
  renderTaskDetail(toolDetail);

  const agentArea = await screen.findByLabelText("Agent 中间工作区");
  const toolGroup = within(agentArea).getByRole("group", { name: "5 collapsed tools" });
  expect(within(toolGroup).getByText("Explored 2 files, saved 1 evidence item, reviewed 1 evidence set, filled 1 field")).toBeInTheDocument();
  expect(within(toolGroup).queryByText("Viewed outline -> Read passage -> Saved evidence for room_numbers")).not.toBeInTheDocument();
  expect(within(agentArea).queryByText("Reviewed evidence for room_numbers")).not.toBeInTheDocument();
  expect(within(agentArea).queryByText("Filled room_numbers")).not.toBeInTheDocument();
  expect(within(agentArea).queryByText("Submitted result")).not.toBeInTheDocument();

  await user.click(within(toolGroup).getByRole("button", { name: "展开 5 个工具调用" }));

  expect(within(agentArea).getByText("Viewed outline")).toBeInTheDocument();
  expect(within(agentArea).getByText("Read passage")).toBeInTheDocument();
  expect(within(agentArea).getByText("Saved evidence for room_numbers")).toBeInTheDocument();
  expect(within(agentArea).getByText("Reviewed evidence for room_numbers")).toBeInTheDocument();
  expect(within(agentArea).getByText("Filled room_numbers")).toBeInTheDocument();
  expect(within(agentArea).getByLabelText("tool tree")).toHaveAttribute("data-tool-icon", "list-tree");
  expect(within(agentArea).getByLabelText("tool read")).toHaveAttribute("data-tool-icon", "book-user");
  expect(within(agentArea).getByLabelText("tool add_candidate_evidence")).toHaveAttribute("data-tool-icon", "bookmark-plus");
  expect(within(agentArea).getByLabelText("tool review_evidences")).toHaveAttribute("data-tool-icon", "file-check");
  expect(within(agentArea).getByLabelText("tool write_field")).toHaveAttribute("data-tool-icon", "pen-line");
  expect(within(agentArea).queryByLabelText("tool submit_result")).not.toBeInTheDocument();
});

it("单个 tool 保持直出，不会折叠成 group", async () => {
  const singleToolDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      actions: [
        {
          tool_name: "read",
          reason: "",
          args: { path_id: "evidence://0000" },
          result: { ok: true, locator: "evidence://0000", kind: "paragraph", text: "single tool evidence" }
        }
      ]
    }
  };
  renderTaskDetail(singleToolDetail);

  const agentArea = await screen.findByLabelText("Agent 中间工作区");
  expect(within(agentArea).queryByRole("group", { name: /collapsed tools/ })).not.toBeInTheDocument();
  expect(within(agentArea).getByLabelText("tool read")).toBeInTheDocument();
  expect(within(agentArea).getByText("Read passage")).toBeInTheDocument();
});

it("Agent 文字后的连续多个 tool 整组折叠，不先直出第一条 tool", async () => {
  const user = userEvent.setup();
  const foldedToolsDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      actions: [
        {
          tool_name: "read",
          reason: "先读取总览文字",
          args: { path_id: "evidence://0000" },
          result: { ok: true, locator: "evidence://0000", kind: "paragraph" }
        },
        {
          tool_name: "tree",
          reason: "",
          args: { path_id: "evidence://0000", depth: 2 },
          result: { ok: true, locator: "evidence://0000" }
        },
        {
          tool_name: "read",
          reason: "",
          args: { path_id: "evidence://0000.0001" },
          result: { ok: true, locator: "evidence://0000.0001", kind: "paragraph" }
        },
        {
          tool_name: "add_candidate_evidence",
          reason: "",
          args: { field_id: "room_numbers", path_id: "evidence://0000.0001" },
          result: { ok: true, field_id: "room_numbers", candidate_evidence: ["evidence://0000.0001"] }
        },
        {
          tool_name: "review_evidences",
          reason: "",
          args: { field_id: "room_numbers" },
          result: { ok: true, field_id: "room_numbers", evidence: ["evidence://0000.0001/S001"] }
        },
        {
          tool_name: "write_field",
          reason: "最后写入字段",
          args: { field_id: "room_numbers", value: "1-101,1-102", final_evidence: [] },
          result: {
            ok: true,
            field: {
              field_id: "room_numbers",
              status: "resolved",
              value: "1-101,1-102",
              evidence: []
            }
          }
        }
      ]
    }
  };
  renderTaskDetail(foldedToolsDetail);

  const agentArea = await screen.findByLabelText("Agent 中间工作区");
  expect(within(agentArea).getByText("先读取总览文字")).toBeInTheDocument();
  expect(within(agentArea).getByText("最后写入字段")).toBeInTheDocument();
  expect(within(agentArea).getByText("Filled room_numbers")).toBeInTheDocument();

  const toolGroup = within(agentArea).getByRole("group", { name: "5 collapsed tools" });
  expect(within(toolGroup).getByText("Explored 3 files, saved 1 evidence item, reviewed 1 evidence set")).toBeInTheDocument();
  expect(within(toolGroup).queryByText("Read passage -> Viewed outline -> Saved evidence for room_numbers")).not.toBeInTheDocument();
  expect(within(agentArea).queryByLabelText("tool read")).not.toBeInTheDocument();
  expect(within(agentArea).queryByLabelText("tool tree")).not.toBeInTheDocument();
  expect(within(agentArea).queryByLabelText("tool add_candidate_evidence")).not.toBeInTheDocument();
  expect(within(agentArea).queryByLabelText("tool review_evidences")).not.toBeInTheDocument();

  await user.click(within(toolGroup).getByRole("button", { name: "展开 5 个工具调用" }));

  expect(within(agentArea).getAllByLabelText("tool read")).toHaveLength(2);
  expect(within(agentArea).getByLabelText("tool tree")).toBeInTheDocument();
  expect(within(agentArea).getByLabelText("tool add_candidate_evidence")).toBeInTheDocument();
  expect(within(agentArea).getByLabelText("tool review_evidences")).toBeInTheDocument();
});

it("关闭左任务栏后自动显示字段 Progress，字段列表只按字段排序", async () => {
  const user = userEvent.setup();
  renderTaskDetail(createMultiFieldDetail());

  expect(await screen.findByLabelText("任务工作台左侧任务栏")).toBeInTheDocument();
  expect(screen.queryByLabelText("字段进度面板")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "关闭任务栏" }));

  expect(screen.queryByLabelText("任务工作台左侧任务栏")).not.toBeInTheDocument();
  const rightPanel = screen.getByLabelText("右侧 Review 工作栏");
  const rightTabs = within(rightPanel).getByRole("tablist", { name: "右侧工作栏选项卡" });
  expect(within(rightTabs).getByRole("tab", { name: "Review" })).toHaveAttribute("aria-selected", "true");
  const progress = screen.getByLabelText("字段进度面板");
  expect(progress).toBeInTheDocument();
  expect(within(progress).getByRole("button", { name: /文明寝室房间号/ })).toBeInTheDocument();
  expect(within(progress).getByRole("button", { name: /楼栋名称/ })).toBeInTheDocument();
  expect(within(progress).getByRole("button", { name: /缺失字段/ })).toBeInTheDocument();
  expect(within(progress).queryByRole("heading", { name: "Review" })).not.toBeInTheDocument();
  expect(within(progress).queryByRole("heading", { name: "Reject" })).not.toBeInTheDocument();
  expect(within(progress).queryByRole("heading", { name: "Accept" })).not.toBeInTheDocument();
});

it("字段 Progress 显示字段摘要，点击字段不会占用 Review 工作区", async () => {
  const user = userEvent.setup();
  renderTaskDetail(createMultiFieldDetail());

  await user.click(await screen.findByRole("button", { name: "关闭任务栏" }));
  const progress = screen.getByLabelText("字段进度面板");
  expect(within(progress).getByText("候选证据支持字段值")).toBeInTheDocument();
  expect(within(progress).getByText("楼栋证据充分")).toBeInTheDocument();

  await user.click(within(progress).getByRole("button", { name: /楼栋名称/ }));

  expect(within(progress).getByRole("button", { name: /楼栋名称/ })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByLabelText("Agent 中间工作区")).toBeInTheDocument();
  expect(screen.queryByLabelText("Inspector 面板")).not.toBeInTheDocument();
  expect(screen.queryByRole("tablist", { name: "Inspector detail tabs" })).not.toBeInTheDocument();
});

it("点击 evidence 链接会打开顶层原文 tab，并定位高亮对应位置", async () => {
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
  await user.click(screen.getByRole("link", { name: "文明寝室证据" }));

  const rightPanel = screen.getByLabelText("右侧 Review 工作栏");
  const workspaceTabs = within(rightPanel).getByRole("tablist", { name: "右侧工作栏选项卡" });
  expect(within(workspaceTabs).getByRole("tab", { name: "Review" })).toHaveAttribute("aria-selected", "false");
  expect(within(workspaceTabs).getByRole("tab", { name: "sample.pdf" })).toHaveAttribute("aria-selected", "true");
  const sourceViewer = within(rightPanel).getByLabelText("原文查看器");
  const sourceFrameHtml = getSourceFrameHtml(sourceViewer);
  expect(screen.getByLabelText("Agent 中间工作区")).toBeInTheDocument();
  expect(sourceFrameHtml).not.toContain("Field value");
  expect(sourceFrameHtml).not.toContain("Evidence text");
  expect(sourceFrameHtml).not.toContain("Original location");
  expect(sourceFrameHtml).toContain("文明寝室名单");
  expect(sourceFrameHtml).toContain("一号楼包含文明寝室");
  expect(sourceFrameHtml).toContain('id="p001_b001" class="is-current-evidence" data-current-evidence="true"');
  expect(sourceFrameHtml).toContain("data-agent-gate-source-frame");
  expect(sourceViewer).toHaveAttribute("data-highlight-selector", "p001_b001");
  expect(screen.queryByText("evidence://task-001/p001_b001")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Inspector 面板")).not.toBeInTheDocument();
});

it("原文文件 tab 只显示解码后的文件名，原文内容上方不再重复文件标题", async () => {
  const user = userEvent.setup();
  const evidenceDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...encodedFilenameReplay,
      actions: [
        {
          tool_name: "read",
          reason: "查看 [文明寝室证据](evidence://task-001/p001_b001)",
          args: { path: "/001-sample/001-Notice.md" },
          result: { ok: true, path: "/001-sample/001-Notice.md", kind: "paragraph", text: "1-101、1-102 被列为文明寝室" }
        }
      ]
    }
  };
  renderTaskDetail(evidenceDetail);

  await user.click(await screen.findByRole("button", { name: "关闭任务栏" }));
  await user.click(screen.getByRole("link", { name: "文明寝室证据" }));

  const rightPanel = screen.getByLabelText("右侧 Review 工作栏");
  expect(within(rightPanel).getByRole("tab", { name: "Confidentiality and Non-Disclosure Agreement.pdf" })).toHaveAttribute("aria-selected", "true");
  expect(within(rightPanel).queryByRole("tab", { name: /%20/ })).not.toBeInTheDocument();
  expect(within(rightPanel).queryByRole("tab", { name: "/contracts/Confidentiality and Non-Disclosure Agreement.pdf" })).not.toBeInTheDocument();
  const sourceViewer = within(rightPanel).getByLabelText("原文查看器");
  expect(within(sourceViewer).queryByText("Confidentiality and Non-Disclosure Agreement.pdf")).not.toBeInTheDocument();
  expect(within(sourceViewer).queryByText("Confidentiality%20and%20Non-Disclosure%20Agreement.pdf")).not.toBeInTheDocument();
  expect(within(sourceViewer).queryByText("/contracts/Confidentiality and Non-Disclosure Agreement.pdf")).not.toBeInTheDocument();
});

it("点号 evidence URI 会打开原文文件 tab 并映射到真实 DOM 位置", async () => {
  const user = userEvent.setup();
  const evidenceDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...encodedFilenameReplay,
      display_html:
        '<main><section class="page"><p id="p001_b008">前一段</p><p id="p001_b009" data-element-id="p001_b009">ii) proprietary, non-public or confidential information</p></section></main>',
      source_selectors: { "0000.0001.0009": "p001_b009" },
      actions: [
        {
          tool_name: "read",
          reason: "查看 [定义证据](evidence://0000.0001.0009)",
          args: { path_id: "evidence://0000.0001.0009" },
          result: {
            ok: true,
            locator: "evidence://0000.0001.0009",
            kind: "paragraph",
            text: "ii) proprietary, non-public or confidential information"
          }
        }
      ]
    }
  };
  renderTaskDetail(evidenceDetail);

  await user.click(await screen.findByRole("button", { name: "关闭任务栏" }));
  await user.click(screen.getByRole("link", { name: "定义证据" }));

  const rightPanel = screen.getByLabelText("右侧 Review 工作栏");
  expect(within(rightPanel).getByRole("tab", { name: "Confidentiality and Non-Disclosure Agreement.pdf" })).toHaveAttribute("aria-selected", "true");
  const sourceViewer = within(rightPanel).getByLabelText("原文查看器");
  expect(sourceViewer).toHaveAttribute("data-highlight-selector", "p001_b009");
  expect(getSourceFrameHtml(sourceViewer)).toContain('id="p001_b009" data-element-id="p001_b009" class="is-current-evidence" data-current-evidence="true"');
});

it("0000.0001.0019 这类 base locator 会按实际段落定位，不会错配成 p001_b019", async () => {
  const user = userEvent.setup();
  const evidenceDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      display_html:
        '<main><section class="page"><h1 id="p001_b000">标题</h1><p id="p002_b004">or (c) has been independently acquired or developed by the undersigned or any of its Representatives without violation of any obligation under this NDA;</p></section></main>',
      source_selectors: { "0000.0001.0019": "p002_b004" },
      actions: [
        {
          tool_name: "read",
          reason: "查看独立开发例外",
          args: { path_id: "evidence://0000.0001.0019" },
          result: {
            ok: true,
            locator: "evidence://0000.0001.0019",
            kind: "paragraph",
            text: "normalized virtual tree text that cannot be matched against the display HTML"
          }
        },
        {
          tool_name: "add_candidate_evidence",
          reason: "保存 [独立开发例外](evidence://0000.0001.0019)",
          args: { field_id: "nda_12_decision", path_id: "evidence://0000.0001.0019" },
          result: { ok: true, field_id: "nda_12_decision", candidate_evidence: ["evidence://0000.0001.0019"] }
        }
      ]
    }
  };
  renderTaskDetail(evidenceDetail);

  await user.click(await screen.findByRole("button", { name: "关闭任务栏" }));
  await user.click(screen.getByRole("link", { name: "独立开发例外" }));

  const rightPanel = screen.getByLabelText("右侧 Review 工作栏");
  const sourceViewer = within(rightPanel).getByLabelText("原文查看器");
  expect(sourceViewer).toHaveAttribute("data-highlight-selector", "p002_b004");
  expect(getSourceFrameHtml(sourceViewer)).toContain('id="p002_b004" class="is-current-evidence" data-current-evidence="true"');
});

it("旧 replay 没有 source_selectors 时，短 quote 链接会在最小原文块内高亮 quote 本身", async () => {
  const user = userEvent.setup();
  const quoteText = "including any documents or copies (paper, electronic or otherwise) thereof";
  const longClause =
    "1. To maintain the Information in the strictest of confidence and to control the dissemination of the Information, including any documents or copies (paper, electronic or otherwise) thereof contained in the Information in accordance with the terms and conditions of this Confidentiality and Non-Disclosure Agreement (“NDA”);";
  const evidenceDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      display_html: `<main><section id="page_001"><h1>CONFIDENTIALITY AND NON-DISCLOSURE AGREEMENT</h1><p id="p001_b012">${longClause}</p><p id="p004_b004">OR</p></section></main>`,
      source_selectors: undefined,
      actions: [
        {
          tool_name: "read",
          reason: `查看 [${quoteText}](evidence://0000.0001.0012)`,
          args: { path_id: "evidence://0000.0001.0012" },
          result: {
            ok: true,
            locator: "evidence://0000.0001.0012",
            kind: "paragraph",
            text: longClause
          }
        }
      ]
    }
  };
  renderTaskDetail(evidenceDetail);

  await user.click(await screen.findByRole("button", { name: "关闭任务栏" }));
  await user.click(screen.getByRole("link", { name: quoteText }));

  const sourceViewer = within(screen.getByLabelText("右侧 Review 工作栏")).getByLabelText("原文查看器");
  expect(sourceViewer).toHaveAttribute("data-highlight-selector", "p001_b012");
  expect(getSourceFrameHtml(sourceViewer)).not.toContain('id="p001_b012" class="is-current-evidence" data-current-evidence="true"');
  expect(getSourceFrameHtml(sourceViewer)).toContain(`<mark class="is-current-evidence" data-current-evidence="true">${quoteText}</mark>`);
});

it("完整原文 tab 填满右侧框体，不再强制固定纸面宽度或横向滚动", async () => {
  const user = userEvent.setup();
  const evidenceDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      display_html: processedDisplayHtml,
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

  await user.click(await screen.findByRole("button", { name: "关闭任务栏" }));
  await user.click(screen.getByRole("link", { name: "文明寝室证据" }));

  const sourceViewer = screen.getByLabelText("原文查看器");
  const sourceFrame = within(sourceViewer).getByTitle("原文文档");
  const sourceFrameHtml = getSourceFrameHtml(sourceViewer);
  expect(sourceFrame).toHaveClass("replay-source-frame");
  expect(sourceFrameHtml).toContain("data-agent-gate-source-frame");
  expect(sourceFrameHtml).toContain("width: 100% !important");
  expect(sourceFrameHtml).toContain("max-width: 100% !important");
  expect(sourceFrameHtml).toContain("box-sizing: border-box");
  expect(sourceFrameHtml).toContain("overflow-x: hidden !important");
  expect(sourceFrameHtml).toContain("background: #ffffff !important");
  expect(sourceFrameHtml).toContain("padding: 0 !important");
  expect(sourceFrameHtml).toContain("border-radius: 0 !important");
  expect(sourceFrameHtml).toContain("box-shadow: none !important");
  expect(sourceFrameHtml).toContain("overflow-x: hidden !important");
  expect(sourceFrameHtml).toContain("table-layout: fixed !important");
  expect(sourceFrameHtml).toContain("white-space: pre-wrap !important");
  expect(sourceFrameHtml).toContain("overflow-wrap: anywhere !important");
  expect(sourceFrameHtml).not.toContain("min-width: 1060px !important");
  expect(sourceFrameHtml).not.toContain("width: 980px !important");
  expect(sourceFrameHtml).not.toContain("min-width: 980px !important");
  expect(sourceFrameHtml).toContain('id="p001_b001" class="is-current-evidence" data-current-evidence="true"');
  expect(sourceFrameHtml).not.toContain("<script>");
});

it("同一文件内不同 evidence 复用同一个原文文件 tab，只更新定位高亮", async () => {
  const user = userEvent.setup();
  const multiFieldDetail = createMultiFieldDetail();
  const evidenceDetail: TaskDetailData = {
    ...multiFieldDetail,
    replay: {
      ...multiFieldDetail.replay!,
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
  await user.click(screen.getByRole("tab", { name: "Review" }));
  await user.click(screen.getByRole("link", { name: "第二条证据" }));

  const rightPanel = screen.getByLabelText("右侧 Review 工作栏");
  const workspaceTabs = within(rightPanel).getByRole("tablist", { name: "右侧工作栏选项卡" });
  expect(within(workspaceTabs).getByRole("tab", { name: "sample.pdf" })).toHaveAttribute("aria-selected", "true");
  expect(within(workspaceTabs).queryByRole("tab", { name: "第一条证据" })).not.toBeInTheDocument();
  expect(within(workspaceTabs).queryByRole("tab", { name: "第二条证据" })).not.toBeInTheDocument();
  expect(within(workspaceTabs).getAllByRole("tab")).toHaveLength(2);
  const sourceViewer = within(rightPanel).getByLabelText("原文查看器");
  const sourceFrameHtml = getSourceFrameHtml(sourceViewer);
  expect(sourceFrameHtml).toContain("文明寝室名单");
  expect(sourceFrameHtml).toContain("1-101、1-102 被列为文明寝室");
  expect(sourceFrameHtml).toContain('id="p001_b002" class="is-current-evidence" data-current-evidence="true"');
  expect(sourceFrameHtml).not.toContain("Field value");
  expect(screen.queryByText("evidence://task-001/p001_b002")).not.toBeInTheDocument();

  await user.click(within(workspaceTabs).getByRole("button", { name: "关闭 sample.pdf" }));

  expect(within(workspaceTabs).queryByRole("tab", { name: "sample.pdf" })).not.toBeInTheDocument();
  expect(within(workspaceTabs).getByRole("tab", { name: "Review" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByLabelText("Agent 中间工作区")).toBeInTheDocument();
  expect(screen.getByLabelText("字段进度面板")).toBeInTheDocument();
});

it("不同文件的 evidence 才会打开不同原文文件 tab", async () => {
  const user = userEvent.setup();
  const multiDocumentDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      documents: [
        { document_id: "doc-1", filename: "sample-a.pdf" },
        { document_id: "doc-2", filename: "sample-b.pdf" }
      ],
      actions: [
        {
          tool_name: "read",
          reason: "查看 [第一份](evidence://001/p001_b001) 和 [第二份](evidence://002/p001_b002)",
          args: { path: "/001-sample/001-Notice.md" },
          result: { ok: true, path: "/001-sample/001-Notice.md", kind: "paragraph", text: "1-101、1-102 被列为文明寝室" }
        }
      ]
    }
  };
  renderTaskDetail(multiDocumentDetail);

  await user.click(await screen.findByRole("button", { name: "关闭任务栏" }));
  await user.click(screen.getByRole("link", { name: "第一份" }));
  await user.click(screen.getByRole("link", { name: "第二份" }));

  const workspaceTabs = within(screen.getByLabelText("右侧 Review 工作栏")).getByRole("tablist", { name: "右侧工作栏选项卡" });
  expect(within(workspaceTabs).getByRole("tab", { name: "sample-a.pdf" })).toBeInTheDocument();
  expect(within(workspaceTabs).getByRole("tab", { name: "sample-b.pdf" })).toHaveAttribute("aria-selected", "true");
  expect(within(workspaceTabs).getAllByRole("tab")).toHaveLength(3);
});

it("右侧原文栏可以拉伸到更宽，便于查看完整文件", async () => {
  renderTaskDetail();

  await userEvent.click(await screen.findByRole("button", { name: "关闭任务栏" }));

  const rightResizeHandle = screen.getByRole("separator", { name: "调整右侧栏宽度" });
  expect(rightResizeHandle).toHaveAttribute("aria-valuemax", "920");
});

it("点击 read 和 add_candidate_evidence 工具行会打开对应顶层原文 tab", async () => {
  const user = userEvent.setup();
  const toolJumpDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      actions: [
        {
          tool_name: "read",
          reason: "读取房间号所在段落",
          args: { path_id: "evidence://task-001/p001_b001" },
          result: {
            ok: true,
            locator: "evidence://task-001/p001_b001",
            path_id: "p001_b001",
            kind: "paragraph",
            text: "1-101、1-102 被列为文明寝室"
          }
        },
        {
          tool_name: "add_candidate_evidence",
          reason: "保存房间号候选证据",
          args: { field_id: "room_numbers", path_id: "evidence://task-001/p001_b001" },
          result: {
            ok: true,
            field_id: "room_numbers",
            candidate_evidence: ["evidence://task-001/p001_b001"]
          }
        }
      ]
    }
  };
  renderTaskDetail(toolJumpDetail);

  expect(await screen.findByLabelText("任务工作台左侧任务栏")).toBeInTheDocument();
  const readToolLink = screen.getByRole("link", { name: "tool read" });
  expect(readToolLink).toHaveAttribute("href", "evidence://task-001/p001_b001");
  await user.click(readToolLink);

  const rightPanel = screen.getByLabelText("右侧 Review 工作栏");
  expect(within(rightPanel).getByRole("tab", { name: "sample.pdf" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByLabelText("Agent 中间工作区")).toBeInTheDocument();
  const sourceViewer = within(rightPanel).getByLabelText("原文查看器");
  expect(sourceViewer).toHaveAttribute("data-highlight-selector", "p001_b001");
  let sourceFrameHtml = getSourceFrameHtml(sourceViewer);
  expect(sourceFrameHtml).toContain("文明寝室名单");
  expect(sourceFrameHtml).toContain("一号楼包含文明寝室");
  expect(sourceFrameHtml).toContain('id="p001_b001" class="is-current-evidence" data-current-evidence="true"');

  await user.click(within(rightPanel).getByRole("tab", { name: "Review" }));
  const addCandidateEvidenceToolLink = screen.getByRole("link", { name: "tool add_candidate_evidence" });
  expect(addCandidateEvidenceToolLink).toHaveAttribute("href", "evidence://task-001/p001_b001");
  await user.click(addCandidateEvidenceToolLink);

  expect(within(screen.getByLabelText("右侧 Review 工作栏")).getByRole("tab", { name: "sample.pdf" })).toHaveAttribute("aria-selected", "true");
  expect(within(screen.getByLabelText("右侧 Review 工作栏")).getByLabelText("原文查看器")).toHaveAttribute("data-highlight-selector", "p001_b001");
  sourceFrameHtml = getSourceFrameHtml(within(screen.getByLabelText("右侧 Review 工作栏")).getByLabelText("原文查看器"));
  expect(sourceFrameHtml).toContain('id="p001_b001" class="is-current-evidence" data-current-evidence="true"');
});

it("failed 任务会展示 backend 返回的失败原因", async () => {
  const failedSummary: TaskSummary = {
    task_id: "task-001",
    status: "failed",
    stage: "extraction",
    has_result: false,
    has_trace: false,
    error_message: "OCR worker crashed"
  };
  renderTaskDetail({
    summary: failedSummary,
    result: null,
    trace: null,
    replay: null,
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
      ...completedSummary,
      status: "failed",
      stage: "extraction",
      error_message: "字段抽取失败"
    }
  };

  renderTaskDetail(failedWithReplay);

  expect(await screen.findByText("任务失败")).toBeInTheDocument();
  expect(screen.getByText("字段抽取失败")).toBeInTheDocument();
  expect(screen.getByLabelText("Agent 中间工作区")).toBeInTheDocument();
  expect(screen.getByLabelText("Agent 文字流")).toBeInTheDocument();
});
