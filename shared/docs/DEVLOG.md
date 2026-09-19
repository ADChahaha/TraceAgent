# Shared Devlog

## 2026-09-19

### 消除对象写入的固定握手等待

真实 storage HTTP 测量显示，读取对象约 2-7ms，写入仅 4 字节也耗时 1.007s。botocore 为 bytes 转成的文件流添加 Expect: 100-continue，连接等待服务器响应超时后才发送正文。Remove 顺序写回四个产物，因此纯裁剪仍耗时约四秒。

S3ObjectStore 取消本客户端添加 Expect 的默认事件处理器，直接发送已在内存中的 bytes。先添加真实 HTTP 测试确认旧实现仍带 Expect 而失败，再修改客户端；测试核对小正文和 256KiB 二进制对象的写入读回，以及请求不带 Expect。shared、storage、document service 和后端文件/文档客户端共 104 项测试通过。

通过临时数据库的真实 backend DELETE 路由调用运行中的 document gRPC 与 storage HTTP，以三个合成文档连续删除两次：修复前 4.078s、4.074s，服务重启后 0.104s、0.045s。测试资源已清理，未删除用户文件。后端和前端 HTTP 200，文档服务 SERVING。数据是小型测试资源的接口耗时，不包含浏览器渲染，也不代表所有大文件场景。
