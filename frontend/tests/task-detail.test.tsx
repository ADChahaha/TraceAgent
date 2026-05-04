import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import {
  getTaskAudit,
  getTaskResult,
  getTaskSummary,
  getTaskTrace,
  loadTaskDetail
} from "@/lib/api";
import { TaskDetail } from "@/components/task-detail";
import type { TaskDetailData, TaskReplay, TaskResult, TaskSummary } from "@/lib/types";

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
      tool_name: "set_field",
      args: {
        name: "room_numbers",
        value: "1-101,1-102",
        evidence_ids: ["p001_b001"],
        reason: "候选证据支持字段值"
      },
      result: {
        ok: true,
        field: {
          name: "room_numbers",
          status: "resolved",
          value: "1-101,1-102",
          evidence_ids: ["p001_b001"],
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

const detailData: TaskDetailData = {
  summary: waitingReviewSummary,
  result: reviewResult,
  trace: {
    task_id: "task-001",
    agent_status: "completed",
    steps: [],
    agent_trace: [],
    fields: []
  },
  replay: baseReplay,
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
        evidence_texts: [],
        evidence_refs: [],
        actions: [],
        reason: "候选证据支持字段值",
        failure_reason: null,
        agent_process: null
      }
    ]
  },
  audit: {
    task_id: "task-001",
    status: "waiting_review",
    field_commits: []
  }
};

async function loadReplayIframe(iframe: HTMLIFrameElement) {
  await act(async () => {
    fireEvent.load(iframe);
  });
}

function jsonResponse(payload: unknown) {
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    text: async () => JSON.stringify(payload)
  } as Response;
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

it("waiting_review 任务只展示 replay，并在 review 字段卡片里提交修正", async () => {
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
    review: null,
    audit: null
  };
  const injectedLoadTaskDetail = jest
    .fn<Promise<TaskDetailData>, [string]>()
    .mockResolvedValueOnce(detailData)
    .mockResolvedValueOnce(completedDetail);
  const submitReview = jest.fn(async () => refreshedSummary);

  render(
    <TaskDetail
      taskId="task-001"
      initialSummary={waitingReviewSummary}
      loadTaskDetail={injectedLoadTaskDetail}
      submitReview={submitReview}
    />
  );

  expect(await screen.findByText("AI extraction replay")).toBeInTheDocument();
  expect(screen.getByText("sample.pdf")).toBeInTheDocument();
  expect(screen.getByText("写入字段：文明寝室房间号")).toBeInTheDocument();
  expect(screen.getAllByText("review").length).toBeGreaterThan(0);
  expect(screen.getByText("字段需要人工确认")).toBeInTheDocument();
  expect(screen.queryByRole("tab", { name: "结果" })).not.toBeInTheDocument();
  expect(screen.queryByRole("tab", { name: "复核" })).not.toBeInTheDocument();
  expect(screen.queryByRole("tab", { name: "证据" })).not.toBeInTheDocument();
  expect(screen.queryByRole("tab", { name: "审计" })).not.toBeInTheDocument();
  expect(screen.queryByText("Agent 原始 trace")).not.toBeInTheDocument();
  expect(screen.queryByText("文档原始 Markdown")).not.toBeInTheDocument();
  expect(screen.queryByText("Agent 决策过程")).not.toBeInTheDocument();

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

it("动作输出展示返回的诊断摘要，字段写入卡不再承接诊断文字", async () => {
  const qualityDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      display_html: [
        '<figure id="p001_b002" data-type="table">',
        '<table id="p001_b002_table">',
        '<tr id="p001_b002_tr_000"><td>作品类型</td><td>论文题目</td></tr>',
        '<tr id="p001_b002_tr_001"><td>学术论文</td><td>论文 A</td></tr>',
        '<tr id="p001_b002_tr_002"><td></td><td>论文 B</td></tr>',
        '<tr id="p001_b002_tr_003"><td>学术 论文</td><td>论文 C</td></tr>',
        '</table>',
        '</figure>'
      ].join(""),
      actions: [
        {
          tool_name: "custom_extraction",
          args: {
            table_id: "p001_b002",
            sql: 'SELECT "论文题目" FROM data WHERE "作品类型" = "学术论文"',
            reason: "抽取作品类型为学术论文的论文题目"
          },
          result: {
            table_id: "p001_b002",
            columns: ["论文题目"],
            rows: [
              {
                row_id: "p001_b002_tr_001",
                values: { "论文题目": "论文 A" },
                evidence_ids: ["p001_b002", "p001_b002_tr_001"]
              }
            ],
            table_audit: {
              summary: "表格 3 行；2 列；空白单元格：作品类型 空白 1 行。"
            },
            query_audit: {
              summary: "返回 1 行；筛选列“作品类型”空白 1 行；非空分布：学术论文 1，学术 论文 1；输出列“论文题目”无空值。",
              predicate_columns: [
                {
                  column: "作品类型",
                  literal: "学术论文",
                  blank_count: 1,
                  blank_row_ids_sample: ["p001_b002_tr_002"],
                  non_empty_distribution: [
                    { value: "学术论文", count: 1 },
                    { value: "学术 论文", count: 1 }
                  ]
                }
              ]
            }
          }
        },
        {
          tool_name: "set_field",
          args: {
            name: "room_numbers",
            value: "论文 A",
            evidence_ids: ["p001_b002", "p001_b002_tr_001"],
            reason: "使用“作品类型 = 学术论文”筛出 1 行；空白作品类型行需要结合上下文判断，本次未作为学术论文证据；选中行论文题目无空值。"
          },
          result: {
            ok: true,
            field: {
              name: "room_numbers",
              status: "resolved",
              value: "论文 A",
              evidence_ids: ["p001_b002", "p001_b002_tr_001"],
              reason: "使用“作品类型 = 学术论文”筛出 1 行；空白作品类型行需要结合上下文判断，本次未作为学术论文证据；选中行论文题目无空值。"
            }
          }
        }
      ]
    }
  };
  const injectedLoadTaskDetail = jest.fn(async () => qualityDetail);

  render(
    <TaskDetail
      taskId="task-001"
      initialSummary={waitingReviewSummary}
      loadTaskDetail={injectedLoadTaskDetail}
    />
  );

  expect(await screen.findByText("AI extraction replay")).toBeInTheDocument();
  expect(screen.getByText("抽取作品类型为学术论文的论文题目")).toBeInTheDocument();
  const actionDiagnostics = screen.getByLabelText("动作诊断摘要");
  expect(within(actionDiagnostics).getByText("表格摘要")).toBeInTheDocument();
  expect(
    within(actionDiagnostics).getByText("表格 3 行；2 列；空白单元格：作品类型 空白 1 行。")
  ).toBeInTheDocument();
  expect(within(actionDiagnostics).getByText("查表摘要")).toBeInTheDocument();
  expect(
    within(actionDiagnostics).getByText("返回 1 行；筛选列“作品类型”空白 1 行；非空分布：学术论文 1，学术 论文 1；输出列“论文题目”无空值。")
  ).toBeInTheDocument();
  fireEvent.click(screen.getByText("抽取作品类型为学术论文的论文题目"));
  expect(screen.getByText("写入字段：文明寝室房间号")).toBeInTheDocument();
  expect(screen.queryByLabelText("字段模型判断")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("动作诊断摘要")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("字段质量风险")).not.toBeInTheDocument();
});

