import { act, render, screen, waitFor, within } from "@testing-library/react";
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
    '<h1 id="p001_b000">文明寝室名单</h1><p id="0001.0000.0001">1-101、1-102 被列为文明寝室</p><p id="0001.0000.0002">一号楼包含文明寝室</p>',
  source_selectors: {
    "0001.0000.0001": "0001.0000.0001",
    "0001.0000.0002": "0001.0000.0002"
  },
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
      tool_name: "model_message",
      reason: "候选证据支持字段值",
      result: { ok: true }
    },
    {
      tool_name: "write_field",
      args: {
        field_id: "room_numbers",
        value: "1-101,1-102",
        final_evidence: [
          {
            path: "/001-sample/001-Notice.md",
            sentences: ["0001.0000.0001"]
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
              sentences: ["0001.0000.0001"]
            }
          ],
          evidence_texts: [
            {
              path: "/001-sample/001-Notice.md",
              selector: "0001.0000.0001",
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
  '<!doctype html><html lang="en"><head><meta charset="utf-8"><style>body { margin: 0; background: #f3f4f6; } main { max-width: 980px; margin: 0 auto; padding: 24px; } .page { background: #fff; padding: 44px 56px; }</style><script>window.__sourceScriptRan = true;</script></head><body><main><section class="page"><h1 id="p001_b000">文明寝室名单</h1><p id="0001.0000.0001">1-101、1-102 被列为文明寝室</p><p id="0001.0000.0002">一号楼包含文明寝室</p></section></main></body></html>';

const detailData: TaskDetailData = {
  summary: completedSummary,
  result: completedResult,
  trace: null,
  replay: baseReplay,
  audit: null
};

class FakeEventSource extends EventTarget {
  closed = false;

  constructor(public readonly url = "") {
    super();
  }

  emit(payload: unknown) {
    this.dispatchEvent(new MessageEvent("message", { data: JSON.stringify(payload) }));
  }

  emitEvent(eventName: string, payload: unknown) {
    this.dispatchEvent(new MessageEvent(eventName, { data: JSON.stringify(payload) }));
  }

  close() {
    this.closed = true;
  }
}

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
    createTaskEventSource?: (taskId: string, afterSeq?: number) => EventSource;
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
      createTaskEventSource={options.createTaskEventSource}
    />
  );

  return { injectedLoadTaskDetail, listTasks, ...renderResult };
}

function getSourceFrameHtml(sourceViewer: HTMLElement): string {
  const frame = within(sourceViewer).getByTitle("原文文档") as HTMLIFrameElement;
  return frame.getAttribute("srcdoc") ?? "";
}

function modelMessage(content: string): TaskReplay["actions"][number] {
  return {
    tool_name: "model_message",
    reason: content,
    result: { ok: true }
  };
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
                sentences: ["0001.0000.0002"]
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
                  sentences: ["0001.0000.0002"]
                }
              ],
              evidence_texts: [
                {
                  path: "/001-sample/001-Notice.md",
                  selector: "0001.0000.0002",
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

it("loadTaskDetail 在处理中也拉 replay 以便实时显示原文", async () => {
  const processingSummary: TaskSummary = {
    task_id: "task-live-source",
    status: "processing",
    stage: "extraction",
    has_result: false,
    has_trace: false,
    error_message: null,
    stream: {
      state: "running",
      last_event_seq: 4
    }
  };
  const runningReplay: TaskReplay = {
    ...baseReplay,
    task_id: "task-live-source",
    status: "processing",
    stage: "extraction",
    actions: []
  };
  global.fetch = jest.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/tasks/task-live-source")) {
      return jsonResponse(processingSummary);
    }
    if (url.endsWith("/tasks/task-live-source/replay")) {
      return jsonResponse(runningReplay);
    }
    throw new Error(`unexpected fetch: ${url}`);
  });

  const loaded = await loadTaskDetail("task-live-source");

  expect(loaded.summary).toEqual(processingSummary);
  expect(loaded.result).toBeNull();
  expect(loaded.replay).toEqual(runningReplay);
  expect(global.fetch).not.toHaveBeenCalledWith(expect.stringContaining("/result"), expect.anything());
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
  expect(within(topbar).getByRole("button", { name: "打开右侧 Review" })).toHaveAttribute("aria-pressed", "false");
  expect(within(topbar).getByText("task-001")).toHaveAttribute("title", "task-001");
  expect(within(topbar).queryByText("task-001 / sample.pdf")).not.toBeInTheDocument();
  expect(await screen.findByLabelText("任务工作台左侧任务栏")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "关闭任务栏" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "新任务" })).toHaveAttribute("href", "/");
  expect(screen.getByRole("link", { name: /task-001/ })).toHaveAttribute("href", "/tasks/task-001");
  expect(screen.getByRole("link", { name: /task-002/ })).toHaveAttribute("href", "/tasks/task-002");
  expect(screen.getByLabelText("Agent 中间工作区")).toBeInTheDocument();
  expect(screen.getByLabelText("Agent 中间工作区")).toHaveAttribute("data-agent-content-mode", "centered");
  expect(screen.getByText("候选证据支持字段值")).toBeInTheDocument();
  expect(screen.getByLabelText("Agent 对话输入框")).toBeInTheDocument();
  expect(screen.queryByLabelText("字段进度面板")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("右侧 Review 工作栏")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Inspector 面板")).not.toBeInTheDocument();
});

it("关闭左栏且未打开右栏时，Agent 仍保持居中内容框", async () => {
  const user = userEvent.setup();
  renderTaskDetail();

  await user.click(await screen.findByRole("button", { name: "关闭任务栏" }));

  const agentArea = screen.getByLabelText("Agent 中间工作区");
  expect(screen.queryByLabelText("任务工作台左侧任务栏")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("右侧 Review 工作栏")).not.toBeInTheDocument();
  expect(agentArea).toHaveAttribute("data-agent-balance-side", "none");
  expect(agentArea).toHaveAttribute("data-agent-content-mode", "centered");
});

