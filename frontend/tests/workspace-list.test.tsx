import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { WorkspaceShell } from "@/components/session/workspace-shell";
import * as api from "@/lib/api";

jest.mock("@/lib/api", () => ({ listSessions: jest.fn() }));

it("无浏览器缓存也能列出服务端工作区，展示可读标题而非 UUID 并重新聚焦刷新", async () => {
  localStorage.clear();
  const list = jest.mocked(api.listSessions);
  list.mockResolvedValueOnce({
    sessions: [
      { id: "remote-uuid-1", title: "Lease Payment Summary", status: "ready", updated_at: "now", active_turn_id: null },
      { id: "empty-uuid-2", status: "ready", updated_at: "earlier", active_turn_id: null },
    ],
  }).mockResolvedValue({
    sessions: [
      { id: "new-tab-uuid", title: "Q3 Revenue Review", status: "ready", updated_at: "later", active_turn_id: null },
    ],
  });
  render(<WorkspaceShell><p>Workspace</p></WorkspaceShell>);
  fireEvent.click(screen.getByRole("button", { name: "Open sidebar" }));
  expect(await screen.findByRole("link", { name: /Lease Payment Summary/ })).toHaveAttribute("href", "/tasks/remote-uuid-1");
  expect(screen.getByRole("link", { name: /Untitled workspace/ })).toHaveAttribute("href", "/tasks/empty-uuid-2");
  expect(screen.queryByText("remote-uuid-1")).not.toBeInTheDocument();
  fireEvent(window, new Event("focus"));
  expect(await screen.findByRole("link", { name: /Q3 Revenue Review/ })).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByRole("link", { name: /Lease Payment Summary/ })).not.toBeInTheDocument());
});
