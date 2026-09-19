import { ReadableStream } from "node:stream/web";
import { TextEncoder, TextDecoder } from "node:util";
import type { SessionSnapshot, SessionFrame } from "@/lib/session-types";

Object.assign(globalThis, { TextDecoder, TextEncoder });

export const ready: SessionSnapshot = {
  session_id: "s1", state: { status: "ready", active_turn_id: null,
    resources: [{ id: "raw1", type: "raw", location: "s3://res_s1/raw/contract.docx" },
      { id: "docs", type: "documents", location: "s3://res_s1/documents.zip" }], turns: [] },
};
export const running: SessionSnapshot = { ...ready, state: { ...ready.state, active_turn_id: "t1", turns: [
  { id: "t1", status: "in_progress", error: null, items: [{ id: "u1", kind: "user", text: "Question", status: "completed" }] },
] } };

export function controlledStream(snapshot?: SessionSnapshot) {
  let controller: ReadableStreamDefaultController<Uint8Array>;
  const cancelled = jest.fn();
  const stream = new ReadableStream<Uint8Array>({ start(value) {
    controller = value as unknown as ReadableStreamDefaultController<Uint8Array>;
  }, cancel: cancelled });
  const push = (frame: SessionFrame) => controller.enqueue(new TextEncoder().encode(`event: ${frame.event}\ndata: ${JSON.stringify(frame.data)}\n\n`));
  if (snapshot) push({ event: "session.snapshot", data: snapshot });
  return {
    response: { body: stream } as unknown as Response, push, cancelled,
    event: (type: string, payload: Record<string, unknown> = {}, turn_id = "t1") => push({ event: "session.event", data: { turn_id, type, payload } }),
    close: () => controller.close(),
  };
}
