import { applySessionEvent } from "@/lib/session-state";
import type { SessionSnapshot, SessionEvent } from "@/lib/session-types";

const initial: SessionSnapshot = { session_id: "s", state: { status: "ready", active_turn_id: "t", resources: [], turns: [{ id: "t", status: "in_progress", items: [], error: null }] } };
function apply(state: SessionSnapshot, type: string, payload: Record<string, unknown>, turn_id = "t") {
  return applySessionEvent(state, { type, payload, turn_id } as SessionEvent);
}

it("增量按消息 ID 追加，done 完整正文替换，不重复拼接", () => {
  let state = apply(initial, "model_message.started", { message_id: "m" });
  state = apply(state, "model_message.delta", { message_id: "m", delta: "Hello" });
  state = apply(state, "model_message.delta", { message_id: "m", delta: " world" });
  state = apply(state, "model_message.done", { message_id: "m", content: "Hello world", is_final: true });
  expect(state.state.turns[0].items).toEqual([expect.objectContaining({ id: "message:m", text: "Hello world", status: "completed" })]);
  expect(initial.state.turns[0].items).toEqual([]);
});

it("相同文本的不同用户消息和不同重试均保留", () => {
  let state = apply(initial, "message.created", { message_id: "u1", role: "user", content: "same" });
  state = apply(state, "message.created", { message_id: "u2", role: "user", content: "same" });
  state = apply(state, "model_message.delta", { message_id: "m1", delta: "partial" });
  state = apply(state, "model_request.retrying", { message_id: "m1", attempt: 2 });
  state = apply(state, "model_message.delta", { message_id: "m2", delta: "new" });
  expect(state.state.turns[0].items.filter((item) => item.kind === "user")).toHaveLength(2);
  expect(state.state.turns[0].items.find((item) => item.id === "message:m1")?.status).toBe("failed");
  expect(state.state.turns[0].items.find((item) => item.id === "message:m2")?.text).toBe("new");
});

it("工具按调用 ID 更新，取消后忽略迟到事件", () => {
  let state = apply(initial, "tool_started", { tool_call_id: "c", tool: "read" });
  state = apply(state, "tool_completed", { tool_call_id: "c", tool: "read", result: { text: "ok" } });
  expect(state.state.turns[0].items).toHaveLength(1);
  state = apply(state, "model_message.delta", { message_id: "m", delta: "partial" });
  state = apply(state, "turn.cancelled", {});
  expect(state.state.active_turn_id).toBeNull();
  expect(state.state.turns[0].items[1].status).toBe("interrupted");
  expect(apply(state, "model_message.delta", { message_id: "m", delta: "late" })).toEqual(state);
});

it("旧轮终态不能清空新轮，新轮开始可追加", () => {
  let state = apply(initial, "turn.completed", {});
  state = apply(state, "turn.started", {}, "t2");
  state = apply(state, "turn.failed", { error: "late" }, "t");
  expect(state.state.active_turn_id).toBe("t2");
  expect(state.state.turns).toHaveLength(2);
});
