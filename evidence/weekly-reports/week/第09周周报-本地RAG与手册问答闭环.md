# 第09周周报：本地 RAG 与手册问答闭环

日期：2026-08-05。本周围绕工业设备手册故障辅助主线，完成本地多文档检索、引用保留和模型生成带来源回答的原型闭环。M9.1B-R2.5 的严格拒答质量门仍未通过，因此本周结论区分“应用功能闭环完成”和“检索质量正式验收为 PARTIAL”。

## 本周完成

- 使用三份本地设备手册构建 SQLite 索引，包含结构化文本、FTS5、Qwen3-Embedding-0.6B Q8_0 向量和稳定 chunk citation。
- 保留设备 ID、故障码硬约束及 R2.5 的 concept/fact-family admission；无证据查询返回空结果，不调用模型。
- 新增 M9.2 原型编排层，将检索片段以 `[S1]`、`[S2]` 等稳定标记注入现有 `/v1/chat`。
- 模型回答、检索 admission、引用和 HTTP/模型指标统一返回 JSON；模型失败时返回结构化 `MODEL_UNAVAILABLE`，不伪造答案。
- 在真实本地 RuntimeService 上完成端到端验证：`BX-9 的出口压力是多少？` 正确回答 `18 MPa`，引用命中 `BX9-MANUAL-001#technical-specifications`。

## 真实闭环证据

| 项目 | 结果 |
| --- | --- |
| 索引 | 3 documents / 12 chunks / 12 embeddings；SQLite 构建成功 |
| Retrieval | BX-9 设备约束通过；pressure fact family coverage `1.0` |
| HTTP | `/v1/chat` 返回 `200` |
| Answer | `BX-9 的出口压力是 18 MPa。` |
| Citation | `S1 -> BX9-MANUAL-001#technical-specifications` |
| Model | Qwen2.5-VL-3B-Instruct Q4_K_M；非流式回答 |
| Timing | total `1769 ms`；TTFT `675 ms`；decode `11.75 token/s` |

## M9.1B 严格验收边界

R2.5 calibration 与 diagnostic 通过，但一次性独立 holdout 结果为：Recall@1/3/MRR `0.875/0.875/0.875`、无答案拒绝率 `0.50`、误命中 `1`。拒答门要求 `>=0.75`，所以 M9.1B 继续标记为 `PARTIAL`；不得重跑或使用该 final set 调参。

这不阻止 M9.2 作为非生产应用原型完成验证，但不能据此声称 RAG 已达到生产质量。

## 测试与边界

- Python 全量测试：`85/85` 通过。
- M9.2 专项测试：`4/4` 通过，覆盖有证据生成、无证据短路、模型失败和错误响应。
- 当前服务仍是单 active request；非空 `session_id` 被拒绝，每次请求清理 KV，没有 KV Prefix 命中证据。
- 尚未接入 PDF/日志解析、音频采集、ASR/TTS/VAD/AEC、鉴权、部署和长稳。

## 第九周结论

第九周的核心应用功能已经完成：手册检索、来源引用和模型生成回答形成可运行闭环；严格检索质量验收未完全通过，周状态为 `PARTIAL`，但项目主线没有偏离。

## 下周最小范围

只实现 M10.1 单热文本会话的 KV Prefix 复用，完成冷热一致性、命中指标和异常失效验证；不扩展到多用户缓存池、图片 KV、工具 Agent 或生产部署。
