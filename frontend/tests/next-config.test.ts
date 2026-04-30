import nextConfig from "../next.config";

it("允许前端代理转发 10MB 内的 PDF multipart 上传", () => {
  expect(nextConfig.experimental?.proxyClientMaxBodySize).toBe("10mb");
});
