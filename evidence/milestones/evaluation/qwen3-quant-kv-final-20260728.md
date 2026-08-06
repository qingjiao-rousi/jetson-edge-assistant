# Qwen3 Q4/Q8 M6.4 离线结果汇总

## 结论范围

本报告只读取以下两个已完成结果目录，不运行模型或采集工具：

- `benchmark-results/qwen3-quant-kv/20260728T033622Z`（Q4_K_M）
- `benchmark-results/qwen3-quant-kv/20260728T035104Z`（Q8_0）

`summary.json` 的字段 `.complete` 均为 `true`，`.valid_measured` 均为 `15`，`.failed` 均为 `0`；`.by_workload.S/L/G.valid_measured` 均为 `5`。两组 `.records.jsonl` 的 measured 记录 prompt tokens 一致：S=45、L=2031、G=59。每组 measured 的 `.finish_reason` 都是 `length`，因为达到配置的 `max_new_tokens`；这符合当前 `valid_run.finish_reasons`，但不代表自然停止或输出完整。

## 环境与固定参数

两份 `plan.json` 的 `.provenance` 完全一致：主项目 `main`、commit `2d72b69bbafd0ff27e88d0de3c7bbfe6a6d5d5e3`、dirty=false；Runtime `jetson-runtime-dev`、commit `19cc26967140407efe34006a355ab445b35b16ac`、dirty=false；provenance SHA-256 为 `8bfdf9d20a659b4c4eeb7f49d547f4b086b548f92b8211d7dbb0b981a25ae91c`。

脚本 SHA-256 为 `bc799b5a19a09cf23f18424b6860655141118d0d1bac5462c294b8912ec423f1`，runner SHA-256 为 `699ebf18c8f80cba93c8b1ca337e0832e2ba9c31db8f11811698c566e8b62cc7`。config、asset manifest、deployment baseline 的 SHA-256 分别为 `a3864ab3e01af05db8b0c2b43c18e663abbc3a2750aa7af535ed2c580032b110`、`09c4b23c99faa6b7c572be545fef952243c6d7b5dc4610924fc901d6d789df5b`、`0ce83292ca573b408b0a45153460de46782b46aed869394acd519850fffa8096`。这些值来自两个目录的 `plan.json`：`.provenance.project`、`.provenance.runtime`、`.provenance.tooling`、`.provenance.inputs`。

固定配置来自 `tools/benchmark/configs/qwen3-quant-kv-benchmark-v1.json`：context=4096、batch=512、ubatch=512、GPU layers=99、Flash Attention=on、KV offload=on、parallel_sequences=1、MODE_30W/id 2；sampling 为 seed=424242、top_k=1、top_p=1、min_p=0、temperature=0。两组均为 F16/F16 KV，见各自 `plan.json` 的 `.kv_cache`。

## 模型审计

| 模型 | 文件大小 | SHA-256 | GGUF metadata |
|---|---:|---|---|
| Q4_K_M | 2,497,280,256 bytes | `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5` | qwen3, GGUF v3, 398 tensors, file_type 15, quantization_version 2, context 40960, blocks 36 |
| Q8_0 | 4,280,404,704 bytes | `8c2f07f26af9747e41988551106f149b03eb9b5cb6df636027b6bf6278473300` | qwen3, GGUF v3, 398 tensors, file_type 7, quantization_version 2, context 40960, blocks 36 |

两者 chat template 均存在，模板 SHA-256 都是 `57f1fd00f0013a2be96aa79b857391f27e23df5b5f847072b524c897e24d0361`。具体值在 `.provenance.models.q4_k_m.gguf_metadata` 和 `.provenance.models.q8_0.gguf_metadata`。

## 分组统计

以下只统计各目录 `records.jsonl` 中 `phase="measured"` 且 `valid=true` 的记录。每个单元 `count=5`；时间单位 ms，RAM 单位 MB，温度为 C，VDD_GPU_SOC 为 mW。表中 `mean/median/min/max` 均来自原始字段；Runtime `first_token_ms` 保持原名，**不是服务 TTFT**。

### S（prompt_tokens=45）

| 指标 | Q4 mean / median / min / max | Q8 mean / median / min / max |
|---|---:|---:|
| model_ready_ms | 2047.4 / 2046 / 2022 / 2086 | 3352.0 / 3361 / 3327 / 3367 |
| prefill_ms | 230.6 / 233 / 223 / 234 | 217.6 / 217 / 214 / 224 |
| first_token_ms（Runtime） | 246.0 / 247 / 239 / 251 | 236.2 / 234 / 232 / 244 |
| total_ms | 3137.6 / 3135 / 3127 / 3153 | 3211.4 / 3213 / 3193 / 3230 |
| decode_ms | 2905.0 / 2908 / 2892 / 2917 | 2992.4 / 2993 / 2977 / 3012 |
| decode_tokens_per_second | 11.0156 / 11.0041 / 10.9702 / 11.0650 | 10.6939 / 10.6916 / 10.6242 / 10.7491 |
| peak_ram_mb | 17402.2 / 17395 / 17324 / 17515 | 17019.0 / 17020 / 16978 / 17058 |
| peak_gpu_temp_c | 54.0 / 54 / 54 / 54 | 54.8 / 55 / 54 / 55 |
| peak_tj_temp_c | 55.6 / 56 / 55 / 56 | 56.2 / 56 / 56 / 57 |
| peak_vdd_gpu_soc_mw | 8408.2 / 8409 / 8405 / 8409 | 9929.0 / 9929 / 9929 / 9929 |

### L（prompt_tokens=2031）

