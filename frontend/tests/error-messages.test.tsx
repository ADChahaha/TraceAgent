import { render, screen } from "@testing-library/react";
import { Conversation } from "@/components/session/conversation";
import { ApiError } from "@/lib/api";
import { formatUserError } from "@/lib/error-messages";

describe("formatUserError", () => {
  it("将系统内部状态码和网络异常映射为可读英文提示", () => {
    expect(formatUserError("backend_restarted", "chat")).toBe(
      "This response was interrupted because the service restarted. You can ask again.",
    );
    expect(formatUserError("storage_failure", "chat")).toBe(
      "We couldn't save the conversation state. Please try again.",
    );
    expect(formatUserError(new Error("backend unavailable"), "session")).toBe(
      "Unable to reach the workspace service. Check that it is running and try again.",
    );
    expect(formatUserError(new TypeError("Failed to fetch"), "session")).toBe(
      "Unable to reach the workspace service. Check your connection and try again.",
    );
    expect(formatUserError(new Error("Stream interrupted"), "session")).toBe(
      "Connection to the live response was interrupted. Reconnecting...",
    );
  });

  it("拦截历史或上游漏出的底层技术报错串，不向界面暴露内部实现", () => {
    const cases: Array<[unknown, "upload" | "chat" | "document" | "session", string]> = [
      [
        "document service gRPC: UNAVAILABLE: ipv4:127.0.0.1:8002: Connection refused",
        "upload",
        "Document processing is temporarily unavailable. Please try again in a moment.",
      ],
      [
        "agent gRPC: INTERNAL: completion initialization failed: Using SOCKS proxy, but the 'socksio' package is not installed. Make sure to install httpx using `pip install httpx[socks]`.",
        "chat",
        "Unable to generate a response right now. Please try again.",
      ],
      [
        "agent gRPC: DEADLINE_EXCEEDED: upstream timeout",
        "chat",
        "The request timed out before an answer was ready. Please try again.",
      ],
      [
        "<html><body>502 Bad Gateway</body></html>",
        "document",
        "We couldn't load this document right now. Please try again.",
      ],
      [
        new ApiError("", 413, null),
        "upload",
        "This upload exceeds the size limit.",
      ],
    ];

    for (const [input, context, expected] of cases) {
      const output = formatUserError(input, context);
      expect(output).toBe(expected);
      expect(output).not.toMatch(/grpc|ipv4|127\.0\.0\.1|socksio|httpx|<html/i);
    }
  });

  it("保留已脱敏的清晰英文业务提示", () => {
    expect(formatUserError(new Error("Upload failed"), "upload")).toBe("Upload failed");
    expect(formatUserError("Only PDF and DOCX files are supported.", "upload")).toBe(
      "Only PDF and DOCX files are supported.",
    );
  });
});

it("Conversation 渲染历史或底层 turn.error 时展示友好英文文案", () => {
  render(
    <Conversation
      running={false}
      pending={null}
      onEvidence={jest.fn()}
      turns={[
        { id: "t1", status: "failed", error: "backend_restarted", items: [] },
        {
          id: "t2",
          status: "failed",
          error: "agent gRPC: INTERNAL: Using SOCKS proxy, but 'socksio' is missing",
          items: [],
        },
      ]}
    />,
  );

  const alerts = screen.getAllByRole("alert");
  expect(alerts[0]).toHaveTextContent(
    "This response was interrupted because the service restarted. You can ask again.",
  );
  expect(alerts[1]).toHaveTextContent("Unable to generate a response right now. Please try again.");
  expect(alerts[1].textContent).not.toMatch(/grpc|socksio/i);
});
