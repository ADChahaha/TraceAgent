import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { UploadWorkbench } from "@/components/upload-workbench";
import * as api from "@/lib/api";
import { controlledStream, ready, running } from "./helpers/session-fixtures";

jest.mock("@/lib/api", () => ({ createSession: jest.fn(), uploadSessionFiles: jest.fn(), openCompletion: jest.fn(), removeSessionFile: jest.fn() }));
const create = jest.mocked(api.createSession);
const upload = jest.mocked(api.uploadSessionFiles);
const complete = jest.mocked(api.openCompletion);

beforeEach(() => {
  jest.resetAllMocks(); localStorage.clear();
  create.mockResolvedValue({ session_id: "s1" });
  upload.mockImplementation(async (_id, files) => ({ resources: [
    ...ready.state.resources, ...files.map((file) => ({ id: file.name, type: "raw" as const, location: `s3://bucket/raw/${file.name}` })),
  ] }));
  jest.mocked(api.removeSessionFile).mockResolvedValue({ resources: ready.state.resources });
  complete.mockResolvedValue(controlledStream(running).response);
});

async function fill() {
  const user = userEvent.setup();
  await user.upload(screen.getByLabelText("Document file input"), new File(["doc"], "contract.docx"));
  fireEvent.change(screen.getByLabelText("QA question input"), { target: { value: "Question" } });
  return user;
}

it("按创建会话、上传、首问快照顺序执行，再跳转", async () => {
  const onCreated = jest.fn();
  render(<UploadWorkbench onCreated={onCreated} />);
  const user = await fill();
  await user.click(screen.getByRole("button", { name: "Upload documents and ask" }));
  await waitFor(() => expect(onCreated).toHaveBeenCalledWith("s1"));
  expect(upload).toHaveBeenCalledWith("s1", [expect.any(File)]);
  expect(complete).toHaveBeenCalledWith("s1", "Question", expect.any(AbortSignal));
  expect(create.mock.invocationCallOrder[0]).toBeLessThan(upload.mock.invocationCallOrder[0]);
  expect(upload.mock.invocationCallOrder[0]).toBeLessThan(complete.mock.invocationCallOrder[0]);
  await user.click(screen.getByRole("button", { name: "Open sidebar" }));
  expect(screen.getByText("s1")).toBeInTheDocument();
});

it("上传失败不发首问，重试复用同一会话", async () => {
  upload.mockRejectedValueOnce(new Error("Upload failed"));
  render(<UploadWorkbench onCreated={jest.fn()} />);
  const user = await fill();
  expect(await screen.findByRole("alert")).toHaveTextContent("Upload failed");
  expect(complete).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Retry contract.docx" }));
  await waitFor(() => expect(upload).toHaveBeenCalledTimes(2));
  await user.click(screen.getByRole("button", { name: "Upload documents and ask" }));
  await waitFor(() => expect(complete).toHaveBeenCalledTimes(1));
  expect(create).toHaveBeenCalledTimes(1);
});

