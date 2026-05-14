import { readFileSync } from "node:fs";
import { join } from "node:path";

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

function getCssRule(css: string, selector: string): string {
  const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = css.match(new RegExp(`${escapedSelector}\\s*\\{([^}]*)\\}`, "m"));
  if (!match) {
    throw new Error(`Missing CSS rule for ${selector}`);
  }
  return match[1];
}

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
            reason: "候选证据支持字段值",
          args: {
        name: "room_numbers",
        value: "1-101,1-102",
        evidence_ids: ["p001_b001"],
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

it("waiting_review 任务只展示 replay，并在 review 字段区里提交修正", async () => {
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
  expect(screen.getByText("task-001 / sample.pdf")).toBeInTheDocument();
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

it("任务详情页使用占满视口的文档工作台布局", async () => {
  const injectedLoadTaskDetail = jest.fn(async () => detailData);

  render(
    <TaskDetail
      taskId="task-001"
      initialSummary={waitingReviewSummary}
      loadTaskDetail={injectedLoadTaskDetail}
    />
  );

  expect(await screen.findByText("AI extraction replay")).toBeInTheDocument();
  const shell = screen.getByLabelText("任务详情全屏工作台");
  const replayRoot = screen.getByLabelText("Replay 全屏文档工作台");
  const toolbar = screen.getByLabelText("Replay 顶部工具栏");
  const stage = document.querySelector(".replay-stage") as HTMLElement;

  expect(shell).toHaveClass("task-detail-fullscreen-shell");
  expect(replayRoot).toHaveClass("replay-review-root-fullscreen");
  expect(toolbar).toHaveClass("replay-topbar");
  expect(within(toolbar).getByText("task-001 / sample.pdf")).toHaveClass("replay-topbar-title");
  expect(stage).toHaveClass("replay-stage-fullscreen");
  expect(screen.getByText("CONTENTS")).toBeInTheDocument();
  expect(within(toolbar).getByText("waiting_review")).toBeInTheDocument();
  expect(within(toolbar).queryByText("review")).not.toBeInTheDocument();
  expect(within(toolbar).queryByText("route: review")).not.toBeInTheDocument();
  expect(within(toolbar).queryByText("paused")).not.toBeInTheDocument();
  expect(within(toolbar).queryByText("1 / 1")).not.toBeInTheDocument();
  expect(within(toolbar).queryByRole("button", { name: "刷新" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "全屏视图" })).not.toBeInTheDocument();
});

it("replay 工作台使用 Codex 式中性配色", async () => {
  const globalsCss = readFileSync(join(process.cwd(), "src/app/globals.css"), "utf8");
  expect(globalsCss).toContain("--primary: #1f1f1f;");
  expect(globalsCss).toContain("--accent: #f2f2f3;");
  expect(globalsCss).toContain("--replay-panel: #fafafa;");
  expect(globalsCss).toContain("--replay-tool-row: #f3f3f4;");
  expect(globalsCss).not.toContain("#2f6fed");
  expect(globalsCss).not.toContain("#eaf2ff");

  const injectedLoadTaskDetail = jest.fn(async () => detailData);

  render(
    <TaskDetail
      taskId="task-001"
      initialSummary={waitingReviewSummary}
      loadTaskDetail={injectedLoadTaskDetail}
    />
  );

  const iframe = (await screen.findByTitle("document replay")) as HTMLIFrameElement;
  const srcDoc = iframe.getAttribute("srcdoc") ?? "";

  expect(srcDoc).toContain("background: #f1f1f2");
  expect(srcDoc).toContain("outline: 2px solid #d8d8da");
  expect(srcDoc).toContain("#1f1f1f");
  expect(srcDoc).toContain('font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif');
  expect(srcDoc).toContain("font-size: 15px");
  expect(srcDoc).toContain("line-height: 1.58");
  expect(srcDoc).not.toContain("#2f6fed");
  expect(srcDoc).not.toContain("#eaf2ff");
  expect(srcDoc).not.toContain("font-family: Inter");
  expect(srcDoc).not.toContain("rgba(14, 165, 164");
  expect(srcDoc).not.toContain("#0ea5a4");
});

it("replay agent 文字流和字段复核区不使用块状卡片样式", () => {
  const globalsCss = readFileSync(join(process.cwd(), "src/app/globals.css"), "utf8");
  const reasonRule = getCssRule(globalsCss, ".replay-agent-message");
  const toolRule = getCssRule(globalsCss, ".replay-agent-tool-line");
  const fieldWriteRule = getCssRule(globalsCss, ".replay-field-write");
  const fieldValueRule = getCssRule(globalsCss, ".replay-field-write-value");

  expect(reasonRule).toContain("border: 0;");
  expect(reasonRule).toContain("border-radius: 0;");
  expect(reasonRule).toContain("background: transparent;");
  expect(reasonRule).toContain("padding: 2px 0;");
  expect(reasonRule).not.toContain("border: 1px");

  expect(toolRule).toContain("border: 0;");
  expect(toolRule).toContain("border-radius: 0;");
  expect(toolRule).toContain("background: transparent;");
  expect(toolRule).toContain("padding: 1px 0;");
  expect(toolRule).not.toContain("var(--replay-tool-row)");

  expect(fieldWriteRule).toContain("border: 0;");
  expect(fieldWriteRule).toContain("background: transparent;");
  expect(fieldWriteRule).toContain("max-width: none;");
  expect(fieldWriteRule).toContain("-apple-system");
  expect(fieldWriteRule).toContain("font-size: 13px;");
  expect(fieldWriteRule).not.toContain("rgb(255 255 255 / 0.72)");

  expect(fieldValueRule).toContain("-apple-system");
  expect(fieldValueRule).toContain("font-size: 13px;");
  expect(fieldValueRule).not.toContain("SFMono-Regular");
});

it("多文件任务顶部标题跟随当前选中文件", async () => {
  const multiFileDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      documents: [
        { document_id: "doc-1", filename: "first.pdf" },
        { document_id: "doc-2", filename: "second.pdf" }
      ],
      actions: [
        {
          tool_name: "read",
          reason: "读取第一个文件",
          args: {
            path: "/001-first/001-Intro.md",
          },
          result: {
            ok: true,
            path: "/001-first/001-Intro.md",
            kind: "paragraph",
            text: "First file text."
          }
        },
        {
          tool_name: "read",
          reason: "读取第二个文件",
          args: {
            path: "/002-second/001-Summary.md",
          },
          result: {
            ok: true,
            path: "/002-second/001-Summary.md",
            kind: "paragraph",
            text: "Second file text."
          }
        }
      ]
    }
  };
  const injectedLoadTaskDetail = jest.fn(async () => multiFileDetail);

  render(
    <TaskDetail
      taskId="task-001"
      initialSummary={waitingReviewSummary}
      loadTaskDetail={injectedLoadTaskDetail}
    />
  );

  expect(await screen.findByText("AI extraction replay")).toBeInTheDocument();
  const toolbar = screen.getByLabelText("Replay 顶部工具栏");
  expect(within(toolbar).getByText("task-001 / first.pdf")).toBeInTheDocument();

  fireEvent.click(screen.getByText("读取第一个文件"));

  expect(within(toolbar).getByText("task-001 / second.pdf")).toBeInTheDocument();
});

it("enum 字段复核提交 tagged payload 而不是字符串", async () => {
  const user = userEvent.setup();
  const enumVariants = [
    { name: "Entailment", type: "null", description: "合同文本支持该判断" },
    { name: "Contradiction", type: "null", description: "合同文本否定该判断" },
    { name: "NotMentioned", type: "null", description: "合同文本没有提到该判断" }
  ];
  const enumValue = { variant: "Entailment", value: null };
  const enumDetail = {
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
          tool_name: "set_field",
          reason: "合同文本支持保密义务判断",
          args: {
            name: "nda_disclosure",
            value: enumValue,
            evidence_ids: ["p001_b001"],
          },
          result: {
            ok: true,
            field: {
              name: "nda_disclosure",
              status: "resolved",
              value: enumValue,
              evidence_ids: ["p001_b001"],
              reason: "合同文本支持保密义务判断"
            }
          }
        }
      ]
    },
    review: {
      ...detailData.review,
      fields: [
        {
          ...detailData.review!.fields[0],
          field_name: "nda_disclosure",
          display_name: "保密义务判断",
          agent_value: enumValue,
          field_type: "enum",
          variants: enumVariants
        }
      ]
    }
  } as TaskDetailData;
  const injectedLoadTaskDetail = jest.fn(async () => enumDetail);
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
  expect(screen.getByText("写入字段：保密义务判断")).toBeInTheDocument();
  expect(screen.getByLabelText("保密义务判断 枚举选项")).toHaveValue("Entailment");
  expect(within(screen.getByLabelText("字段写入内容")).getByText("Entailment", { selector: ".replay-field-write-value" })).toBeInTheDocument();

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

