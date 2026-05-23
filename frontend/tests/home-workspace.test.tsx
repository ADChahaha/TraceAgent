import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { HomeWorkspace } from "@/components/home-workspace";
import type { QaInputCreated, TaskCreated, TaskSummary } from "@/lib/types";

const push = jest.fn();

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push })
}));

jest.mock("@/lib/api", () => ({
  createTask: jest.fn(),
  createTaskInput: jest.fn(),
  listTasks: jest.fn()
}));

const api = jest.requireMock("@/lib/api") as {
  createTask: jest.Mock<Promise<TaskCreated>, [FormData]>;
  createTaskInput: jest.Mock<Promise<QaInputCreated>, [string, string]>;
  listTasks: jest.Mock<Promise<TaskSummary[]>, []>;
};

beforeEach(() => {
  window.localStorage.clear();
  push.mockClear();
  api.createTask.mockReset();
  api.createTaskInput.mockReset();
  api.listTasks.mockReset();
  api.createTask.mockResolvedValue({
    task_id: "task_jump_target",
    status: "ready",
    stage: "ready",
    error_message: null,
    document_count: 1,
    active_turn_id: null,
    stream: { state: "idle", last_event_seq: 3 }
  });
  api.createTaskInput.mockResolvedValue({
    task_id: "task_jump_target",
    turn_id: "turn_jump_target",
    status: "completed",
    agent_completion_id: "cmp_jump_target"
  });
  api.listTasks.mockResolvedValue([]);
});

it("创建 QA task 并提交首问后直接跳到新任务详情页", async () => {
  const user = userEvent.setup();
  render(<HomeWorkspace />);

  await user.upload(
    screen.getByLabelText("PDF file input"),
    new File(["%PDF-1.4 fake"], "sample.pdf", { type: "application/pdf" })
  );
  fireEvent.change(screen.getByLabelText("QA question input"), {
    target: { value: "这份招生简章的申请截止日期是什么？" }
  });
  await user.click(screen.getByRole("button", { name: "Upload documents and ask" }));

  await waitFor(() => expect(api.createTask).toHaveBeenCalledTimes(1));
  expect(api.createTaskInput).toHaveBeenCalledWith(
    "task_jump_target",
    "这份招生简章的申请截止日期是什么？"
  );
  expect(push).toHaveBeenCalledWith("/tasks/task_jump_target");
});