it("Agent 流直接显示完整文字和工具行，不再暴露 replay 播放控制", async () => {
  const directStreamDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      actions: [
        modelMessage("读取 [文明寝室证据](evidence://0001.0000.0001)"),
        {
          tool_name: "read",
          args: { path: "/001-sample/001-Notice.md" },
          result: { ok: true, path: "/001-sample/001-Notice.md", kind: "paragraph" }
        },
        modelMessage("写入文明寝室字段"),
        {
          tool_name: "write_field",
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

it("tool action 的旧 reason 字段不进入 Agent 文字流", async () => {
  const reasonlessToolDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      actions: [
        {
          tool_name: "read",
          reason: "这个旧 reason 不应该显示",
          args: { path_id: "evidence://0001.0000.0001" },
          result: { ok: true, locator: "evidence://0001.0000.0001", kind: "paragraph", text: "1-101、1-102 被列为文明寝室" }
        }
      ]
    }
  };
  renderTaskDetail(reasonlessToolDetail);

  const agentArea = await screen.findByLabelText("Agent 中间工作区");
  expect(within(agentArea).queryByText("这个旧 reason 不应该显示")).not.toBeInTheDocument();
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
        modelMessage("先读取总览文字"),
        {
          tool_name: "read",
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
        modelMessage("最后写入字段"),
        {
          tool_name: "write_field",
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

it("终态 replay 保留文字和 tool group 的原始时间线位置", async () => {
  const timelineDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      actions: [
        modelMessage("先说明接下来读取原文"),
        {
          tool_name: "read",
          args: { path_id: "evidence://0001.0000.0001" },
          result: { ok: true, locator: "evidence://0001.0000.0001", kind: "paragraph" },
          metadata: { seq: 2 }
        },
        {
          tool_name: "add_candidate_evidence",
          args: { field_id: "room_numbers", path_id: "evidence://0001.0000.0001" },
          result: { ok: true, field_id: "room_numbers", candidate_evidence: ["evidence://0001.0000.0001"] },
          metadata: { seq: 3 }
        },
        modelMessage("读完后说明将写入字段"),
        {
          tool_name: "write_field",
          args: { field_id: "room_numbers", value: "1-101,1-102", final_evidence: [] },
          result: {
            ok: true,
            field: {
              field_id: "room_numbers",
              status: "resolved",
              value: "1-101,1-102",
              evidence: []
            }
          },
          metadata: { seq: 5 }
        }
      ]
    }
  };
  renderTaskDetail(timelineDetail);

  const agentArea = await screen.findByLabelText("Agent 中间工作区");
  const firstMessage = within(agentArea).getByText("先说明接下来读取原文");
  const toolGroup = within(agentArea).getByRole("group", { name: "2 collapsed tools" });
  const secondMessage = within(agentArea).getByText("读完后说明将写入字段");
  const writeField = within(agentArea).getByText("Filled room_numbers");
  expect(firstMessage.compareDocumentPosition(toolGroup) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(toolGroup.compareDocumentPosition(secondMessage) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(secondMessage.compareDocumentPosition(writeField) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

it("顶部最右侧 Review 按钮打开右侧字段 Progress，字段列表只按字段排序", async () => {
  const user = userEvent.setup();
  renderTaskDetail(createMultiFieldDetail());

  expect(await screen.findByLabelText("任务工作台左侧任务栏")).toBeInTheDocument();
  expect(screen.queryByLabelText("字段进度面板")).not.toBeInTheDocument();

  const topbar = screen.getByLabelText("Replay 顶部工具栏");
  const reviewButton = within(topbar).getByRole("button", { name: "打开右侧 Review" });
  expect(reviewButton).toHaveClass("replay-topbar-review-toggle");
  await user.click(reviewButton);

  expect(screen.getByLabelText("任务工作台左侧任务栏")).toBeInTheDocument();
  expect(within(topbar).getByRole("button", { name: "关闭右侧 Review" })).toHaveAttribute("aria-pressed", "true");
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

  await user.click(within(topbar).getByRole("button", { name: "关闭右侧 Review" }));
  expect(screen.queryByLabelText("右侧 Review 工作栏")).not.toBeInTheDocument();
});

it("字段 Progress 显示字段摘要，点击字段不会占用 Review 工作区", async () => {
  const user = userEvent.setup();
  renderTaskDetail(createMultiFieldDetail());

  await user.click(await screen.findByRole("button", { name: "打开右侧 Review" }));
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
        modelMessage("查看 [文明寝室证据](evidence://0001.0000.0001)"),
        {
          tool_name: "read",
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
  expect(sourceFrameHtml).toContain('id="0001.0000.0001" class="is-current-evidence" data-current-evidence="true"');
  expect(sourceFrameHtml).toContain("data-agent-gate-source-frame");
  expect(sourceViewer).toHaveAttribute("data-highlight-selector", "0001.0000.0001");
  expect(screen.queryByText("evidence://0001.0000.0001")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Inspector 面板")).not.toBeInTheDocument();
});

it("Agent model_message 用受控 Markdown 渲染面向用户的 outline", async () => {
  const user = userEvent.setup();
  const outlineDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      actions: [
        modelMessage(
          [
            "我先把结构分成几块：",
            "",
            "- **募集概要**：确认 [募集人員](evidence://0001.0000.0001)",
            "- `修士課程`：继续核对出愿条件"
          ].join("\n")
        )
      ]
    }
  };
  renderTaskDetail(outlineDetail);

  const agentArea = await screen.findByLabelText("Agent 中间工作区");
  expect(within(agentArea).getByText("募集概要", { selector: "strong" })).toBeInTheDocument();
  expect(within(agentArea).getByText("修士課程", { selector: "code" })).toBeInTheDocument();
  expect(within(agentArea).getAllByRole("listitem")).toHaveLength(2);

  await user.click(within(agentArea).getByRole("link", { name: "募集人員" }));

  const rightPanel = screen.getByLabelText("右侧 Review 工作栏");
  expect(within(rightPanel).getByRole("tab", { name: "sample.pdf" })).toHaveAttribute("aria-selected", "true");
  expect(getSourceFrameHtml(within(rightPanel).getByLabelText("原文查看器"))).toContain(
    'id="0001.0000.0001" class="is-current-evidence" data-current-evidence="true"'
  );
  expect(within(agentArea).queryByText("evidence://0001.0000.0001")).not.toBeInTheDocument();
});

it("点击连续 block range evidence 链接会打开原文并高亮整段连续 block", async () => {
  const user = userEvent.setup();
  const evidenceDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      display_html:
        '<main><section class="page"><p id="0001.0028.0002">先注册 Web 出願系统。</p><p id="0001.0028.0003">再输入志愿信息。</p><p id="0001.0028.0004">然后缴纳选考料并生成マイページ。</p><p id="0001.0028.0005">最后上传 PDF 出願书类。</p></section></main>',
      source_selectors: {
        "0001.0028.0002": "0001.0028.0002",
        "0001.0028.0003": "0001.0028.0003",
        "0001.0028.0004": "0001.0028.0004",
        "0001.0028.0005": "0001.0028.0005"
      },
      actions: [
        modelMessage("出愿流程见 [出願手順一式](evidence://range/0001.0028.0002/0001.0028.0005)"),
        {
          tool_name: "read",
          args: { path_id: "evidence://0001.0028.0002" },
          result: { ok: true, locator: "evidence://0001.0028.0002", kind: "paragraph", text: "先注册 Web 出願系统。" }
        }
      ]
    }
  };
  renderTaskDetail(evidenceDetail);

  expect(await screen.findByLabelText("任务工作台左侧任务栏")).toBeInTheDocument();
  await user.click(screen.getByRole("link", { name: "出願手順一式" }));

  const rightPanel = screen.getByLabelText("右侧 Review 工作栏");
  expect(within(rightPanel).getByRole("tab", { name: "sample.pdf" })).toHaveAttribute("aria-selected", "true");
  const sourceViewer = within(rightPanel).getByLabelText("原文查看器");
  const sourceFrameHtml = getSourceFrameHtml(sourceViewer);
  expect(sourceViewer).toHaveAttribute("data-highlight-selector", "0001.0028.0002");
  expect(sourceFrameHtml).toContain('id="0001.0028.0002" class="is-current-evidence" data-current-evidence="true"');
  expect(sourceFrameHtml).toContain('id="0001.0028.0003" class="is-current-evidence" data-current-evidence="true"');
  expect(sourceFrameHtml).toContain('id="0001.0028.0004" class="is-current-evidence" data-current-evidence="true"');
  expect(sourceFrameHtml).toContain('id="0001.0028.0005" class="is-current-evidence" data-current-evidence="true"');
});

it("连续 block range evidence 会按起始 block 所属文件打开正确原文 tab", async () => {
  const user = userEvent.setup();
  const evidenceDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      documents: [
        { document_id: "doc-1", filename: "sample-a.pdf" },
        { document_id: "doc-2", filename: "sample-b.pdf" }
      ],
      display_html:
        '<main><section class="page"><p id="0002.0001.0001">先在第二份文件中确认报名资格。</p><p id="0002.0001.0002">再准备并上传修士申请书类。</p></section></main>',
      source_selectors: {
        "0002.0001.0001": "0002.0001.0001",
        "0002.0001.0002": "0002.0001.0002"
      },
      actions: [
        modelMessage("第二份材料见 [修士申请流程](evidence://range/0002.0001.0001/0002.0001.0002)")
      ]
    }
  };
  renderTaskDetail(evidenceDetail);

  expect(await screen.findByLabelText("任务工作台左侧任务栏")).toBeInTheDocument();
  await user.click(screen.getByRole("link", { name: "修士申请流程" }));

  const rightPanel = screen.getByLabelText("右侧 Review 工作栏");
  expect(within(rightPanel).getByRole("tab", { name: "sample-b.pdf" })).toHaveAttribute("aria-selected", "true");
  const sourceViewer = within(rightPanel).getByLabelText("原文查看器");
  expect(sourceViewer).toHaveAttribute("data-highlight-selector", "0002.0001.0001");
});

it("原文文件 tab 只显示解码后的文件名，原文内容上方不再重复文件标题", async () => {
  const user = userEvent.setup();
  const evidenceDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...encodedFilenameReplay,
      actions: [
        modelMessage("查看 [文明寝室证据](evidence://0001.0000.0001)"),
        {
          tool_name: "read",
          args: { path: "/001-sample/001-Notice.md" },
          result: { ok: true, path: "/001-sample/001-Notice.md", kind: "paragraph", text: "1-101、1-102 被列为文明寝室" }
        }
      ]
    }
  };
  renderTaskDetail(evidenceDetail);

  expect(await screen.findByLabelText("任务工作台左侧任务栏")).toBeInTheDocument();
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
        '<main><section class="page"><p id="0001.0000.0008">前一段</p><p id="0001.0000.0009" data-element-id="0001.0000.0009">ii) proprietary, non-public or confidential information</p></section></main>',
      source_selectors: { "0001.0000.0009": "0001.0000.0009" },
      actions: [
        modelMessage("查看 [定义证据](evidence://0001.0000.0009)"),
        {
          tool_name: "read",
          args: { path_id: "evidence://0001.0000.0009" },
          result: {
            ok: true,
            locator: "evidence://0001.0000.0009",
            kind: "paragraph",
            text: "ii) proprietary, non-public or confidential information"
          }
        }
      ]
    }
  };
  renderTaskDetail(evidenceDetail);

  expect(await screen.findByLabelText("任务工作台左侧任务栏")).toBeInTheDocument();
  await user.click(screen.getByRole("link", { name: "定义证据" }));

  const rightPanel = screen.getByLabelText("右侧 Review 工作栏");
  expect(within(rightPanel).getByRole("tab", { name: "Confidentiality and Non-Disclosure Agreement.pdf" })).toHaveAttribute("aria-selected", "true");
  const sourceViewer = within(rightPanel).getByLabelText("原文查看器");
  expect(sourceViewer).toHaveAttribute("data-highlight-selector", "0001.0000.0009");
  expect(getSourceFrameHtml(sourceViewer)).toContain('id="0001.0000.0009" data-element-id="0001.0000.0009" class="is-current-evidence" data-current-evidence="true"');
});

it("0001.0019.0001 这类 base locator 会按实际段落定位，不会错配成旧 DOM id", async () => {
  const user = userEvent.setup();
  const evidenceDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      display_html:
        '<main><section class="page"><h1 id="p001_b000">标题</h1><p id="0001.0019.0001">or (c) has been independently acquired or developed by the undersigned or any of its Representatives without violation of any obligation under this NDA;</p></section></main>',
      source_selectors: { "0001.0019.0001": "0001.0019.0001" },
      actions: [
        {
          tool_name: "read",
          args: { path_id: "evidence://0001.0019.0001" },
          result: {
            ok: true,
            locator: "evidence://0001.0019.0001",
            kind: "paragraph",
            text: "normalized virtual tree text that cannot be matched against the display HTML"
          }
        },
        modelMessage("保存 [独立开发例外](evidence://0001.0019.0001)"),
        {
          tool_name: "add_candidate_evidence",
          args: { field_id: "nda_12_decision", path_id: "evidence://0001.0019.0001" },
          result: { ok: true, field_id: "nda_12_decision", candidate_evidence: ["evidence://0001.0019.0001"] }
        }
      ]
    }
  };
  renderTaskDetail(evidenceDetail);

  expect(await screen.findByLabelText("任务工作台左侧任务栏")).toBeInTheDocument();
  await user.click(screen.getByRole("link", { name: "独立开发例外" }));

  const rightPanel = screen.getByLabelText("右侧 Review 工作栏");
  const sourceViewer = within(rightPanel).getByLabelText("原文查看器");
  expect(sourceViewer).toHaveAttribute("data-highlight-selector", "0001.0019.0001");
  expect(getSourceFrameHtml(sourceViewer)).toContain('id="0001.0019.0001" class="is-current-evidence" data-current-evidence="true"');
});

