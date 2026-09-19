import { act, renderHook, waitFor } from "@testing-library/react";
import { useSession } from "@/lib/use-session";
import * as api from "@/lib/api";
import { controlledStream, ready, running } from "./helpers/session-fixtures";

jest.mock("@/lib/api", () => ({ openResume: jest.fn(), openCompletion: jest.fn(), cancelCompletion: jest.fn(), ApiError: class extends Error {} }));
const resume = jest.mocked(api.openResume);
const complete = jest.mocked(api.openCompletion);
const cancel = jest.mocked(api.cancelCompletion);

beforeEach(() => { jest.resetAllMocks(); localStorage.clear(); });
afterEach(() => jest.useRealTimers());

it("快照恢复后合并增量，完成即停止订阅，卸载不取消服务端轮次", async () => {
  const stream = controlledStream(running);
  resume.mockResolvedValue(stream.response);
  const view = renderHook(() => useSession("s1"));
  await waitFor(() => expect(view.result.current.snapshot?.state.active_turn_id).toBe("t1"));
  await act(async () => {
    stream.event("model_message.delta", { message_id: "m1", delta: "answer" });
    stream.event("model_message.done", { message_id: "m1", content: "answer" });
    stream.event("turn.completed");
  });
  expect(view.result.current.snapshot?.state.turns[0].items[1].text).toBe("answer");
  expect(view.result.current.running).toBe(false);
  expect(stream.cancelled).toHaveBeenCalled();
  view.unmount();
  expect(cancel).not.toHaveBeenCalled();
  expect(resume.mock.calls[0][1]?.aborted).toBe(true);
});

it("提交后的流意外结束只 GET 恢复，不重复 POST 或叠加快照", async () => {
  const initial = controlledStream(ready);
  const submitted = controlledStream(running);
  const recovered = controlledStream({ ...running, state: { ...running.state, turns: [{ ...running.state.turns[0], items: [...running.state.turns[0].items, { id: "message:m", kind: "assistant", status: "streaming", text: "restored" }] }] } });
  resume.mockResolvedValueOnce(initial.response).mockResolvedValue(recovered.response);
  complete.mockResolvedValue(submitted.response);
  const view = renderHook(() => useSession("s1"));
  await waitFor(() => expect(view.result.current.connection).toBe("idle"));
  jest.useFakeTimers();
  await act(async () => { view.result.current.send("Question"); });
  await act(async () => { submitted.close(); });
  await act(async () => { await jest.advanceTimersByTimeAsync(1500); });
  expect(complete).toHaveBeenCalledTimes(1);
  expect(resume).toHaveBeenCalledTimes(2);
  expect(view.result.current.snapshot?.state.turns[0].items).toHaveLength(2);
  expect(view.result.current.snapshot?.state.turns[0].items[1].text).toBe("restored");
  view.unmount();
});

it("取消提交准确的 session 和 turn，响应后解除运行状态", async () => {
  const stream = controlledStream(running);
  resume.mockResolvedValue(stream.response);
  cancel.mockResolvedValue({ status: "cancelled" });
  const view = renderHook(() => useSession("s1"));
  await waitFor(() => expect(view.result.current.running).toBe(true));
  await act(async () => { await view.result.current.cancel(); });
  expect(cancel).toHaveBeenCalledWith("s1", "t1");
  expect(view.result.current.running).toBe(false);
  expect(view.result.current.snapshot?.state.turns[0].status).toBe("cancelled");
  view.unmount();
});

it("旧会话的迟到响应不能覆盖新会话", async () => {
  let resolveOld!: (value: Response) => void;
  const old = controlledStream(running);
  resume.mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }))
    .mockResolvedValueOnce(controlledStream({ ...ready, session_id: "s2" }).response);
  const view = renderHook(({ id }) => useSession(id), { initialProps: { id: "s1" } });
  view.rerender({ id: "s2" });
  await waitFor(() => expect(view.result.current.snapshot?.session_id).toBe("s2"));
  await act(async () => { resolveOld(old.response); });
  expect(view.result.current.snapshot?.session_id).toBe("s2");
  expect(complete).not.toHaveBeenCalled();
  view.unmount();
});
