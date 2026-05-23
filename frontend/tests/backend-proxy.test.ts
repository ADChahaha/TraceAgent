/**
 * @jest-environment node
 */


import { forwardBackendRequest } from "@/lib/backend-proxy";

type FetcherMock = jest.Mock<Promise<Response>, Parameters<typeof fetch>>;

it("会把 multipart 表单转发到 backend 目标路径", async () => {
  const formData = new FormData();
  formData.set("file", new File(["%PDF-1.4 fake"], "sample.pdf", { type: "application/pdf" }));

  const fetcher: FetcherMock = jest.fn(async () =>
    Response.json({ task_id: "qa_task_001", status: "ready", stage: "ready" })
  );
  const request = new Request("http://frontend.test/api/backend/qa/tasks", {
    method: "POST",
    body: formData,
    headers: {
      expect: "100-continue"
    }
  });

  const response = await forwardBackendRequest(request, ["qa", "tasks"], {
    backendBaseUrl: "http://backend.test",
    fetcher
  });

  expect(response.status).toBe(200);
  expect(fetcher).toHaveBeenCalledTimes(1);
  const [url, init] = fetcher.mock.calls[0];
  expect(url).toBe("http://backend.test/qa/tasks");
  expect(init?.method).toBe("POST");
  expect(init?.body).toBeInstanceOf(ArrayBuffer);
  expect((init?.body as ArrayBuffer).byteLength).toBeGreaterThan(0);
  expect((init?.headers as Headers).get("content-type")).toContain("multipart/form-data");
  expect((init?.headers as Headers).has("expect")).toBe(false);
});

it("会保留 backend 错误状态和 detail 响应", async () => {
  const fetcher: FetcherMock = jest.fn(async () =>
    Response.json({ detail: "content is required" }, { status: 422 })
  );
  const request = new Request("http://frontend.test/api/backend/qa/tasks/task-001/inputs", {
    method: "POST",
    body: JSON.stringify({}),
    headers: { "content-type": "application/json" }
  });

  const response = await forwardBackendRequest(request, ["qa", "tasks", "task-001", "inputs"], {
    backendBaseUrl: "http://backend.test",
    fetcher
  });

  expect(response.status).toBe(422);
  await expect(response.json()).resolves.toEqual({ detail: "content is required" });
});

it("backend 不可达时会返回明确的 502 detail", async () => {
  const fetcher: FetcherMock = jest.fn(async () => {
    throw new TypeError("fetch failed");
  });
  const request = new Request("http://frontend.test/api/backend/capabilities");

  const response = await forwardBackendRequest(request, ["capabilities"], {
    backendBaseUrl: "http://backend.test",
    fetcher
  });

  expect(response.status).toBe(502);
  await expect(response.json()).resolves.toEqual({
    detail: "backend unavailable"
  });
});

it("会把 text/event-stream 响应作为流转发，不先读成完整文本", async () => {
  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode('data: {"seq":1}\\n\\n'));
    }
  });
  const fetcher: FetcherMock = jest.fn(async () =>
    new Response(stream, {
      status: 200,
      headers: { "content-type": "text/event-stream" }
    })
  );
  const request = new Request("http://frontend.test/api/backend/qa/tasks/qa_task_001/events?after_seq=0");

  const response = await forwardBackendRequest(request, ["qa", "tasks", "qa_task_001", "events"], {
    backendBaseUrl: "http://backend.test",
    fetcher
  });

  expect(response.status).toBe(200);
  expect(response.headers.get("content-type")).toBe("text/event-stream");
  expect(response.body).toBe(stream);
});
