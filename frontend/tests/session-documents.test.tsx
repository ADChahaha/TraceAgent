import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { SessionDocuments } from "@/components/session/documents";
import * as api from "@/lib/api";
import { ready } from "./helpers/session-fixtures";

jest.mock("@/lib/api", () => ({ listSessionDocuments: jest.fn(), readFullDocument: jest.fn(), readSessionDocument: jest.fn(), readSessionBlock: jest.fn(), sessionFileUrl: () => "/download" }));
const first = "documents/001-contract/001-intro.md";
const target = "documents/001-contract/002-Terms/001-budget.md";
const last = "documents/001-contract/003-end.md";
const other = "documents/002-other/001-body.md";
const props = { sessionId: "s1", resources: ready.state.resources, disabled: false, selection: null,
  onSelect: jest.fn(), onUpload: jest.fn(), onRemove: jest.fn(), onClose: jest.fn() };

beforeEach(() => {
  jest.resetAllMocks();
  Element.prototype.scrollIntoView = jest.fn();
  jest.mocked(api.listSessionDocuments).mockResolvedValue({ documents: [first, target, last, other].map((key) => ({ key, size: 20 })) });
  jest.mocked(api.readFullDocument).mockImplementation(async (_id, key) => ({ key, blocks: key.endsWith("002-other")
    ? [{ key: other, text: "Other document" }]
    : [{ key: first, text: "Introduction" }, { key: target, text: "**Budget:** 48,000" }, { key: last, text: "- First item\n- Last item" }] }));
});

it("显示整份文档，引用只高亮目标段落并滚动，不重新请求或替换上下文", async () => {
  const view = render(<SessionDocuments {...props} selection={{ key: "documents/001-contract", block: false, version: 1 }} />);
  await screen.findByText("Introduction");
  expect(screen.getByText("Budget:")).toHaveProperty("tagName", "STRONG");
  expect(screen.getByText("Last item").closest("li")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Terms" })).toBeInTheDocument();
  expect(screen.getAllByRole("option")).toHaveLength(2);
  view.rerender(<SessionDocuments {...props} selection={{ key: target, block: true, version: 1 }} />);
  await waitFor(() => expect(screen.getByText("Budget:").closest("[data-source-key]")).toHaveAttribute("data-evidence-selected", "true"));
  expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
  expect(screen.getByText("Introduction")).toBeInTheDocument();
  expect(screen.getByText("Last item")).toBeInTheDocument();
  expect(api.readFullDocument).toHaveBeenCalledTimes(1);
  expect(api.readSessionBlock).not.toHaveBeenCalled();
  view.rerender(<SessionDocuments {...props} resources={[...ready.state.resources]} selection={{ key: last, block: true, version: 2 }} />);
  expect(screen.getByText("Budget:").closest("[data-source-key]")).toHaveAttribute("data-evidence-selected", "false");
  expect(screen.getByText("Last item").closest("[data-source-key]")).toHaveAttribute("data-evidence-selected", "true");
  expect(api.readFullDocument).toHaveBeenCalledTimes(1);
});

it("按文档而不是片段切换，切换后加载另一整份文档", async () => {
  const view = render(<SessionDocuments {...props} selection={{ key: "documents/001-contract", block: false, version: 1 }} />);
  await screen.findByText("Introduction");
  fireEvent.change(screen.getByLabelText("Source document"), { target: { value: "documents/002-other" } });
  expect(props.onSelect).toHaveBeenCalledWith("documents/002-other");
  view.rerender(<SessionDocuments {...props} selection={{ key: other, block: true, version: 1 }} />);
  expect(await screen.findByText("Other document")).toBeInTheDocument();
  expect(screen.queryByText("Introduction")).not.toBeInTheDocument();
});

it("默认只显示 Sources，阅读器替换整个列表，关闭后返回列表", async () => {
  const onClose = jest.fn();
  const view = render(<SessionDocuments {...props} onClose={onClose} />);
  await waitFor(() => expect(api.listSessionDocuments).toHaveBeenCalledWith("s1"));
  expect(screen.queryByRole("combobox", { name: "Source document" })).not.toBeInTheDocument();
  expect(screen.queryByText("Open a document...")).not.toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Sources" })).toBeInTheDocument();
  expect(screen.queryByLabelText("Source content")).not.toBeInTheDocument();
  expect(api.readFullDocument).not.toHaveBeenCalled();
  view.rerender(<SessionDocuments {...props} onClose={onClose} selection={{ key: target, block: true, version: 1 }} />);
  await screen.findByText("Introduction");
  expect(screen.getByText("Last item")).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Sources" })).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Sources list")).not.toBeInTheDocument();
  expect(screen.getByText("Budget:").closest("[data-source-key]")).toHaveAttribute("data-evidence-selected", "true");
  fireEvent.click(screen.getByRole("button", { name: "Close document" }));
  expect(onClose).toHaveBeenCalledTimes(1);
  view.rerender(<SessionDocuments {...props} onClose={onClose} />);
  expect(screen.getByLabelText("Sources list")).toBeInTheDocument();
  expect(screen.queryByLabelText("Full document")).not.toBeInTheDocument();
});
