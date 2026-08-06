# EdgeOmni Jetson 端侧原型交付说明

日期：2026-08-05

## 1. 交付结论

本项目是在开源 `llama.cpp-omni` Runtime 基础上的 Jetson ARM64/CUDA 二次开发，已交付一个可构建、可测试、可本地演示的端侧 LLM/VLM/RAG 后端原型。

已形成的核心闭环是：

```text
本地设备手册 -> 混合检索 -> 稳定引用 -> 本地模型生成带来源回答
```

同时完成了单热文本会话的 KV Prefix 复用验证。项目仍不是生产系统，也不是完整的工业现场实时音视频全双工系统。

## 2. 各阶段开发内容

### 第 1～2 周：环境与 Jetson 基线

- 固定 Jetson AGX Orin、L4T、CUDA、GCC、CMake 环境。
- 完成 `llama.cpp-omni` ARM64/CUDA 构建和 Runtime fork 追溯。
- 固定模型、构建、环境和 SHA-256 manifest。
- 验证 CUDA offload、模型加载和 tegrastats 资源采样。

### 第 3～4 周：文本 Runtime 与服务

- 实现 `DirectBackend` 文本模型生命周期和生成接口。
- 实现 `RuntimeService` HTTP JSON/SSE 服务。
- 支持请求校验、超时、取消、错误码、模型信息和运行指标。
- 使用 FakeBackend 和 C++ loopback 测试验证请求生命周期。

### 第 5～6 周：量化、KV 基线与性能

- 完成 Qwen3 Q4/Q8 固定资产和重复性能评测。
- 固定 Q4 为部署优先候选，Q8 作为精度对照。
- 记录 Prefill、Decode、TTFT、Total Latency、GPU offload 和 KV 内存。
- KV 基线固定为 F16/F16，完成 context、容量和 OOM 边界验证。

### 第 7～8 周：VLM 与应用 API

- 接入 Qwen2.5-VL 主模型和 mmproj。
- 完成图片输入校验、单图视觉编码和 `MtmdBackend`。
- 实现 `/v1/diagnose/image` 应用接口和 JSON/SSE 输出。
- 完成固定图片、8192 context、单常驻服务和应用 API 冒烟验证。

### 第 9 周：本地 RAG 与带来源回答

- 完成多文档 Markdown 手册解析、chunk 和 citation。
- 接入本地 Qwen3-Embedding-0.6B Q8_0 GGUF。
- 构建 SQLite float32 L2 向量、FTS5 和 hybrid 检索索引。
- 实现设备 ID、故障码和 concept/fact-family admission。
- 完成 calibration、diagnostic、一次性 holdout 流程和无命中门禁。
- 实现 M9.2：检索片段注入本地 `/v1/chat`，输出带 `[S1]` 引用的模型回答。
- 真实演示：BX-9 出口压力回答为 `18 MPa`，引用技术规格章节。

### 第 10 周：单热文本 KV Prefix 复用

- 支持 `/v1/chat` 和 `/v1/generate` 的非空 `session_id`。
- 按 Token ID LCP 复用单个热文本会话的 KV。
- 支持 Prefix 分叉回滚，并重新计算最后一个 Prompt Token。
- 生成 token 不进入持久缓存；取消、超时、错误、reset、图片和配置变化会清理或绕过缓存。
- 新增 `cache_hit_tokens`、`cache_miss_tokens`、`cache_hit_ratio`、`prefill_input_tokens`、`cache_reused` 等指标。
- 增加多请求 benchmark runner 和实模型集成测试。

## 3. 第十周是否完成

**M10.1 最小任务已完成。** 实机 Qwen3-4B-Q4 验证结果：

| 请求 | 命中 | Prefill | TTFT | Total | 输出 |
| --- | ---: | ---: | ---: | ---: | --- |
| 冷请求 | 0/18 | 179 ms | 194 ms | 421 ms | `Ready.` |
| 热请求 | 17/18 | 0 ms | 91 ms | 267 ms | `Ready.` |
| Prefix 分叉 | 8/18 | 16 ms | 102 ms | 379 ms | `Stable.` |

`cold_hot_output_equal=true`。CTest `5/5`、Python unittest `85/85`、实模型 `edgeomni_qwen3_integration_test` 均通过。

注意：原计划第十周还包括受限工具、Agent 和多 session，这些没有开发，不应写成已完成。已完成的是 M10.1 单热文本 KV Prefix 原型。

## 4. 当前验收状态

| 模块 | 状态 | 说明 |
| --- | --- | --- |
| Jetson/CUDA 基线 | 完成 | 构建、offload、环境和资产可追溯 |
| 文本 Runtime/HTTP 服务 | 完成 | 单 context、单 active request |
| Q4/Q8 与 KV 基线 | 完成 | Q4 部署优先，KV F16/F16 |
| VLM 图片链路 | 阶段完成 | 固定资产和有限单图验证 |
| M9.1B-R2.5 检索 | `PARTIAL` | holdout 拒答率 `0.50`，质量门未通过 |
| M9.2 手册问答 | 完成原型 | 检索、引用、模型回答闭环 |
| M10.1 KV Prefix | 完成原型 | 单热文本 session，不是多用户缓存 |
| 工具/Agent/多 session | 未交付 | 无代码和验收证据 |
| Docker/systemd/长稳 | 未交付 | 只有设计，没有实测交付 |

## 5. 关键提交

- `aa8b542`：完成 M10.1 单热文本 KV Prefix 复用并收口。
- `ad8750f`：完成 M9.2 手册检索、引用和模型带来源回答原型。
- `b7a8594` / `4249430`：冻结并执行 M9.1B-R2.5 评测流程。

## 6. 交付边界

本交付不包含：

- 真实音视频采集和传输；
- ASR、TTS、VAD、AEC、播放和全双工打断控制；
- PDF/日志生产级解析；
- 多用户 session、LRU/TTL、持久化或跨进程 KV；
- 图片/VLM KV 复用；
- 工具 Agent、Docker/systemd、并发和长稳生产验证。

最终定位为：**基于开源 `llama.cpp-omni` 二次开发的 Jetson 端侧离线 LLM/VLM Runtime 与 RAG 应用原型。**

## 7. 交付后建议

停止继续扩展代码，保留当前提交、模型 manifest、测试结果和两条演示链路作为交付证据。若后续确需产品化，应另立项目完成真实手册质量集、音视频链路、鉴权、部署、并发、故障恢复和长稳验收。
