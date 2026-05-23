import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import {
  cancelTask,
  createTaskInput,
  getTaskEventsUrl,
  loadTaskDetail
} from "@/lib/api";
import { TaskDetail } from "@/components/task-detail";
import type {
  QaInputCreated,
  TaskDetailData,
  TaskEvent,
  TaskSummary
} from "@/lib/types";

const readySummary: TaskSummary = {
  task_id: "qa_task_001",
  status: "ready",
  stage: "ready",
  error_message: null,
  document_count: 1,
  active_turn_id: null,
  stream: {
    state: "idle",
    last_event_seq: 3
  }
};

const readyDetailSummary: TaskSummary = {
  ...readySummary,
  documents: [
    {
      document_id: "doc_001",
      filename: "contract.pdf",
      display_html: '<html><body><p id="p1">Either party may terminate with 30 days notice.</p><p id="p2">The notice must be written.</p><table id="table1"><tr id="table1_tr_000"><th>Clause</th><th>Value</th></tr><tr id="table1_tr_001"><td>Notice</td><td>30 days</td></tr></table></body></html>'
    }
  ],
  source_selectors: {
    "0001.0001.0001": "p1",
    "0001.0001.0002": "p2",
    "0001.0001.0003": "table1"
  }
};

const runningSummary: TaskSummary = {
  ...readySummary,
  status: "running",
  stage: "answering",
  active_turn_id: "turn_active",
  stream: {
    state: "running",
    last_event_seq: 8
  }
};

const detailData: TaskDetailData = {
  summary: readyDetailSummary,
  result: null,
  trace: null,
  replay: null,
  audit: null
};

const recentTaskSummaries: TaskSummary[] = [
  readySummary,
  {
    task_id: "qa_task_002",
    status: "running",
    stage: "answering",
    error_message: null,
    document_count: 2,
    active_turn_id: "turn_002",
    stream: {
      state: "running",
      last_event_seq: 4
    }
  }
];

class FakeEventSource extends EventTarget {
  closed = false;
  onerror: ((event: Event) => void) | null = null;

  constructor(public readonly url = "") {
    super();
  }

  emitEvent(eventName: string, payload: TaskEvent) {
    this.dispatchEvent(new MessageEvent(eventName, { data: JSON.stringify(payload) }));
  }

  emitError() {
    this.onerror?.(new Event("error"));
    this.dispatchEvent(new Event("error"));
  }

  close() {
    this.closed = true;
  }
}

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
    createTaskInput?: (taskId: string, content: string) => Promise<QaInputCreated>;
    cancelTask?: (taskId: string) => Promise<unknown>;
    createTaskEventSource?: (taskId: string, afterSeq?: number) => EventSource;
  } = {}
) {
  const taskId = options.taskId ?? data.summary.task_id;
  const loadTaskDetailImpl = options.loadTaskDetail ?? (async () => data);
  const listTasksImpl = options.listTasks ?? (async () => recentTaskSummaries);
  const createTaskInputImpl =
    options.createTaskInput ??
    (async () => ({
      task_id: taskId,
      turn_id: "turn_created",
      status: "queued",
      agent_completion_id: null
    }));
  const cancelTaskImpl = options.cancelTask ?? (async () => ({ task_id: taskId, status: "cancelling" }));

  const injectedLoadTaskDetail = jest.fn(loadTaskDetailImpl) as jest.MockedFunction<
    (taskId: string) => Promise<TaskDetailData>
  >;
  const listTasks = jest.fn(listTasksImpl) as jest.MockedFunction<() => Promise<TaskSummary[]>>;
  const injectedCreateTaskInput = jest.fn(createTaskInputImpl) as jest.MockedFunction<
    (taskId: string, content: string) => Promise<QaInputCreated>
  >;
  const injectedCancelTask = jest.fn(cancelTaskImpl) as jest.MockedFunction<(taskId: string) => Promise<unknown>>;

  const renderResult = render(
    <TaskDetail
      taskId={taskId}
      initialSummary={data.summary}
      loadTaskDetail={injectedLoadTaskDetail}
      listTasks={listTasks}
      createTaskInput={injectedCreateTaskInput}
      cancelTask={injectedCancelTask}
      createTaskEventSource={options.createTaskEventSource}
    />
  );

  return { injectedLoadTaskDetail, listTasks, injectedCreateTaskInput, injectedCancelTask, ...renderResult };
}

function taskEvent(overrides: Partial<TaskEvent>): TaskEvent {
  return {
    seq: overrides.seq ?? 1,
    task_id: overrides.task_id ?? "qa_task_001",
    turn_id: overrides.turn_id ?? null,
    type: overrides.type ?? "message.created",
    status: overrides.status ?? "ready",
    stage: overrides.stage ?? "ready",
    payload: overrides.payload ?? {},
    created_at: overrides.created_at ?? "2026-05-23T00:00:00Z"
  };
}

it("loadTaskDetail 只读取 QA task summary，不再请求 result/replay/trace/audit", async () => {
  global.fetch = jest.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/api/backend/qa/tasks/qa_task_001")) {
      return jsonResponse(readyDetailSummary);
    }
    throw new Error(`unexpected fetch: ${url}`);
  });

  const loaded = await loadTaskDetail("qa_task_001");

  expect(loaded.summary).toEqual(readyDetailSummary);
  expect(loaded.result).toBeNull();
  expect(loaded.trace).toBeNull();
  expect(loaded.replay).toBeNull();
  expect(loaded.audit).toBeNull();
  expect(global.fetch).not.toHaveBeenCalledWith(expect.stringContaining("/result"), expect.anything());
  expect(global.fetch).not.toHaveBeenCalledWith(expect.stringContaining("/replay"), expect.anything());
  expect(global.fetch).not.toHaveBeenCalledWith(expect.stringContaining("/trace"), expect.anything());
  expect(global.fetch).not.toHaveBeenCalledWith(expect.stringContaining("/audit"), expect.anything());
});