it("字段证据 chip 只定位文档证据，不回跳 replay action", async () => {
  const user = userEvent.setup();
  const multiActionDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      display_html: baseReplay.display_html,
      actions: [
        {
          tool_name: "search_grep",
          args: {
            element_id: "p001_b001",
            reason: "先定位证据"
          },
          result: {
            evidence_ids: ["p001_b001"]
          }
        },
        baseReplay.actions[0]
      ]
    }
  };
  const injectedLoadTaskDetail = jest.fn(async () => multiActionDetail);

  render(
    <TaskDetail
      taskId="task-001"
      initialSummary={waitingReviewSummary}
      loadTaskDetail={injectedLoadTaskDetail}
    />
  );

  expect(await screen.findByText("AI extraction replay")).toBeInTheDocument();
  await user.click(screen.getByText("先定位证据"));
  expect(screen.getByText("2/2")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "文明寝室名单 中的内容" }));

  expect(screen.getByText("2/2")).toBeInTheDocument();
});

it("read_element 查询表结构时高亮表名和表头", async () => {
  const tableStructureDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      display_html: [
        '<figure id="p001_b002" data-type="table">',
        '<div class="caption">文明模范寝室表</div>',
        '<table id="p001_b002_table">',
        '<tr id="p001_b002_tr_000"><td>房间</td><td>结论</td></tr>',
        '<tr id="p001_b002_tr_001"><td>1-101</td><td>文明寝室</td></tr>',
        '</table>',
        '</figure>'
      ].join(""),
      actions: [
        {
          tool_name: "read_element",
          args: {
            element_id: "p001_b002",
            reason: "查询表格结构"
          },
          result: {
            id: "p001_b002",
            type: "TABLE",
            html: '<table-ref id="p001_b002" rows="2" columns="房间 | 结论" />',
            evidence_ids: ["p001_b002"]
          }
        }
      ]
    }
  };
  const injectedLoadTaskDetail = jest.fn(async () => tableStructureDetail);

  render(
    <TaskDetail
      taskId="task-001"
      initialSummary={waitingReviewSummary}
      loadTaskDetail={injectedLoadTaskDetail}
    />
  );

  const iframe = (await screen.findByTitle("document replay")) as HTMLIFrameElement;
  const iframeDocument = iframe.contentDocument;
  expect(iframeDocument).not.toBeNull();
  iframeDocument?.open();
  iframeDocument?.write(tableStructureDetail.replay?.display_html ?? "");
  iframeDocument?.close();
  await loadReplayIframe(iframe);

  const figure = iframeDocument?.getElementById("p001_b002");
  const caption = iframeDocument?.querySelector(".caption");
  const table = iframeDocument?.getElementById("p001_b002_table") as HTMLTableElement | null;

  expect(figure).not.toHaveClass("is-current-highlight");
  expect(iframeDocument?.querySelector('[data-table-reference-for="p001_b002"]')).toBeNull();
  expect(caption).toHaveClass("is-table-reference-highlight");
  expect(table?.rows[0]).toHaveClass("is-table-reference-highlight");
  expect(table?.rows[0]).not.toHaveClass("is-table-row-result-highlight");
  expect(table?.rows[1]).not.toHaveClass("is-table-row-result-highlight");
});

