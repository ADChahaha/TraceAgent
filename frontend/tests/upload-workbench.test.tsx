import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as React from "react";
import { renderToString } from "react-dom/server";

import { UploadWorkbench } from "@/components/upload-workbench";
import type { QaInputCreated, TaskCreated, TaskSummary } from "@/lib/types";

type CreateTaskFn = (formData: FormData) => Promise<TaskCreated>;
type CreateTaskInputFn = (taskId: string, content: string) => Promise<QaInputCreated>;
type ListTasksFn = () => Promise<TaskSummary[]>;

const defaultCreatedTask: TaskCreated = {
  task_id: "task-created",
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

const defaultInputCreated: QaInputCreated = {
  task_id: "task-created",
  turn_id: "turn-created",
  status: "completed",
  agent_completion_id: "cmp-created"
};

function setup(
  createTask: CreateTaskFn = jest.fn(async () => defaultCreatedTask),
  createTaskInput: CreateTaskInputFn = jest.fn(async () => defaultInputCreated),
  listTasks: ListTasksFn = jest.fn(async () => []),
  options: { strict?: boolean } = {}
) {
  const onCreated = jest.fn();
  const element = (
    <UploadWorkbench
      createTask={createTask}
      createTaskInput={createTaskInput}
      listTasks={listTasks}
      onCreated={onCreated}
    />
  );
  render(options.strict ? <React.StrictMode>{element}</React.StrictMode> : element);
  return {
    createTask: createTask as jest.MockedFunction<CreateTaskFn>,
    createTaskInput: createTaskInput as jest.MockedFunction<CreateTaskInputFn>,
    listTasks: listTasks as jest.MockedFunction<ListTasksFn>,
    onCreated
  };
}

it("首页默认就是 Codex 式新任务界面，不再显示旧上传首屏", () => {
  setup();

  expect(screen.getByRole("complementary", { name: "Tasks sidebar" })).toBeInTheDocument();
  expect(screen.getByRole("main", { name: "Agent task workspace" })).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: "What should we ask these documents?" })
  ).toBeInTheDocument();
  expect(screen.getByRole("form", { name: "Create task composer" })).toBeInTheDocument();
  expect(screen.getByLabelText("QA question input")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Add PDF" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Upload documents and ask" })).toBeInTheDocument();

  expect(screen.queryByText("上传工作台")).not.toBeInTheDocument();
  expect(screen.queryByText("backend 能力边界")).not.toBeInTheDocument();
  expect(screen.queryByText("等待 task_spec。")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Agent text stream")).not.toBeInTheDocument();
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

  expect(screen.getByRole("complementary", { name: "Tasks sidebar" })).toBeInTheDocument();
  expect(screen.queryByLabelText("当前进度")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Close sidebar" }));

  expect(screen.queryByRole("complementary", { name: "Tasks sidebar" })).not.toBeInTheDocument();
  expect(screen.getByRole("main", { name: "Agent task workspace" })).toBeInTheDocument();
  expect(screen.queryByLabelText("当前进度")).not.toBeInTheDocument();
});

it("首页左侧任务栏默认宽度和详情页一致，并支持键盘调整", async () => {
  const user = userEvent.setup();
  setup();

  const resizeHandle = screen.getByRole("separator", { name: "Resize left sidebar" });
  expect(resizeHandle).toHaveAttribute("aria-valuemin", "176");
  expect(resizeHandle).toHaveAttribute("aria-valuemax", "360");
  expect(resizeHandle).toHaveAttribute("aria-valuenow", "224");

  await user.keyboard("{ArrowRight}");
  expect(resizeHandle).toHaveAttribute("aria-valuenow", "224");

  resizeHandle.focus();
  await user.keyboard("{ArrowRight}");

  expect(resizeHandle).toHaveAttribute("aria-valuenow", "240");

  fireEvent(resizeHandle, new MouseEvent("pointerdown", { bubbles: true, clientX: 100 }));
  fireEvent(window, new MouseEvent("pointermove", { bubbles: true, clientX: 120 }));
  fireEvent(window, new MouseEvent("pointerup", { bubbles: true, clientX: 120 }));

  expect(resizeHandle).toHaveAttribute("aria-valuenow", "260");
});

it("启动时从 backend 任务列表加载左侧任务栏", async () => {
  window.localStorage.clear();
  const listTasks = jest.fn(async () => [
    {
      task_id: "task_contract_nli_hard5_enum_final_evidence_72",
      status: "running",
      stage: "answering",
      error_message: null,
      document_count: 2,
      active_turn_id: "turn-72",
      stream: { state: "running", last_event_seq: 12 },
      created_at: "2026-05-14T03:36:34Z",
      updated_at: "2026-05-14T16:50:44Z"
    },
    {
      task_id: "task_contract_nli_hard5_enum_final_evidence_27",
      status: "ready",
      stage: "ready",
      error_message: null,
      document_count: 1,
      active_turn_id: null,
      stream: { state: "idle", last_event_seq: 9 },
      created_at: "2026-05-14T03:36:32Z",
      updated_at: "2026-05-14T16:50:44Z"
    }
  ] satisfies TaskSummary[]);

  setup(undefined, undefined, listTasks, { strict: true });

  await waitFor(() => expect(listTasks).toHaveBeenCalled());
  const sidebar = screen.getByRole("complementary", { name: "Tasks sidebar" });
  expect(await within(sidebar).findByText("task_contract_nli_hard5_enum_final_evidence_72")).toBeInTheDocument();
  expect(within(sidebar).getByText("task_contract_nli_hard5_enum_final_evidence_27")).toBeInTheDocument();
});

