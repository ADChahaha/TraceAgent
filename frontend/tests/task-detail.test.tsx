import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TaskDetail } from "@/components/task-detail";
import * as api from "@/lib/api";
import { controlledStream, ready, running } from "./helpers/session-fixtures";

jest.mock("@/lib/api", () => ({
  openResume: jest.fn(), openCompletion: jest.fn(), cancelCompletion: jest.fn(),
  readFullDocument: jest.fn(), listSessionDocuments: jest.fn(), readSessionDocument: jest.fn(), readSessionBlock: jest.fn(),
  uploadSessionFiles: jest.fn(), removeSessionFile: jest.fn(), sessionFileUrl: () => "/download", ApiError: class extends Error {},
}));
const resume = jest.mocked(api.openResume);
const complete = jest.mocked(api.openCompletion);

beforeEach(() => {
  jest.resetAllMocks(); localStorage.clear();
  jest.mocked(api.listSessionDocuments).mockResolvedValue({ documents: [{ key: "documents/contract.md", size: 25 }] });
  jest.mocked(api.readFullDocument).mockResolvedValue({ key: "documents/contract.md", blocks: [
    { key: "documents/contract.md", text: "Full source document\n\nPayment due in 37 days" },
  ] });
  jest.mocked(api.readSessionBlock).mockResolvedValue({ key: "documents/contract.md", text: "Payment due in 37 days", found: true });
});

