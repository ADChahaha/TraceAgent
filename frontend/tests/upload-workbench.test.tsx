import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as React from "react";

import { UploadWorkbench } from "@/components/upload-workbench";
import type { Capabilities, TaskCreated, TaskSummary } from "@/lib/types";

const capabilities: Capabilities = {
  supported_file_types: ["pdf"],
  task_types: [],
  routes: ["accept", "review", "reject"],
  review_decisions: ["approve", "revise_and_approve", "reject"],
  features: {
    trace: true,
    review: true,
    audit: true,
    external_task_spec: true,
    multiple_files: true
  }
};

type CreateTaskFn = (formData: FormData) => Promise<TaskCreated>;
type GetTaskSummaryFn = (taskId: string) => Promise<TaskSummary>;
type ListTasksFn = () => Promise<TaskSummary[]>;

function setup(
  createTask: CreateTaskFn = jest.fn<CreateTaskFn>(),
  getTaskSummary: GetTaskSummaryFn = jest.fn<GetTaskSummaryFn>(async (taskId) => ({
    task_id: taskId,
    status: "completed",
    stage: "done",
    route: "accept",
    route_reason: null,
    error_message: null,
    has_result: true,
    has_trace: true,
    needs_review: false
  })),
  listTasks: ListTasksFn = jest.fn<ListTasksFn>(async () => []),
  options: { strict?: boolean } = {}
) {
  const onCreated = jest.fn();
  const element = (
    <UploadWorkbench
      capabilities={capabilities}
      createTask={createTask}
      getTaskSummary={getTaskSummary}
      listTasks={listTasks}
      onCreated={onCreated}
    />
  );
  render(options.strict ? <React.StrictMode>{element}</React.StrictMode> : element);
  return {
    createTask: createTask as jest.MockedFunction<CreateTaskFn>,
    getTaskSummary: getTaskSummary as jest.MockedFunction<GetTaskSummaryFn>,
    listTasks: listTasks as jest.MockedFunction<ListTasksFn>,
    onCreated
  };
}

it("默认 task_spec 不预置字段", () => {
  setup();

  const taskSpec = JSON.parse((screen.getByLabelText("task_spec JSON") as HTMLTextAreaElement).value);
  expect(taskSpec).toEqual({
    task_name: "",
    fields: []
  });
});

it("默认 task_type 为空且不展示内置类型提示", () => {
  setup();

  const taskType = screen.getByLabelText("task_type");
  expect(taskType).toHaveValue("");
  expect(taskType).not.toHaveAttribute("placeholder");
});

it("非法 task_spec 会阻止提交并提示 JSON object 错误", async () => {
  const user = userEvent.setup();
  const { createTask } = setup();

  await user.upload(
    screen.getByLabelText("上传 PDF（可多选）"),
    new File(["%PDF-1.4 fake"], "sample.pdf", { type: "application/pdf" })
  );
  await user.type(screen.getByLabelText("task_type"), "paper");
  await user.clear(screen.getByLabelText("task_spec JSON"));
  fireEvent.change(screen.getByLabelText("task_spec JSON"), {
    target: { value: "{bad json" }
  });
  await user.click(screen.getByRole("button", { name: "创建任务" }));

  expect(await screen.findByText("task_spec 必须是合法 JSON object")).toBeInTheDocument();
  expect(createTask).not.toHaveBeenCalled();
});