it("QA API 会提交输入、取消 active turn，并生成可续传事件 URL", async () => {
  global.fetch = jest.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/api/backend/qa/tasks/qa_task_001/inputs")) {
      return jsonResponse({
        task_id: "qa_task_001",
        turn_id: "turn_001",
        status: "completed",
        agent_completion_id: "cmp_001"
      });
    }
    if (url.endsWith("/api/backend/qa/tasks/qa_task_001/cancel")) {
      return jsonResponse({
        task_id: "qa_task_001",
        turn_id: "turn_001",
        status: "cancelling"
      });
    }
    throw new Error(`unexpected fetch: ${url}`);
  });

  await expect(createTaskInput("qa_task_001", "通知期限是多少？", { max_tool_calls: 12 })).resolves.toEqual({
    task_id: "qa_task_001",
    turn_id: "turn_001",
    status: "completed",
    agent_completion_id: "cmp_001"
  });
  await expect(cancelTask("qa_task_001")).resolves.toEqual({
    task_id: "qa_task_001",
    turn_id: "turn_001",
    status: "cancelling"
  });

  expect(getTaskEventsUrl("qa_task_001", 5)).toBe("/api/backend/qa/tasks/qa_task_001/events?after_seq=5");
  expect(global.fetch).toHaveBeenCalledWith(
    "/api/backend/qa/tasks/qa_task_001/inputs",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ content: "通知期限是多少？", run_options: { max_tool_calls: 12 } })
    })
  );
  expect(global.fetch).toHaveBeenCalledWith(
    "/api/backend/qa/tasks/qa_task_001/cancel",
    expect.objectContaining({ method: "POST" })
  );
});

it("任务详情会从 QA 事件流重建用户问题、模型回答和 inline evidence", async () => {
  const fakeEventSource = new FakeEventSource();
  const createTaskEventSource = jest.fn(() => fakeEventSource as unknown as EventSource);
  renderTaskDetail(detailData, { createTaskEventSource });

  await waitFor(() => expect(createTaskEventSource).toHaveBeenCalledWith("qa_task_001", 0));
  act(() => {
    fakeEventSource.emitEvent(
      "message.created",
      taskEvent({
        seq: 4,
        type: "message.created",
        status: "running",
        stage: "answering",
        turn_id: "turn_001",
        payload: { role: "user", content: "这份合同可以提前终止吗？" }
      })
    );
    fakeEventSource.emitEvent(
      "agent.event",
      taskEvent({
        seq: 5,
        type: "agent.event",
        status: "running",
        stage: "answering",
        turn_id: "turn_001",
        payload: {
          agent: "file_extraction_agent",
          type: "model_message",
          content: "可以提前终止，但需要提前 30 天通知。[30 天通知](evidence://0001.0001.0001/S001)"
        }
      })
    );
  });

  const qaStream = await screen.findByLabelText("QA conversation and reading process");
  expect(within(qaStream).getByText("这份合同可以提前终止吗？")).toBeInTheDocument();
  expect(within(qaStream).getByText("可以提前终止，但需要提前 30 天通知。")).toBeInTheDocument();
  expect(within(qaStream).getByRole("link", { name: "30 天通知" })).toHaveAttribute(
    "href",
    "evidence://0001.0001.0001/S001"
  );
});

it("点击 inline evidence 会用现有任务详情数据打开右侧 review 文档", async () => {
  const user = userEvent.setup();
  const fakeEventSource = new FakeEventSource();
  const createTaskEventSource = jest.fn(() => fakeEventSource as unknown as EventSource);
  renderTaskDetail(detailData, { createTaskEventSource });

  await waitFor(() => expect(createTaskEventSource).toHaveBeenCalledWith("qa_task_001", 0));
  act(() => {
    fakeEventSource.emitEvent(
      "agent.event",
      taskEvent({
        seq: 5,
        type: "agent.event",
        status: "running",
        stage: "answering",
        turn_id: "turn_001",
        payload: {
          agent: "file_extraction_agent",
          type: "model_message",
          content: "需要提前 30 天通知。[30 天通知](evidence://0001.0001.0001/S001)"
        }
      })
    );
  });

  await user.click(await screen.findByRole("link", { name: "30 天通知" }));

  const reviewWorkspace = await screen.findByLabelText("Right review workspace");
  expect(reviewWorkspace).not.toHaveClass("is-fullscreen");
  expect(screen.getByLabelText("QA stage")).toHaveStyle({
    "--replay-stage-columns": "var(--replay-left-panel-width) 10px minmax(0, 1fr) 10px var(--replay-right-panel-width)"
  });
  expect(within(reviewWorkspace).getByRole("button", { name: "Close document review" })).toBeInTheDocument();
  expect(within(reviewWorkspace).getByText("contract.pdf")).toBeInTheDocument();
  expect(within(reviewWorkspace).getByTitle("Source document")).toHaveAttribute(
    "srcdoc",
    expect.stringContaining("data-current-evidence=\"true\"")
  );
});

it("首轮生成中收到 source_indexed 后可以立刻打开右侧 review 文档", async () => {
  const user = userEvent.setup();
  const fakeEventSource = new FakeEventSource();
  const createTaskEventSource = jest.fn(() => fakeEventSource as unknown as EventSource);
  const loadTaskDetail = jest
    .fn<Promise<TaskDetailData>, [string]>()
    .mockResolvedValueOnce({
      ...detailData,
      summary: {
        ...runningSummary,
        documents: [
          {
            document_id: "doc_001",
            filename: "contract.pdf",
            display_html: '<html><body><p id="p1">Either party may terminate with 30 days notice.</p></body></html>'
          }
        ],
        source_selectors: {}
      }
    })
    .mockResolvedValue({
      ...detailData,
      summary: {
        ...runningSummary,
        documents: [
          {
            document_id: "doc_001",
            filename: "contract.pdf",
            display_html: '<html><body><p id="p1">Either party may terminate with 30 days notice.</p></body></html>'
          }
        ],
        source_selectors: {
          "0001.0001.0001": "p1"
        }
      }
    });
  renderTaskDetail({ ...detailData, summary: runningSummary }, { createTaskEventSource, loadTaskDetail });

  await waitFor(() => expect(createTaskEventSource).toHaveBeenCalledWith("qa_task_001", 0));
  await waitFor(() => expect(loadTaskDetail).toHaveBeenCalledTimes(1));
  act(() => {
    fakeEventSource.emitEvent(
      "agent.event",
      taskEvent({
        seq: 4,
        type: "agent.event",
        status: "running",
        stage: "answering",
        turn_id: "turn_active",
        payload: {
          agent: "file_extraction_agent",
          type: "source_indexed",
          result: {
            ok: true,
            document_tree: [],
            source_selectors: {
              "0001.0001.0001": "p1"
            }
          }
        }
      })
    );
    fakeEventSource.emitEvent(
      "agent.event",
      taskEvent({
        seq: 5,
        type: "agent.event",
        status: "running",
        stage: "answering",
        turn_id: "turn_active",
        payload: {
          agent: "file_extraction_agent",
          type: "model_message",
          content: "需要提前 30 天通知。[30 天通知](evidence://0001.0001.0001/S001)"
        }
      })
    );
  });

  await user.click(await screen.findByRole("link", { name: "30 天通知" }));

  const reviewWorkspace = await screen.findByLabelText("Right review workspace");
  expect(within(reviewWorkspace).getByText("contract.pdf")).toBeInTheDocument();
  expect(within(reviewWorkspace).getByTitle("Source document")).toHaveAttribute(
    "srcdoc",
    expect.stringContaining("data-current-evidence=\"true\"")
  );
});