it("QA composer 会创建多文档 task 并提交首轮问题", async () => {
  const user = userEvent.setup();
  const created: TaskCreated = {
    task_id: "task-001",
    status: "ready",
    stage: "ready",
    error_message: null,
    document_count: 2,
    active_turn_id: null,
    stream: { state: "idle", last_event_seq: 3 }
  };
  const createTask = jest.fn<Promise<TaskCreated>, [FormData]>(async () => created);
  let resolveInput: (value: QaInputCreated) => void = () => {};
  const createTaskInput = jest.fn<Promise<QaInputCreated>, [string, string]>(
    () =>
      new Promise<QaInputCreated>((resolve) => {
        resolveInput = resolve;
      })
  );
  const { onCreated } = setup(createTask, createTaskInput);

  await user.upload(
    screen.getByLabelText("PDF file input"),
    [
      new File(["%PDF-1.4 fake"], "contract.pdf", { type: "application/pdf" }),
      new File(["%PDF-1.4 appendix"], "appendix.pdf", { type: "application/pdf" })
    ]
  );
  fireEvent.change(screen.getByLabelText("QA question input"), {
    target: { value: "这份合同可以提前终止吗？" }
  });
  await user.click(screen.getByRole("button", { name: "Upload documents and ask" }));

  await waitFor(() => expect(createTask).toHaveBeenCalledTimes(1));
  const formData = createTask.mock.calls[0][0];
  expect(formData.get("task_type")).toBeNull();
  expect(formData.get("task_spec")).toBeNull();
  expect(formData.get("metadata")).toBeNull();
  expect(formData.getAll("files")).toHaveLength(2);
  expect((formData.getAll("files")[0] as File).name).toBe("contract.pdf");
  expect((formData.getAll("files")[1] as File).name).toBe("appendix.pdf");
  await waitFor(() => expect(createTaskInput).toHaveBeenCalledWith("task-001", "这份合同可以提前终止吗？"));
  expect(await screen.findByText("task-001")).toBeInTheDocument();
  expect(onCreated).toHaveBeenCalledWith(created);
  resolveInput({
    task_id: "task-001",
    turn_id: "turn-001",
    status: "queued",
    agent_completion_id: null
  });
});

it("QA composer 用 Enter 提交问题，Shift Enter 保留换行", async () => {
  const user = userEvent.setup();
  const created: TaskCreated = {
    task_id: "task-keyboard",
    status: "ready",
    stage: "ready",
    error_message: null,
    document_count: 1,
    active_turn_id: null,
    stream: { state: "idle", last_event_seq: 1 }
  };
  const createTask = jest.fn<Promise<TaskCreated>, [FormData]>(async () => created);
  const createTaskInput = jest.fn(async () => ({
    task_id: "task-keyboard",
    turn_id: "turn-keyboard",
    status: "queued",
    agent_completion_id: null
  }));
  setup(createTask, createTaskInput);

  await user.upload(
    screen.getByLabelText("PDF file input"),
    new File(["%PDF-1.4 fake"], "contract.pdf", { type: "application/pdf" })
  );
  const input = screen.getByLabelText("QA question input");
  await user.type(input, "第一行{Shift>}{Enter}{/Shift}第二行");

  expect(input).toHaveValue("第一行\n第二行");
  expect(createTask).not.toHaveBeenCalled();

  await user.keyboard("{Enter}");

  await waitFor(() => expect(createTask).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(createTaskInput).toHaveBeenCalledWith("task-keyboard", "第一行\n第二行"));
});

it("没有 PDF 或问题为空时不会创建任务", async () => {
  const user = userEvent.setup();
  const { createTask, createTaskInput } = setup();

  fireEvent.change(screen.getByLabelText("QA question input"), {
    target: { value: "   " }
  });
  await user.click(screen.getByRole("button", { name: "Upload documents and ask" }));

  expect(await screen.findByText("Select at least one PDF file")).toBeInTheDocument();
  expect(createTask).not.toHaveBeenCalled();
  expect(createTaskInput).not.toHaveBeenCalled();

  await user.upload(
    screen.getByLabelText("PDF file input"),
    new File(["%PDF-1.4 fake"], "contract.pdf", { type: "application/pdf" })
  );
  await user.click(screen.getByRole("button", { name: "Upload documents and ask" }));

  expect(await screen.findByText("Enter a question")).toBeInTheDocument();
  expect(createTask).not.toHaveBeenCalled();
  expect(createTaskInput).not.toHaveBeenCalled();
});