it("恢复历史和实时增量，done 不重复文本，引用高亮整份原文中的段落", async () => {
  const stream = controlledStream(running);
  resume.mockResolvedValue(stream.response);
  render(<TaskDetail taskId="s1" />);
  expect(await screen.findByText("Question")).toBeInTheDocument();
  await act(async () => {
    stream.event("model_message.delta", { message_id: "m", delta: "37 days [source](documents/contract.md)" });
    stream.event("model_message.done", { message_id: "m", content: "37 days [source](documents/contract.md)" });
    stream.event("turn.completed");
  });
  expect(within(screen.getByLabelText("QA conversation and reading process")).getAllByText(/37 days/)).toHaveLength(1);
  await userEvent.click(screen.getByRole("link", { name: "Source 1" }));
  expect(await screen.findByText("Payment due in 37 days")).toBeInTheDocument();
  expect(api.readFullDocument).toHaveBeenCalledWith("s1", "documents/contract.md");
  expect(screen.queryByLabelText("Sources list")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Close document" }));
  expect(screen.getByLabelText("Sources list")).toBeInTheDocument();
  expect(screen.queryByLabelText("Full document")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("link", { name: "Source 1" }));
  expect(await screen.findByText("Payment due in 37 days")).toBeInTheDocument();
});

it("追问走 POST 流，输入框节点稳定，取消携带当前轮次", async () => {
  resume.mockResolvedValue(controlledStream(ready).response);
  const stream = controlledStream(running);
  complete.mockResolvedValue(stream.response);
  jest.mocked(api.cancelCompletion).mockResolvedValue({ status: "cancelled" });
  render(<TaskDetail taskId="s1" />);
  await screen.findByRole("link", { name: "Download contract.docx" });
  for (const name of ["Summarize the main ideas", "What are the key findings?", "Compare the sources"]) {
    expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
  }
  const input = screen.getByLabelText("QA question input");
  const action = screen.getByRole("button", { name: "Submit or pause answer" });
  fireEvent.change(input, { target: { value: "Question" } });
  fireEvent.keyDown(input, { key: "Enter" });
  await waitFor(() => expect(complete).toHaveBeenCalledWith("s1", "Question", expect.any(AbortSignal)));
  await screen.findByText("Question");
  expect(screen.getByLabelText("QA question input")).toBe(input);
  expect(screen.getByRole("button", { name: "Submit or pause answer" })).toBe(action);
  await userEvent.click(action);
  await waitFor(() => expect(api.cancelCompletion).toHaveBeenCalledWith("s1", "t1"));
  expect(await screen.findByText("Cancelled")).toBeInTheDocument();
});

it("窄窗口点击引用自动显示文档，并能返回聊天", async () => {
  const width = window.innerWidth;
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 600 });
  resume.mockResolvedValue(controlledStream({ ...ready, state: { ...ready.state, turns: [{ id: "t1", status: "completed", error: null, items: [
    { id: "message:m", kind: "assistant", status: "completed", text: "37 days [source](documents/contract.md)" },
  ] }] } }).response);
  try {
    render(<TaskDetail taskId="s1" />);
    expect(await screen.findByRole("link", { name: "Source 1" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Source content")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: "Source 1" }));
    expect(await screen.findByText("Payment due in 37 days")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Chat", exact: true }));
    expect(screen.queryByLabelText("Source content")).not.toBeInTheDocument();
  } finally { Object.defineProperty(window, "innerWidth", { configurable: true, value: width }); }
});

it("用户取消的历史轮次显示取消状态，不再重复报错", async () => {
  resume.mockResolvedValue(controlledStream({ ...ready, state: { ...ready.state, turns: [
    { id: "t1", status: "cancelled", error: "执行已取消", items: [] },
  ] } }).response);
  render(<TaskDetail taskId="s1" />);
  expect(await screen.findByText("Cancelled")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("合并被空消息打断的连续工具调用，以友好英文动作名展示且不暴露原始工具名", async () => {
  const withTools = {
    ...ready,
    state: {
      ...ready.state,
      turns: [{
        id: "t1",
        status: "completed" as const,
        error: null,
        items: [
          { id: "u1", kind: "user" as const, status: "completed" as const, text: "Check payment terms" },
          { id: "message:m1", kind: "assistant" as const, status: "completed" as const, text: "", tool_calls: [{ id: "c1" }] },
          { id: "tool:c1", kind: "tool" as const, status: "completed" as const, name: "ls" },
          { id: "message:m2", kind: "assistant" as const, status: "completed" as const, text: "   ", tool_calls: [{ id: "c2" }] },
          { id: "tool:c2", kind: "tool" as const, status: "completed" as const, name: "search_embedding" },
          { id: "message:m3", kind: "assistant" as const, status: "completed" as const, text: "", tool_calls: [{ id: "c3" }, { id: "c4" }] },
          { id: "tool:c3", kind: "tool" as const, status: "failed" as const, name: "grep" },
          { id: "tool:c4", kind: "tool" as const, status: "completed" as const, name: "read" },
          { id: "message:m4", kind: "assistant" as const, status: "completed" as const, text: "Payment due in 37 days [source](documents/contract.md)" },
        ],
      }],
    },
  };
  resume.mockResolvedValue(controlledStream(withTools).response);
  render(<TaskDetail taskId="s1" />);
  const stream = await screen.findByLabelText("QA conversation and reading process");
  const summaries = stream.querySelectorAll("summary");
  expect(summaries).toHaveLength(1);
  expect(summaries[0]).toHaveAttribute("aria-label", "4 lookup steps");
  expect(summaries[0]).toHaveTextContent("4");

  const steps = within(stream).getAllByRole("listitem");
  expect(steps.map((node) => node.textContent)).toEqual([
    "Browse files",
    "Semantic search",
    "Keyword search (unavailable)",
    "Read passage",
  ]);
  for (const rawName of ["ls", "grep", "read", "search_embedding", "tool activity"]) {
    expect(stream.textContent).not.toContain(rawName);
  }
});

it("顶栏加号位于左侧菜单旁，默认 36% 左栏分栏且点击引用与切回列表不重置宽度", async () => {
  const withTitle = {
    ...ready,
    state: {
      ...ready.state,
      title: "Contract Payment Terms",
      turns: [{
        id: "t1",
        status: "completed" as const,
        error: null,
        items: [{ id: "message:m", kind: "assistant" as const, status: "completed" as const, text: "37 days [source](documents/contract.md)" }],
      }],
    },
  };
  const originalWidth = window.innerWidth;
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 1440 });
  try {
    resume.mockResolvedValue(controlledStream(withTitle).response);
    const user = userEvent.setup();
    render(<TaskDetail taskId="s1" />);
    expect(await screen.findByText("Contract Payment Terms")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Document conversation" })).not.toBeInTheDocument();

    const header = screen.getByRole("banner");
    const menuBtn = within(header).getByRole("button", { name: "Open sidebar" });
    const newWorkspaceLink = within(header).getByRole("link", { name: "New workspace" });
    const themeBtn = within(header).getByRole("button", { name: "Toggle theme" });
    expect(menuBtn.parentElement).toBe(newWorkspaceLink.parentElement);
    expect(newWorkspaceLink.parentElement).not.toBe(themeBtn.parentElement);

    const resize = screen.getByRole("separator", { name: "Resize left sidebar" });
    resize.focus();
    await user.keyboard("{ArrowRight}{ArrowRight}");
    const resizedWidth = resize.getAttribute("aria-valuenow");
    expect(Number(resizedWidth)).toBe(566);

    await user.click(screen.getByRole("link", { name: "Source 1" }));
    expect(await screen.findByText("Payment due in 37 days")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Source 1" })).toHaveAttribute("data-active", "true");
    expect(screen.getByRole("separator", { name: "Resize left sidebar" })).toHaveAttribute("aria-valuenow", resizedWidth!);

    await user.click(screen.getByRole("button", { name: "Close document" }));
    expect(screen.getByLabelText("Sources list")).toBeInTheDocument();
    expect(screen.getByRole("separator", { name: "Resize left sidebar" })).toHaveAttribute("aria-valuenow", resizedWidth!);
  } finally {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: originalWidth });
  }
});