it("右侧 review 会压平文档页面外框，只保留正文排版", async () => {
  const user = userEvent.setup();
  const fakeEventSource = new FakeEventSource();
  const createTaskEventSource = jest.fn(() => fakeEventSource as unknown as EventSource);
  const framedDetailData: TaskDetailData = {
    summary: {
      ...readyDetailSummary,
      documents: [
        {
          document_id: "doc_001",
          filename: "framed.pdf",
          display_html:
            '<!doctype html><html lang="ja"><head><meta charset="utf-8"><title>Processed Document</title><style>body { margin: 0; background: #f3f4f6; color: #171717; font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", "Yu Gothic", sans-serif; } main { max-width: 980px; margin: 0 auto; padding: 24px; } .page { background: #fff; margin: 0 0 20px; padding: 44px 56px; box-shadow: 0 1px 4px rgba(0,0,0,.12); position: relative; }</style></head><body><main><section class="page" id="page_001"><p id="p1">Either party may terminate with 30 days notice.</p></section></main></body></html>'
        }
      ],
      source_selectors: {
        "0001.0001.0001": "p1"
      }
    },
    result: null,
    trace: null,
    replay: null,
    audit: null
  };
  renderTaskDetail(framedDetailData, { createTaskEventSource });

  await waitFor(() => expect(createTaskEventSource).toHaveBeenCalledWith("qa_task_001", 0));
  act(() => {
    fakeEventSource.emitEvent(
      "agent.event",
      taskEvent({
        seq: 5,
        type: "agent.event",
        status: "running",
        stage: "answering",
        turn_id: "turn_001",
        payload: {
          agent: "file_extraction_agent",
          type: "model_message",
          content: "需要提前 30 天通知。[30 天通知](evidence://0001.0001.0001/S001)"
        }
      })
    );
  });

  await user.click(await screen.findByRole("link", { name: "30 天通知" }));

  const sourceFrame = await screen.findByTitle("Source document");
  expect(sourceFrame).toHaveAttribute(
    "srcdoc",
    expect.stringContaining(".page { background: transparent !important; margin: 0 0 20px !important; padding: 0 !important; box-shadow: none !important; }")
  );
});

it("右侧 review panel 支持拖拽调整宽度，并保持 Agent 对话列左右空白对称", async () => {
  const user = userEvent.setup();
  const fakeEventSource = new FakeEventSource();
  const createTaskEventSource = jest.fn(() => fakeEventSource as unknown as EventSource);
  renderTaskDetail(detailData, { createTaskEventSource });

  await waitFor(() => expect(createTaskEventSource).toHaveBeenCalledWith("qa_task_001", 0));
  const agentWorkspace = screen.getByLabelText("Agent workspace");
  const initialAgentStyle = agentWorkspace.getAttribute("style") ?? "";
  expect(agentWorkspace).toHaveAttribute("data-agent-balance-side", "left");
  expect(initialAgentStyle).not.toContain("--replay-agent-left-outer-width");
  expect(initialAgentStyle).not.toContain("--replay-agent-right-outer-width");
  expect(initialAgentStyle).not.toContain("--replay-agent-left-balance");
  expect(initialAgentStyle).not.toContain("--replay-agent-right-balance");

  act(() => {
    fakeEventSource.emitEvent(
      "agent.event",
      taskEvent({
        seq: 5,
        type: "agent.event",
        status: "running",
        stage: "answering",
        turn_id: "turn_001",
        payload: {
          agent: "file_extraction_agent",
          type: "model_message",
          content: "需要提前 30 天通知。[30 天通知](evidence://0001.0001.0001/S001)"
        }
      })
    );
  });

  await user.click(await screen.findByRole("link", { name: "30 天通知" }));

  const stage = await screen.findByLabelText("QA stage");
  expect(stage).toHaveStyle({
    "--replay-right-panel-width": "560px",
    "--replay-stage-columns": "var(--replay-left-panel-width) 10px minmax(0, 1fr) 10px var(--replay-right-panel-width)"
  });
  expect(agentWorkspace).toHaveAttribute("data-agent-balance-side", "both");
  const openAgentStyle = agentWorkspace.getAttribute("style") ?? "";
  expect(openAgentStyle).not.toContain("--replay-agent-left-outer-width");
  expect(openAgentStyle).not.toContain("--replay-agent-right-outer-width");
  expect(openAgentStyle).not.toContain("--replay-agent-left-balance");
  expect(openAgentStyle).not.toContain("--replay-agent-right-balance");

  const resizeHandle = screen.getByRole("separator", { name: "Resize right review" });
  expect(resizeHandle).toHaveAttribute("aria-valuemin", "480");
  expect(resizeHandle).toHaveAttribute("aria-valuemax", "960");
  expect(resizeHandle).toHaveAttribute("aria-valuenow", "560");

  resizeHandle.focus();
  await user.keyboard("{ArrowLeft}");

  expect(resizeHandle).toHaveAttribute("aria-valuenow", "576");
  expect(stage).toHaveStyle({ "--replay-right-panel-width": "576px" });

  fireEvent(resizeHandle, new MouseEvent("pointerdown", { bubbles: true, clientX: 700 }));
  fireEvent(window, new MouseEvent("pointermove", { bubbles: true, clientX: 680 }));
  fireEvent(window, new MouseEvent("pointerup", { bubbles: true, clientX: 680 }));

  expect(resizeHandle).toHaveAttribute("aria-valuenow", "596");
  expect(stage).toHaveStyle({ "--replay-right-panel-width": "596px" });
});

it("文件夹级 inline evidence 会定位到对应 header 而不是子节点", async () => {
  const user = userEvent.setup();
  const fakeEventSource = new FakeEventSource();
  const createTaskEventSource = jest.fn(() => fakeEventSource as unknown as EventSource);
  const sourceDocument = document.implementation.createHTMLDocument("source");
  sourceDocument.body.innerHTML = '<h2 id="0001.0001">Termination</h2><p id="p1">Either party may terminate with 30 days notice.</p><p id="p2">The notice must be written.</p>';
  const headerTarget = sourceDocument.getElementById("0001.0001") as HTMLElement;
  const childTarget = sourceDocument.getElementById("p1") as HTMLElement;
  const headerScrollIntoView = jest.fn();
  headerTarget.scrollIntoView = headerScrollIntoView;
  jest.spyOn(HTMLIFrameElement.prototype, "contentDocument", "get").mockReturnValue(sourceDocument);

  renderTaskDetail(detailData, { createTaskEventSource });

  await waitFor(() => expect(createTaskEventSource).toHaveBeenCalledWith("qa_task_001", 0));
  act(() => {
    fakeEventSource.emitEvent(
      "agent.event",
      taskEvent({
        seq: 5,
        type: "agent.event",
        status: "running",
        stage: "answering",
        turn_id: "turn_001",
        payload: {
          agent: "file_extraction_agent",
          type: "model_message",
          content: "相关内容在[终止条款](evidence://0001.0001)里。"
        }
      })
    );
  });

  await user.click(await screen.findByRole("link", { name: "终止条款" }));

  await waitFor(() => {
    expect(headerTarget.getAttribute("data-current-evidence")).toBe("true");
    expect(childTarget.hasAttribute("data-current-evidence")).toBe(false);
    expect(headerScrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "center", inline: "nearest" });
  });
});

