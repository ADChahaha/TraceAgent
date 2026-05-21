import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { HomeWorkspace } from "@/components/home-workspace";
import type { TaskCreated, TaskSummary } from "@/lib/types";

const push = jest.fn();

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push })
}));

jest.mock("@/lib/api", () => ({
  createTask: jest.fn(),
  getTaskSummary: jest.fn(),
  listTasks: jest.fn()
}));

const api = jest.requireMock("@/lib/api") as {
  createTask: jest.Mock<Promise<TaskCreated>, [FormData]>;
  getTaskSummary: jest.Mock<Promise<TaskSummary>, [string]>;
  listTasks: jest.Mock<Promise<TaskSummary[]>, []>;
};

beforeEach(() => {
  window.localStorage.clear();
  push.mockClear();
  api.createTask.mockReset();
  api.getTaskSummary.mockReset();
  api.listTasks.mockReset();
  api.createTask.mockResolvedValue({
    task_id: "task_jump_target",
    status: "pending",
    stage: "uploaded",
    error_message: null
  });
  api.getTaskSummary.mockResolvedValue({
    task_id: "task_jump_target",
    status: "processing",
    stage: "document_processing",
    error_message: null,
    has_result: false,
    has_trace: false
  });
  api.listTasks.mockResolvedValue([]);
});

it("创建任务成功后直接跳到新任务详情页", async () => {
  const user = userEvent.setup();
  render(<HomeWorkspace />);

  await user.upload(
    screen.getByLabelText("PDF 文件输入"),
    new File(["%PDF-1.4 fake"], "sample.pdf", { type: "application/pdf" })
  );
  fireEvent.change(screen.getByLabelText("task_spec 输入框"), {
    target: {
      value: JSON.stringify({
        task_name: "admissions_guideline",
        fields: [{ name: "document_identity", type: "string", required: true }]
      })
    }
  });
  await user.click(screen.getByRole("button", { name: "发送 task_spec 创建任务" }));

  await waitFor(() => expect(api.createTask).toHaveBeenCalledTimes(1));
  expect(push).toHaveBeenCalledWith("/tasks/task_jump_target");
});
