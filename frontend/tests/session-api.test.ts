/** @jest-environment node */
import * as api from "@/lib/api";
import { consumeSessionStream } from "@/lib/session-stream";

afterEach(() => jest.restoreAllMocks());

it("创建会话、上传和删除文件使用独立接口", async () => {
  const fetcher = jest.spyOn(globalThis, "fetch").mockImplementation(async () => Response.json({ session_id: "s1", resources: [] }));
  await expect(api.createSession()).resolves.toEqual({ session_id: "s1", resources: [] });
  await api.uploadSessionFiles("s/1", [new File(["data"], "a.docx")]);
  await api.removeSessionFile("s/1", "r/1");
  expect(fetcher.mock.calls[0][0]).toBe("/api/backend/chat/sessions");
  expect(fetcher.mock.calls[1][0]).toBe("/api/backend/chat/sessions/s%2F1/files");
  expect((fetcher.mock.calls[1][1]?.body as FormData).getAll("files")).toHaveLength(1);
  expect(fetcher.mock.calls[2][0]).toBe("/api/backend/chat/sessions/s%2F1/files/r%2F1");
  expect(fetcher.mock.calls[2][1]?.method).toBe("DELETE");
});

it("提问用 POST 流，恢复用 GET，取消包含轮次 ID", async () => {
  const fetcher = jest.spyOn(globalThis, "fetch").mockImplementation(async () => new Response("", { headers: { "content-type": "text/event-stream" } }));
  const controller = new AbortController();
  await api.openCompletion("s1", "Question", controller.signal);
  await api.openResume("s1", controller.signal);
  fetcher.mockResolvedValueOnce(Response.json({ status: "cancelled" }));
  await api.cancelCompletion("s1", "t1");
  expect(fetcher.mock.calls[0][0]).toBe("/api/backend/chat/completion");
  expect(JSON.parse(fetcher.mock.calls[0][1]?.body as string)).toEqual({ session_id: "s1", content: "Question" });
  expect(fetcher.mock.calls[0][1]?.signal).toBe(controller.signal);
  expect(fetcher.mock.calls[1][0]).toBe("/api/backend/resume?session_id=s1");
  expect(JSON.parse(fetcher.mock.calls[2][1]?.body as string)).toEqual({ session_id: "s1", turn_id: "t1" });
});

it("文档与证据路径编码为查询参数，原文件保留下载 URL", async () => {
  const fetcher = jest.spyOn(globalThis, "fetch").mockImplementation(async () => Response.json({ documents: [], text: "text" }));
  await api.listSessionDocuments("s1");
  await api.readSessionDocument("s1", "documents/a #1.md");
  await api.readSessionBlock("s1", "documents/a #1.md");
  expect(fetcher.mock.calls.map(([url]) => String(url))).toEqual([
    "/api/backend/chat/sessions/s1/documents",
    "/api/backend/chat/sessions/s1/documents/content?key=documents%2Fa+%231.md",
    "/api/backend/chat/sessions/s1/blocks?key=documents%2Fa+%231.md",
  ]);
  expect(api.sessionFileUrl("s1", "r1")).toBe("/api/backend/chat/sessions/s1/files/r1");
});

it("流请求拒绝 HTTP 错误和非 SSE 响应", async () => {
  jest.spyOn(globalThis, "fetch").mockResolvedValueOnce(Response.json({ detail: "busy" }, { status: 409 }))
    .mockResolvedValueOnce(new Response("<html>proxy error</html>"));
  await expect(api.openCompletion("s", "q")).rejects.toThrow("busy");
  await expect(api.openResume("s")).rejects.toThrow("Expected an event stream");
});

it("解析跨字节分块的中文、CRLF、多行数据和心跳", async () => {
  const text = ': heartbeat\r\nevent: session.snapshot\r\ndata: {"session_id":"s",\r\ndata: "state":{"turns":[]}}\r\n\r\nevent: session.event\ndata: {"turn_id":"t","type":"model_message.delta","payload":{"delta":"你好"}}\n\n';
  const bytes = new TextEncoder().encode(text);
  const response = new Response(new ReadableStream({ start(controller) {
    for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
    controller.close();
  } }));
  const frames: unknown[] = [];
  await consumeSessionStream(response, (frame) => { frames.push(frame); });
  expect(frames).toHaveLength(2);
  expect(frames[1]).toEqual({ event: "session.event", data: { turn_id: "t", type: "model_message.delta", payload: { delta: "你好" } } });
});

it("首帧处理后可释放订阅，不等待整个回答", async () => {
  const cancel = jest.fn();
  const stream = new ReadableStream({ start(controller) {
    controller.enqueue(new TextEncoder().encode('event: session.snapshot\ndata: {"session_id":"s","state":{}}\n\n'));
  }, cancel });
  await consumeSessionStream(new Response(stream), () => true);
  expect(cancel).toHaveBeenCalled();
});

it("无效 JSON 流报错而不是默默丢失状态", async () => {
  await expect(consumeSessionStream(new Response('event: session.snapshot\ndata: invalid\n\n'), () => {})).rejects.toThrow();
});

it("取消订阅立即释放正在等待数据的 reader", async () => {
  const cancel = jest.fn();
  const controller = new AbortController();
  const consuming = consumeSessionStream(new Response(new ReadableStream({ cancel })), () => {}, controller.signal);
  controller.abort();
  await consuming;
  expect(cancel).toHaveBeenCalled();
});