it("真实 file_extraction_agent 工具以 Codex 工具行展示", async () => {
  const toolDetail: TaskDetailData = {
    ...detailData,
    result: {
      ...reviewResult,
      fields: [
        {
          ...reviewResult.fields[0],
          field_name: "nda_disclosure",
          display_name: "保密义务判断",
          agent_value: { variant: "Entailment", value: null },
          field_type: "enum",
          route: "review"
        }
      ]
    },
    review: {
      ...detailData.review,
      fields: [
        {
          ...detailData.review!.fields[0],
          field_name: "nda_disclosure",
          display_name: "保密义务判断",
          agent_value: { variant: "Entailment", value: null },
          field_type: "enum",
          review_reason: "需要人工确认 NLI 判断"
        }
      ]
    },
    replay: {
      ...baseReplay,
      actions: [
        {
          tool_name: "tree",
          reason: "先查看虚拟文件树",
          args: {
            path: "/",
            depth: 2,
          },
          result: {
            ok: true,
            path: "/",
            depth: 2,
            text: "/\n└── 001-sample-合同/\n    ├── 001-定义/\n    │   └── 001-Confidential.md\n    └── 002-条款/\n        └── 001-披露.table"
          }
        },
        {
          tool_name: "read",
          reason: "读取保密信息定义段落",
          args: {
            path: "/001-sample-合同/001-定义/001-Confidential.md",
            offset: 0,
            limit: 30,
          },
          result: {
            ok: true,
            path: "/001-sample-合同/001-定义/001-Confidential.md",
            kind: "paragraph",
            text: "Confidential Information includes financial information."
          }
        },
        {
          tool_name: "anchors",
          reason: "取得句子编号",
          args: {
            path: "/001-sample-合同/001-定义/001-Confidential.md",
          },
          result: {
            ok: true,
            path: "/001-sample-合同/001-定义/001-Confidential.md",
            anchors: [
              {
                id: "S001",
                preview: "Confidential Information includes financial information."
              }
            ]
          }
        },
        {
          tool_name: "query_table",
          reason: "查询披露限制表格行",
          args: {
            path: "/001-sample-合同/002-条款/001-披露.table",
            sql: "SELECT row, clause FROM data WHERE clause LIKE '%disclose%'",
            offset: 0,
            limit: 30,
          },
          result: {
            ok: true,
            path: "/001-sample-合同/002-条款/001-披露.table",
            kind: "table_query",
            text: [
              "---",
              "kind: table_query",
              "matched_rows: 1",
              "---",
              "",
              "| row | clause |",
              "| --- | --- |",
              "| R002 | 接收方不得披露保密信息 |"
            ].join("\n"),
            offset: 0,
            limit: 30,
            total: 1,
            has_more: false
          }
        },
        {
          tool_name: "bind_evidence",
          reason: "把定义句绑定为候选证据",
          args: {
            field_id: "nda_disclosure",
            evidence: [
              {
                path: "/001-sample-合同/001-定义/001-Confidential.md",
                sentences: ["S001"]
              }
            ],
          },
          result: {
            ok: true,
            field_id: "nda_disclosure",
            evidence: [
              {
                path: "/001-sample-合同/001-定义/001-Confidential.md",
                sentences: ["S001"]
              }
            ],
            evidence_texts: [
              {
                path: "/001-sample-合同/001-定义/001-Confidential.md",
                selector: "S001",
                text: "Confidential Information includes financial information."
              }
            ]
          }
        },
        {
          tool_name: "review_field",
          reason: "复看候选证据后再写字段",
          args: {
            field_id: "nda_disclosure",
          },
          result: {
            ok: true,
            field_id: "nda_disclosure",
            field_description: "判断合同是否支持保密义务",
            field: null,
            evidence_texts: [
              {
                path: "/001-sample-合同/001-定义/001-Confidential.md",
                selector: "S001",
                text: "Confidential Information includes financial information."
              }
            ],
            guidance: "This tool does not judge correctness."
          }
        },
        {
          tool_name: "write_field",
          reason: "最终写入 entailment 判断",
          args: {
            field_id: "nda_disclosure",
            value: { variant: "Entailment", value: null },
            final_evidence: [
              {
                path: "/001-sample-合同/001-定义/001-Confidential.md",
                sentences: ["S001"]
              }
            ],
            status: "resolved",
          },
          result: {
            ok: true,
            field: {
              field_id: "nda_disclosure",
              status: "resolved",
              value: { variant: "Entailment", value: null },
              evidence: [
                {
                  path: "/001-sample-合同/001-定义/001-Confidential.md",
                  sentences: ["S001"]
                }
              ],
              evidence_texts: [
                {
                  path: "/001-sample-合同/001-定义/001-Confidential.md",
                  selector: "S001",
                  text: "Confidential Information includes financial information."
                }
              ],
              reason: "最终写入 entailment 判断"
            }
          }
        },
        {
          tool_name: "submit_result",
          reason: "提交字段结果",
          args: {
          },
          result: {
            ok: false,
            errors: [
              {
                field_id: "governing_law",
                code: "MISSING_FIELD",
                message: "field was not written"
              }
            ]
          }
        }
      ]
    }
  };
  const injectedLoadTaskDetail = jest.fn(async () => toolDetail);

  render(
    <TaskDetail
      taskId="task-001"
      initialSummary={waitingReviewSummary}
      loadTaskDetail={injectedLoadTaskDetail}
    />
  );

  expect(await screen.findByText("AI extraction replay")).toBeInTheDocument();
  const firstReason = screen.getByText("先查看虚拟文件树");
  expect(firstReason.tagName.toLowerCase()).toBe("span");
  expect(firstReason).toHaveClass("replay-agent-reason-text");
  expect(firstReason).not.toHaveClass("is-emphasized");
  expect(within(screen.getByLabelText("Agent 文字流")).getByLabelText("tool tree")).toBeInTheDocument();
  expect(screen.getByLabelText("tool tree")).toHaveClass("replay-agent-tool-line");
  expect(screen.getByLabelText("tool tree")).toHaveAttribute("data-tool-icon", "terminal");
  expect(within(screen.getByLabelText("tool tree")).getByText("Ran tree /")).toBeInTheDocument();
  expect(within(screen.getByLabelText("tool tree")).queryByText("tree", { selector: ".replay-agent-tool-name" })).not.toBeInTheDocument();
  expect(
    within(screen.getByLabelText("虚拟文件树导航")).getByRole("button", { name: "001-sample-合同" })
  ).toBeInTheDocument();

  fireEvent.click(screen.getByText("先查看虚拟文件树"));
  expect(within(screen.getByLabelText("Agent 文字流")).getByLabelText("tool read")).toBeInTheDocument();
  expect(screen.getByLabelText("tool read")).toHaveClass("is-read-tool");
  expect(screen.getByLabelText("tool read")).toHaveAttribute("data-tool-icon", "search");
  expect(within(screen.getByLabelText("tool read")).getByText("Read paragraph Confidential · 30 limit")).toBeInTheDocument();
  expect(within(screen.getByLabelText("Agent 文字流")).queryByText("Confidential Information includes financial information.")).not.toBeInTheDocument();

  fireEvent.click(screen.getByText("读取保密信息定义段落"));
  expect(within(screen.getByLabelText("Agent 文字流")).queryByLabelText("tool anchors")).not.toBeInTheDocument();
  expect(within(screen.getByLabelText("Agent 文字流")).getByLabelText("tool query_table")).toBeInTheDocument();
  expect(within(screen.getByLabelText("tool query_table")).getByText("Queried 001-披露.table · 1 row · 30 limit")).toBeInTheDocument();
  expect(within(screen.getByLabelText("Agent 文字流")).queryByText("R002")).not.toBeInTheDocument();

  fireEvent.click(screen.getByText("查询披露限制表格行"));
  expect(within(screen.getByLabelText("Agent 文字流")).getByLabelText("tool bind_evidence")).toBeInTheDocument();

  fireEvent.click(screen.getByText("把定义句绑定为候选证据"));
  expect(within(screen.getByLabelText("Agent 文字流")).getByLabelText("tool review_field")).toBeInTheDocument();
  expect(within(screen.getByLabelText("Agent 文字流")).queryByText("判断合同是否支持保密义务")).not.toBeInTheDocument();

  fireEvent.click(screen.getByText("复看候选证据后再写字段"));
  expect(screen.getByText("写入字段：保密义务判断")).toBeInTheDocument();
  expect(screen.getByText("需要人工确认 NLI 判断")).toBeInTheDocument();

  fireEvent.click(screen.getByText("最终写入 entailment 判断"));
  expect(within(screen.getByLabelText("Agent 文字流")).getByLabelText("tool submit_result")).toBeInTheDocument();
  expect(within(screen.getByLabelText("Agent 文字流")).queryByText("MISSING_FIELD")).not.toBeInTheDocument();
  expect(within(screen.getByLabelText("Agent 文字流")).queryByText("field was not written")).not.toBeInTheDocument();
});

