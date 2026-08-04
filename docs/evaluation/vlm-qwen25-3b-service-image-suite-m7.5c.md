# M7.5C-R Qwen2.5-VL-3B Service Image Suite

本次在一个常驻 MtmdBackend/RuntimeService 进程中，以 8192 context 顺序执行三张固定图片的 HTTP/SSE 请求。服务启动一次、请求三次、无重试，child exit code 为 0。第一张图片的 publisher gate 通过；三次 SSE 都满足 `metadata -> token* -> done`，实际 image tokens 分别为 391、77、77。

这是一次固定三图、顺序独立请求的冒烟，不是多轮 session、RAG、Agent、并发或生产服务压测。8192 仍是开发默认候选；16384 仅保留既有实验事实；32768 未执行且禁用。模型 metadata 的 128000 context 声明不是 Jetson 部署长度结论。本次不形成平均性能、稳定性、并发能力或部署结论。

完整原始证据位于 `benchmark-results/vlm-service-image-suite/20260730-m7.5cr-001/`。
