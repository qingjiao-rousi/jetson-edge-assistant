# Qwen3 量化部署决策 v1（M6.5）

## 决策状态

M6 量化与 KV Cache 性能阶段现已收口。本文件冻结量化部署选择；它是独立的量化层决策，不覆盖或改写 `manifests/deployment-baseline-v1.json` 中的原始模型选择基线。

| 角色 | 工件 |
|---|---|
| 第一阶段端侧部署优先候选 | `models/Qwen3-4B-Q4_K_M.gguf`，Q4_K_M，2,497,280,256 bytes，SHA-256 `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5` |
| 高精度对照/质量优先候选 | `models/Qwen3-4B-Q8_0.gguf`，Q8_0，4,280,404,704 bytes，SHA-256 `8c2f07f26af9747e41988551106f149b03eb9b5cb6df636027b6bf6278473300` |

两者均来自 `Qwen/Qwen3-4B-GGUF` revision `a9a60d009fa7ff9606305047c2bf77ac25dbec49`，asset manifest 记录许可证为 Apache-2.0。完整机器可读决策位于 `manifests/quantization-deployment-baseline-v1.json`。

## 证据与 provenance

决策依据为：

- `benchmark-results/qwen3-quant-kv/20260728T033622Z`：Q4_K_M，`summary.json.complete=true`，15/15 有效 measured，S/L/G 各 5/5，`failed=0`；
- `benchmark-results/qwen3-quant-kv/20260728T035104Z`：Q8_0，`summary.json.complete=true`，15/15 有效 measured，S/L/G 各 5/5，`failed=0`；
- `docs/evaluation/qwen3-quant-kv-final-20260728.md` 与对应 JSON 报告。

两份 `plan.json` 的 `.provenance` 一致：主项目 `main` commit `2d72b69bbafd0ff27e88d0de3c7bbfe6a6d5d5e3`、Runtime `jetson-runtime-dev` commit `19cc26967140407efe34006a355ab445b35b16ac`，provenance SHA-256 为 `8bfdf9d20a659b4c4eeb7f49d547f4b086b548f92b8211d7dbb0b981a25ae91c`。脚本、runner、config、asset manifest 和原 deployment baseline 的哈希均已在新 manifest 的 `.evidence` 中冻结。

## 固定 Runtime 决策

- KV Cache 固定 `F16/F16`。
- 不启用 Q8/Q4 KV Cache。当前 DirectBackend 没有暴露受控 K/V 类型配置；不能把 CLI/common 层的能力表述成 DirectBackend 公开契约。
- context=4096、batch=512、ubatch=512、GPU layers=99、Flash Attention=on、KV offload=on、parallel sequences=1、MODE_30W/id 2。
- sampling 固定 seed=424242、top_k=1、top_p=1.0、min_p=0.0、temperature=0.0，reasoning=off。

后续若要改变 KV 类型或上述任何参数，必须创建新的协议/决策版本，不能与本次结果混合。

## 实测工程性能结论

在两个最终目录的有效 measured 样本中，Q4 的 `model_ready_ms` 三个 workload 均低于 Q8，decode tokens/s 略高；Q8 的 prefill 在本次 L workload 较低，且峰值 RAM 观测较低，但 VDD_GPU_SOC 和温度观测较高。差异详见报告的 S/L/G 表格和 JSON `.statistics`。

这些是固定 Jetson、固定 Runtime、固定 prompt 和 F16/F16 KV 下的工程观测，不是普遍模型性能定律。Runtime `first_token_ms` 是本地 Runtime 计时，不能称为服务 TTFT；本轮没有服务 TTFT/TPOT。

## 质量结论边界

没有独立的 perplexity、任务准确率、人评、偏好或完整输出质量测试。两组最终 measured 记录均为 `finish_reason=length`，说明输出达到 `max_new_tokens` 上限，不能作为质量优劣或自然停止结论。因此本决策只冻结部署优先级，不声称 Q4 质量高于 Q8。

## OOM 与失败记录

两个用于本决策的最终完整目录均没有失败记录。历史结果仍保留：`final-q4` 有 5 条 `oom_or_allocation_failed`、11 条有效 measured；`final-q8` 有 2 条同类失败、14 条有效 measured；另有早期 token-target/hash 门禁失败。历史失败不进入本决策统计，也没有被删除或覆盖。

## 部署条件与下一阶段

部署必须同时满足模型 SHA-256、Runtime commit、F16/F16 KV、固定 runtime/sampling 配置和 Jetson 功耗/散热条件。许可证和来源以 `manifests/qwen3-quant-kv-assets.json` 为准，不因量化性能数据改变。

M6 完成。下一阶段进入第 7--8 周 VLM 图片输入设计：先核实实际支持的 VLM、vision/mmproj 来源与 hash，再设计单张图片文本闭环、错误边界和视觉指标；本次不实现 VLM、RAG、Agent、Docker 或 systemd。