it("read_element 查询表结构自动播放时读取表名入口", async () => {
  jest.useFakeTimers();
  const scrolledIds: string[] = [];
  const tableStructureDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      display_html: [
        '<figure id="p001_b002" data-type="table">',
        '<div id="p001_b002_caption" class="caption">文明模范寝室表</div>',
        '<table id="p001_b002_table">',
        '<tr id="p001_b002_tr_000"><td>房间</td><td>结论</td></tr>',
        '<tr id="p001_b002_tr_001"><td>1-101</td><td>文明寝室</td></tr>',
        '</table>',
        '</figure>'
      ].join(""),
      actions: [
        {
          tool_name: "read_element",
          args: {
            element_id: "p001_b002",
            reason: "查询表格结构"
          },
          result: {
            id: "p001_b002",
            type: "TABLE",
            html: '<table-ref id="p001_b002" rows="2" columns="房间 | 结论" />',
            evidence_ids: ["p001_b002"]
          }
        }
      ]
    }
  };
  const injectedLoadTaskDetail = jest.fn(async () => tableStructureDetail);

  try {
    render(
      <TaskDetail
        taskId="task-001"
        initialSummary={waitingReviewSummary}
        loadTaskDetail={injectedLoadTaskDetail}
      />
    );

    expect(await screen.findByText("AI extraction replay")).toBeInTheDocument();
    const iframe = screen.getByTitle("document replay") as HTMLIFrameElement;
    iframe.contentDocument?.open();
    iframe.contentDocument?.write(tableStructureDetail.replay?.display_html ?? "");
    iframe.contentDocument?.close();
    await loadReplayIframe(iframe);
    for (const id of ["p001_b002", "p001_b002_caption"]) {
      const element = iframe.contentDocument?.getElementById(id);
      if (!element) {
        continue;
      }
      Object.defineProperty(element, "scrollIntoView", {
        configurable: true,
        value: function scrollIntoView(this: Element) {
          scrolledIds.push(this.id);
        }
      });
    }

    fireEvent.click(screen.getByRole("button", { name: "自动播放" }));
    await act(async () => {
      await jest.advanceTimersByTimeAsync(1600);
    });

    expect(scrolledIds[0]).toBe("p001_b002_caption");
  } finally {
    jest.useRealTimers();
  }
});

it("set_field 的整表证据高亮表名和表头并靠上滚动", async () => {
  jest.useFakeTimers();
  const scrollTargets: Array<{ id: string; block?: ScrollLogicalPosition }> = [];
  const tableEvidenceDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      display_html: [
        '<figure id="p001_b002" data-type="table">',
        '<div id="p001_b002_caption" class="caption">文明模范寝室表</div>',
        '<table id="p001_b002_table">',
        '<tr id="p001_b002_tr_000"><td>房间</td><td>结论</td></tr>',
        '<tr id="p001_b002_tr_001"><td>1-101</td><td>文明寝室</td></tr>',
        '</table>',
        '</figure>'
      ].join(""),
      actions: [
        {
          tool_name: "set_field",
          args: {
            name: "room_numbers",
            value: "1-101",
            evidence_ids: ["p001_b002"],
            reason: "整张表作为字段依据"
          },
          result: {
            ok: true,
            field: {
              name: "room_numbers",
              status: "resolved",
              value: "1-101",
              evidence_ids: ["p001_b002"],
              reason: "整张表作为字段依据"
            }
          }
        }
      ]
    }
  };
  const injectedLoadTaskDetail = jest.fn(async () => tableEvidenceDetail);

  try {
    render(
      <TaskDetail
        taskId="task-001"
        initialSummary={waitingReviewSummary}
        loadTaskDetail={injectedLoadTaskDetail}
      />
    );

    expect(await screen.findByText("AI extraction replay")).toBeInTheDocument();
    const iframe = screen.getByTitle("document replay") as HTMLIFrameElement;
    iframe.contentDocument?.open();
    iframe.contentDocument?.write(tableEvidenceDetail.replay?.display_html ?? "");
    iframe.contentDocument?.close();
    for (const id of ["p001_b002", "p001_b002_caption"]) {
      const element = iframe.contentDocument?.getElementById(id);
      if (!element) {
        continue;
      }
      Object.defineProperty(element, "scrollIntoView", {
        configurable: true,
        value: function scrollIntoView(this: Element, options?: ScrollIntoViewOptions) {
          scrollTargets.push({ id: this.id, block: options?.block });
        }
      });
    }
    await loadReplayIframe(iframe);

    const figure = iframe.contentDocument?.getElementById("p001_b002");
    const caption = iframe.contentDocument?.getElementById("p001_b002_caption");
    const table = iframe.contentDocument?.getElementById("p001_b002_table") as HTMLTableElement | null;
    expect(figure).not.toHaveClass("is-current-highlight");
    expect(figure).not.toHaveClass("is-field-write-highlight");
    expect(caption).toHaveClass("is-current-highlight");
    expect(caption).toHaveClass("is-field-write-highlight");
    expect(table?.rows[0]).toHaveClass("is-current-highlight");
    expect(table?.rows[0]).toHaveClass("is-field-write-highlight");

    fireEvent.click(screen.getByRole("button", { name: "自动播放" }));
    await act(async () => {
      await jest.advanceTimersByTimeAsync(1600);
    });

    expect(scrollTargets[0]).toEqual({ id: "p001_b002_caption", block: "start" });
  } finally {
    jest.useRealTimers();
  }
});