it("read 工具摘要按 paragraph/table/list 语义展示，不暴露虚拟文件扩展名", async () => {
  const semanticReadDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      actions: [
        {
          tool_name: "read",
          reason: "读取定义段落",
          args: {
            path: "/001-合同/001-Confidential.md",
          },
          result: {
            ok: true,
            path: "/001-合同/001-Confidential.md",
            kind: "paragraph",
            text: "Confidential Information means..."
          }
        },
        {
          tool_name: "read",
          reason: "读取披露表",
          args: {
            path: "/001-合同/002-Disclosure.table",
          },
          result: {
            ok: true,
            path: "/001-合同/002-Disclosure.table",
            kind: "table",
            text: "| row | clause |"
          }
        },
        {
          tool_name: "read",
          reason: "读取义务列表",
          args: {
            path: "/001-合同/003-Obligations.list",
          },
          result: {
            ok: true,
            path: "/001-合同/003-Obligations.list",
            kind: "list",
            text: "- keep confidential"
          }
        }
      ]
    }
  };
  const injectedLoadTaskDetail = jest.fn(async () => semanticReadDetail);

  render(
    <TaskDetail
      taskId="task-001"
      initialSummary={waitingReviewSummary}
      loadTaskDetail={injectedLoadTaskDetail}
    />
  );

  expect(await screen.findByText("AI extraction replay")).toBeInTheDocument();
  expect(screen.getByText("Read paragraph Confidential")).toBeInTheDocument();
  expect(screen.queryByText("Read 001-Confidential.md")).not.toBeInTheDocument();

  fireEvent.click(screen.getByText("读取定义段落"));
  expect(screen.getByText("Read table Disclosure")).toBeInTheDocument();
  expect(screen.queryByText("Read 002-Disclosure.table")).not.toBeInTheDocument();

  fireEvent.click(screen.getByText("读取披露表"));
  expect(screen.getByText("Read list Obligations")).toBeInTheDocument();
  expect(screen.queryByText("Read 003-Obligations.list")).not.toBeInTheDocument();
});

