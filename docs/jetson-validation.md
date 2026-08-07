# Jetson 验证摘要

以下是可对外复述的冻结摘要，不包含原始模型、私有 holdout 或大型原始 benchmark 日志。

| 项目 | 已验证范围 | 结论 |
| --- | --- | --- |
| 平台 | Jetson AGX Orin、ARM64、CUDA Release 构建 | 37/37 layer CUDA offload 已记录 |
| 量化 | Q4_K_M 与 Q8_0，各 15 次有效基线测量 | Q4 为部署优先候选；Q8 为对照 |
| KV | 文本单热 session、Token LCP、分叉/回滚与异常失效 | 仅单热 Prefix reuse，不是生产缓存 |
| VLM | 固定 Qwen2.5-VL 主模型/MMProj、单图 API | 单图链路已验证；不宣称通用多图/视频能力 |
| RAG | SQLite/FTS5 hybrid、引用和拒答门禁 | M9.1B R2.5 为 PARTIAL，最终质量门未通过 |

性能数字只在原始环境、固定模型、功耗模式、上下文、采样和测量口径相同的前提下可比较。本仓库不把未随 clone 提供的本机日志作为运行依赖，也不将上述摘要外推为高并发、长稳、生产 SLA 或多用户结论。

## M12 终端单图冒烟

在 Jetson ARM64 环境中，统一入口成功启动 Runtime 并通过 `/ready`。对
`tests/fixtures/vlm-service/synthetic-alarm-panel.png` 执行一次
`/image`：单图、单请求、`stream:false` 返回非空文本，终端明确标识结果
“未经过 RAG 检索或引用校验”，且未回显 Base64。`/image ../README.md`
在客户端仓库相对路径校验阶段被拒绝，未发送给 Runtime。`/quit` 后入口以
退出码 0 结束，端口释放且无残留进程。

这只是一项固定 fixture 的单图、单请求、非流式端到端冒烟证据；不构成 VLM
准确率、CUDA/GPU 指标、视频、多图、批处理、并发、RAG 融合、生产或长稳验证。
它不改变 M9.1B R2.5 为 PARTIAL 的冻结结论。