it("左侧 overview 表格项也滚到表名而不是整表", async () => {
  const user = userEvent.setup();
  const scrollTargets: Array<{ id: string; block?: ScrollLogicalPosition }> = [];
  const overviewDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      display_html: [
        '<figure id="p001_b002" data-type="table">',
        '<div id="p001_b002_caption" class="caption">文明模范寝室表</div>',
        '<table id="p001_b002_table">',
        '<tr id="p001_b002_tr_000"><td>房间</td><td>结论</td></tr>',
        '<tr id="p001_b002_tr_001"><td>1-101</td><td>文明寝室</td></tr>',
        '</table>',
        '</figure>'
      ].join(""),
      outline_tree: [
        {
          id: "p001_b002",
          type: "TABLE",
          text: "文明模范寝室表",
          children: []
        }
      ],
      actions: []
    }
  };
  const injectedLoadTaskDetail = jest.fn(async () => overviewDetail);

  render(
    <TaskDetail
      taskId="task-001"
      initialSummary={waitingReviewSummary}
      loadTaskDetail={injectedLoadTaskDetail}
    />
  );

  expect(await screen.findByText("AI extraction replay")).toBeInTheDocument();
  const iframe = screen.getByTitle("document replay") as HTMLIFrameElement;
  iframe.contentDocument?.open();
  iframe.contentDocument?.write(overviewDetail.replay?.display_html ?? "");
  iframe.contentDocument?.close();
  for (const id of ["p001_b002", "p001_b002_caption"]) {
    const element = iframe.contentDocument?.getElementById(id);
    if (!element) {
      continue;
    }
    Object.defineProperty(element, "scrollIntoView", {
      configurable: true,
      value: function scrollIntoView(this: Element, options?: ScrollIntoViewOptions) {
        scrollTargets.push({ id: this.id, block: options?.block });
      }
    });
  }
  await loadReplayIframe(iframe);

  await user.click(screen.getByRole("button", { name: "表格：文明模范寝室表" }));

  await waitFor(() => expect(scrollTargets[0]).toEqual({ id: "p001_b002_caption", block: "start" }));
});

it("read_element 查询无 caption 表格时高亮表头而不框整表", async () => {
  const tableStructureDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      display_html: [
        '<figure id="p001_b002" data-type="table">',
        '<table id="p001_b002_table">',
        '<tr id="p001_b002_tr_000"><td>房间</td><td>结论</td></tr>',
        '<tr id="p001_b002_tr_001"><td>1-101</td><td>文明寝室</td></tr>',
        '</table>',
        '</figure>'
      ].join(""),
      actions: [
        {
          tool_name: "read_element",
          args: {
            element_id: "p001_b002",
            reason: "查询表格结构"
          },
          result: {
            id: "p001_b002",
            type: "TABLE",
            html: '<table-ref id="p001_b002" label="文明模范寝室表" rows="166" columns="房间 | 结论" />',
            evidence_ids: ["p001_b002"]
          }
        }
      ]
    }
  };
  const injectedLoadTaskDetail = jest.fn(async () => tableStructureDetail);

  render(
    <TaskDetail
      taskId="task-001"
      initialSummary={waitingReviewSummary}
      loadTaskDetail={injectedLoadTaskDetail}
    />
  );

  const iframe = (await screen.findByTitle("document replay")) as HTMLIFrameElement;
  const iframeDocument = iframe.contentDocument;
  expect(iframeDocument).not.toBeNull();
  iframeDocument?.open();
  iframeDocument?.write(tableStructureDetail.replay?.display_html ?? "");
  iframeDocument?.close();
  await loadReplayIframe(iframe);

  const figure = iframeDocument?.getElementById("p001_b002");
  const table = iframeDocument?.getElementById("p001_b002_table") as HTMLTableElement | null;

  expect(figure).not.toHaveClass("is-current-highlight");
  expect(table).not.toHaveClass("is-table-reference-highlight");
  expect(iframeDocument?.querySelector('[data-table-reference-for="p001_b002"]')).toBeNull();
  expect(table?.rows[0]).toHaveClass("is-table-reference-highlight");
});