it("旧 source_selectors 缺少文件夹映射时会用链接文本定位 header", async () => {
  const user = userEvent.setup();
  const fakeEventSource = new FakeEventSource();
  const createTaskEventSource = jest.fn(() => fakeEventSource as unknown as EventSource);
  const sourceDocument = document.implementation.createHTMLDocument("source");
  sourceDocument.body.innerHTML = '<h2 id="h1">Termination</h2><p id="p1">Either party may terminate with 30 days notice.</p>';
  const headerTarget = sourceDocument.getElementById("h1") as HTMLElement;
  const childTarget = sourceDocument.getElementById("p1") as HTMLElement;
  const headerScrollIntoView = jest.fn();
  headerTarget.scrollIntoView = headerScrollIntoView;
  jest.spyOn(HTMLIFrameElement.prototype, "contentDocument", "get").mockReturnValue(sourceDocument);

  renderTaskDetail(detailData, { createTaskEventSource });

  await waitFor(() => expect(createTaskEventSource).toHaveBeenCalledWith("qa_task_001", 0));
  act(() => {
    fakeEventSource.emitEvent(
      "agent.event",
      taskEvent({
        seq: 5,
        type: "agent.event",
        status: "running",
        stage: "answering",
        turn_id: "turn_001",
        payload: {
          agent: "file_extraction_agent",
          type: "model_message",
          content: "I found the relevant section in [Termination](evidence://0001.0001)."
        }
      })
    );
  });

  await user.click(await screen.findByRole("link", { name: "Termination" }));

  await waitFor(() => {
    expect(headerTarget.getAttribute("data-current-evidence")).toBe("true");
    expect(childTarget.hasAttribute("data-current-evidence")).toBe(false);
    expect(headerScrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "center", inline: "nearest" });
  });
});

it("切换同一文档内的 inline evidence 会在 iframe 内平滑跳转并移动高亮", async () => {
  const user = userEvent.setup();
  const fakeEventSource = new FakeEventSource();
  const createTaskEventSource = jest.fn(() => fakeEventSource as unknown as EventSource);
  const sourceDocument = document.implementation.createHTMLDocument("source");
  sourceDocument.body.innerHTML = '<p id="p1">Either party may terminate with 30 days notice.</p><p id="p2">The notice must be written.</p>';
  const firstTarget = sourceDocument.getElementById("p1") as HTMLElement;
  const secondTarget = sourceDocument.getElementById("p2") as HTMLElement;
  const firstScrollIntoView = jest.fn();
  const secondScrollIntoView = jest.fn();
  firstTarget.scrollIntoView = firstScrollIntoView;
  secondTarget.scrollIntoView = secondScrollIntoView;
  jest.spyOn(HTMLIFrameElement.prototype, "contentDocument", "get").mockReturnValue(sourceDocument);

  renderTaskDetail(detailData, { createTaskEventSource });

  await waitFor(() => expect(createTaskEventSource).toHaveBeenCalledWith("qa_task_001", 0));
  act(() => {
    fakeEventSource.emitEvent(
      "agent.event",
      taskEvent({
        seq: 5,
        type: "agent.event",
        status: "running",
        stage: "answering",
        turn_id: "turn_001",
        payload: {
          agent: "file_extraction_agent",
          type: "model_message",
          content: "[30 天通知](evidence://0001.0001.0001/S001) 还必须是 [书面通知](evidence://0001.0001.0002/S001)。"
        }
      })
    );
  });

  await user.click(await screen.findByRole("link", { name: "30 天通知" }));
  const sourceFrame = await screen.findByTitle("Source document");
  const initialSrcDoc = sourceFrame.getAttribute("srcdoc");

  await waitFor(() => {
    expect(firstTarget.getAttribute("data-current-evidence")).toBe("true");
    expect(firstScrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "center", inline: "nearest" });
  });

  await user.click(await screen.findByRole("link", { name: "书面通知" }));

  await waitFor(() => {
    expect(firstTarget.hasAttribute("data-current-evidence")).toBe(false);
    expect(secondTarget.getAttribute("data-current-evidence")).toBe("true");
    expect(secondScrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "center", inline: "nearest" });
  });
  expect(sourceFrame).toHaveAttribute("srcdoc", initialSrcDoc);
});

it("range evidence 会在右侧 review 同时高亮范围内多个节点并滚到起始节点", async () => {
  const user = userEvent.setup();
  const fakeEventSource = new FakeEventSource();
  const createTaskEventSource = jest.fn(() => fakeEventSource as unknown as EventSource);
  const sourceDocument = document.implementation.createHTMLDocument("source");
  sourceDocument.body.innerHTML = '<p id="p1">First range paragraph.</p><p id="p2">Second range paragraph.</p><p id="p3">Outside paragraph.</p>';
  const firstTarget = sourceDocument.getElementById("p1") as HTMLElement;
  const secondTarget = sourceDocument.getElementById("p2") as HTMLElement;
  const outsideTarget = sourceDocument.getElementById("p3") as HTMLElement;
  const firstScrollIntoView = jest.fn();
  firstTarget.scrollIntoView = firstScrollIntoView;
  jest.spyOn(HTMLIFrameElement.prototype, "contentDocument", "get").mockReturnValue(sourceDocument);

  renderTaskDetail(detailData, { createTaskEventSource });

  await waitFor(() => expect(createTaskEventSource).toHaveBeenCalledWith("qa_task_001", 0));
  act(() => {
    fakeEventSource.emitEvent(
      "agent.event",
      taskEvent({
        seq: 5,
        type: "agent.event",
        status: "running",
        stage: "answering",
        turn_id: "turn_001",
        payload: {
          agent: "file_extraction_agent",
          type: "model_message",
          content: "The answer depends on [both paragraphs](evidence://range/0001.0001.0001/0001.0001.0002)."
        }
      })
    );
  });

  await user.click(await screen.findByRole("link", { name: "both paragraphs" }));

  await waitFor(() => {
    expect(firstTarget.getAttribute("data-current-evidence")).toBe("true");
    expect(secondTarget.getAttribute("data-current-evidence")).toBe("true");
    expect(outsideTarget.hasAttribute("data-current-evidence")).toBe(false);
    expect(firstScrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "center", inline: "nearest" });
  });
});