it("旧 replay 没有 source_selectors 时，evidence 链接只打开原文，不猜测 DOM 高亮位置", async () => {
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
        modelMessage(`查看 [${quoteText}](evidence://0000.0001.0012)`),
        {
          tool_name: "read",
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

  expect(await screen.findByLabelText("任务工作台左侧任务栏")).toBeInTheDocument();
  await user.click(screen.getByRole("link", { name: quoteText }));

  const sourceViewer = within(screen.getByLabelText("右侧 Review 工作栏")).getByLabelText("原文查看器");
  expect(sourceViewer).toHaveAttribute("data-highlight-selector", "");
  expect(getSourceFrameHtml(sourceViewer)).toContain(longClause);
  expect(getSourceFrameHtml(sourceViewer)).not.toContain('class="is-current-evidence" data-current-evidence="true"');
  expect(getSourceFrameHtml(sourceViewer)).not.toContain('<mark class="is-current-evidence"');
});

it("完整原文 tab 填满右侧框体，不再强制固定纸面宽度或横向滚动", async () => {
  const user = userEvent.setup();
  const evidenceDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      display_html: processedDisplayHtml,
      actions: [
        modelMessage("查看 [文明寝室证据](evidence://0001.0000.0001)"),
        {
          tool_name: "read",
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
  expect(sourceFrameHtml).toContain('id="0001.0000.0001" class="is-current-evidence" data-current-evidence="true"');
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
        modelMessage("查看 [第一条证据](evidence://0001.0000.0001) 和 [第二条证据](evidence://0001.0000.0002)"),
        {
          tool_name: "read",
          args: { path: "/001-sample/001-Notice.md" },
          result: { ok: true, path: "/001-sample/001-Notice.md", kind: "paragraph", text: "1-101、1-102 被列为文明寝室" }
        }
      ]
    }
  };
  renderTaskDetail(evidenceDetail);

  expect(await screen.findByLabelText("任务工作台左侧任务栏")).toBeInTheDocument();
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
  expect(sourceFrameHtml).toContain('id="0001.0000.0002" class="is-current-evidence" data-current-evidence="true"');
  expect(sourceFrameHtml).not.toContain("Field value");
  expect(screen.queryByText("evidence://0001.0000.0002")).not.toBeInTheDocument();

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
        modelMessage("查看 [第一份](evidence://0001.0000.0001) 和 [第二份](evidence://0002.0000.0002)"),
        {
          tool_name: "read",
          args: { path: "/001-sample/001-Notice.md" },
          result: { ok: true, path: "/001-sample/001-Notice.md", kind: "paragraph", text: "1-101、1-102 被列为文明寝室" }
        }
      ]
    }
  };
  renderTaskDetail(multiDocumentDetail);

  expect(await screen.findByLabelText("任务工作台左侧任务栏")).toBeInTheDocument();
  await user.click(screen.getByRole("link", { name: "第一份" }));
  await user.click(screen.getByRole("link", { name: "第二份" }));

  const workspaceTabs = within(screen.getByLabelText("右侧 Review 工作栏")).getByRole("tablist", { name: "右侧工作栏选项卡" });
  expect(within(workspaceTabs).getByRole("tab", { name: "sample-a.pdf" })).toBeInTheDocument();
  expect(within(workspaceTabs).getByRole("tab", { name: "sample-b.pdf" })).toHaveAttribute("aria-selected", "true");
  expect(within(workspaceTabs).getAllByRole("tab")).toHaveLength(3);
});

