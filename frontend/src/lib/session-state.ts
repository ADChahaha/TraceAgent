import type { SessionEvent, SessionItem, SessionSnapshot, SessionTurn } from "@/lib/session-types";

export const isTerminal = (status: string) => ["completed", "cancelled", "failed"].includes(status);
const text = (value: unknown) => typeof value === "string" ? value : "";

export function applySessionEvent(snapshot: SessionSnapshot, event: SessionEvent): SessionSnapshot {
  const { type, payload, turn_id: id } = event;
  const existing = snapshot.state.turns.find((turn) => turn.id === id);
  if (existing && isTerminal(existing.status)) return snapshot;
  if (!existing && type !== "turn.started") return snapshot;
  const turn: SessionTurn = existing
    ? { ...existing, items: existing.items.map((item) => ({ ...item })) }
    : { id, status: "queued", items: [], error: null };
  const state = { ...snapshot.state };
  function item(key: string, kind: SessionItem["kind"]) {
    let result = turn.items.find((entry) => entry.id === key);
    if (!result) {
      result = { id: key, kind, status: "streaming", text: "" };
      turn.items.push(result);
    }
    return result;
  }
  if (type === "turn.started") {
    turn.status = "in_progress";
    state.active_turn_id = id;
  } else if (["turn.completed", "turn.failed", "turn.cancelled"].includes(type)) {
    turn.status = type.split(".")[1];
    turn.error = text(payload.error) || null;
    if (state.active_turn_id === id) state.active_turn_id = null;
    turn.items.forEach((entry) => {
      if (["streaming", "running", "retrying"].includes(entry.status)) entry.status = "interrupted";
    });
  } else if (type === "message.created") {
    const message = item(text(payload.message_id), payload.role === "user" ? "user" : "assistant");
    Object.assign(message, { text: text(payload.content), status: "completed" });
  } else if (type.startsWith("model_message.")) {
    const message = item(`message:${payload.message_id}`, "assistant");
    if (type === "model_message.delta") message.text = (message.text ?? "") + text(payload.delta);
    if (type === "model_message.done") {
      Object.assign(message, { text: text(payload.content), status: "completed", tool_calls: payload.tool_calls ?? [] });
    }
  } else if (["tool_started", "tool_completed", "tool_failed"].includes(type)) {
    Object.assign(item(`tool:${payload.tool_call_id}`, "tool"), {
      name: text(payload.tool), detail: payload,
      status: type === "tool_started" ? "running" : type === "tool_failed" ? "failed" : "completed",
    });
  } else if (type === "model_request.retrying") {
    const failed = turn.items.find((entry) => entry.id === `message:${payload.message_id}`);
    if (failed) failed.status = "failed";
    Object.assign(item(`retry:${payload.message_id}`, "retry"), { status: "retrying", detail: payload });
  }
  state.turns = existing ? snapshot.state.turns.map((entry) => entry.id === id ? turn : entry) : [...snapshot.state.turns, turn];
  return { ...snapshot, state };
}