it("table_extraction 只高亮返回行，不高亮整张表或列", async () => {
  const tableDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      display_html: [
        '<figure id="p001_b002" data-type="table">',
        '<table id="p001_b002_table">',
        '<tr id="p001_b002_tr_000"><td>房间</td><td>结论</td></tr>',
        '<tr id="p001_b002_tr_001"><td>1-101</td><td>文明寝室</td></tr>',
        '<tr id="p001_b002_tr_002"><td>1-102</td><td>普通寝室</td></tr>',
        '</table>',
        '</figure>'
      ].join(""),
      actions: [
        {
          tool_name: "table_extraction",
          args: {
            table_id: "p001_b002",
            reason: "抽取结论列"
          },
          result: {
            table_id: "p001_b002",
            columns: ["结论"],
            rows: [
              {
                row_id: "p001_b002_tr_001",
                values: { "结论": "文明寝室" },
                evidence_ids: ["p001_b002", "p001_b002_tr_001"]
              }
            ]
          }
        }
      ]
    }
  };
  const injectedLoadTaskDetail = jest.fn(async () => tableDetail);

  render(
    <TaskDetail
      taskId="task-001"
      initialSummary={waitingReviewSummary}
      loadTaskDetail={injectedLoadTaskDetail}
    />
  );

  const iframe = (await screen.findByTitle("document replay")) as HTMLIFrameElement;
  const iframeDocument = iframe.contentDocument;
  expect(iframeDocument).not.toBeNull();
  iframeDocument?.open();
  iframeDocument?.write(tableDetail.replay?.display_html ?? "");
  iframeDocument?.close();
  await loadReplayIframe(iframe);

  const figure = iframeDocument?.getElementById("p001_b002");
  const row = iframeDocument?.getElementById("p001_b002_tr_001");
  const table = iframeDocument?.getElementById("p001_b002_table") as HTMLTableElement | null;

  expect(figure).not.toHaveClass("is-current-highlight");
  expect(row).toHaveClass("is-table-row-result-highlight");
  expect(table?.rows[0]).not.toHaveClass("is-table-row-result-highlight");
  expect(table?.rows[2]).not.toHaveClass("is-table-row-result-highlight");
});

it("table_extraction 返回具体行时会逐行动画读取", async () => {
  jest.useFakeTimers();
  const rowScrolls: string[] = [];
  const tableRowsDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      display_html: [
        '<figure id="p001_b002" data-type="table">',
        '<table id="p001_b002_table">',
        '<tr id="p001_b002_tr_000"><td>房间</td><td>结论</td></tr>',
        '<tr id="p001_b002_tr_001"><td>1-101</td><td>文明寝室</td></tr>',
        '<tr id="p001_b002_tr_002"><td>1-102</td><td>普通寝室</td></tr>',
        '<tr id="p001_b002_tr_003"><td>1-103</td><td>文明寝室</td></tr>',
        '</table>',
        '</figure>'
      ].join(""),
      actions: [
        {
          tool_name: "table_extraction",
          args: {
            table_id: "p001_b002",
            reason: "抽取文明寝室行"
          },
          result: {
            table_id: "p001_b002",
            columns: ["房间", "结论"],
            rows: [
              {
                row_id: "p001_b002_tr_001",
                values: { "房间": "1-101", "结论": "文明寝室" },
                evidence_ids: ["p001_b002", "p001_b002_tr_001"]
              },
              {
                row_id: "p001_b002_tr_003",
                values: { "房间": "1-103", "结论": "文明寝室" },
                evidence_ids: ["p001_b002", "p001_b002_tr_003"]
              }
            ]
          }
        }
      ]
    }
  };
  const injectedLoadTaskDetail = jest.fn(async () => tableRowsDetail);

  try {
    render(
      <TaskDetail
        taskId="task-001"
        initialSummary={waitingReviewSummary}
        loadTaskDetail={injectedLoadTaskDetail}
      />
    );

    expect(await screen.findByText("AI extraction replay")).toBeInTheDocument();
    const iframe = screen.getByTitle("document replay") as HTMLIFrameElement;
    iframe.contentDocument?.open();
    iframe.contentDocument?.write(tableRowsDetail.replay?.display_html ?? "");
    iframe.contentDocument?.close();
    for (const rowId of ["p001_b002_tr_001", "p001_b002_tr_002", "p001_b002_tr_003"]) {
      const row = iframe.contentDocument?.getElementById(rowId);
      if (!row) {
        continue;
      }
      Object.defineProperty(row, "scrollIntoView", {
        configurable: true,
        value: function scrollIntoView(this: Element) {
          rowScrolls.push(this.id);
        }
      });
    }
    await loadReplayIframe(iframe);

    fireEvent.click(screen.getByRole("button", { name: "自动播放" }));
    await act(async () => {
      await jest.advanceTimersByTimeAsync(6000);
    });

    expect(rowScrolls).toEqual(["p001_b002_tr_001", "p001_b002_tr_003"]);
  } finally {
    jest.useRealTimers();
  }
});