it("追加去重文件、移除文件，Enter 提交而 Shift Enter 换行", async () => {
  render(<UploadWorkbench />);
  const user = await fill();
  const second = new File(["pdf"], "second.pdf", { type: "application/pdf" });
  await user.upload(screen.getByLabelText("Document file input"), second);
  await user.upload(screen.getByLabelText("Document file input"), second);
  expect(screen.getByText("2 documents")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Remove second.pdf" }));
  const input = screen.getByLabelText("QA question input");
  await user.click(input);
  await user.keyboard("{Shift>}{Enter}{/Shift}More");
  expect(input).toHaveValue("Question\nMore");
  expect(create).toHaveBeenCalledTimes(1);
  expect(complete).not.toHaveBeenCalled();
  await user.keyboard("{Enter}");
  await waitFor(() => expect(complete).toHaveBeenCalled());
});

it("无文件不创建会话，选文件即创建但空问题不发送，保留主题和侧栏缩放", async () => {
  render(<UploadWorkbench />);
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Upload documents and ask" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Select at least one");
  await user.upload(screen.getByLabelText("Document file input"), new File(["doc"], "a.docx"));
  await user.click(screen.getByRole("button", { name: "Upload documents and ask" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Enter a question");
  expect(create).toHaveBeenCalledTimes(1);
  expect(complete).not.toHaveBeenCalled();
  const resize = screen.getByRole("separator", { name: "Resize left sidebar" });
  resize.focus(); await user.keyboard("{ArrowRight}");
  expect(resize).toHaveAttribute("aria-valuenow", "240");
  await user.click(screen.getByRole("button", { name: "Toggle theme" }));
  expect(document.documentElement).toHaveAttribute("data-theme", "dark");
});

it("窄窗口默认收起侧栏，仍可打开最近会话", async () => {
  const width = window.innerWidth;
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 600 });
  try {
    render(<UploadWorkbench />);
    expect(screen.queryByRole("complementary", { name: "Tasks sidebar" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Open sidebar" }));
    expect(screen.getByRole("complementary", { name: "Tasks sidebar" })).toBeInTheDocument();
  } finally { Object.defineProperty(window, "innerWidth", { configurable: true, value: width }); }
});

it("资料工作台提供来源列表和可编辑的问题建议，不显示参考品牌", async () => {
  render(<UploadWorkbench />);
  expect(screen.getByRole("heading", { name: "Your document workspace" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Sources" })).toBeInTheDocument();
  expect(screen.queryByText(/notebooklm/i)).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Summarize the main ideas" }));
  expect(screen.getByLabelText("QA question input")).toHaveValue("Summarize the main ideas");
  expect(create).not.toHaveBeenCalled();
  await userEvent.upload(screen.getByLabelText("Document file input"), new File(["doc"], "contract.docx"));
  expect(screen.getByLabelText("Sources list")).toHaveTextContent("contract.docx");
});


it("选择多个文件立即逐个处理，各自显示状态，完成前阻止发送且发送不重复上传", async () => {
  let finishFirst!: () => void;
  let finishSecond!: () => void;
  upload.mockImplementationOnce(() => new Promise((resolve) => { finishFirst = () => resolve({ resources: ready.state.resources }); }))
    .mockImplementationOnce(() => new Promise((resolve) => { finishSecond = () => resolve({ resources: ready.state.resources }); }));
  render(<UploadWorkbench />);
  const files = [new File(["a"], "a.docx"), new File(["b"], "b.docx")];
  await userEvent.upload(screen.getByLabelText("Document file input"), files);
  await waitFor(() => expect(upload).toHaveBeenCalledWith("s1", [files[0]]));
  expect(screen.getByRole("status", { name: "Processing a.docx" })).toBeInTheDocument();
  expect(screen.getByRole("status", { name: "Queued b.docx" })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("QA question input"), { target: { value: "Question" } });
  fireEvent.keyDown(screen.getByLabelText("QA question input"), { key: "Enter" });
  expect(complete).not.toHaveBeenCalled();
  await act(async () => finishFirst());
  expect(screen.getByRole("status", { name: "Ready a.docx" })).toBeInTheDocument();
  expect(screen.getByRole("status", { name: "Processing b.docx" })).toBeInTheDocument();
  expect(upload).toHaveBeenNthCalledWith(2, "s1", [files[1]]);
  await act(async () => finishSecond());
  await userEvent.click(screen.getByRole("button", { name: "Upload documents and ask" }));
  await waitFor(() => expect(complete).toHaveBeenCalledTimes(1));
  expect(upload).toHaveBeenCalledTimes(2);
  expect(create).toHaveBeenCalledTimes(1);
});

it("移除已处理文件调用后端删除，失败文件不阻塞其他文件处理", async () => {
  upload.mockRejectedValueOnce(new Error("Bad document"));
  render(<UploadWorkbench />);
  await userEvent.upload(screen.getByLabelText("Document file input"), [new File(["a"], "bad.docx"), new File(["b"], "good.docx")]);
  expect(await screen.findByRole("status", { name: "Ready good.docx" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Retry bad.docx" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Remove good.docx" }));
  await waitFor(() => expect(api.removeSessionFile).toHaveBeenCalledWith("s1", "good.docx"));
});
