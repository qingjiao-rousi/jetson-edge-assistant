# M7.1 VLM 多 Context 与模型矩阵

原始设计日期：2026-07-28；M7.2b 资产状态同步：2026-07-30。本文定义设计与实测门禁。`已校验` 只表示本地文件完整性及 GGUF metadata 已闭合；没有 Runtime 加载、推理和目标 Jetson 实测证据时，不得标记为可部署。

## 单一常驻 VLM 决策

最终部署只常驻一个 VLM Runtime。文本请求走该 VLM 的语言 backbone；图片请求走同一 VLM 的 vision encoder、mmproj 和语言 backbone。Qwen3 LLM 只作为独立文本基线或显式文本 fallback，不默认常驻，也不是 VLM 第二候选。Qwen2.5-VL-7B 是审计候选，不是主候选失败时自动加载的 Runtime fallback。候选选择不以参数规模推断 context 或性能。

## 固定 Context 矩阵

| context | 用途 | 部署承诺 |
| ---: | --- | --- |
| `4096` | 加载、单图和最小功能冒烟 | 仅冒烟基线 |
| `8192` | 第一版默认候选 | 默认候选，须实测 |
| `16384` | 长手册和多轮图文 | 目标场景候选，须实测 |
| `32768` | 容量/OOM 风险验证 | 不承诺部署 |

有效预算统一为：

```text
image_tokens + image_text_tokens + manual_text_tokens + history_tokens + output_reservation <= n_ctx
```

图片 token 不能按固定常数估算：`mtmd_image_tokens_get_n_tokens()` 返回实际 image token 数，`mtmd_image_tokens_get_n_pos()` 和 decoder position API 提供位置数/位置布局；Qwen-VL 等路径可能使用 M-RoPE。每个分辨率、候选和 context 档都要记录实际值。

## 候选审计

| 顺位 | 候选 | 主模型 / mmproj 与资产状态 | context 证据 | 当前结论 |
| ---: | --- | --- | --- | --- |
| 1 | `Qwen2.5-VL-3B-Instruct Q4_K_M` | 主模型 `Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf` 和 `mmproj-Qwen2.5-VL-3B-Instruct-Q8_0.gguf` 均已通过大小与 SHA-256；来源 `ggml-org/Qwen2.5-VL-3B-Instruct-GGUF`，revision `5037fcf163dd95d1e41d1974465f0898ed108ca2`，license `Apache-2.0` | 主 GGUF `qwen2vl.context_length=128000`；只作为远程仓库/模型及资产 metadata 声明 | 主候选已冻结，binding metadata 已匹配；尚未运行，必须逐档实测 |
| 2 | `Qwen2.5-VL-7B-Instruct Q4_K_M` | 只冻结仓库 `ggml-org/Qwen2.5-VL-7B-Instruct-GGUF` 与 revision `508edd0afaa66bb9e9f40587acc2184f02daf1f6`；不下载。本轮远程 API 连接超时，精确文件清单、大小、hash、license 待复核 | 待远程 metadata 审计；不能由 7B 参数规模推断 | 第二审计候选，不是自动 Runtime fallback |
| 3 | `InternVL3-8B-Instruct Q4_K_M` | 仓库候选 `ggml-org/InternVL3-8B-Instruct-GGUF`；本轮不下载、不固定资产 | 待审计；不能由 8B 参数规模推断 | 保留为第三审计候选 |

主候选两个本地文件的精确字节数、SHA-256、GGUF metadata 和 binding 证据见 `manifests/vlm-assets-v1.json`。当前 fork 的候选支持证据为 `third_party/llama.cpp-omni/tools/mtmd/tests.sh:83-85,104-113`；Qwen2.5-VL projector 与 graph 证据为 `third_party/llama.cpp-omni/tools/mtmd/clip-impl.h:303-323` 和 `clip.cpp:878-881`。源码路径兼容仍不能替代本机加载或 Jetson 实测。

## 实测门禁与记录字段

每个候选与 context 档至少记录：主模型/mmproj 加载结果、metadata context、实际 KV 分配、峰值 RAM/GPU、OOM/失败原因、图片尺寸、image token/position 数、preprocess、vision encode、prefill、first-token/TTFT、decode tokens/s、输出完整性和运行配置。没有原始日志和结构化结果的项目保持 `待实测`；不填写未经实测的性能数字。

加载参数的最低审计集合：主模型路径、`--mmproj` 路径、`--ctx-size`、GPU layers、batch/ubatch、Flash Attention、KV 类型（当前决策为 F16/F16）、线程数、采样配置、动态 image token min/max（若候选支持）。

## 证据边界

`128000` 是远程仓库/模型 metadata 与本地 GGUF metadata 的声明，不是 Jetson context 承诺。`llama-mtmd-cli` 的 `-m/--mmproj/--image/-p` 组合和 `mtmd_tokenize`/`mtmd_helper_eval_chunks` 只证明接口路径；不能替代目标 Jetson 的 VLM 加载、context、延迟、OOM 或长稳实测。`32768` 始终是风险验证档。