it("表格 row evidence 会定位到具体表格行而不是整张表", async () => {
  const user = userEvent.setup();
  const fakeEventSource = new FakeEventSource();
  const createTaskEventSource = jest.fn(() => fakeEventSource as unknown as EventSource);
  const sourceDocument = document.implementation.createHTMLDocument("source");
  sourceDocument.body.innerHTML = '<table id="table1"><tr id="table1_tr_000"><th>Clause</th><th>Value</th></tr><tr id="table1_tr_001"><td>Notice</td><td>30 days</td></tr></table>';
  const tableTarget = sourceDocument.getElementById("table1") as HTMLElement;
  const rowTarget = sourceDocument.getElementById("table1_tr_001") as HTMLElement;
  const rowScrollIntoView = jest.fn();
  rowTarget.scrollIntoView = rowScrollIntoView;
  jest.spyOn(HTMLIFrameElement.prototype, "contentDocument", "get").mockReturnValue(sourceDocument);

  renderTaskDetail(detailData, { createTaskEventSource });

  await waitFor(() => expect(createTaskEventSource).toHaveBeenCalledWith("qa_task_001", 0));
  act(() => {
    fakeEventSource.emitEvent(
      "agent.event",
      taskEvent({
        seq: 5,
        type: "agent.event",
        status: "running",
        stage: "answering",
        turn_id: "turn_001",
        payload: {
          agent: "file_extraction_agent",
          type: "model_message",
          content: "通知期限是 30 天。[表格行](evidence://0001.0001.0003/R001)"
        }
      })
    );
  });

  await user.click(await screen.findByRole("link", { name: "表格行" }));

  await waitFor(() => {
    expect(tableTarget.hasAttribute("data-current-evidence")).toBe(false);
    expect(rowTarget.getAttribute("data-current-evidence")).toBe("true");
    expect(rowScrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "center", inline: "nearest" });
  });
});

it("任务详情不显示 Agent 面板内部标题栏", async () => {
  renderTaskDetail(detailData);

  const agentPanel = await screen.findByLabelText("Document QA Agent");
  expect(within(agentPanel).getByLabelText("QA conversation and reading process")).toBeInTheDocument();
  expect(within(agentPanel).queryByText("Document QA")).not.toBeInTheDocument();
  expect(within(agentPanel).queryByText("ready")).not.toBeInTheDocument();
});

it("任务详情左侧任务栏默认宽度和首页一致，并支持键盘调整", async () => {
  const user = userEvent.setup();
  renderTaskDetail(detailData);

  const resizeHandle = await screen.findByRole("separator", { name: "Resize left sidebar" });
  expect(resizeHandle).toHaveAttribute("aria-valuemin", "176");
  expect(resizeHandle).toHaveAttribute("aria-valuemax", "360");
  expect(resizeHandle).toHaveAttribute("aria-valuenow", "224");

  resizeHandle.focus();
  await user.keyboard("{ArrowRight}");

  expect(resizeHandle).toHaveAttribute("aria-valuenow", "240");

  fireEvent(resizeHandle, new MouseEvent("pointerdown", { bubbles: true, clientX: 100 }));
  fireEvent(window, new MouseEvent("pointermove", { bubbles: true, clientX: 120 }));
  fireEvent(window, new MouseEvent("pointerup", { bubbles: true, clientX: 120 }));

  expect(resizeHandle).toHaveAttribute("aria-valuenow", "260");
});

it("任务详情会显示工具阅读过程并在 turn 完成后恢复可追问状态", async () => {
  const fakeEventSource = new FakeEventSource();
  const createTaskEventSource = jest.fn(() => fakeEventSource as unknown as EventSource);
  renderTaskDetail({ ...detailData, summary: runningSummary }, { createTaskEventSource });

  expect(await screen.findByRole("button", { name: "Submit or pause answer" })).toBeInTheDocument();
  act(() => {
    fakeEventSource.emitEvent(
      "agent.event",
      taskEvent({
        seq: 9,
        type: "agent.event",
        status: "running",
        stage: "answering",
        turn_id: "turn_active",
        payload: {
          agent: "file_extraction_agent",
          type: "tool_completed",
          tool: "grep",
          args: { query: "termination" },
          result: { ok: true }
        }
      })
    );
    fakeEventSource.emitEvent(
      "turn.completed",
      taskEvent({
        seq: 10,
        type: "turn.completed",
        status: "ready",
        stage: "ready",
        turn_id: "turn_active",
        payload: { turn_id: "turn_active" }
      })
    );
  });

  expect(await screen.findByText("Searched termination")).toBeInTheDocument();
  expect(await screen.findByRole("button", { name: "Submit or pause answer" })).toBeInTheDocument();
});

it("运行中任务详情不启动定时轮询刷新 summary", async () => {
  const setIntervalSpy = jest.spyOn(window, "setInterval");

  renderTaskDetail({ ...detailData, summary: runningSummary });

  expect(await screen.findByRole("button", { name: "Submit or pause answer" })).toBeInTheDocument();
  expect(setIntervalSpy).not.toHaveBeenCalledWith(expect.any(Function), 1500);
});

it("运行中的 SSE 更新不会禁用正在输入的追问草稿", async () => {
  const user = userEvent.setup();
  const fakeEventSource = new FakeEventSource();
  const createTaskEventSource = jest.fn(() => fakeEventSource as unknown as EventSource);
  renderTaskDetail(detailData, { createTaskEventSource });

  await waitFor(() => expect(createTaskEventSource).toHaveBeenCalledWith("qa_task_001", 0));
  const input = await screen.findByLabelText("QA question input");
  await user.type(input, "下一轮草稿");
  expect(input).toHaveValue("下一轮草稿");
  expect(input).not.toBeDisabled();

  act(() => {
    fakeEventSource.emitEvent(
      "agent.event",
      taskEvent({
        seq: 9,
        type: "agent.event",
        status: "running",
        stage: "answering",
        turn_id: "turn_active",
        payload: {
          agent: "file_extraction_agent",
          type: "tool_completed",
          tool: "grep",
          args: { query: "notice" },
          result: { ok: true }
        }
      })
    );
  });

  expect(await screen.findByRole("button", { name: "Submit or pause answer" })).toBeInTheDocument();
  expect(input).toHaveValue("下一轮草稿");
  expect(input).not.toBeDisabled();
});