it("中间 HTML 直接铺满文档容器，不保留灰色边框槽位", async () => {
  const injectedLoadTaskDetail = jest.fn(async () => detailData);

  render(
    <TaskDetail
      taskId="task-001"
      initialSummary={waitingReviewSummary}
      loadTaskDetail={injectedLoadTaskDetail}
    />
  );

  const iframe = (await screen.findByTitle("document replay")) as HTMLIFrameElement;
  const documentPanel = iframe.closest(".replay-document-panel");

  expect(documentPanel).not.toBeNull();
  expect(documentPanel).not.toHaveClass("rounded-md");
  expect(documentPanel).not.toHaveClass("border");
  expect(iframe).toHaveClass("block");
  expect(iframe).toHaveClass("border-0");
});

it("中间 HTML 使用全屏白底文档排版", async () => {
  const canvasDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      display_html: [
        '<h1 id="p001_b000">Report title</h1>',
        '<p id="p001_b001">A neutral paragraph for review.</p>',
        '<ul id="p001_b002"><li id="p001_b002_item_001">First item</li></ul>',
        '<figure id="p001_b003" data-type="table"><table id="p001_b003_table"><thead><tr><th>Name</th><th>Value</th></tr></thead><tbody><tr id="p001_b003_tr_001"><td>A</td><td>1</td></tr></tbody></table></figure>'
      ].join(""),
    },
  };
  const injectedLoadTaskDetail = jest.fn(async () => canvasDetail);

  render(
    <TaskDetail
      taskId="task-001"
      initialSummary={waitingReviewSummary}
      loadTaskDetail={injectedLoadTaskDetail}
    />
  );

  const iframe = (await screen.findByTitle("document replay")) as HTMLIFrameElement;
  const srcDoc = iframe.getAttribute("srcdoc") ?? "";

  expect(srcDoc).toContain("class=\"document-canvas\"");
  expect(srcDoc).toContain("max-width: min(100%, 1040px)");
  expect(srcDoc).toContain("background: #ffffff");
  expect(srcDoc).toContain("min-height: 100vh");
  expect(srcDoc).toContain("border: 0");
  expect(srcDoc).not.toContain("box-shadow: 0 26px 70px");
  expect(srcDoc).toContain("padding: clamp(42px, 5.2vw, 72px)");
  expect(srcDoc).toContain('font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif');
  expect(srcDoc).toContain("font-size: 15px");
  expect(srcDoc).toContain("line-height: 1.58");
  expect(srcDoc).toContain("border-collapse: collapse");
  expect(srcDoc).toContain("tbody tr:hover");
  expect(srcDoc).toContain(".document-canvas ul");
  expect(srcDoc).toContain(".document-canvas ol");
  expect(srcDoc).toContain("data-document-canvas=\"true\"");
});

it("中间 HTML 画布不展示页码和页脚噪声", async () => {
  const htmlDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      display_html: [
        '<section class="page" id="page_001" data-page="1">',
        '<div class="page-number">Page 1</div>',
        '<h1 id="p001_b000">MUTUAL NON-DISCLOSURE AGREEMENT</h1>',
        '<p id="p001_b001">正文内容</p>',
        '<div id="p001_b006" class="block block-page_footer" data-type="page_footer">428249v2</div>',
        '</section>',
        '<section class="page" id="page_002" data-page="2">',
        '<div class="page-number">Page 2</div>',
        '<p id="p002_b001">第二页正文</p>',
        '</section>'
      ].join(""),
    },
  };
  const injectedLoadTaskDetail = jest.fn(async () => htmlDetail);

  render(
    <TaskDetail
      taskId="task-001"
      initialSummary={waitingReviewSummary}
      loadTaskDetail={injectedLoadTaskDetail}
    />
  );

  const iframe = (await screen.findByTitle("document replay")) as HTMLIFrameElement;
  const srcDoc = iframe.getAttribute("srcdoc") ?? "";

  expect(srcDoc).toContain("MUTUAL NON-DISCLOSURE AGREEMENT");
  expect(srcDoc).toContain("第二页正文");
  expect(srcDoc).not.toContain("Page 1");
  expect(srcDoc).not.toContain("Page 2");
  expect(srcDoc).not.toContain("428249v2");
  expect(srcDoc).not.toContain("page-number");
  expect(srcDoc).not.toContain("block-page_footer");
});

it("右侧 agent 没有真实 reason 时只显示 tool 行，不灌默认占位文案", async () => {
  const toolOnlyDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      display_html: '<h1 id="p001_b000">Contract</h1>',
      outline_tree: [],
      actions: [
        {
          tool_name: "search_elements",
          args: {
            query: "Confidential Information",
            max_results: 10
          },
          result: {
            query: "Confidential Information",
            match_count: 0,
            matches: []
          }
        }
      ]
    }
  };
  const injectedLoadTaskDetail = jest.fn(async () => toolOnlyDetail);

  render(
    <TaskDetail
      taskId="task-001"
      initialSummary={waitingReviewSummary}
      loadTaskDetail={injectedLoadTaskDetail}
    />
  );

  expect(await screen.findByText("AI extraction replay")).toBeInTheDocument();
  const stream = screen.getByLabelText("Agent 文字流");
  expect(within(stream).getByLabelText("tool search_elements")).toBeInTheDocument();
  expect(within(stream).queryByText("模型等待下一步动作。")).not.toBeInTheDocument();
  expect(within(stream).queryByText("等待模型执行下一步。")).not.toBeInTheDocument();
});