it("set_field 写入证据按 HTML 顺序从上到下读取", async () => {
  jest.useFakeTimers();
  const readOrder: string[] = [];
  const orderedEvidenceDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      display_html: [
        '<h1 id="p001_b000">文明寝室名单</h1>',
        '<p id="p001_b001">第一行证据</p>',
        '<p id="p001_b002">第二行证据</p>',
        '<p id="p001_b003">第三行证据</p>'
      ].join(""),
      actions: [
        {
          tool_name: "set_field",
          args: {
            name: "room_numbers",
            value: "1-101,1-102,1-103",
            evidence_ids: ["p001_b003", "p001_b001", "p001_b002"],
            reason: "乱序 evidence ids 也要按 HTML 顺序读取"
          },
          result: {
            ok: true,
            field: {
              name: "room_numbers",
              status: "resolved",
              value: "1-101,1-102,1-103",
              evidence_ids: ["p001_b003", "p001_b001", "p001_b002"],
              reason: "乱序 evidence ids 也要按 HTML 顺序读取"
            }
          }
        }
      ]
    }
  };
  const injectedLoadTaskDetail = jest.fn(async () => orderedEvidenceDetail);

  try {
    render(
      <TaskDetail
        taskId="task-001"
        initialSummary={waitingReviewSummary}
        loadTaskDetail={injectedLoadTaskDetail}
      />
    );

    expect(await screen.findByText("AI extraction replay")).toBeInTheDocument();
    const iframe = screen.getByTitle("document replay") as HTMLIFrameElement;
    iframe.contentDocument?.open();
    iframe.contentDocument?.write(orderedEvidenceDetail.replay?.display_html ?? "");
    iframe.contentDocument?.close();
    if (iframe.contentDocument) {
      iframe.contentDocument.createRange = jest.fn(() => ({
        selectNodeContents: jest.fn(),
        getClientRects: jest.fn(() => []),
        detach: jest.fn()
      }) as unknown as Range);
    }
    Object.defineProperty(iframe.contentWindow, "scrollTo", {
      configurable: true,
      value: jest.fn()
    });
    for (const evidenceId of ["p001_b001", "p001_b002", "p001_b003"]) {
      const element = iframe.contentDocument?.getElementById(evidenceId);
      if (!element) {
        continue;
      }
      Object.defineProperty(element, "scrollIntoView", {
        configurable: true,
        value: function scrollIntoView(this: Element) {
          readOrder.push(this.id);
        }
      });
    }
    await loadReplayIframe(iframe);

    fireEvent.click(screen.getByRole("button", { name: "自动播放" }));
    await act(async () => {
      await jest.advanceTimersByTimeAsync(9000);
    });

    expect(readOrder).toEqual(["p001_b001", "p001_b002", "p001_b003"]);
  } finally {
    jest.useRealTimers();
  }
});

it("连续 action 指向同一 block 时不重复播放 outline 鼠标路径", async () => {
  jest.useFakeTimers();
  const originalElementScrollTo = HTMLElement.prototype.scrollTo;
  const outlineScrollTo = jest.fn();
  const htmlScrollIntoView = jest.fn();
  Object.defineProperty(HTMLElement.prototype, "scrollTo", {
    configurable: true,
    value: outlineScrollTo
  });
  const sameBlockDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      display_html: '<h1 id="p001_b000">文明寝室名单</h1><p id="p001_b001">同一证据块</p>',
      actions: [
        {
          tool_name: "search_grep",
          args: {
            element_id: "p001_b001",
            reason: "第一次读取同一证据块"
          },
          result: {
            evidence_ids: ["p001_b001"]
          }
        },
        {
          tool_name: "lookup_block",
          args: {
            element_id: "p001_b001",
            reason: "继续使用同一证据块"
          },
          result: {
            evidence_ids: ["p001_b001"]
          }
        }
      ]
    }
  };
  const injectedLoadTaskDetail = jest.fn(async () => sameBlockDetail);

  try {
    render(
      <TaskDetail
        taskId="task-001"
        initialSummary={waitingReviewSummary}
        loadTaskDetail={injectedLoadTaskDetail}
      />
    );

    expect(await screen.findByText("AI extraction replay")).toBeInTheDocument();
    const iframe = screen.getByTitle("document replay") as HTMLIFrameElement;
    iframe.contentDocument?.open();
    iframe.contentDocument?.write(sameBlockDetail.replay?.display_html ?? "");
    iframe.contentDocument?.close();
    if (iframe.contentDocument) {
      iframe.contentDocument.createRange = jest.fn(() => ({
        selectNodeContents: jest.fn(),
        getClientRects: jest.fn(() => []),
        detach: jest.fn()
      }) as unknown as Range);
    }
    Object.defineProperty(iframe.contentWindow, "scrollTo", {
      configurable: true,
      value: jest.fn()
    });
    iframe.contentDocument?.getElementById("p001_b001")?.setAttribute("data-testid", "same-block-evidence");
    const evidence = iframe.contentDocument?.getElementById("p001_b001");
    if (evidence) {
      Object.defineProperty(evidence, "scrollIntoView", {
        configurable: true,
        value: htmlScrollIntoView
      });
    }
    await loadReplayIframe(iframe);

    fireEvent.click(screen.getByRole("button", { name: "自动播放" }));
    await act(async () => {
      await jest.advanceTimersByTimeAsync(9000);
    });

    expect(screen.getByText("2/2")).toBeInTheDocument();
    expect(outlineScrollTo).toHaveBeenCalledTimes(1);
    expect(htmlScrollIntoView).toHaveBeenCalled();
  } finally {
    Object.defineProperty(HTMLElement.prototype, "scrollTo", {
      configurable: true,
      value: originalElementScrollTo
    });
    jest.useRealTimers();
  }
});

