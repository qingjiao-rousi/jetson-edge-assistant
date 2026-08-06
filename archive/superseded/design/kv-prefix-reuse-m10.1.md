# M10.1 Text KV Prefix Reuse

状态：`DONE`，已完成实现、契约测试和 Jetson 实机验证。
计划位置：M9.1B/M9.2 RAG 闭环之后，第 10 周 session 基础能力。
适用范围：`DirectBackend` 文本请求；第一版不复用图片/视频请求的视觉 KV。

## 1. 目标与现状

本任务在上游 `llama.cpp-omni` KV Memory API 基础上实现请求间缓存生命周期管理，
属于本项目的 Runtime 二次开发，不表述为从零实现 KV Cache。

`RuntimeService` 的 `/v1/generate` 与 `/v1/chat` 已接受非空 `session_id`。`DirectBackend`
维护一个热文本 session，按 Token ID LCP 回滚 sequence 0 的后缀，只重新 Prefill 未命中
Token，并至少重算最后一个 Prompt Token。图片请求不复用 KV，仍由 VLM 路径独立处理。

M10.1 的目标是：在不改变单 context、单 active request 基线的前提下，为一个热文本
会话复用已经计算过的 Token Prefix，减少后续回合的实际 Prefill Token 和 TTFT，并为
后续有界多 session 管理建立可验证的缓存契约。

## 2. 第一版范围

- `GenerateRequest` 接受可选非空 `session_id`，调用方仍提交完整 `messages`；
- `session_id=null` 保持无状态冷请求，不跨请求保留 KV；
- 相同 `session_id` 使用 Token ID 最长公共前缀（LCP）复用 KV；
- 不同 `session_id` 清理当前热缓存并建立新热会话，不声称真正多 session；
- 对话分叉时删除 LCP 之后的 sequence memory，再 Prefill 新后缀；
- cancel、timeout、decode error、reset、模型或模板指纹变化时缓存失效；
- 图片请求第一版 bypass 并使文本热缓存失效；不复用 image embedding、图片 Token
  或多模态位置状态；
- 第一版不实现并发 decode、自动历史裁剪、持久化缓存和跨会话共享 Prefix。

完整 `messages` 是会话内容的事实来源，KV 仅是可丢弃的性能缓存。不能只按字符串、
消息数量或 `session_id` 判断命中。

## 3. 缓存状态与指纹

实现维护以下状态：

```cpp
struct SessionCache {
    std::string session_id;
    std::vector<llama_token> tokens;
    llama_pos n_past = 0;
    CacheFingerprint fingerprint;
    bool valid = false;
};
```

`CacheFingerprint` 至少绑定模型 SHA-256、Tokenizer/Chat Template hash、context、RoPE
和 KV K/V 类型。后续若引入 LoRA、grammar 或其他会改变 Prefill 状态的配置，也必须
进入指纹或显式触发失效。Sampling 参数不直接改变已经计算的 Prompt KV，但缓存的
assistant 输出仍必须通过下一请求完整 Token 序列的 LCP 校验。

## 4. 请求算法

1. 使用冻结 Chat Template 渲染完整 `messages` 并 Tokenize；
2. 验证 session、缓存指纹和 context 上限；
3. 计算新 Prompt Token 与缓存 Token 的 LCP；
4. 最多复用到 `prompt_tokens.size() - 1`，确保至少重新计算最后一个 Prompt Token，
   从而为当前请求产生有效 logits；
5. 调用 `llama_memory_seq_rm(memory, 0, reuse_tokens, -1)` 删除分叉后的 KV；若部分删除
   不受支持或失败，则全量清理并冷 Prefill；
6. 仅 Decode `prompt_tokens[reuse_tokens:]`，位置从 `reuse_tokens` 开始；
7. 生成结束后先 synchronize，再删除 Prompt 末尾之后的 generated-token KV；只提交完整
   Prompt Token 列表；
