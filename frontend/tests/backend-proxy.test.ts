/**
 * @jest-environment node
 */


import { forwardBackendRequest } from "@/lib/backend-proxy";

it("会把 multipart 表单转发到 backend 目标路径", async () => {
  const formData = new FormData();
  formData.set("task_type", "civilized_dormitory");
  formData.set("task_spec", JSON.stringify({ task_name: "civilized_dormitory" }));
  formData.set("file", new File(["%PDF-1.4 fake"], "sample.pdf", { type: "application/pdf" }));

  const fetcher = jest.fn(async () =>
    Response.json({ task_id: "task-001", status: "completed", stage: "done" })
  );
  const request = new Request("http://frontend.test/api/backend/tasks", {
    method: "POST",
    body: formData
  });

  const response = await forwardBackendRequest(request, ["tasks"], {
    backendBaseUrl: "http://backend.test",
    fetcher
  });

  expect(response.status).toBe(200);
  expect(fetcher).toHaveBeenCalledTimes(1);
  const [url, init] = fetcher.mock.calls[0];
  expect(url).toBe("http://backend.test/tasks");
  expect(init?.method).toBe("POST");
  expect(init?.body).toBeInstanceOf(FormData);
  expect((init?.body as FormData).get("task_type")).toBe("civilized_dormitory");
  expect((init?.headers as Headers).has("content-type")).toBe(false);
});

it("会保留 backend 错误状态和 detail 响应", async () => {
  const fetcher = jest.fn(async () =>
    Response.json({ detail: "task_spec is required" }, { status: 422 })
  );
  const request = new Request("http://frontend.test/api/backend/tasks", {
    method: "POST",
    body: JSON.stringify({}),
    headers: { "content-type": "application/json" }
  });

  const response = await forwardBackendRequest(request, ["tasks"], {
    backendBaseUrl: "http://backend.test",
    fetcher
  });

  expect(response.status).toBe(422);
  await expect(response.json()).resolves.toEqual({ detail: "task_spec is required" });
});

it("backend 不可达时会返回明确的 502 detail", async () => {
  const fetcher = jest.fn(async () => {
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
