import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { WorkspaceShell } from "@/components/session/workspace-shell";
import * as api from "@/lib/api";

jest.mock("@/lib/api", () => ({ listSessions: jest.fn() }));

it("无浏览器缓存也能列出服务端工作区，重新聚焦刷新列表", async () => {
  localStorage.clear();
  const list = jest.mocked(api.listSessions);
  list.mockResolvedValueOnce({ sessions: [{ id: "remote", status: "ready", updated_at: "now", active_turn_id: null }] })
    .mockResolvedValue({ sessions: [{ id: "new-tab", status: "ready", updated_at: "later", active_turn_id: null }] });
  render(<WorkspaceShell><p>Workspace</p></WorkspaceShell>);
  fireEvent.click(screen.getByRole("button", { name: "Open sidebar" }));
  expect(await screen.findByRole("link", { name: /remote/ })).toHaveAttribute("href", "/tasks/remote");
  fireEvent(window, new Event("focus"));
  expect(await screen.findByRole("link", { name: /new-tab/ })).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByRole("link", { name: /remote/ })).not.toBeInTheDocument());
});