it("已选择的 PDF 可以逐个移除", async () => {
  const user = userEvent.setup();
  setup();

  await user.upload(
    screen.getByLabelText("PDF file input"),
    [
      new File(["%PDF-1.4 fake"], "contract.pdf", { type: "application/pdf" }),
      new File(["%PDF-1.4 appendix"], "appendix.pdf", { type: "application/pdf" })
    ]
  );

  expect(screen.getByText("contract.pdf")).toBeInTheDocument();
  expect(screen.getByText("appendix.pdf")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Remove contract.pdf" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Remove appendix.pdf" })).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Remove contract.pdf" }));

  expect(screen.queryByText("contract.pdf")).not.toBeInTheDocument();
  expect(screen.getByText("appendix.pdf")).toBeInTheDocument();
});

it("再次选择 PDF 会追加到已选文件而不是覆盖", async () => {
  const user = userEvent.setup();
  const created: TaskCreated = {
    task_id: "task-multi-add",
    status: "ready",
    stage: "ready",
    error_message: null,
    document_count: 2,
    active_turn_id: null,
    stream: { state: "idle", last_event_seq: 3 }
  };
  const createTask = jest.fn<Promise<TaskCreated>, [FormData]>(async () => created);
  const createTaskInput = jest.fn<Promise<QaInputCreated>, [string, string]>(async () => ({
    task_id: "task-multi-add",
    turn_id: "turn-multi-add",
    status: "completed",
    agent_completion_id: "cmp-multi-add"
  }));
  setup(createTask, createTaskInput);

  await user.upload(
    screen.getByLabelText("PDF file input"),
    new File(["%PDF-1.4 fake"], "contract.pdf", { type: "application/pdf" })
  );
  await user.upload(
    screen.getByLabelText("PDF file input"),
    new File(["%PDF-1.4 appendix"], "appendix.pdf", { type: "application/pdf" })
  );

  expect(screen.getByText("contract.pdf")).toBeInTheDocument();
  expect(screen.getByText("appendix.pdf")).toBeInTheDocument();
  expect(screen.getByText("2 PDFs")).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("QA question input"), {
    target: { value: "这两份 PDF 有什么共同点？" }
  });
  await user.click(screen.getByRole("button", { name: "Upload documents and ask" }));

  await waitFor(() => expect(createTask).toHaveBeenCalledTimes(1));
  const formData = createTask.mock.calls[0][0];
  expect(formData.getAll("files")).toHaveLength(2);
  expect((formData.getAll("files")[0] as File).name).toBe("contract.pdf");
  expect((formData.getAll("files")[1] as File).name).toBe("appendix.pdf");
  expect(await screen.findByText("task-multi-add")).toBeInTheDocument();
});

it("创建任务后左侧任务栏立即显示新任务，不轮询刷新摘要", async () => {
  const user = userEvent.setup();
  window.localStorage.clear();
  const created: TaskCreated = {
    task_id: "task-queue",
    status: "ready",
    stage: "ready",
    error_message: null,
    document_count: 1,
    active_turn_id: null,
    stream: { state: "idle", last_event_seq: 3 }
  };
  const createTask = jest.fn(async () => created);
  const createTaskInput = jest.fn(async () => ({
    task_id: "task-queue",
    turn_id: "turn-queue",
    status: "completed",
    agent_completion_id: "cmp-queue"
  }));
  setup(createTask, createTaskInput, jest.fn(async () => []));

  await user.upload(
    screen.getByLabelText("PDF file input"),
    new File(["%PDF-1.4 fake"], "sample.pdf", { type: "application/pdf" })
  );
  fireEvent.change(screen.getByLabelText("QA question input"), {
    target: { value: "总结这份 PDF。" }
  });
  await user.click(screen.getByRole("button", { name: "Upload documents and ask" }));

  expect(await screen.findByText("task-queue")).toBeInTheDocument();
  expect(screen.getByText("ready / ready")).toBeInTheDocument();
  await waitFor(() => expect(createTaskInput).toHaveBeenCalledWith("task-queue", "总结这份 PDF。"));

  expect(document.querySelector(".replay-task-route")).not.toBeInTheDocument();
  expect(document.querySelector(".replay-task-status-detail")).toBeInTheDocument();
});

it("主题切换仍在任务工作台顶部生效", async () => {
  const user = userEvent.setup();
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");

  setup();

  const themeButton = screen.getByRole("button", { name: "Toggle theme" });
  expect(themeButton).toHaveTextContent("Light");
  expect(document.documentElement).toHaveAttribute("data-theme", "light");

  await user.click(themeButton);

  expect(document.documentElement).toHaveAttribute("data-theme", "dark");
  expect(window.localStorage.getItem("agent-gate.theme")).toBe("dark");
  expect(themeButton).toHaveTextContent("Dark");
});