| 指标 | Q4 mean / median / min / max | Q8 mean / median / min / max |
|---|---:|---:|
| model_ready_ms | 2150.6 / 2150 / 2131 / 2178 | 3384.6 / 3389 / 3372 / 3395 |
| prefill_ms | 5206.0 / 5205 / 5194 / 5226 | 4580.6 / 4579 / 4574 / 4593 |
| first_token_ms（Runtime） | 5230.2 / 5228 / 5218 / 5250 | 4606.6 / 4605 / 4602 / 4618 |
| total_ms | 8193.2 / 8195 / 8181 / 8210 | 7608.2 / 7611 / 7596 / 7615 |
| decode_ms | 2977.2 / 2976 / 2974 / 2981 | 3018.2 / 3022 / 3010 / 3026 |
| decode_tokens_per_second | 10.7484 / 10.7527 / 10.7347 / 10.7599 | 10.6024 / 10.5890 / 10.5750 / 10.6312 |
| peak_ram_mb | 17775.6 / 17777 / 17680 / 17865 | 17114.8 / 17109 / 17086 / 17149 |
| peak_gpu_temp_c | 55.0 / 55 / 55 / 55 | 55.6 / 56 / 55 / 56 |
| peak_tj_temp_c | 56.2 / 56 / 56 / 57 | 57.0 / 57 / 57 / 57 |
| peak_vdd_gpu_soc_mw | 8790.2 / 8791 / 8787 / 8791 | 10159.2 / 10311 / 9929 / 10311 |

### G（prompt_tokens=59）

| 指标 | Q4 mean / median / min / max | Q8 mean / median / min / max |
|---|---:|---:|
| model_ready_ms | 2211.8 / 2211 / 2193 / 2237 | 3404.6 / 3404 / 3393 / 3423 |
| prefill_ms | 257.8 / 259 / 250 / 263 | 239.4 / 241 / 232 / 246 |
| first_token_ms（Runtime） | 273.8 / 274 / 265 / 279 | 257.6 / 258 / 251 / 264 |
| total_ms | 23483.8 / 23494 / 23460 / 23498 | 23658.2 / 23650 / 23639 / 23685 |
| decode_ms | 23224.2 / 23233 / 23209 / 23237 | 23416.8 / 23403 / 23402 / 23451 |
| decode_tokens_per_second | 11.0230 / 11.0188 / 11.0169 / 11.0302 | 10.9323 / 10.9388 / 10.9164 / 10.9392 |
| peak_ram_mb | 18035.8 / 18032 / 17972 / 18095 | 17232.2 / 17230 / 17220 / 17241 |
| peak_gpu_temp_c | 56.2 / 56 / 56 / 57 | 57.4 / 57 / 57 / 58 |
| peak_tj_temp_c | 57.6 / 58 / 57 / 58 | 59.0 / 59 / 58 / 60 |
| peak_vdd_gpu_soc_mw | 8791.0 / 8791 / 8791 / 8791 | 10311.0 / 10311 / 10311 / 10311 |

## Q4/Q8 对比

- 启动：Q8 的 `model_ready_ms` 明显更高，按各组均值差为 S +1304.6 ms、L +1234.0 ms、G +1192.8 ms。该指标是独立进程加载/初始化时间，不是 TTFT。
- Prefill：Q8 在三组均低于 Q4（S -13.0 ms、L -625.4 ms、G -18.4 ms）。L 的差异不能外推到其他 prompt 长度。
- Decode：Q8 的 `decode_ms` 均略高（S +87.4 ms、L +41.0 ms、G +192.6 ms），`decode_tokens_per_second` 均略低（S -2.92%、L -1.36%、G -0.82%）。
- Total：S Q8 +73.8 ms，L Q8 -585.0 ms，G Q8 +174.4 ms；结果显示 workload 组成影响明显，不能只用启动时间判断请求总延迟。
- 资源：本次采样中 Q8 的峰值 RAM 反而低于 Q4（约 383--804 MB），但 peak VDD_GPU_SOC 高约 1.37--1.52 W；GPU/TJ 温度 Q8 高约 0.6--1.4 C。RAM 是 UMA 系统 RAM，不是离散显存；VDD_GPU_SOC 不是整机功耗。

## 失败记录与限制

指定的两个目录没有失败记录。历史目录中，`20260727T140113Z` 有 18 条 `workload_token_target_mismatch`，`20260727T140949Z` 有 18 条 `model_hash_mismatch`；`final-q4` 有 5 条、`final-q8` 有 2 条 `oom_or_allocation_failed`。这些记录未进入本报告统计，分别见各目录 `summary.json` 的 `.failed`/`.by_workload` 或 `records.jsonl` 的 `.failure_class`。

本报告没有服务请求边界，因此没有服务 TTFT 或 TPOT；wall-clock/Runtime 时间字段不得被称为 TTFT/TPOT。没有独立 perplexity、准确率、人评、偏好或输出质量数据，不能从速度推导质量。所有 measured 结果都以 `length` 结束，因而只能作为吞吐/资源比较，不能作为自然完成质量评估。

## 第一阶段部署建议

- 工程性能：Q4_K_M 是当前端侧部署优先候选，启动时间更低、decode 吞吐略高；仍需在目标 Jetson 状态下重复确认。
- 质量：没有独立质量测试，不能声称 Q4 质量更高。Q8_0 保留为高精度对照或质量优先候选。
- 许可证与条件：asset manifest 将两者记录为 Qwen/Qwen3-4B-GGUF、Apache-2.0；部署必须继续绑定上述模型哈希、Runtime commit、F16/F16 KV、MODE_30W 和热/功耗约束。

机器可读的完整统计、provenance 和历史失败清单见 [qwen3-quant-kv-final-20260728.json](/home/nvidia/Desktop/llm/vlmllm-main/docs/evaluation/qwen3-quant-kv-final-20260728.json)。