it("file_extraction_agent 的虚拟文件树固定在左侧并随 path action 高亮", async () => {
  const fileTreeDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      display_html: '<h1 id="p001_b000">Contract</h1><p id="p001_b001">Confidential Information includes financial information.</p>',
      outline_tree: [],
      actions: [
        {
          tool_name: "tree",
          reason: "查看虚拟文件树",
          args: {
            path: "/",
            depth: 3,
          },
          result: {
            ok: true,
            path: "/",
            depth: 3,
            text: "/\n└── 001-sample-合同/\n    └── 001-定义/\n        └── 001-Confidential.md"
          }
        },
        {
          tool_name: "read",
          reason: "读取定义文件",
          args: {
            path: "/001-sample-合同/001-定义/001-Confidential.md",
          },
          result: {
            ok: true,
            path: "/001-sample-合同/001-定义/001-Confidential.md",
            kind: "paragraph",
            text: "Confidential Information includes financial information."
          }
        }
      ]
    }
  };
  const injectedLoadTaskDetail = jest.fn(async () => fileTreeDetail);

  render(
    <TaskDetail
      taskId="task-001"
      initialSummary={waitingReviewSummary}
      loadTaskDetail={injectedLoadTaskDetail}
    />
  );

  expect(await screen.findByText("AI extraction replay")).toBeInTheDocument();
  const fileTree = screen.getByLabelText("虚拟文件树导航");
  expect(screen.queryByRole("heading", { name: "文件树" })).not.toBeInTheDocument();
  expect(screen.queryByText("工具路径和证据会同步定位到这里")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "展开全部" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "折叠" })).not.toBeInTheDocument();
  const closeTreeButton = screen.getByRole("button", { name: "关闭左侧文件树" });
  const stage = document.querySelector(".replay-stage") as HTMLElement;
  expect(stage).toHaveAttribute("data-left-panel-open", "true");
  expect(stage.getAttribute("style")).toContain("--replay-left-panel-width: 224px");
  expect(stage.getAttribute("style")).toContain("--replay-right-panel-width: 384px");
  expect(within(fileTree).getByRole("button", { name: "001-sample-合同" })).toBeInTheDocument();
  expect(within(fileTree).getByRole("button", { name: "001-定义" })).toBeInTheDocument();
  expect(within(fileTree).getByRole("button", { name: "Confidential" })).toBeInTheDocument();
  expect(within(fileTree).queryByRole("button", { name: "001-Confidential.md" })).not.toBeInTheDocument();

  fireEvent.click(closeTreeButton);
  expect(stage).toHaveAttribute("data-left-panel-open", "false");
  expect(screen.queryByLabelText("虚拟文件树导航")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "打开左侧文件树" })).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "打开左侧文件树" }));
  const reopenedFileTree = screen.getByLabelText("虚拟文件树导航");
  expect(within(reopenedFileTree).getByRole("button", { name: "001-sample-合同" })).toBeInTheDocument();
  expect(within(reopenedFileTree).getByRole("button", { name: "Confidential" })).toBeInTheDocument();

  const folderNode = within(reopenedFileTree).getByRole("button", { name: "001-定义" });
  fireEvent.click(folderNode);
  expect(within(reopenedFileTree).queryByRole("button", { name: "Confidential" })).not.toBeInTheDocument();
  fireEvent.click(within(reopenedFileTree).getByRole("button", { name: "001-定义" }));

  const fileNode = within(reopenedFileTree).getByRole("button", { name: "Confidential" });
  expect(fileNode).not.toHaveClass("virtual-file-item-active");

  fireEvent.click(screen.getByText("查看虚拟文件树"));

  expect(within(screen.getByLabelText("Agent 文字流")).getByLabelText("tool read")).toBeInTheDocument();
  expect(fileNode).toHaveClass("virtual-file-item-active");
  expect(within(reopenedFileTree).getByRole("button", { name: "001-定义" })).toHaveClass("virtual-file-item-active-path");
});

it("左右侧栏可以通过分隔条手动调整宽度", async () => {
  const fileTreeDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      display_html: '<h1 id="p001_b000">Contract</h1><p id="p001_b001">Confidential Information includes financial information.</p>',
      outline_tree: [],
      actions: [
        {
          tool_name: "tree",
          reason: "查看虚拟文件树",
          args: {
            path: "/",
            depth: 3,
          },
          result: {
            ok: true,
            path: "/",
            depth: 3,
            text: "/\n└── 001-sample-合同/\n    └── 001-定义/\n        └── 001-Confidential.md"
          }
        },
        {
          tool_name: "read",
          reason: "读取定义文件",
          args: {
            path: "/001-sample-合同/001-定义/001-Confidential.md",
          },
          result: {
            ok: true,
            path: "/001-sample-合同/001-定义/001-Confidential.md",
            kind: "paragraph",
            text: "Confidential Information includes financial information."
          }
        }
      ]
    }
  };
  const injectedLoadTaskDetail = jest.fn(async () => fileTreeDetail);

  render(
    <TaskDetail
      taskId="task-001"
      initialSummary={waitingReviewSummary}
      loadTaskDetail={injectedLoadTaskDetail}
    />
  );

  expect(await screen.findByText("AI extraction replay")).toBeInTheDocument();
  const stage = document.querySelector(".replay-stage") as HTMLElement;
  const leftResizeHandle = screen.getByRole("separator", { name: "调整左侧栏宽度" });
  const rightResizeHandle = screen.getByRole("separator", { name: "调整右侧栏宽度" });
  expect(stage).toHaveAttribute("data-left-panel-open", "true");
  expect(stage.getAttribute("style")).toContain("--replay-left-panel-width: 224px");
  expect(stage.getAttribute("style")).toContain("--replay-right-panel-width: 384px");

  act(() => {
    fireEvent(leftResizeHandle, new MouseEvent("pointerdown", { clientX: 220, bubbles: true }));
    window.dispatchEvent(new MouseEvent("pointermove", { clientX: 260, bubbles: true }));
    window.dispatchEvent(new MouseEvent("pointerup", { clientX: 260, bubbles: true }));
  });

  expect(stage.getAttribute("style")).toContain("--replay-left-panel-width: 264px");

  act(() => {
    fireEvent(rightResizeHandle, new MouseEvent("pointerdown", { clientX: 800, bubbles: true }));
    window.dispatchEvent(new MouseEvent("pointermove", { clientX: 760, bubbles: true }));
    window.dispatchEvent(new MouseEvent("pointerup", { clientX: 760, bubbles: true }));
  });

  expect(stage.getAttribute("style")).toContain("--replay-right-panel-width: 424px");

  fireEvent.keyDown(rightResizeHandle, { key: "ArrowRight" });
  expect(stage.getAttribute("style")).toContain("--replay-right-panel-width: 408px");

  fireEvent.click(screen.getByRole("button", { name: "关闭左侧文件树" }));
  expect(stage).toHaveAttribute("data-left-panel-open", "false");
  expect(screen.queryByRole("separator", { name: "调整左侧栏宽度" })).not.toBeInTheDocument();
  expect(screen.getByRole("separator", { name: "调整右侧栏宽度" })).toBeInTheDocument();
});

it("虚拟文件树按工具返回顺序展示，不把文件夹排到文件上面", async () => {
  const orderedTreeDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      display_html: '<h1 id="p001_b000">Contract</h1>',
      outline_tree: [],
      actions: [
        {
          tool_name: "tree",
          reason: "查看虚拟文件树",
          args: {
            path: "/",
            depth: 2,
          },
          result: {
            ok: true,
            path: "/",
            depth: 2,
            text: "/\n├── 001-contract.md\n├── producer/\n│   └── 001-note.md\n└── 002-summary.md"
          }
        }
      ]
    }
  };
  const injectedLoadTaskDetail = jest.fn(async () => orderedTreeDetail);

  render(
    <TaskDetail
      taskId="task-001"
      initialSummary={waitingReviewSummary}
      loadTaskDetail={injectedLoadTaskDetail}
    />
  );

  expect(await screen.findByText("AI extraction replay")).toBeInTheDocument();
  const rootLabels = within(screen.getByLabelText("虚拟文件树导航"))
    .getAllByRole("button")
    .map((button) => button.getAttribute("aria-label"));
  expect(rootLabels.slice(0, 3)).toEqual(["contract", "producer", "note"]);
  expect(rootLabels).not.toContain("001-contract.md");
  expect(rootLabels).not.toContain("001-note.md");
});

