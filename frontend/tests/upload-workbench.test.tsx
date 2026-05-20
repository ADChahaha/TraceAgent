import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as React from "react";
import { renderToString } from "react-dom/server";

import { UploadWorkbench } from "@/components/upload-workbench";
import type { TaskCreated, TaskSummary } from "@/lib/types";

type CreateTaskFn = (formData: FormData) => Promise<TaskCreated>;
type GetTaskSummaryFn = (taskId: string) => Promise<TaskSummary>;
type ListTasksFn = () => Promise<TaskSummary[]>;

const defaultCreatedTask: TaskCreated = {
  task_id: "task-created",
  status: "pending",
  stage: "uploaded",
  error_message: null
};

const defaultCompletedSummary: TaskSummary = {
  task_id: "task-created",
  status: "completed",
  stage: "done",
  error_message: null,
  has_result: true,
  has_trace: true,
};

function setup(
  createTask: CreateTaskFn = jest.fn(async () => defaultCreatedTask),
  getTaskSummary: GetTaskSummaryFn = jest.fn(async (taskId) => ({
    ...defaultCompletedSummary,
    task_id: taskId
  })),
  listTasks: ListTasksFn = jest.fn(async () => []),
  options: { strict?: boolean } = {}
) {
  const onCreated = jest.fn();
  const element = (
    <UploadWorkbench
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

it("首页默认就是 Codex 式新任务界面，不再显示旧上传首屏", () => {
  setup();

  expect(screen.getByRole("complementary", { name: "任务栏" })).toBeInTheDocument();
  expect(screen.getByRole("main", { name: "Agent 任务工作区" })).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: "What task should we run in agent_gate?" })
  ).toBeInTheDocument();
  expect(screen.getByRole("form", { name: "创建任务对话框" })).toBeInTheDocument();
  expect(screen.getByLabelText("task_spec 输入框")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "添加 PDF" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "发送 task_spec 创建任务" })).toBeInTheDocument();

  expect(screen.queryByText("上传工作台")).not.toBeInTheDocument();
  expect(screen.queryByText("backend 能力边界")).not.toBeInTheDocument();
  expect(screen.queryByText("等待 task_spec。")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Agent 文字流")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("task_type")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("metadata JSON")).not.toBeInTheDocument();
});

it("首页服务端首帧不读取 localStorage，避免服务端 HTML 与客户端 hydrate 不一致", async () => {
  window.localStorage.setItem(
    "agent-gate.recent-tasks",
    JSON.stringify([
      {
        task_id: "local-task-before-hydration",
        status: "completed",
        stage: "done",
        created_at: "2026-05-18T00:00:00Z"
      }
    ])
  );

  const serverHtml = renderToString(<UploadWorkbench listTasks={async () => []} />);
  expect(serverHtml).not.toContain("local-task-before-hydration");

  setup(undefined, undefined, async () => []);

  expect(await screen.findByText("local-task-before-hydration")).toBeInTheDocument();
});

it("New Chat 关闭左侧任务栏后不自动显示右侧 Progress", async () => {
  const user = userEvent.setup();
  setup();

  expect(screen.getByRole("complementary", { name: "任务栏" })).toBeInTheDocument();
  expect(screen.queryByLabelText("当前进度")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "关闭任务栏" }));

  expect(screen.queryByRole("complementary", { name: "任务栏" })).not.toBeInTheDocument();
  expect(screen.getByRole("main", { name: "Agent 任务工作区" })).toBeInTheDocument();
  expect(screen.queryByLabelText("当前进度")).not.toBeInTheDocument();
});

it("启动时从 backend 任务列表加载左侧任务栏", async () => {
  window.localStorage.clear();
  const listTasks = jest.fn(async () => [
    {
      task_id: "task_contract_nli_hard5_enum_final_evidence_72",
      status: "processing",
      stage: "extraction",
      error_message: null,
      has_result: true,
      has_trace: true,
      created_at: "2026-05-14T03:36:34Z",
      updated_at: "2026-05-14T16:50:44Z"
    },
    {
      task_id: "task_contract_nli_hard5_enum_final_evidence_27",
      status: "completed",
      stage: "done",
      error_message: null,
      has_result: true,
      has_trace: true,
      created_at: "2026-05-14T03:36:32Z",
      updated_at: "2026-05-14T16:50:44Z"
    }
  ] satisfies TaskSummary[]);

  setup(undefined, undefined, listTasks, { strict: true });

  await waitFor(() => expect(listTasks).toHaveBeenCalled());
  const sidebar = screen.getByRole("complementary", { name: "任务栏" });
  expect(await within(sidebar).findByText("task_contract_nli_hard5_enum_final_evidence_72")).toBeInTheDocument();
  expect(within(sidebar).getByText("task_contract_nli_hard5_enum_final_evidence_27")).toBeInTheDocument();
});