it("合法 PDF 和 JSON 会构造 backend 需要的 FormData", async () => {
  const user = userEvent.setup();
  const created: TaskCreated = {
    task_id: "task-001",
    status: "pending",
    stage: "uploaded",
    error_message: null
  };
  const createTask = jest.fn(async () => created);
  const { onCreated } = setup(createTask);

  const files = [
    new File(["%PDF-1.4 fake"], "sample.pdf", { type: "application/pdf" }),
    new File(["%PDF-1.4 fake supplement"], "supplement.pdf", { type: "application/pdf" })
  ];

  await user.upload(screen.getByLabelText("上传 PDF（可多选）"), files);
  await user.clear(screen.getByLabelText("task_type"));
  await user.type(screen.getByLabelText("task_type"), "civilized_dormitory");
  const taskSpec = {
    task_name: "civilized_dormitory",
    fields: [
      {
        field_name: "civilized_dormitory_rooms",
        display_name: "文明寝室房间号",
        type: "string",
        required: true
      },
      {
        field_name: "civilized_dormitory_count",
        display_name: "文明寝室数量",
        type: "string",
        required: true
      }
    ]
  };
  fireEvent.change(screen.getByLabelText("task_spec JSON"), {
    target: { value: JSON.stringify(taskSpec) }
  });
  await user.clear(screen.getByLabelText("metadata JSON"));
  fireEvent.change(screen.getByLabelText("metadata JSON"), {
    target: { value: "{\"source\":\"demo\"}" }
  });
  await user.click(screen.getByRole("button", { name: "创建任务" }));

  await waitFor(() => expect(createTask).toHaveBeenCalledTimes(1));
  const formData = createTask.mock.calls[0][0];
  expect(formData.get("task_type")).toBe("civilized_dormitory");
  expect(JSON.parse(String(formData.get("task_spec")))).toEqual(taskSpec);
  expect(JSON.parse(String(formData.get("metadata")))).toEqual({ source: "demo" });
  expect(formData.getAll("files")).toHaveLength(2);
  expect((formData.getAll("files")[0] as File).name).toBe("sample.pdf");
  expect((formData.getAll("files")[1] as File).name).toBe("supplement.pdf");
  await waitFor(() => expect(onCreated).toHaveBeenCalledWith(created));
});

it("创建任务后右侧列表先显示处理中，轮询完成后显示处理结果", async () => {
  const user = userEvent.setup();
  window.localStorage.clear();
  const created: TaskCreated = {
    task_id: "task-queue",
    status: "pending",
    stage: "uploaded",
    error_message: null
  };
  let resolveSummary: (value: TaskSummary) => void = () => {};
  const createTask = jest.fn(async () => created);
  const getTaskSummary = jest.fn(
    () =>
      new Promise<TaskSummary>((resolve) => {
        resolveSummary = resolve;
      })
  );
  setup(createTask, getTaskSummary);

  await user.upload(
    screen.getByLabelText("上传 PDF（可多选）"),
    new File(["%PDF-1.4 fake"], "sample.pdf", { type: "application/pdf" })
  );
  await user.clear(screen.getByLabelText("task_type"));
  await user.type(screen.getByLabelText("task_type"), "paper");
  fireEvent.change(screen.getByLabelText("task_spec JSON"), {
    target: {
      value: JSON.stringify({
        task_name: "paper",
        fields: [
          {
            field_name: "paper_titles",
            display_name: "论文名称",
            type: "string",
            required: true
          }
        ]
      })
    }
  });
  await user.click(screen.getByRole("button", { name: "创建任务" }));

  expect(await screen.findByText("task-queue")).toBeInTheDocument();
  expect(screen.getByText("处理中")).toBeInTheDocument();
  await waitFor(() => expect(getTaskSummary).toHaveBeenCalledWith("task-queue"));

  resolveSummary({
    task_id: "task-queue",
    status: "completed",
    stage: "done",
    route: "accept",
    route_reason: null,
    error_message: null,
    has_result: true,
    has_trace: true,
    needs_review: false
  });

  expect(await screen.findByText("处理结果")).toBeInTheDocument();
  expect(screen.getByText("accept")).toBeInTheDocument();
});

