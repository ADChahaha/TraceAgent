# next-config.test.ts

- 代理容量覆盖后端 32 MiB 文件和 multipart 开销：Next.js proxyClientMaxBodySize 为 40mb，避免文件还未到 backend 就被较小的旧 10mb 上限截断。
