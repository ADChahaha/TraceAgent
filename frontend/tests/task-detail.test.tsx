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
});

it("追问走 POST 流，输入框节点稳定，取消携带当前轮次", async () => {
  resume.mockResolvedValue(controlledStream(ready).response);
  const stream = controlledStream(running);
  complete.mockResolvedValue(stream.response);
  jest.mocked(api.cancelCompletion).mockResolvedValue({ status: "cancelled" });
  render(<TaskDetail taskId="s1" />);
  await screen.findByText("Full source document");
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

it("显示原文件下载，删除与补传刷新资源", async () => {
  resume.mockImplementation(async () => controlledStream(ready).response);
  jest.mocked(api.removeSessionFile).mockResolvedValue({ resources: [] });
  jest.mocked(api.uploadSessionFiles).mockResolvedValue({ resources: ready.state.resources });
  render(<TaskDetail taskId="s1" />);
  expect(await screen.findByRole("link", { name: "Download contract.docx" })).toHaveAttribute("href", "/download");
  await userEvent.click(screen.getByRole("button", { name: "Remove contract.docx" }));
  await waitFor(() => expect(api.removeSessionFile).toHaveBeenCalledWith("s1", "raw1"));
  await waitFor(() => expect(screen.getByLabelText("Add session files")).not.toBeDisabled());
  await userEvent.upload(screen.getByLabelText("Add session files"), new File(["doc"], "new.docx"));
  await waitFor(() => expect(api.uploadSessionFiles).toHaveBeenCalledWith("s1", [expect.any(File)]));
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

it("来源搜索过滤文件但保留当前原文，清空搜索恢复列表", async () => {
  resume.mockResolvedValue(controlledStream(ready).response);
  render(<TaskDetail taskId="s1" />);
  await screen.findByText("Full source document");
  fireEvent.change(screen.getByRole("searchbox", { name: "Search sources" }), { target: { value: "missing" } });
  expect(screen.queryByRole("link", { name: "Download contract.docx" })).not.toBeInTheDocument();
  expect(screen.getByText("No matching sources")).toBeInTheDocument();
  expect(screen.getByText("Full source document")).toBeInTheDocument();
  fireEvent.change(screen.getByRole("searchbox", { name: "Search sources" }), { target: { value: "" } });
  expect(screen.getByRole("link", { name: "Download contract.docx" })).toBeInTheDocument();
});


it("补传立即逐文件处理，列表显示对应转圈并禁止处理期间提问", async () => {
  resume.mockImplementation(async () => controlledStream(ready).response);
  let finish!: () => void;
  jest.mocked(api.uploadSessionFiles).mockImplementationOnce(() => new Promise((resolve) => { finish = () => resolve({ resources: ready.state.resources }); }))
    .mockResolvedValue({ resources: ready.state.resources });
  render(<TaskDetail taskId="s1" />);
  await screen.findByText("Full source document");
  const files = [new File(["a"], "a.docx"), new File(["b"], "b.docx")];
  await userEvent.upload(screen.getByLabelText("Add session files"), files);
  expect(api.uploadSessionFiles).toHaveBeenCalledWith("s1", [files[0]]);
  expect(screen.getByRole("status", { name: "Processing a.docx" })).toBeInTheDocument();
  expect(screen.getByRole("status", { name: "Queued b.docx" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Submit or pause answer" })).toBeDisabled();
  await act(async () => finish());
  await waitFor(() => expect(api.uploadSessionFiles).toHaveBeenNthCalledWith(2, "s1", [files[1]]));
});

it("删除刚补传成功的文件后不留下本地就绪占位", async () => {
  let resources = ready.state.resources;
  resume.mockImplementation(async () => controlledStream({ ...ready, state: { ...ready.state, resources } }).response);
  jest.mocked(api.uploadSessionFiles).mockImplementation(async () => {
    resources = [...resources, { id: "new-raw", type: "raw", location: "s3://bucket/raw/new.docx" }];
    return { resources };
  });
  jest.mocked(api.removeSessionFile).mockImplementation(async () => {
    resources = ready.state.resources;
    return { resources };
  });
  render(<TaskDetail taskId="s1" />);
  await screen.findByText("Full source document");
  await userEvent.upload(screen.getByLabelText("Add session files"), new File(["doc"], "new.docx"));
  await screen.findByRole("link", { name: "Download new.docx" });
  await userEvent.click(screen.getByRole("button", { name: "Remove new.docx" }));
  await waitFor(() => expect(api.removeSessionFile).toHaveBeenCalledWith("s1", "new-raw"));
  await waitFor(() => expect(screen.queryByText("new.docx")).not.toBeInTheDocument());
});

it("其他标签页修改文件后，当前空闲工作区重新聚焦即恢复新快照", async () => {
  resume.mockResolvedValueOnce(controlledStream(ready).response)
    .mockResolvedValue(controlledStream({ ...ready, state: { ...ready.state, resources: [] } }).response);
  render(<TaskDetail taskId="s1" />);
  await screen.findByRole("link", { name: "Download contract.docx" });
  fireEvent(window, new Event("focus"));
  await waitFor(() => expect(screen.queryByRole("link", { name: "Download contract.docx" })).not.toBeInTheDocument());
});

it("空闲标签页定期同步其他标签页的更新，不重新提交问题", async () => {
  resume.mockResolvedValueOnce(controlledStream(ready).response)
    .mockResolvedValue(controlledStream({ ...ready, state: { ...ready.state, resources: [] } }).response);
  const view = render(<TaskDetail taskId="s1" />);
  await screen.findByRole("link", { name: "Download contract.docx" });
  jest.useFakeTimers();
  try {
    // 切换焦点使空闲订阅在可控计时器下重新建立。
    fireEvent(window, new Event("focus"));
    await act(async () => {});
    resume.mockResolvedValue(controlledStream(ready).response);
    await act(async () => { await jest.advanceTimersByTimeAsync(5000); });
    expect(screen.getByRole("link", { name: "Download contract.docx" })).toBeInTheDocument();
    expect(complete).not.toHaveBeenCalled();
  } finally { view.unmount(); jest.useRealTimers(); }
});

it("另一标签页删除已补传文件后，恢复时不重建本地上传占位", async () => {
  let resources = ready.state.resources;
  resume.mockImplementation(async () => controlledStream({ ...ready, state: { ...ready.state, resources } }).response);
  jest.mocked(api.uploadSessionFiles).mockImplementation(async () => {
    resources = [...resources, { id: "cross-tab", type: "raw", location: "s3://bucket/raw/cross.docx" }];
    return { resources };
  });
  render(<TaskDetail taskId="s1" />);
  await screen.findByText("Full source document");
  await userEvent.upload(screen.getByLabelText("Add session files"), new File(["doc"], "cross.docx"));
  await screen.findByRole("link", { name: "Download cross.docx" });
  resources = ready.state.resources;
  fireEvent(window, new Event("focus"));
  await waitFor(() => expect(screen.queryByText("cross.docx")).not.toBeInTheDocument());
});