it("task_spec composer 会用 task_name 作为 task_type 并提交 PDF files", async () => {
  const user = userEvent.setup();
  const created: TaskCreated = {
    task_id: "task-001",
    status: "pending",
    stage: "uploaded",
    error_message: null
  };
  const createTask = jest.fn<Promise<TaskCreated>, [FormData]>(async () => created);
  const { onCreated } = setup(createTask);
  const taskSpec = {
    task_name: "contract_review",
    fields: [
      {
        field_name: "effective_date",
        display_name: "生效日期",
        type: "string",
        required: true
      }
    ]
  };

  await user.upload(
    screen.getByLabelText("PDF 文件输入"),
    [
      new File(["%PDF-1.4 fake"], "contract.pdf", { type: "application/pdf" }),
      new File(["%PDF-1.4 appendix"], "appendix.pdf", { type: "application/pdf" })
    ]
  );
  fireEvent.change(screen.getByLabelText("task_spec 输入框"), {
    target: { value: JSON.stringify(taskSpec) }
  });
  await user.click(screen.getByRole("button", { name: "发送 task_spec 创建任务" }));

  await waitFor(() => expect(createTask).toHaveBeenCalledTimes(1));
  const formData = createTask.mock.calls[0][0];
  expect(formData.get("task_type")).toBe("contract_review");
  expect(JSON.parse(String(formData.get("task_spec")))).toEqual(taskSpec);
  expect(formData.get("metadata")).toBeNull();
  expect(formData.getAll("files")).toHaveLength(2);
  expect((formData.getAll("files")[0] as File).name).toBe("contract.pdf");
  expect((formData.getAll("files")[1] as File).name).toBe("appendix.pdf");
  expect(await screen.findByText("task-001")).toBeInTheDocument();
  expect(onCreated).toHaveBeenCalledWith(created);
});

it("没有 PDF 或缺少 task_name 时不会创建任务", async () => {
  const user = userEvent.setup();
  const { createTask } = setup();

  fireEvent.change(screen.getByLabelText("task_spec 输入框"), {
    target: { value: JSON.stringify({ fields: [] }) }
  });
  await user.click(screen.getByRole("button", { name: "发送 task_spec 创建任务" }));

  expect(await screen.findByText("请选择 PDF 文件")).toBeInTheDocument();
  expect(createTask).not.toHaveBeenCalled();

  await user.upload(
    screen.getByLabelText("PDF 文件输入"),
    new File(["%PDF-1.4 fake"], "contract.pdf", { type: "application/pdf" })
  );
  await user.click(screen.getByRole("button", { name: "发送 task_spec 创建任务" }));

  expect(await screen.findByText("task_spec.task_name 不能为空")).toBeInTheDocument();
  expect(createTask).not.toHaveBeenCalled();
});

it("已选择的 PDF 可以逐个移除", async () => {
  const user = userEvent.setup();
  setup();

  await user.upload(
    screen.getByLabelText("PDF 文件输入"),
    [
      new File(["%PDF-1.4 fake"], "contract.pdf", { type: "application/pdf" }),
      new File(["%PDF-1.4 appendix"], "appendix.pdf", { type: "application/pdf" })
    ]
  );

  expect(screen.getByText("contract.pdf")).toBeInTheDocument();
  expect(screen.getByText("appendix.pdf")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "移除 contract.pdf" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "移除 appendix.pdf" })).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "移除 contract.pdf" }));

  expect(screen.queryByText("contract.pdf")).not.toBeInTheDocument();
  expect(screen.getByText("appendix.pdf")).toBeInTheDocument();
});

it("创建任务后左侧任务栏先显示处理中，轮询完成后显示处理结果", async () => {
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
    screen.getByLabelText("PDF 文件输入"),
    new File(["%PDF-1.4 fake"], "sample.pdf", { type: "application/pdf" })
  );
  fireEvent.change(screen.getByLabelText("task_spec 输入框"), {
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
  await user.click(screen.getByRole("button", { name: "发送 task_spec 创建任务" }));

  expect(await screen.findByText("task-queue")).toBeInTheDocument();
  expect(screen.getByText("处理中")).toBeInTheDocument();
  await waitFor(() => expect(getTaskSummary).toHaveBeenCalledWith("task-queue"));

  resolveSummary({
    task_id: "task-queue",
    status: "completed",
    stage: "done",
    error_message: null,
    has_result: true,
    has_trace: true
  });

  expect(await screen.findByText("处理结果")).toBeInTheDocument();
  expect(screen.getByText("completed")).toBeInTheDocument();
  expect(document.querySelector(".replay-task-route")).not.toBeInTheDocument();
  expect(document.querySelector(".replay-task-status-detail")).toBeInTheDocument();
});

it("主题切换仍在任务工作台顶部生效", async () => {
  const user = userEvent.setup();
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");

  setup();

  const themeButton = screen.getByRole("button", { name: "切换主题" });
  expect(themeButton).toHaveTextContent("Light");
  expect(document.documentElement).toHaveAttribute("data-theme", "light");

  await user.click(themeButton);

  expect(document.documentElement).toHaveAttribute("data-theme", "dark");
  expect(window.localStorage.getItem("agent-gate.theme")).toBe("dark");
  expect(themeButton).toHaveTextContent("Dark");
});