it("右侧 agent 以从上往下的文字流累积 reason 和当前 tool", async () => {
  const streamDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      display_html: '<h1 id="p001_b000">Contract</h1><p id="p001_b001">Confidential Information includes financial information.</p>',
      outline_tree: [],
      actions: [
        {
          tool_name: "tree",
          reason: "查看虚拟文件树",
          args: {
            path: "/",
            depth: 3,
          },
          result: {
            ok: true,
            path: "/",
            depth: 3,
            text: "/\n└── 001-sample-合同/\n    └── 001-定义/\n        └── 001-Confidential.md"
          }
        },
        {
          tool_name: "read",
          reason: "读取定义文件",
          args: {
            path: "/001-sample-合同/001-定义/001-Confidential.md",
          },
          result: {
            ok: true,
            path: "/001-sample-合同/001-定义/001-Confidential.md",
            kind: "paragraph",
            text: "Confidential Information includes financial information."
          }
        }
      ]
    }
  };
  const injectedLoadTaskDetail = jest.fn(async () => streamDetail);

  render(
    <TaskDetail
      taskId="task-001"
      initialSummary={waitingReviewSummary}
      loadTaskDetail={injectedLoadTaskDetail}
    />
  );

  expect(await screen.findByText("AI extraction replay")).toBeInTheDocument();
  const stream = screen.getByLabelText("Agent 文字流");
  expect(within(stream).getByText("查看虚拟文件树")).toBeInTheDocument();
  expect(within(stream).queryByText("读取定义文件")).not.toBeInTheDocument();

  fireEvent.click(within(stream).getByText("查看虚拟文件树"));

  expect(within(stream).getByText("查看虚拟文件树")).toBeInTheDocument();
  expect(within(stream).getByText("读取定义文件")).toBeInTheDocument();
  expect(within(screen.getByLabelText("Agent 文字流")).getByLabelText("tool read")).toBeInTheDocument();
});

it("右侧 agent 条目悬浮时显示跳转和单步播放按钮，左键文字继续下一步", async () => {
  const hoverControlDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      display_html: '<h1 id="p001_b000">Contract</h1><p id="p001_b001">Confidential Information includes financial information.</p>',
      outline_tree: [],
      actions: [
        {
          tool_name: "tree",
          reason: "查看虚拟文件树",
          args: {
            path: "/",
            depth: 3,
          },
          result: {
            ok: true,
            path: "/",
            depth: 3,
            text: "/\n└── 001-sample-合同/\n    └── 001-定义/\n        └── 001-Confidential.md"
          }
        },
        {
          tool_name: "read",
          reason: "读取定义文件",
          args: {
            path: "/001-sample-合同/001-定义/001-Confidential.md",
          },
          result: {
            ok: true,
            path: "/001-sample-合同/001-定义/001-Confidential.md",
            kind: "paragraph",
            text: "Confidential Information includes financial information."
          }
        }
      ]
    }
  };
  const injectedLoadTaskDetail = jest.fn(async () => hoverControlDetail);

  render(
    <TaskDetail
      taskId="task-001"
      initialSummary={waitingReviewSummary}
      loadTaskDetail={injectedLoadTaskDetail}
    />
  );

  expect(await screen.findByText("AI extraction replay")).toBeInTheDocument();
  const stream = screen.getByLabelText("Agent 文字流");
  expect(within(stream).queryByRole("button", { name: "跳到第 1 步" })).not.toBeInTheDocument();
  expect(within(stream).queryByRole("button", { name: "只播放第 1 步" })).not.toBeInTheDocument();

  const firstStep = within(stream).getByLabelText("第 1 步 tree");
  fireEvent.mouseEnter(firstStep);
  expect(within(firstStep).getByRole("button", { name: "跳到第 1 步" })).toBeInTheDocument();
  expect(within(firstStep).getByRole("button", { name: "只播放第 1 步" })).toBeInTheDocument();

  fireEvent.click(within(firstStep).getByText("查看虚拟文件树"));
  expect(screen.getByText("2/2")).toBeInTheDocument();

  fireEvent.mouseEnter(within(stream).getByLabelText("第 1 步 tree"));
  fireEvent.click(within(stream).getByRole("button", { name: "跳到第 1 步" }));
  expect(screen.getByText("1/2")).toBeInTheDocument();

  fireEvent.mouseEnter(within(stream).getByLabelText("第 1 步 tree"));
  fireEvent.click(within(stream).getByRole("button", { name: "只播放第 1 步" }));
  expect(screen.getByText("1/2")).toBeInTheDocument();
});

it("path + selector 证据会映射并高亮 iframe HTML", async () => {
  const selectorDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      display_html: '<h1 id="p001_b000">Contract</h1><p id="p001_b001">Definitions. Confidential Information\n        includes <strong>financial</strong> information. The rest of this paragraph is not evidence.</p>',
      outline_tree: [],
      actions: [
        {
          tool_name: "bind_evidence",
          reason: "绑定定义文件中的 S001",
          args: {
            field_id: "nda_disclosure",
            evidence: [
              {
                path: "/001-sample-合同/001-定义/001-Confidential.md",
                sentences: ["S001"]
              }
            ],
          },
          result: {
            ok: true,
            field_id: "nda_disclosure",
            evidence: [
              {
                path: "/001-sample-合同/001-定义/001-Confidential.md",
                sentences: ["S001"]
              }
            ],
            evidence_texts: [
              {
                path: "/001-sample-合同/001-定义/001-Confidential.md",
                selector: "S001",
                text: "Confidential Information includes financial information."
              }
            ]
          }
        }
      ]
    }
  };
  const injectedLoadTaskDetail = jest.fn(async () => selectorDetail);

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
  iframeDocument?.write(iframe.getAttribute("srcdoc") ?? "");
  iframeDocument?.close();
  await loadReplayIframe(iframe);

  const inlineEvidence = iframeDocument?.querySelector(".replay-inline-evidence.is-current-highlight");
  expect(inlineEvidence).toHaveTextContent("Confidential Information includes financial information.");
  expect(inlineEvidence?.id).toContain("S001");
  expect(iframeDocument?.getElementById("p001_b001")).not.toHaveClass("is-current-highlight");
  expect(within(screen.getByLabelText("虚拟文件树导航")).getByRole("button", { name: "Confidential" })).toHaveClass("virtual-file-item-active");
});