it("右侧原文栏可以拉伸到更宽，便于查看完整文件", async () => {
  renderTaskDetail();

  await userEvent.click(await screen.findByRole("button", { name: "打开右侧 Review" }));

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
          args: { path_id: "evidence://0001.0000.0001" },
          result: {
            ok: true,
            locator: "evidence://0001.0000.0001",
            path_id: "0001.0000.0001",
            kind: "paragraph",
            text: "1-101、1-102 被列为文明寝室"
          }
        },
        {
          tool_name: "add_candidate_evidence",
          args: { field_id: "room_numbers", path_id: "evidence://0001.0000.0001" },
          result: {
            ok: true,
            field_id: "room_numbers",
            candidate_evidence: ["evidence://0001.0000.0001"]
          }
        }
      ]
    }
  };
  renderTaskDetail(toolJumpDetail);

  expect(await screen.findByLabelText("任务工作台左侧任务栏")).toBeInTheDocument();
  const agentArea = screen.getByLabelText("Agent 中间工作区");
  const toolGroup = within(agentArea).getByRole("group", { name: "2 collapsed tools" });
  await user.click(within(toolGroup).getByRole("button", { name: "展开 2 个工具调用" }));

  const readToolLink = screen.getByRole("link", { name: "tool read" });
  expect(readToolLink).toHaveAttribute("href", "evidence://0001.0000.0001");
  await user.click(readToolLink);

  const rightPanel = screen.getByLabelText("右侧 Review 工作栏");
  expect(within(rightPanel).getByRole("tab", { name: "sample.pdf" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByLabelText("Agent 中间工作区")).toBeInTheDocument();
  const sourceViewer = within(rightPanel).getByLabelText("原文查看器");
  expect(sourceViewer).toHaveAttribute("data-highlight-selector", "0001.0000.0001");
  let sourceFrameHtml = getSourceFrameHtml(sourceViewer);
  expect(sourceFrameHtml).toContain("文明寝室名单");
  expect(sourceFrameHtml).toContain("一号楼包含文明寝室");
  expect(sourceFrameHtml).toContain('id="0001.0000.0001" class="is-current-evidence" data-current-evidence="true"');

  await user.click(within(rightPanel).getByRole("tab", { name: "Review" }));
  const addCandidateEvidenceToolLink = screen.getByRole("link", { name: "tool add_candidate_evidence" });
  expect(addCandidateEvidenceToolLink).toHaveAttribute("href", "evidence://0001.0000.0001");
  await user.click(addCandidateEvidenceToolLink);

  expect(within(screen.getByLabelText("右侧 Review 工作栏")).getByRole("tab", { name: "sample.pdf" })).toHaveAttribute("aria-selected", "true");
  expect(within(screen.getByLabelText("右侧 Review 工作栏")).getByLabelText("原文查看器")).toHaveAttribute("data-highlight-selector", "0001.0000.0001");
  sourceFrameHtml = getSourceFrameHtml(within(screen.getByLabelText("右侧 Review 工作栏")).getByLabelText("原文查看器"));
  expect(sourceFrameHtml).toContain('id="0001.0000.0001" class="is-current-evidence" data-current-evidence="true"');
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

it("处理中任务详情先显示常规对话工作台和 Thinking，再自动刷新到 replay", async () => {
  jest.useFakeTimers();
  const processingDetail: TaskDetailData = {
    summary: {
      task_id: "task-live",
      status: "processing",
      stage: "document_processing",
      has_result: false,
      has_trace: false,
      error_message: null,
      stream: {
        state: "running",
        last_event_seq: 1
      }
    },
    result: null,
    trace: null,
    replay: null,
    audit: null
  };
  const completedLiveDetail: TaskDetailData = {
    ...detailData,
    summary: {
      ...completedSummary,
      task_id: "task-live",
      stream: {
        state: "ended",
        last_event_seq: 8
      }
    },
    result: {
      ...completedResult,
      task_id: "task-live"
    },
    replay: {
      ...baseReplay,
      task_id: "task-live"
    }
  };
  const loadTaskDetail = jest
    .fn<Promise<TaskDetailData>, [string]>()
    .mockResolvedValueOnce(processingDetail)
    .mockResolvedValueOnce(completedLiveDetail);

  try {
    renderTaskDetail(processingDetail, { taskId: "task-live", loadTaskDetail });

    expect(await screen.findByLabelText("Agent 中间工作区")).toBeInTheDocument();
    expect(screen.getByLabelText("Agent 文字流")).toBeInTheDocument();
    expect(screen.getByText("Thinking")).toBeInTheDocument();
    expect(screen.queryByText("正在处理任务...")).not.toBeInTheDocument();
    expect(screen.queryByText("暂无 replay 数据。")).not.toBeInTheDocument();

    await jest.advanceTimersByTimeAsync(1500);

    expect(await screen.findByText("候选证据支持字段值")).toBeInTheDocument();
    await waitFor(() => expect(loadTaskDetail).toHaveBeenCalledTimes(2));
  } finally {
    jest.useRealTimers();
  }
});

it("处理中任务详情会消费事件流并实时追加 Agent 工具输出", async () => {
  const processingDetail: TaskDetailData = {
    summary: {
      task_id: "task-streaming",
      status: "processing",
      stage: "extraction",
      has_result: false,
      has_trace: false,
      error_message: null,
      stream: {
        state: "running",
        last_event_seq: 1
      }
    },
    result: null,
    trace: null,
    replay: null,
    audit: null
  };
  const eventSources: FakeEventSource[] = [];
  const createTaskEventSource = jest.fn((_taskId: string, afterSeq = 0) => {
    const eventSource = new FakeEventSource(String(afterSeq));
    eventSources.push(eventSource);
    return eventSource as unknown as EventSource;
  });

  renderTaskDetail(processingDetail, {
    taskId: "task-streaming",
    createTaskEventSource,
    loadTaskDetail: async () => processingDetail
  });

  expect(await screen.findByText("Thinking")).toBeInTheDocument();
  expect(createTaskEventSource).toHaveBeenCalledWith("task-streaming", 0);

  await act(async () => {
    eventSources[0].emitEvent("task.stage_changed", {
      seq: 2,
      task_id: "task-streaming",
      type: "task.stage_changed",
      status: "processing",
      stage: "extraction",
      payload: {}
    });
  });

  expect(createTaskEventSource).toHaveBeenCalledTimes(1);

  await act(async () => {
    eventSources[0].emitEvent("agent.event", {
      seq: 3,
      task_id: "task-streaming",
      type: "agent.event",
      status: "processing",
      stage: "extraction",
      payload: {
        type: "model_message",
        content: "查看目录"
      }
    });
    eventSources[0].emitEvent("agent.event", {
      seq: 4,
      task_id: "task-streaming",
      type: "agent.event",
      status: "processing",
      stage: "extraction",
      payload: {
        type: "tool_completed",
        tool: "tree",
        result: { ok: true }
      }
    });
  });

  expect(await screen.findByText("查看目录")).toBeInTheDocument();
  expect(screen.getByText("Viewed outline")).toBeInTheDocument();
  expect(createTaskEventSource).toHaveBeenCalledTimes(1);
});

it("刷新从头回放时不把同一工具的 start、completed 和 replay action 重复显示", async () => {
  const readAction = {
    tool_name: "read",
    args: { path_id: "0001.0000.0001" },
    result: { ok: true, locator: "0001.0000.0001", kind: "paragraph", text: "1-101、1-102 被列为文明寝室" }
  };
  const processingDetail: TaskDetailData = {
    summary: {
      task_id: "task-no-duplicate-live",
      status: "processing",
      stage: "extraction",
      has_result: false,
      has_trace: false,
      error_message: null,
      stream: {
        state: "running",
        last_event_seq: 4
      }
    },
    result: null,
    trace: null,
    replay: {
      ...baseReplay,
      task_id: "task-no-duplicate-live",
      status: "processing",
      stage: "extraction",
      actions: [modelMessage("读取证据"), readAction]
    },
    audit: null
  };
  const eventSources: FakeEventSource[] = [];
  const createTaskEventSource = jest.fn((_taskId: string, afterSeq = 0) => {
    const eventSource = new FakeEventSource(String(afterSeq));
    eventSources.push(eventSource);
    return eventSource as unknown as EventSource;
  });

  renderTaskDetail(processingDetail, {
    taskId: "task-no-duplicate-live",
    createTaskEventSource,
    loadTaskDetail: async () => processingDetail
  });

  expect(await screen.findByText("Read passage")).toBeInTheDocument();
  expect(screen.getAllByText("Read passage")).toHaveLength(1);

  await act(async () => {
    eventSources[0].emitEvent("agent.event", {
      seq: 2,
      task_id: "task-no-duplicate-live",
      type: "agent.event",
      status: "processing",
      stage: "extraction",
      payload: {
        type: "tool_started",
        tool: "read",
        args: { path_id: "0001.0000.0001" }
      }
    });
    eventSources[0].emitEvent("agent.event", {
      seq: 3,
      task_id: "task-no-duplicate-live",
      type: "agent.event",
      status: "processing",
      stage: "extraction",
      payload: {
        type: "tool_completed",
        tool: "read",
        args: { path_id: "0001.0000.0001" },
        result: { ok: true, locator: "0001.0000.0001", kind: "paragraph", text: "1-101、1-102 被列为文明寝室" }
      }
    });
  });

  expect(screen.getAllByText("读取证据")).toHaveLength(1);
  expect(screen.getAllByText("Read passage")).toHaveLength(1);
});

it("空 model_message 不渲染成 Thinking 工具行，前后工具继续按组折叠", async () => {
  const processingDetail: TaskDetailData = {
    summary: {
      task_id: "task-empty-content",
      status: "processing",
      stage: "extraction",
      has_result: false,
      has_trace: false,
      error_message: null,
      stream: {
        state: "running",
        last_event_seq: 1
      }
    },
    result: null,
    trace: null,
    replay: null,
    audit: null
  };
  const eventSources: FakeEventSource[] = [];
  const createTaskEventSource = jest.fn((_taskId: string, afterSeq = 0) => {
    const eventSource = new FakeEventSource(String(afterSeq));
    eventSources.push(eventSource);
    return eventSource as unknown as EventSource;
  });

  renderTaskDetail(processingDetail, {
    taskId: "task-empty-content",
    createTaskEventSource,
    loadTaskDetail: async () => processingDetail
  });

  expect(await screen.findByText("Thinking")).toBeInTheDocument();

  await act(async () => {
    eventSources[0].emitEvent("agent.event", {
      seq: 2,
      task_id: "task-empty-content",
      type: "agent.event",
      status: "processing",
      stage: "extraction",
      payload: {
        type: "model_message",
        content: ""
      }
    });
    eventSources[0].emitEvent("agent.event", {
      seq: 3,
      task_id: "task-empty-content",
      type: "agent.event",
      status: "processing",
      stage: "extraction",
      payload: {
        type: "tool_completed",
        tool: "tree",
        reason: "",
        result: { ok: true }
      }
    });
    eventSources[0].emitEvent("agent.event", {
      seq: 4,
      task_id: "task-empty-content",
      type: "agent.event",
      status: "processing",
      stage: "extraction",
      payload: {
        type: "tool_completed",
        tool: "read",
        reason: "",
        result: { ok: true, locator: "evidence://0001.0000.0001", kind: "paragraph" }
      }
    });
  });

  const agentArea = screen.getByLabelText("Agent 中间工作区");
  const toolGroup = await within(agentArea).findByRole("group", { name: "2 collapsed tools" });
  expect(within(toolGroup).getByText("Explored 2 files")).toBeInTheDocument();
  expect(within(agentArea).queryByText("Thinking")).not.toBeInTheDocument();
  expect(within(agentArea).queryByLabelText("tool model_message")).not.toBeInTheDocument();
});

it("处理中 source_indexed 事件会刷新出原文 replay", async () => {
  const processingDetail: TaskDetailData = {
    summary: {
      task_id: "task-live-source",
      status: "processing",
      stage: "extraction",
      has_result: false,
      has_trace: false,
      error_message: null,
      stream: {
        state: "running",
        last_event_seq: 1
      }
    },
    result: null,
    trace: null,
    replay: null,
    audit: null
  };
  const processingWithReplay: TaskDetailData = {
    ...processingDetail,
    replay: {
      ...baseReplay,
      task_id: "task-live-source",
      status: "processing",
      stage: "extraction",
      actions: []
    }
  };
  const eventSources: FakeEventSource[] = [];
  const createTaskEventSource = jest.fn((_taskId: string, afterSeq = 0) => {
    const eventSource = new FakeEventSource(String(afterSeq));
    eventSources.push(eventSource);
    return eventSource as unknown as EventSource;
  });
  const loadTaskDetail = jest
    .fn<Promise<TaskDetailData>, [string]>()
    .mockResolvedValueOnce(processingDetail)
    .mockResolvedValueOnce(processingWithReplay);

  renderTaskDetail(processingDetail, {
    taskId: "task-live-source",
    createTaskEventSource,
    loadTaskDetail
  });

  expect(await screen.findByText("Thinking")).toBeInTheDocument();

  await act(async () => {
    eventSources[0].emitEvent("agent.event", {
      seq: 2,
      task_id: "task-live-source",
      type: "agent.event",
      status: "processing",
      stage: "extraction",
      payload: {
        type: "source_indexed",
        tool: "source_index",
        result: {
          ok: true,
          source_selectors: { "0001.0000.0001": "0001.0000.0001" }
        }
      }
    });
  });

  await waitFor(() => expect(loadTaskDetail).toHaveBeenCalledTimes(2));
  expect(await screen.findByLabelText("Agent 中间工作区")).toBeInTheDocument();
});

it("实时追加工具输出时，用户不在底部就保持当前阅读位置", async () => {
  const processingDetail: TaskDetailData = {
    summary: {
      task_id: "task-no-autoscroll",
      status: "processing",
      stage: "extraction",
      has_result: false,
      has_trace: false,
      error_message: null,
      stream: {
        state: "running",
        last_event_seq: 1
      }
    },
    result: null,
    trace: null,
    replay: null,
    audit: null
  };
  const eventSources: FakeEventSource[] = [];
  const createTaskEventSource = jest.fn((_taskId: string, afterSeq = 0) => {
    const eventSource = new FakeEventSource(String(afterSeq));
    eventSources.push(eventSource);
    return eventSource as unknown as EventSource;
  });

  renderTaskDetail(processingDetail, {
    taskId: "task-no-autoscroll",
    createTaskEventSource,
    loadTaskDetail: async () => processingDetail
  });

  const agentStream = await screen.findByLabelText("Agent 文字流");
  Object.defineProperty(agentStream, "scrollHeight", { configurable: true, value: 999 });
  Object.defineProperty(agentStream, "clientHeight", { configurable: true, value: 120 });
  agentStream.scrollTop = 17;
  await act(async () => {
    agentStream.dispatchEvent(new Event("scroll"));
  });

  await act(async () => {
    eventSources[0].emitEvent("agent.event", {
      seq: 2,
      task_id: "task-no-autoscroll",
      type: "agent.event",
      status: "processing",
      stage: "extraction",
      payload: {
        type: "tool_completed",
        tool: "read",
        args: { path_id: "evidence://0001.0000.0001" },
        result: { ok: true, locator: "evidence://0001.0000.0001", kind: "paragraph", text: "1-101 被列为文明寝室" }
      }
    });
  });

  expect(await screen.findByText("Read passage")).toBeInTheDocument();
  expect(agentStream.scrollTop).toBe(17);
});

it("实时追加工具输出时，用户在底部就继续跟随到底部", async () => {
  const processingDetail: TaskDetailData = {
    summary: {
      task_id: "task-autoscroll-bottom",
      status: "processing",
      stage: "extraction",
      has_result: false,
      has_trace: false,
      error_message: null,
      stream: {
        state: "running",
        last_event_seq: 1
      }
    },
    result: null,
    trace: null,
    replay: null,
    audit: null
  };
  const eventSources: FakeEventSource[] = [];
  const createTaskEventSource = jest.fn((_taskId: string, afterSeq = 0) => {
    const eventSource = new FakeEventSource(String(afterSeq));
    eventSources.push(eventSource);
    return eventSource as unknown as EventSource;
  });

  renderTaskDetail(processingDetail, {
    taskId: "task-autoscroll-bottom",
    createTaskEventSource,
    loadTaskDetail: async () => processingDetail
  });

  const agentStream = await screen.findByLabelText("Agent 文字流");
  let streamScrollHeight = 500;
  Object.defineProperty(agentStream, "scrollHeight", {
    configurable: true,
    get: () => streamScrollHeight
  });
  Object.defineProperty(agentStream, "clientHeight", { configurable: true, value: 100 });
  agentStream.scrollTop = 400;
  await act(async () => {
    agentStream.dispatchEvent(new Event("scroll"));
  });

  streamScrollHeight = 999;
  await act(async () => {
    eventSources[0].emitEvent("agent.event", {
      seq: 2,
      task_id: "task-autoscroll-bottom",
      type: "agent.event",
      status: "processing",
      stage: "extraction",
      payload: {
        type: "tool_completed",
        tool: "read",
        args: { path_id: "evidence://0001.0000.0001" },
        result: { ok: true, locator: "evidence://0001.0000.0001", kind: "paragraph", text: "1-101 被列为文明寝室" }
      }
    });
  });

  expect(await screen.findByText("Read passage")).toBeInTheDocument();
  expect(agentStream.scrollTop).toBe(999);
});

it("处理中已有 replay 时，live read 工具行能打开原文并高亮", async () => {
  const processingDetail: TaskDetailData = {
    summary: {
      task_id: "task-live-highlight",
      status: "processing",
      stage: "extraction",
      has_result: false,
      has_trace: false,
      error_message: null,
      stream: {
        state: "running",
        last_event_seq: 1
      }
    },
    result: null,
    trace: null,
    replay: {
      ...baseReplay,
      task_id: "task-live-highlight",
      status: "processing",
      stage: "extraction",
      actions: []
    },
    audit: null
  };
  const eventSources: FakeEventSource[] = [];
  const createTaskEventSource = jest.fn((_taskId: string, afterSeq = 0) => {
    const eventSource = new FakeEventSource(String(afterSeq));
    eventSources.push(eventSource);
    return eventSource as unknown as EventSource;
  });

  renderTaskDetail(processingDetail, {
    taskId: "task-live-highlight",
    createTaskEventSource,
    loadTaskDetail: async () => processingDetail
  });

  await act(async () => {
    eventSources[0].emitEvent("agent.event", {
      seq: 2,
      task_id: "task-live-highlight",
      type: "agent.event",
      status: "processing",
      stage: "extraction",
      payload: {
        type: "tool_completed",
        tool: "read",
        args: { path_id: "evidence://0001.0000.0001" },
        result: { ok: true, locator: "evidence://0001.0000.0001", kind: "paragraph", text: "1-101、1-102 被列为文明寝室" }
      }
    });
  });

  const readToolLink = await screen.findByRole("link", { name: "tool read" });
  await userEvent.click(readToolLink);

  const sourceViewer = within(screen.getByLabelText("右侧 Review 工作栏")).getByLabelText("原文查看器");
  expect(sourceViewer).toHaveAttribute("data-highlight-selector", "0001.0000.0001");
  expect(getSourceFrameHtml(sourceViewer)).toContain('id="0001.0000.0001" class="is-current-evidence" data-current-evidence="true"');
});

it("处理中已有 replay actions 时，live 裸 path_id 可跳原文且字段 Progress 实时更新", async () => {
  const processingDetail: TaskDetailData = {
    summary: {
      task_id: "task-live-merge",
      status: "processing",
      stage: "extraction",
      has_result: false,
      has_trace: false,
      error_message: null,
      stream: {
        state: "running",
        last_event_seq: 1
      }
    },
    result: null,
    trace: null,
    replay: {
      ...baseReplay,
      task_id: "task-live-merge",
      status: "processing",
      stage: "extraction",
      actions: [
        {
          tool_name: "tree",
          reason: "",
          args: { path_id: "0001.0000.0000" },
          result: { ok: true, locator: "0001.0000.0000" }
        }
      ]
    },
    audit: null
  };
  const eventSources: FakeEventSource[] = [];
  const createTaskEventSource = jest.fn((_taskId: string, afterSeq = 0) => {
    const eventSource = new FakeEventSource(String(afterSeq));
    eventSources.push(eventSource);
    return eventSource as unknown as EventSource;
  });

  renderTaskDetail(processingDetail, {
    taskId: "task-live-merge",
    createTaskEventSource,
    loadTaskDetail: async () => processingDetail
  });

  expect(await screen.findByText("Viewed outline")).toBeInTheDocument();

  await act(async () => {
    eventSources[0].emitEvent("agent.event", {
      seq: 2,
      task_id: "task-live-merge",
      type: "agent.event",
      status: "processing",
      stage: "extraction",
      payload: {
        type: "tool_completed",
        tool: "read",
        args: { path_id: "0001.0000.0001" },
        result: { ok: true, locator: "0001.0000.0001", kind: "paragraph", text: "1-101、1-102 被列为文明寝室" }
      }
    });
    eventSources[0].emitEvent("agent.event", {
      seq: 3,
      task_id: "task-live-merge",
      type: "agent.event",
      status: "processing",
      stage: "extraction",
      payload: {
        type: "tool_completed",
        tool: "write_field",
        args: {
          field_id: "room_numbers",
          value: "1-101,1-102",
          final_evidence: [
            {
              path: "/001-sample/001-Notice.md",
              sentences: ["0001.0000.0001"]
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
                sentences: ["0001.0000.0001"]
              }
            ],
            reason: "实时写入字段"
          }
        }
      }
    });
  });

  const agentArea = screen.getByLabelText("Agent 中间工作区");
  const toolGroup = await within(agentArea).findByRole("group", { name: "3 collapsed tools" });
  await userEvent.click(within(toolGroup).getByRole("button", { name: "展开 3 个工具调用" }));

  const readToolLink = await screen.findByRole("link", { name: "tool read" });
  expect(readToolLink).toHaveAttribute("href", "evidence://0001.0000.0001");
  await userEvent.click(readToolLink);

  const sourceViewer = within(screen.getByLabelText("右侧 Review 工作栏")).getByLabelText("原文查看器");
  expect(sourceViewer).toHaveAttribute("data-highlight-selector", "0001.0000.0001");
  expect(getSourceFrameHtml(sourceViewer)).toContain('id="0001.0000.0001" class="is-current-evidence" data-current-evidence="true"');

  await userEvent.click(within(screen.getByLabelText("右侧 Review 工作栏")).getByRole("tab", { name: "Review" }));

  const progress = screen.getByLabelText("字段进度面板");
  expect(within(progress).getByRole("button", { name: /room_numbers/ })).toBeInTheDocument();
  expect(within(progress).getByText("实时写入字段")).toBeInTheDocument();
});

it("已展开的 live tool group 追加新工具后保持展开", async () => {
  const user = userEvent.setup();
  const processingDetail: TaskDetailData = {
    summary: {
      task_id: "task-live-expanded-group",
      status: "processing",
      stage: "extraction",
      has_result: false,
      has_trace: false,
      error_message: null,
      stream: {
        state: "running",
        last_event_seq: 1
      }
    },
    result: null,
    trace: null,
    replay: {
      ...baseReplay,
      task_id: "task-live-expanded-group",
      status: "processing",
      stage: "extraction",
      actions: [
        {
          tool_name: "tree",
          args: { path_id: "0001.0000.0000" },
          result: { ok: true, locator: "0001.0000.0000" }
        },
        {
          tool_name: "read",
          args: { path_id: "0001.0000.0001" },
          result: { ok: true, locator: "0001.0000.0001", kind: "paragraph", text: "1-101、1-102 被列为文明寝室" }
        }
      ]
    },
    audit: null
  };
  const eventSources: FakeEventSource[] = [];
  const createTaskEventSource = jest.fn((_taskId: string, afterSeq = 0) => {
    const eventSource = new FakeEventSource(String(afterSeq));
    eventSources.push(eventSource);
    return eventSource as unknown as EventSource;
  });

  renderTaskDetail(processingDetail, {
    taskId: "task-live-expanded-group",
    createTaskEventSource,
    loadTaskDetail: async () => processingDetail
  });

  const agentArea = await screen.findByLabelText("Agent 中间工作区");
  const initialToolGroup = await within(agentArea).findByRole("group", { name: "2 collapsed tools" });
  await user.click(within(initialToolGroup).getByRole("button", { name: "展开 2 个工具调用" }));
  expect(within(initialToolGroup).getByRole("button", { name: "收起 2 个工具调用" })).toHaveAttribute("aria-expanded", "true");
  expect(within(agentArea).getByText("Viewed outline")).toBeInTheDocument();
  expect(within(agentArea).getByText("Read passage")).toBeInTheDocument();

  await act(async () => {
    eventSources[0].emitEvent("agent.event", {
      seq: 2,
      task_id: "task-live-expanded-group",
      type: "agent.event",
      status: "processing",
      stage: "extraction",
      payload: {
        type: "tool_completed",
        tool: "add_candidate_evidence",
        args: { field_id: "room_numbers", path_id: "0001.0000.0001" },
        result: {
          ok: true,
          field_id: "room_numbers",
          candidate_evidence: ["0001.0000.0001"]
        }
      }
    });
  });

  const updatedToolGroup = await within(agentArea).findByRole("group", { name: "3 collapsed tools" });
  expect(within(updatedToolGroup).getByRole("button", { name: "收起 3 个工具调用" })).toHaveAttribute("aria-expanded", "true");
  expect(within(agentArea).getByText("Saved evidence for room_numbers")).toBeInTheDocument();
});
