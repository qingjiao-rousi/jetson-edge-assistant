# 当前限制

- Runtime 目标是 Jetson AGX Orin ARM64/CUDA 的本地离线原型；Docker、systemd、生产鉴权、高并发和长稳验证尚未实现。
- RAG 的 M9.1B R2.5 holdout 已消费。该结果为 PARTIAL，不能重跑、修改或用于调参，不能表述为最终质量门通过。
- M10.1 只实现单热文本 session 的 KV Prefix reuse。没有多用户 KV Cache、LRU/TTL、跨进程共享或持久化。
- M10.2 只实现有界进程内 Agent/session、只读工具和 citation 门禁；没有身份认证或跨重启状态。
- VLM 是单图路径。它不意味着视频、多图批处理或生产多模态服务已完成。
- ASR/TTS 是半双工原型。外接麦克风实测、AEC、打断、流式输出和真实全双工尚未验证或实现。
- 启动器只使用本地资产并拒绝端口复用；不会下载、构建、建索引或修改知识库。
