# 第10周周报-KVPrefix复用与阶段收口

状态日期：2026-08-05

## 本周完成

M10.1 已完成：`DirectBackend` 在单 context、单 active request 架构中支持一个热文本 session 的 Token ID LCP KV Prefix 复用。调用方持续提交完整 `messages`；KV 仅为可丢弃的性能缓存。实现覆盖相同 Prefix 命中、分叉回滚、最后 Prompt Token 重算、生成 KV 清理、cancel/timeout/decode error/reset/context limit/图片请求失效或 bypass，以及 session、模型、模板和 Runtime 配置指纹失效。

固定 Qwen3-4B Q4 实机结果：冷请求 `0/18` 命中、Prefill/TTFT/Total 为 `179/194/421ms`，输出 `Ready.`；热请求 `17/18` 命中、`0/91/267ms`，输出仍为 `Ready.`；分叉请求 `8/18` 命中、`16/102/379ms`，输出 `Stable.`。`cold_hot_output_equal=true`。

## 阶段判断

M9.1B-R2.5 保持 `PARTIAL`：Recall@1/3/MRR 为 `0.875/0.875/0.875`，但无答案拒绝率 `0.50` 未达到 `0.75`；该 holdout 已消费，不重跑、不用于调参。M9.2 已完成本地手册检索、citation 与本地模型带来源回答的真实闭环。

至此，本仓库后端原型主线收口，进入项目交付归档/演示准备，而非继续扩展缓存、RAG 门禁、工具或 Agent。

## 验证

- build-runtime CTest：5/5；
- Python unittest：85/85；
- `edgeomni_qwen3_integration_test`：通过；
- `git diff --check`：通过。

## 明确边界

本成果是可集成的 Jetson Runtime/RAG 原型，不是生产可用系统、完整工业全双工音视频系统或多用户会话系统。M10.1 不提供多 session、LRU、TTL、持久化、跨进程共享、图片/VLM KV 或缓存池；不新增部署、音视频、RAG 算法、工具或 Agent 功能。
