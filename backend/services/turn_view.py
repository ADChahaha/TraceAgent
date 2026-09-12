"""事件按原始消息/工具 ID 累积为一轮展示；历史读取复用同一转换。"""

import copy


class TurnView:
    def __init__(self, turn_id):
        self.id = turn_id
        self.status = "queued"
        self.items = {}
        self.error = None

    def apply(self, event):
        kind = event["type"]
        payload = event.get("payload", {})
        if kind == "turn.started":
            self.status = "in_progress"
        elif kind in {"turn.completed", "turn.failed", "turn.cancelled"}:
            self.status = kind.split(".")[1]
            self.error = payload.get("error")
            for item in self.items.values():
                if item["status"] in {"streaming", "running", "retrying"}:
                    item["status"] = "interrupted"
        elif kind == "message.created":
            key = payload["message_id"]
            self.items[key] = {"id": key, "kind": payload["role"], "text": payload["content"], "status": "completed"}
        elif kind.startswith("model_message."):
            key = "message:" + payload["message_id"]
            item = self.items.setdefault(key, {"id": key, "kind": "assistant", "text": "", "status": "streaming"})
            if kind == "model_message.delta":
                item["text"] += payload.get("delta", "")
            elif kind == "model_message.done":
                item.update(text=payload.get("content", ""), status="completed")
                item["tool_calls"] = copy.deepcopy(payload.get("tool_calls", []))
            elif "retry" in kind or "failed" in kind:
                item.update(status="failed", detail=copy.deepcopy(payload))
        elif kind in {"tool_started", "tool_completed", "tool_failed"}:
            key = "tool:" + payload["tool_call_id"]
            item = self.items.setdefault(key, {"id": key, "kind": "tool"})
            item.update(name=payload.get("tool", ""), status={"tool_started": "running", "tool_completed": "completed", "tool_failed": "failed"}[kind], detail=copy.deepcopy(payload))
        elif "retry" in kind:
            failed = self.items.get("message:" + str(payload.get("message_id", "")))
            if failed is not None:
                failed["status"] = "failed"
            key = "retry:" + str(payload.get("message_id", ""))
            self.items[key] = {"id": key, "kind": "retry", "status": "retrying", "detail": copy.deepcopy(payload)}

    def snapshot(self):
        return {"id": self.id, "status": self.status, "items": copy.deepcopy(list(self.items.values())), "error": self.error}