8. 正常 `stop` 或 `length` 结束后提交缓存事务；其他终止原因清理并标记无效。

缓存更新应采用事务式 Guard：请求开始时标记为未提交，只有正常终止才保留。上游
decode abort/error 可能留下部分 ubatch，错误路径不得继续使用状态不确定的 KV。

## 5. 接口和指标

响应和 SSE metadata/terminal 事件应回传实际 `session_id`。原有 `prompt_tokens` 保持为
完整逻辑 Prompt 长度，并新增：

- `prefill_input_tokens`：本次实际送入 Prefill 的 Token 数；
- `cache_hit_tokens`、`cache_miss_tokens`、`cache_hit_ratio`；
- `cache_reused`；
- `cache_invalidation_reason`；

`reset_context()` 继续表示全局管理操作，同时清理 KV 和缓存 metadata。真正多 session
阶段再增加按 session reset/close 的显式接口，不在第一版复用全局 reset 语义。

## 6. 验收门

- 固定 seed/确定性 Sampling 下，冷热缓存输出一致；
- 第二回合 `cache_hit_tokens > 0`，且实际 Prefill Token 等于未命中后缀；
- 对话分叉能回滚到正确 Token 位置，输出与全量重算一致；
- `session_id=null`、切换 session、reset 和指纹变化后的首请求均为冷缓存；
- cancel、timeout、客户端断开和 decode error 后下一请求不使用污染缓存；
- context 超限返回稳定错误，不静默裁剪；
- 连续 20～100 回合无错误累积或异常内存增长；
- Jetson 同一 workload 保存冷/热 Prefill、TTFT、Total Latency、命中 Token 和资源证据；
- 图片请求明确报告 bypass/invalidation，不产生虚假命中。

验收完成：固定 Qwen3-4B Q4_K_M、固定 sampling 下，冷/热输出均为 `Ready.`，
`cold_hot_output_equal=true`；分叉输出为 `Stable.`。实机数据和限制见
[`docs/evaluation/kv-prefix-reuse-m10.1.md`](../evaluation/kv-prefix-reuse-m10.1.md)。

## 6.1 实现边界

这是单热文本 session 原型：不支持多 session、LRU、TTL、持久化、跨进程共享、图片/VLM
KV 复用、缓存池、并发 decode 或自动历史裁剪。它不构成多用户生产缓存或完整工业系统。

## 7. 后续阶段与难度

| 范围 | 难度 | 预估 |
| --- | --- | --- |
| M10.1 单热会话文本 LCP 复用 | 中等 | 编码 3～5 天；含 Jetson 回归约 5～8 个工作日 |
| 有界多 session、LRU/TTL、状态换入换出 | 高 | 约 2～3 周 |
| 多 sequence 共享 Prefix 和内存调度 | 很高 | 约 3～5 周并需长稳验证 |
| VLM 图片 KV 复用 | 中高到高 | 独立设计和实机验证，不并入 M10.1 |

当前单 active request 架构下，多 session 优先评估
`llama_state_seq_get_data`/`llama_state_seq_set_data` 对非热 session 的有界换入换出。
只有业务确实需要多个常驻热 sequence，且 Jetson KV 容量允许时，再评估
`llama_memory_seq_cp`、sequence ID 分配和共享 Prefix。所有策略都必须配置 LRU、TTL、
session 上限、内存预算、鉴权绑定和可观测淘汰原因。

## 8. 与业务主线的关系

该任务不改变“工业现场实时音视频全双工多模态交互，以及离线设备知识检索与故障
辅助”主线。它优化的是 Runtime 内文本对话和 RAG 故障报告生成的 Prefill/TTFT，
不替代 ASR、TTS、音视频传输、打断或全双工流控。

为提高 Prefix 命中，Prompt 应保持固定系统策略和设备身份在前，将当前回合的动态
检索证据、故障描述和实时转写放在稳定历史之后。图片/视频帧持续变化，第一版仍按
冷 VLM 请求处理。