it("自动读取多个证据块时优先滚到当前视口最近的 HTML block", async () => {
  jest.useFakeTimers();
  const scrolledIds: string[] = [];
  const nearestDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      display_html: [
        '<p id="p001_b001">页面顶部证据</p>',
        '<p id="p001_b002">当前视口附近证据</p>',
        '<p id="p001_b003">页面底部证据</p>'
      ].join(""),
      outline_tree: [],
      actions: [
        {
          tool_name: "search_grep",
          args: {
            reason: "读取多个候选证据"
          },
          result: {
            evidence_ids: ["p001_b001", "p001_b002", "p001_b003"]
          }
        }
      ]
    }
  };
  const injectedLoadTaskDetail = jest.fn(async () => nearestDetail);

  try {
    render(
      <TaskDetail
        taskId="task-001"
        initialSummary={waitingReviewSummary}
        loadTaskDetail={injectedLoadTaskDetail}
      />
    );

    expect(await screen.findByText("AI extraction replay")).toBeInTheDocument();
    const iframe = screen.getByTitle("document replay") as HTMLIFrameElement;
    iframe.contentDocument?.open();
    iframe.contentDocument?.write(nearestDetail.replay?.display_html ?? "");
    iframe.contentDocument?.close();
    Object.defineProperty(iframe.contentWindow, "scrollY", {
      configurable: true,
      value: 500
    });
    Object.defineProperty(iframe.contentWindow, "innerHeight", {
      configurable: true,
      value: 600
    });
    Object.defineProperty(iframe.contentWindow, "scrollTo", {
      configurable: true,
      value: jest.fn()
    });
    const rectById: Record<string, Partial<DOMRect>> = {
      p001_b001: { top: -470, bottom: -440, height: 30 },
      p001_b002: { top: 260, bottom: 290, height: 30 },
      p001_b003: { top: 1300, bottom: 1330, height: 30 }
    };
    for (const [id, rect] of Object.entries(rectById)) {
      const element = iframe.contentDocument?.getElementById(id);
      if (!element) {
        continue;
      }
      Object.defineProperty(element, "scrollIntoView", {
        configurable: true,
        value: function scrollIntoView(this: Element) {
          scrolledIds.push(this.id);
        }
      });
      element.getBoundingClientRect = jest.fn(() => ({
        x: 0,
        y: rect.top ?? 0,
        left: 0,
        right: 200,
        top: rect.top ?? 0,
        bottom: rect.bottom ?? 0,
        width: 200,
        height: rect.height ?? 0,
        toJSON: () => ({})
      }));
    }
    await loadReplayIframe(iframe);

    fireEvent.click(screen.getByRole("button", { name: "自动播放" }));
    await act(async () => {
      await jest.advanceTimersByTimeAsync(1200);
    });

    expect(scrolledIds[0]).toBe("p001_b002");
  } finally {
    jest.useRealTimers();
  }
});

it("必填字段没有 agent value 时在 replay 末尾显示空复核输入", async () => {
  const user = userEvent.setup();
  const missingRequiredDetail: TaskDetailData = {
    ...detailData,
    result: {
      task_id: "task-001",
      status: "waiting_review",
      route: "review",
      fields: [
        {
          field_name: "room_numbers",
          display_name: "文明寝室房间号",
          agent_value: null,
          review_value: null,
          final_value: null,
          field_status: "failed",
          route: "review",
          source: null,
          committed: false
        }
      ]
    },
    replay: {
      ...baseReplay,
      display_html: '<h1 id="p001_b000">测试文档</h1><p id="p001_b001">需要人工补录</p>',
      broad_plan: { plan: [] },
      actions: [],
      result: {},
      audit: { route: "review", route_reason: "必填字段没有返回，需要人工补录" }
    },
    review: {
      task_id: "task-001",
      status: "waiting_review",
      route: "review",
      route_reason: "必填字段没有返回，需要人工补录",
      fields: [
        {
          field_name: "room_numbers",
          display_name: "文明寝室房间号",
          agent_value: null,
          field_status: "failed",
          needs_review: true,
          review_reason: "必填字段没有返回，需要人工补录",
          evidence_texts: [],
          evidence_refs: [],
          actions: [],
          reason: null,
          failure_reason: "file_extraction_agent did not return this field",
          agent_process: null
        }
      ]
    }
  };
  const injectedLoadTaskDetail = jest.fn(async () => missingRequiredDetail);
  const submitReview = jest.fn(async () => ({
    ...waitingReviewSummary,
    status: "completed",
    stage: "done",
    needs_review: false
  }));

  render(
    <TaskDetail
      taskId="task-001"
      initialSummary={waitingReviewSummary}
      loadTaskDetail={injectedLoadTaskDetail}
      submitReview={submitReview}
    />
  );

  expect(await screen.findByText("AI extraction replay")).toBeInTheDocument();
  expect(screen.getByText("等待人工补录")).toBeInTheDocument();
  const input = screen.getByLabelText("文明寝室房间号 复核值");
  expect(input).toHaveValue("");
  await user.type(input, "1-101");
  await user.click(screen.getByRole("button", { name: "提交修正并通过" }));

  await waitFor(() => expect(submitReview).toHaveBeenCalledTimes(1));
  expect(submitReview).toHaveBeenCalledWith("task-001", {
    decision: "revise_and_approve",
    fields: [
      {
        field_name: "room_numbers",
        review_value: "1-101"
      }
    ],
    comment: "",
    reviewer: "frontend"
  });
});