it("启动时从 backend 任务列表加载数据库任务", async () => {
  window.localStorage.clear();
  const listTasks = jest.fn(async () => [
    {
      task_id: "task_contract_nli_hard5_enum_final_evidence_72",
      status: "waiting_review",
      stage: "review",
      route: "review",
      route_reason: "需要人工复核",
      error_message: null,
      has_result: true,
      has_trace: true,
      needs_review: true,
      created_at: "2026-05-14T03:36:34Z",
      updated_at: "2026-05-14T16:50:44Z"
    },
    {
      task_id: "task_contract_nli_hard5_enum_final_evidence_27",
      status: "waiting_review",
      stage: "review",
      route: "review",
      route_reason: "需要人工复核",
      error_message: null,
      has_result: true,
      has_trace: true,
      needs_review: true,
      created_at: "2026-05-14T03:36:32Z",
      updated_at: "2026-05-14T16:50:44Z"
    }
  ] satisfies TaskSummary[]);

  setup(undefined, undefined, listTasks, { strict: true });

  await waitFor(() => expect(listTasks).toHaveBeenCalled());
  expect(await screen.findByText("task_contract_nli_hard5_enum_final_evidence_72")).toBeInTheDocument();
  expect(screen.getByText("task_contract_nli_hard5_enum_final_evidence_27")).toBeInTheDocument();
  expect(getRecentTaskIds()).toEqual([
    "task_contract_nli_hard5_enum_final_evidence_72",
    "task_contract_nli_hard5_enum_final_evidence_27"
  ]);
});

it("轮询旧任务完成时不会把它移动到最新任务上方", async () => {
  const user = userEvent.setup();
  window.localStorage.clear();
  const createdTasks: TaskCreated[] = [
    {
      task_id: "task-old",
      status: "pending",
      stage: "uploaded",
      error_message: null
    },
    {
      task_id: "task-new",
      status: "pending",
      stage: "uploaded",
      error_message: null
    }
  ];
  const summaryResolvers: Record<string, (value: TaskSummary) => void> = {};
  const createTask = jest.fn(async () => createdTasks.shift() as TaskCreated);
  const getTaskSummary = jest.fn(
    (taskId: string) =>
      new Promise<TaskSummary>((resolve) => {
        summaryResolvers[taskId] = resolve;
      })
  );
  setup(createTask, getTaskSummary);

  await user.upload(
    screen.getByLabelText("上传 PDF（可多选）"),
    new File(["%PDF-1.4 fake"], "sample.pdf", { type: "application/pdf" })
  );
  await user.type(screen.getByLabelText("task_type"), "paper");
  fireEvent.change(screen.getByLabelText("task_spec JSON"), {
    target: {
      value: JSON.stringify({
        task_name: "paper",
        fields: [
          {
            field_name: "paper_titles",
            display_name: "论文名称",
            type: "string",
            required: true
          }
        ]
      })
    }
  });

  await user.click(screen.getByRole("button", { name: "创建任务" }));
  await user.click(screen.getByRole("button", { name: "创建任务" }));

  await screen.findByText("task-new");
  expect(getRecentTaskIds()).toEqual(["task-new", "task-old"]);

  summaryResolvers["task-old"]({
    task_id: "task-old",
    status: "completed",
    stage: "done",
    route: "accept",
    route_reason: null,
    error_message: null,
    has_result: true,
    has_trace: true,
    needs_review: false
  });

  expect(await screen.findByText("处理结果")).toBeInTheDocument();
  await waitFor(() => expect(getRecentTaskIds()).toEqual(["task-new", "task-old"]));
});

it("能力边界会显示支持文件类型和 external task_spec 约束", () => {
  setup();

  expect(screen.getByText("支持文件：pdf")).toBeInTheDocument();
  expect(screen.getByText("task_spec 必须由前端显式提交")).toBeInTheDocument();
  expect(screen.getByText("支持多文件任务")).toBeInTheDocument();
  expect(screen.getByText("multipart 字段：files（可重复）")).toBeInTheDocument();
  expect(screen.getByText("旧版 file 字段仅后端兼容，前端固定提交 files。")).toBeInTheDocument();
});

function getRecentTaskIds(): string[] {
  return screen
    .getAllByRole("link")
    .map((link) => link.textContent ?? "")
    .filter((text) => text.startsWith("task"));
}