it("用户不在底部时 SSE 新消息不会强制滚到最底部", async () => {
  const fakeEventSource = new FakeEventSource();
  const createTaskEventSource = jest.fn(() => fakeEventSource as unknown as EventSource);
  renderTaskDetail(detailData, { createTaskEventSource });

  await waitFor(() => expect(createTaskEventSource).toHaveBeenCalledWith("qa_task_001", 0));
  const qaStream = await screen.findByLabelText("QA conversation and reading process");
  Object.defineProperty(qaStream, "clientHeight", { configurable: true, value: 300 });
  Object.defineProperty(qaStream, "scrollHeight", { configurable: true, value: 1200 });

  act(() => {
    fakeEventSource.emitEvent(
      "agent.event",
      taskEvent({
        seq: 9,
        type: "agent.event",
        status: "running",
        stage: "answering",
        turn_id: "turn_active",
        payload: {
          agent: "file_extraction_agent",
          type: "model_message",
          content: "第一条过程消息。"
        }
      })
    );
  });
  expect(await screen.findByText("第一条过程消息。")).toBeInTheDocument();
  qaStream.scrollTop = 320;
  fireEvent.scroll(qaStream);

  act(() => {
    fakeEventSource.emitEvent(
      "agent.event",
      taskEvent({
        seq: 10,
        type: "agent.event",
        status: "running",
        stage: "answering",
        turn_id: "turn_active",
        payload: {
          agent: "file_extraction_agent",
          type: "model_message",
          content: "我继续核对受验注意。"
        }
      })
    );
  });

  expect(await screen.findByText("我继续核对受验注意。")).toBeInTheDocument();
  expect(qaStream.scrollTop).toBe(320);
});

it("运行状态变化不会改变 composer 单按钮结构和按钮外观", async () => {
  const user = userEvent.setup();
  const fakeEventSource = new FakeEventSource();
  const createTaskEventSource = jest.fn(() => fakeEventSource as unknown as EventSource);
  const { injectedCancelTask, injectedCreateTaskInput } = renderTaskDetail(detailData, { createTaskEventSource });

  await waitFor(() => expect(createTaskEventSource).toHaveBeenCalledWith("qa_task_001", 0));
  const input = await screen.findByLabelText("QA question input");
  await user.type(input, "下一轮草稿");
  const composer = screen.getByRole("form", { name: "QA composer" });
  const actionButton = within(composer).getByRole("button", { name: "Submit or pause answer" });
  expect(input).toHaveValue("下一轮草稿");
  expect(input).toHaveAttribute("placeholder", "Ask a follow-up question");
  expect(actionButton).not.toBeDisabled();
  expect(actionButton).not.toHaveAttribute("aria-disabled");
  expect(within(composer).queryByRole("button", { name: "Send question" })).not.toBeInTheDocument();
  expect(within(composer).queryByRole("button", { name: "Pause answer" })).not.toBeInTheDocument();
  expect(within(composer).getAllByRole("button").filter((button) => !button.hasAttribute("disabled"))).toEqual([actionButton]);
  const sendIcon = actionButton.querySelector(".lucide-send-horizontal");
  const pauseIcon = actionButton.querySelector(".lucide-pause");
  expect(sendIcon).toHaveAttribute("data-visible", "true");
  expect(pauseIcon).toHaveAttribute("data-visible", "false");
  expect(injectedCancelTask).not.toHaveBeenCalled();
  const actionClassName = actionButton.getAttribute("class");
  const iconShellHtmlBefore = actionButton.querySelector(".replay-agent-composer-action-icon-shell")?.innerHTML ?? "";

  act(() => {
    fakeEventSource.emitEvent(
      "agent.event",
      taskEvent({
        seq: 9,
        type: "agent.event",
        status: "running",
        stage: "answering",
        turn_id: "turn_active",
        payload: {
          agent: "file_extraction_agent",
          type: "tool_completed",
          tool: "grep",
          args: { query: "notice" },
          result: { ok: true }
        }
      })
    );
  });

  expect(input).toHaveAttribute("placeholder", "Ask a follow-up question");
  expect(input).toHaveValue("下一轮草稿");
  expect(within(composer).getByRole("button", { name: "Submit or pause answer" })).toBe(actionButton);
  expect(within(composer).queryByRole("button", { name: "Send question" })).not.toBeInTheDocument();
  expect(within(composer).queryByRole("button", { name: "Pause answer" })).not.toBeInTheDocument();
  expect(actionButton).not.toBeDisabled();
  expect(actionButton).not.toHaveAttribute("aria-disabled");
  expect(actionButton).toHaveAttribute("class", actionClassName);
  expect(within(composer).getAllByRole("button").filter((button) => !button.hasAttribute("disabled"))).toEqual([actionButton]);
  expect(sendIcon).toHaveAttribute("data-visible", "false");
  expect(pauseIcon).toHaveAttribute("data-visible", "true");
  expect(actionButton.querySelectorAll(".replay-agent-composer-action-icon")).toHaveLength(2);
  expect(actionButton.querySelector(".replay-agent-composer-action-icon-shell")?.innerHTML).not.toBe(iconShellHtmlBefore);

  await user.click(actionButton);
  expect(injectedCreateTaskInput).not.toHaveBeenCalled();
  expect(injectedCancelTask).toHaveBeenCalledWith("qa_task_001");
});

it("追问会复用同一个 task 提交下一轮输入", async () => {
  const user = userEvent.setup();
  let resolveInput: (value: QaInputCreated) => void = () => {};
  const createTaskInput = jest.fn(
    () =>
      new Promise<QaInputCreated>((resolve) => {
        resolveInput = resolve;
      })
  );
  const { injectedCreateTaskInput } = renderTaskDetail(detailData, { createTaskInput });

  await user.type(await screen.findByLabelText("QA question input"), "通知期限是多少？");
  await user.click(screen.getByRole("button", { name: "Submit or pause answer" }));

  await waitFor(() =>
    expect(injectedCreateTaskInput).toHaveBeenCalledWith("qa_task_001", "通知期限是多少？")
  );
  const qaStream = await screen.findByLabelText("QA conversation and reading process");
  expect(within(qaStream).getByText("通知期限是多少？")).toBeInTheDocument();
  expect(screen.getByLabelText("QA question input")).toHaveValue("");
  resolveInput({
    task_id: "qa_task_001",
    turn_id: "turn_created",
    status: "queued",
    agent_completion_id: null
  });
});

