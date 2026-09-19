import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { HomeWorkspace } from "@/components/home-workspace";

const push = jest.fn();
jest.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
jest.mock("@/components/upload-workbench", () => ({ UploadWorkbench: ({ onCreated }: { onCreated: (id: string) => void }) => <button onClick={() => onCreated("s1")}>Created</button> }));

it("首问接受后进入会话详情路由", async () => {
  render(<HomeWorkspace />);
  fireEvent.click(screen.getByText("Created"));
  await waitFor(() => expect(push).toHaveBeenCalledWith("/tasks/s1"));
});
