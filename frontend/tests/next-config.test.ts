import nextConfig from "../next.config";

it("代理容量覆盖后端 32 MiB 文件和 multipart 开销", () => {
  expect(nextConfig.experimental?.proxyClientMaxBodySize).toBe("40mb");
});