it("追问 composer 用 Enter 提交问题，Shift Enter 保留换行", async () => {
  const user = userEvent.setup();
  const createTaskInput = jest.fn(
    () =>
      new Promise<QaInputCreated>(() => {
        // 保持 pending，测试只关心键盘触发提交和本地清空输入框。
      })
  );
  renderTaskDetail(detailData, { createTaskInput });

  const input = await screen.findByLabelText("QA question input");
  await user.type(input, "第一行{Shift>}{Enter}{/Shift}第二行");

  expect(input).toHaveValue("第一行\n第二行");
  expect(createTaskInput).not.toHaveBeenCalled();

  await user.keyboard("{Enter}");

  await waitFor(() => expect(createTaskInput).toHaveBeenCalledWith("qa_task_001", "第一行\n第二行"));
  expect(input).toHaveValue("");
});

it("追问提交后会立即显示重复用户消息并追加 Thinking 状态", async () => {
  const user = userEvent.setup();
  const fakeEventSource = new FakeEventSource();
  const createTaskEventSource = jest.fn(() => fakeEventSource as unknown as EventSource);
  const createTaskInput = jest.fn(
    () =>
      new Promise<QaInputCreated>(() => {
        // 保持请求 pending，验证前端本地提交态。
      })
  );
  renderTaskDetail(detailData, { createTaskEventSource, createTaskInput });

  await waitFor(() => expect(createTaskEventSource).toHaveBeenCalledWith("qa_task_001", 0));
  act(() => {
    fakeEventSource.emitEvent(
      "message.created",
      taskEvent({
        seq: 4,
        type: "message.created",
        status: "ready",
        stage: "ready",
        turn_id: "turn_001",
        payload: { role: "user", content: "通知期限是多少？" }
      })
    );
  });

  await user.type(await screen.findByLabelText("QA question input"), "通知期限是多少？");
  await user.click(screen.getByRole("button", { name: "Submit or pause answer" }));

  await waitFor(() => expect(createTaskInput).toHaveBeenCalledWith("qa_task_001", "通知期限是多少？"));
  const qaStream = await screen.findByLabelText("QA conversation and reading process");
  expect(within(qaStream).getAllByText("通知期限是多少？")).toHaveLength(2);
  expect(within(qaStream).getByText("Thinking")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Submit or pause answer" })).toBeInTheDocument();
});

it("追问提交后会立即按当前 seq 重新连接 SSE，不等待输入请求返回", async () => {
  const user = userEvent.setup();
  const eventSources: FakeEventSource[] = [];
  const createTaskEventSource = jest.fn((_taskId: string, afterSeq = 0) => {
    const eventSource = new FakeEventSource(String(afterSeq));
    eventSources.push(eventSource);
    return eventSource as unknown as EventSource;
  });
  const createTaskInput = jest.fn(
    () =>
      new Promise<QaInputCreated>(() => {
        // 保持 pending，验证前端不会等 POST 返回才续连事件流。
      })
  );
  renderTaskDetail(detailData, { createTaskEventSource, createTaskInput });

  await waitFor(() => expect(createTaskEventSource).toHaveBeenCalledWith("qa_task_001", 0));
  act(() => {
    eventSources[0].emitEvent(
      "message.created",
      taskEvent({
        seq: 4,
        type: "message.created",
        status: "ready",
        stage: "ready",
        turn_id: "turn_001",
        payload: { role: "user", content: "上一轮问题" }
      })
    );
  });

  await user.type(await screen.findByLabelText("QA question input"), "下一轮问题");
  await user.click(screen.getByRole("button", { name: "Submit or pause answer" }));

  await waitFor(() => expect(createTaskEventSource).toHaveBeenCalledTimes(2));
  expect(createTaskEventSource).toHaveBeenLastCalledWith("qa_task_001", 4);
});

it("SSE error 不主动关闭事件源，避免空闲连接断开后只能刷新恢复", async () => {
  const fakeEventSource = new FakeEventSource();
  const createTaskEventSource = jest.fn(() => fakeEventSource as unknown as EventSource);
  renderTaskDetail(detailData, { createTaskEventSource });

  await waitFor(() => expect(createTaskEventSource).toHaveBeenCalledWith("qa_task_001", 0));
  act(() => {
    fakeEventSource.emitError();
  });

  expect(fakeEventSource.closed).toBe(false);
});

it("Thinking 使用 Codex 式跳动指示器，不渲染问号或 spinner", async () => {
  const user = userEvent.setup();
  const createTaskInput = jest.fn(
    () =>
      new Promise<QaInputCreated>(() => {
        // 保持 pending，验证 thinking 占位的视觉结构。
      })
  );
  renderTaskDetail(detailData, { createTaskInput });

  await user.type(await screen.findByLabelText("QA question input"), "请继续");
  await user.click(screen.getByRole("button", { name: "Submit or pause answer" }));

  const thinking = await screen.findByLabelText("Assistant is thinking");
  expect(within(thinking).getByText("Thinking")).toBeInTheDocument();
  expect(thinking.querySelector(".qa-thinking-bounce")).toBeInTheDocument();
  expect(thinking.querySelector(".animate-spin")).not.toBeInTheDocument();
  expect(within(thinking).queryByText("?")).not.toBeInTheDocument();
});

it("QA 对话使用左右布局，用户消息在右侧，assistant 消息在左侧且不显示角色标签", async () => {
  const fakeEventSource = new FakeEventSource();
  const createTaskEventSource = jest.fn(() => fakeEventSource as unknown as EventSource);
  renderTaskDetail(detailData, { createTaskEventSource });

  await waitFor(() => expect(createTaskEventSource).toHaveBeenCalledWith("qa_task_001", 0));
  act(() => {
    fakeEventSource.emitEvent(
      "message.created",
      taskEvent({
        seq: 4,
        type: "message.created",
        status: "running",
        stage: "answering",
        turn_id: "turn_001",
        payload: { role: "user", content: "我的申请截止日是什么？" }
      })
    );
    fakeEventSource.emitEvent(
      "agent.event",
      taskEvent({
        seq: 5,
        type: "agent.event",
        status: "running",
        stage: "answering",
        turn_id: "turn_001",
        payload: {
          agent: "file_extraction_agent",
          type: "model_message",
          content: "申请截止日在募集要项中说明。"
        }
      })
    );
  });

  const userMessage = screen.getByText("我的申请截止日是什么？").closest(".qa-message-turn");
  const assistantMessage = screen.getByText("申请截止日在募集要项中说明。").closest(".qa-message-turn");
  expect(userMessage).toHaveClass("is-user");
  expect(assistantMessage).toHaveClass("is-assistant");
  expect(screen.queryByText("You")).not.toBeInTheDocument();
  expect(screen.queryByText("AI")).not.toBeInTheDocument();
});

it("连续工具事件会用 Codex 式轻量过程行默认折叠，并允许展开查看每个 tool", async () => {
  const user = userEvent.setup();
  const fakeEventSource = new FakeEventSource();
  const createTaskEventSource = jest.fn(() => fakeEventSource as unknown as EventSource);
  renderTaskDetail(detailData, { createTaskEventSource });

  await waitFor(() => expect(createTaskEventSource).toHaveBeenCalledWith("qa_task_001", 0));
  act(() => {
    fakeEventSource.emitEvent(
      "agent.event",
      taskEvent({
        seq: 4,
        type: "agent.event",
        status: "running",
        stage: "answering",
        turn_id: "turn_001",
        payload: {
          agent: "file_extraction_agent",
          type: "tool_completed",
          tool: "grep",
          args: { query: "出願期間" },
          result: { ok: true }
        }
      })
    );
    fakeEventSource.emitEvent(
      "agent.event",
      taskEvent({
        seq: 5,
        type: "agent.event",
        status: "running",
        stage: "answering",
        turn_id: "turn_001",
        payload: {
          agent: "file_extraction_agent",
          type: "tool_failed",
          tool: "grep",
          args: { query: "入試方式" },
          result: { ok: false }
        }
      })
    );
    fakeEventSource.emitEvent(
      "agent.event",
      taskEvent({
        seq: 6,
        type: "agent.event",
        status: "running",
        stage: "answering",
        turn_id: "turn_001",
        payload: {
          agent: "file_extraction_agent",
          type: "tool_completed",
          tool: "read",
          args: { locator: "0001.0001.0001" },
          result: { ok: true, kind: "paragraph" }
        }
      })
    );
    fakeEventSource.emitEvent(
      "agent.event",
      taskEvent({
        seq: 7,
        type: "agent.event",
        status: "running",
        stage: "answering",
        turn_id: "turn_001",
        payload: {
          agent: "file_extraction_agent",
          type: "tool_completed",
          tool: "inspect",
          args: { locator: "evidence://0001.0001.0003/R001" },
          result: { ok: true, kind: "table_row" }
        }
      })
    );
  });

  const groupToggle = await screen.findByRole("button", { name: "Expand tool activity" });
  expect(groupToggle).toHaveAttribute("aria-expanded", "false");
  expect(groupToggle.querySelector(".replay-agent-tool-group-chevron")).toBeInTheDocument();
  expect(screen.getByText("Read 1 passage, inspected 1 evidence, 2 searches")).toBeInTheDocument();
  expect(screen.queryByText(/failed/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/0001\.0001/)).not.toBeInTheDocument();
  expect(screen.queryByLabelText("tool grep")).not.toBeInTheDocument();

  await user.click(groupToggle);

  expect(await screen.findByRole("button", { name: "Collapse tool activity" })).toHaveAttribute("aria-expanded", "true");
  const grepTools = await screen.findAllByLabelText("tool grep");
  expect(grepTools).toHaveLength(2);
  expect(grepTools[0]).toHaveClass("replay-agent-tool-line");
  expect(grepTools[1]).toHaveClass("replay-agent-tool-line");
  expect(grepTools[0]).not.toHaveClass("is-failed");
  expect(grepTools[1]).not.toHaveClass("is-failed");
  const readTool = screen.getByRole("button", { name: "tool read" });
  const inspectTool = screen.getByLabelText("tool inspect");
  expect(within(readTool).getByText("Read paragraph")).toBeInTheDocument();
  expect(within(inspectTool).getByText("Inspected table row")).toBeInTheDocument();
  expect(readTool.querySelector(".lucide-book-open-text")).toBeInTheDocument();
  expect(inspectTool.querySelector(".lucide-eye")).toBeInTheDocument();
  expect(inspectTool.querySelector(".lucide-book-open-text")).not.toBeInTheDocument();
  expect(screen.queryByText(/0001\.0001/)).not.toBeInTheDocument();

  await user.click(readTool);

  const reviewWorkspace = await screen.findByLabelText("Right review workspace");
  expect(reviewWorkspace).not.toHaveClass("is-fullscreen");
  expect(within(reviewWorkspace).getByText("contract.pdf")).toBeInTheDocument();
  expect(within(reviewWorkspace).getByTitle("Source document")).toHaveAttribute(
    "srcdoc",
    expect.stringContaining("data-current-evidence=\"true\"")
  );

  act(() => {
    fakeEventSource.emitEvent(
      "agent.event",
      taskEvent({
        seq: 8,
        type: "agent.event",
        status: "running",
        stage: "answering",
        turn_id: "turn_001",
        payload: {
          agent: "file_extraction_agent",
          type: "tool_completed",
          tool: "tree",
          args: {},
          result: { ok: true }
        }
      })
    );
  });

  expect(await screen.findByRole("button", { name: "Collapse tool activity" })).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByLabelText("tool tree")).toBeInTheDocument();
});