it("动作 result 的诊断内容不进入右侧文字流，字段写入区也不承接诊断文字", async () => {
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
          reason: "抽取作品类型为学术论文的论文题目",
          args: {
            table_id: "p001_b002",
            sql: 'SELECT "论文题目" FROM data WHERE "作品类型" = "学术论文"',
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
          reason: "使用“作品类型 = 学术论文”筛出 1 行；空白作品类型行需要结合上下文判断，本次未作为学术论文证据；选中行论文题目无空值。",
          args: {
            name: "room_numbers",
            value: "论文 A",
            evidence_ids: ["p001_b002", "p001_b002_tr_001"],
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
  const stream = screen.getByLabelText("Agent 文字流");
  expect(within(stream).getByLabelText("tool custom_extraction")).toBeInTheDocument();
  expect(within(stream).queryByText("表格摘要")).not.toBeInTheDocument();
  expect(within(stream).queryByText("查表摘要")).not.toBeInTheDocument();
  expect(within(stream).queryByText("表格 3 行；2 列；空白单元格：作品类型 空白 1 行。")).not.toBeInTheDocument();
  expect(
    within(stream).queryByText("返回 1 行；筛选列“作品类型”空白 1 行；非空分布：学术论文 1，学术 论文 1；输出列“论文题目”无空值。")
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("抽取作品类型为学术论文的论文题目"));
  expect(screen.getByText("写入字段：文明寝室房间号")).toBeInTheDocument();
  expect(screen.queryByLabelText("字段模型判断")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("动作诊断摘要")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("字段质量风险")).not.toBeInTheDocument();
});

it("search_elements 动作只在右侧显示工具行摘要，命中片段留给 HTML 高亮", async () => {
  const searchDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      display_html: '<h1 id="p001_b000">Contract</h1><p id="p001_b001">Confidential Information includes financial information.</p>',
      actions: [
        {
          tool_name: "search_elements",
          reason: "Search for Confidential Information clauses",
          args: {
            query: "Confidential Information",
            limit: 20,
          },
          result: {
            query: "Confidential Information",
            limit: 20,
            match_count: 1,
            matches: [
              {
                element_id: "p001_b001",
                type: "TEXT",
                snippet: "Confidential Information includes financial information.",
                evidence_ids: ["p001_b001"],
                text_chars: 58
              }
            ],
            truncated: false
          }
        }
      ]
    }
  };
  const injectedLoadTaskDetail = jest.fn(async () => searchDetail);

  render(
    <TaskDetail
      taskId="task-001"
      initialSummary={waitingReviewSummary}
      loadTaskDetail={injectedLoadTaskDetail}
    />
  );

  expect(await screen.findByText("AI extraction replay")).toBeInTheDocument();
  const toolLine = screen.getByLabelText("tool search_elements");
  expect(within(toolLine).getByText("Searched for Confidential Information · 1 match · 20 limit")).toBeInTheDocument();
  expect(within(screen.getByLabelText("Agent 文字流")).queryByText("Confidential Information includes financial information.")).not.toBeInTheDocument();
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
          reason: "先定位证据",
          args: {
            element_id: "p001_b001",
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
          reason: "查询表格结构",
          args: {
            element_id: "p001_b002",
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
          reason: "查询表格结构",
          args: {
            element_id: "p001_b002",
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
          reason: "整张表作为字段依据",
          args: {
            name: "room_numbers",
            value: "1-101",
            evidence_ids: ["p001_b002"],
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
          reason: "查询表格结构",
          args: {
            element_id: "p001_b002",
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
          reason: "抽取结论列",
          args: {
            table_id: "p001_b002",
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

it("table_extraction 失败或空结果时不自动读取整表", async () => {
  jest.useFakeTimers();
  const tableScrolls: string[] = [];
  const emptyQueryDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      display_html: [
        '<figure id="p001_b002" data-type="table">',
        '<table id="p001_b002_table">',
        '<tr id="p001_b002_tr_000"><td>序号</td><td>作品类型</td><td>论文题目</td></tr>',
        '<tr id="p001_b002_tr_001"><td>1</td><td>学术论文</td><td>论文 A</td></tr>',
        '<tr id="p001_b002_tr_112"><td>112</td><td>学术论文</td><td>论文 B</td></tr>',
        '</table>',
        '</figure>'
      ].join(""),
      actions: [
        {
          tool_name: "table_extraction",
          reason: "LIKE 查询学术论文行",
          args: {
            table_id: "p001_b002",
            sql: 'SELECT * FROM data WHERE "作品类型" LIKE \'%学术论文%\'',
          },
          result: {
            ok: false,
            table_id: "p001_b002",
            row_count: 114,
            rows: [],
            error: "table is too large for unbounded SELECT *"
          }
        },
        {
          tool_name: "table_extraction",
          reason: "只查询序号 112",
          args: {
            table_id: "p001_b002",
            sql: 'SELECT "序号","论文题目" FROM data WHERE "序号" = \'112\'',
          },
          result: {
            ok: true,
            table_id: "p001_b002",
            row_count: 0,
            rows: []
          }
        },
        {
          tool_name: "update_plan",
          reason: "继续改用姓名查询",
          args: {
            plan_index: 1,
            status: "completed",
          },
          result: {
            ok: true
          }
        }
      ]
    }
  };
  const injectedLoadTaskDetail = jest.fn(async () => emptyQueryDetail);

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
    iframe.contentDocument?.write(emptyQueryDetail.replay?.display_html ?? "");
    iframe.contentDocument?.close();
    for (const id of ["p001_b002", "p001_b002_table", "p001_b002_tr_000", "p001_b002_tr_001", "p001_b002_tr_112"]) {
      const element = iframe.contentDocument?.getElementById(id);
      if (!element) {
        continue;
      }
      Object.defineProperty(element, "scrollIntoView", {
        configurable: true,
        value: function scrollIntoView(this: Element) {
          tableScrolls.push(this.id);
        }
      });
    }
    await loadReplayIframe(iframe);

    expect(screen.getByText("查询失败 · table is too large for unbounded SELECT *")).toBeInTheDocument();
    expect(screen.queryByText("未查到结果")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("LIKE 查询学术论文行"));
    expect(await screen.findByText("未查到结果 · 0 rows · 没有查到匹配行。")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "自动播放" }));
    await act(async () => {
      await jest.advanceTimersByTimeAsync(6000);
    });

    expect(tableScrolls).toEqual([]);
    expect(iframe.contentDocument?.getElementById("p001_b002")).not.toHaveClass("is-reading-line");
    expect(iframe.contentDocument?.getElementById("p001_b002_tr_000")).not.toHaveClass("is-table-row-result-highlight");
    expect(iframe.contentDocument?.getElementById("p001_b002_tr_001")).not.toHaveClass("is-table-row-result-highlight");
    expect(iframe.contentDocument?.getElementById("p001_b002_tr_112")).not.toHaveClass("is-table-row-result-highlight");
  } finally {
    jest.useRealTimers();
  }
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
          reason: "抽取文明寝室行",
          args: {
            table_id: "p001_b002",
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
          reason: "乱序 evidence ids 也要按 HTML 顺序读取",
          args: {
            name: "room_numbers",
            value: "1-101,1-102,1-103",
            evidence_ids: ["p001_b003", "p001_b001", "p001_b002"],
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
          reason: "第一次读取同一证据块",
          args: {
            element_id: "p001_b001",
          },
          result: {
            evidence_ids: ["p001_b001"]
          }
        },
        {
          tool_name: "lookup_block",
          reason: "继续使用同一证据块",
          args: {
            element_id: "p001_b001",
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

it("左侧栏关闭后自动播放不再执行左侧鼠标路径动画", async () => {
  jest.useFakeTimers();
  const originalElementScrollTo = HTMLElement.prototype.scrollTo;
  const outlineScrollTo = jest.fn();
  Object.defineProperty(HTMLElement.prototype, "scrollTo", {
    configurable: true,
    value: outlineScrollTo
  });
  const closedPanelDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      display_html: '<h1 id="p001_b000">文明寝室名单</h1><p id="p001_b001">关闭左栏后仍读取 HTML</p>',
      actions: [
        {
          tool_name: "search_grep",
          reason: "读取证据块",
          args: {
            element_id: "p001_b001",
          },
          result: {
            evidence_ids: ["p001_b001"]
          }
        }
      ]
    }
  };
  const injectedLoadTaskDetail = jest.fn(async () => closedPanelDetail);

  try {
    render(
      <TaskDetail
        taskId="task-001"
        initialSummary={waitingReviewSummary}
        loadTaskDetail={injectedLoadTaskDetail}
      />
    );

    expect(await screen.findByText("AI extraction replay")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "关闭左侧文档结构" }));
    const iframe = screen.getByTitle("document replay") as HTMLIFrameElement;
    iframe.contentDocument?.open();
    iframe.contentDocument?.write(closedPanelDetail.replay?.display_html ?? "");
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
    await loadReplayIframe(iframe);

    fireEvent.click(screen.getByRole("button", { name: "自动播放" }));
    await act(async () => {
      await jest.advanceTimersByTimeAsync(4000);
    });

    expect(outlineScrollTo).not.toHaveBeenCalled();
    expect(document.querySelector(".replay-cursor.is-visible")).not.toBeInTheDocument();
  } finally {
    Object.defineProperty(HTMLElement.prototype, "scrollTo", {
      configurable: true,
      value: originalElementScrollTo
    });
    jest.useRealTimers();
  }
});

it("文档结构不显示 page_001、页码和页脚这类节点", async () => {
  const pageOutlineDetail: TaskDetailData = {
    ...detailData,
    replay: {
      ...baseReplay,
      display_html: [
        '<section id="page_001">',
        '<div id="p001_b006" data-type="page_footer">428249v2</div>',
        '<h1 id="p001_b000">第一页标题</h1>',
        '<p id="p001_b001">第一页内容</p>',
        '</section>',
        '<section id="page_002">',
        '<div id="p002_b000" data-type="page_number">Page 2</div>',
        '<h1 id="p002_b000_title">第二页标题</h1>',
        '<p id="p002_b001">第二页内容</p>',
        '</section>'
      ].join(""),
      outline_tree: [
        {
          id: "page_001",
          type: "PAGE",
          text: "Page 1",
          children: [
            {
              id: "p001_b000",
              type: "TITLE",
              text: "第一页标题",
              children: []
            }
          ]
        },
        {
          id: "p001_b006",
          type: "PAGE_FOOTER",
          text: "428249v2",
          children: []
        },
        {
          id: "page_002",
          type: "PAGE",
          text: "Page 2",
          children: [
            {
              id: "p002_b000",
              type: "PAGE_NUMBER",
              text: "Page 2",
              children: []
            },
            {
              id: "p002_b000_title",
              type: "TITLE",
              text: "第二页标题",
              children: []
            }
          ]
        }
      ],
      actions: []
    }
  };
  const injectedLoadTaskDetail = jest.fn(async () => pageOutlineDetail);

  render(
    <TaskDetail
      taskId="task-001"
      initialSummary={waitingReviewSummary}
      loadTaskDetail={injectedLoadTaskDetail}
    />
  );

  expect(await screen.findByText("AI extraction replay")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Page 1" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Page 2" })).not.toBeInTheDocument();
  expect(screen.queryByText(/Page 2/)).not.toBeInTheDocument();
  expect(screen.queryByText(/428249v2/)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Header: 第一页标题" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Header: 第二页标题" })).toBeInTheDocument();
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
          reason: "读取多个候选证据",
          args: {
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

it("长字段写入区把字段内容和复核区分离，避免全屏时复核入口被撑出视口", async () => {
  const longValue = Array.from({ length: 36 }, (_, index) => `论文题目 ${index + 1}`);
  const longFieldDetail: TaskDetailData = {
    ...detailData,
    result: {
      ...reviewResult,
      fields: [
        {
          ...reviewResult.fields[0],
          agent_value: longValue
        }
      ]
    },
    replay: {
      ...baseReplay,
      actions: [
        {
          tool_name: "set_field",
          reason: "长列表字段写入",
          args: {
            name: "room_numbers",
            value: longValue,
            evidence_ids: ["p001_b001"],
          },
          result: {
            ok: true,
            field: {
              name: "room_numbers",
              status: "resolved",
              value: longValue,
              evidence_ids: ["p001_b001"]
            }
          }
        }
      ]
    },
    review: {
      ...detailData.review,
      fields: [
        {
          ...detailData.review.fields[0],
          agent_value: longValue,
          review_reason: "字段很长，需要人工确认"
        }
      ]
    }
  };
  const injectedLoadTaskDetail = jest.fn(async () => longFieldDetail);

  render(
    <TaskDetail
      taskId="task-001"
      initialSummary={waitingReviewSummary}
      loadTaskDetail={injectedLoadTaskDetail}
    />
  );

  expect(await screen.findByText("AI extraction replay")).toBeInTheDocument();
  const fieldCard = screen.getByLabelText("字段写入区");
  const fieldContent = within(fieldCard).getByLabelText("字段写入内容");
  const reviewArea = within(fieldCard).getByLabelText("字段复核区");
  const replayRoot = fieldCard.closest(".replay-review-root");
  expect(within(fieldContent).getByText(/论文题目 36/)).toBeInTheDocument();
  expect(within(reviewArea).getByLabelText("文明寝室房间号 复核值")).toBeInTheDocument();
  expect(within(reviewArea).getByRole("button", { name: "提交修正并通过" })).toBeInTheDocument();
  expect(within(fieldContent).queryByRole("button", { name: "提交修正并通过" })).not.toBeInTheDocument();
  expect(replayRoot).toHaveClass("has-field-write");
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