it("reject 字段只显示拒绝路由，不提供人工修改入口", async () => {
  const rejectedSummary: TaskSummary = {
    task_id: "task-rejected",
    status: "rejected",
    stage: "done",
    route: "reject",
    route_reason: "字段违反硬性规则",
    has_result: true,
    has_trace: true,
    needs_review: false
  };
  const rejectedDetail: TaskDetailData = {
    ...detailData,
    summary: rejectedSummary,
    result: {
      task_id: "task-rejected",
      status: "rejected",
      route: "reject",
      fields: [
        {
          field_name: "room_numbers",
          display_name: "文明寝室房间号",
          agent_value: "1-101",
          review_value: null,
          final_value: null,
          field_status: "resolved",
          route: "reject",
          source: null,
          committed: false
        }
      ]
    },
    replay: {
      ...baseReplay,
      task_id: "task-rejected",
      status: "rejected",
      stage: "done",
      audit: { route: "reject", route_reason: "字段违反硬性规则" }
    },
    review: null,
    audit: null
  };
  const injectedLoadTaskDetail = jest.fn(async () => rejectedDetail);

  render(
    <TaskDetail
      taskId="task-rejected"
      initialSummary={rejectedSummary}
      loadTaskDetail={injectedLoadTaskDetail}
    />
  );

  expect(await screen.findByText("AI extraction replay")).toBeInTheDocument();
  expect(screen.getByText("reject")).toBeInTheDocument();
  expect(screen.queryByLabelText("文明寝室房间号 复核值")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "提交修正并通过" })).not.toBeInTheDocument();
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
  const injectedLoadTaskDetail = jest.fn(async (): Promise<TaskDetailData> => ({
    summary: failedSummary,
    result: null,
    trace: null,
    replay: null,
    review: null,
    audit: null
  }));

  render(
    <TaskDetail
      taskId="task-failed"
      initialSummary={failedSummary}
      loadTaskDetail={injectedLoadTaskDetail}
    />
  );

  expect(await screen.findByText("failed")).toBeInTheDocument();
  expect(screen.getByText("任务失败")).toBeInTheDocument();
  expect(screen.getByText("resolution 执行失败: lookup_blocks action exceeded limit")).toBeInTheDocument();
});

it("failed 但已有 result/trace 的任务仍展示 replay", async () => {
  const failedSummary: TaskSummary = {
    task_id: "task-route-policy-failed",
    status: "failed",
    stage: "done",
    route: null,
    route_reason: null,
    has_result: true,
    has_trace: true,
    needs_review: false,
    error_message: "agent service returned 422: missing api_key"
  };
  const injectedLoadTaskDetail = jest.fn(async (): Promise<TaskDetailData> => ({
    summary: failedSummary,
    result: {
      task_id: "task-route-policy-failed",
      status: "failed",
      route: null,
      fields: [
        {
          field_name: "room_numbers",
          display_name: "文明寝室房间号",
          agent_value: "1-101",
          review_value: null,
          final_value: null,
          field_status: "resolved",
          route: null,
          source: null,
          committed: false
        }
      ]
    },
    trace: null,
    replay: {
      ...baseReplay,
      task_id: "task-route-policy-failed",
      status: "failed",
      stage: "done",
      result: { room_numbers: "1-101" },
      audit: { route: null, route_reason: null }
    },
    review: null,
    audit: null
  }));

  render(
    <TaskDetail
      taskId="task-route-policy-failed"
      initialSummary={failedSummary}
      loadTaskDetail={injectedLoadTaskDetail}
    />
  );

  expect(await screen.findByText("AI extraction replay")).toBeInTheDocument();
  expect(screen.queryByText("暂无 replay 数据。")).not.toBeInTheDocument();
  expect(screen.getAllByText("候选证据支持字段值").length).toBeGreaterThan(0);
});