it("运行中点击稳定单按钮会调用 cancel", async () => {
  const user = userEvent.setup();
  const { injectedCancelTask } = renderTaskDetail({ ...detailData, summary: runningSummary });

  await user.click(await screen.findByRole("button", { name: "Submit or pause answer" }));

  await waitFor(() => expect(injectedCancelTask).toHaveBeenCalledWith("qa_task_001"));
});

it("cancel 成功并刷新为 ready 后会解除 running 锁定", async () => {
  const user = userEvent.setup();
  const readyAfterCancelSummary: TaskSummary = {
    ...readySummary,
    active_turn_id: null,
    stream: {
      state: "idle",
      last_event_seq: 9
    }
  };
  const loadTaskDetail = jest
    .fn()
    .mockResolvedValueOnce({ ...detailData, summary: runningSummary })
    .mockResolvedValueOnce({ ...detailData, summary: readyAfterCancelSummary });
  const cancelTask = jest.fn(async () => ({
    task_id: "qa_task_001",
    turn_id: "turn_active",
    status: "cancelling"
  }));

  renderTaskDetail({ ...detailData, summary: runningSummary }, { loadTaskDetail, cancelTask });

  await waitFor(() => expect(loadTaskDetail).toHaveBeenCalledTimes(1));
  const actionButton = await screen.findByRole("button", { name: "Submit or pause answer" });
  expect(actionButton.querySelector(".lucide-send-horizontal")).toHaveAttribute("data-visible", "false");
  expect(actionButton.querySelector(".lucide-pause")).toHaveAttribute("data-visible", "true");

  await user.click(actionButton);

  await waitFor(() => expect(cancelTask).toHaveBeenCalledWith("qa_task_001"));
  await waitFor(() => expect(loadTaskDetail).toHaveBeenCalledTimes(2));

  const updatedActionButton = screen.getByRole("button", { name: "Submit or pause answer" });
  expect(updatedActionButton.querySelector(".lucide-send-horizontal")).toHaveAttribute("data-visible", "true");
  expect(updatedActionButton.querySelector(".lucide-pause")).toHaveAttribute("data-visible", "false");
});
