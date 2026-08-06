# Qwen3 Q4_K_M/Q8_0 Jetson 端侧工程性能排名

## 数据有效性

本报告只读取 `benchmark-results/qwen3-quant-kv/20260728T033622Z`（Q4）和 `benchmark-results/qwen3-quant-kv/20260728T035104Z`（Q8）的 `summary.json`、`records.jsonl`、`plan.json`。两者均 `complete=true`、15 条有效 measured、`failed=0`，S/L/G 各 5 条；prompt tokens 一致为 S=45、L=2031、G=59。

两份 `plan.json` 的 provenance、Runtime commit、runner/script hash 相同：Runtime `jetson-runtime-dev@19cc26967140407efe34006a355ab445b35b16ac`，provenance SHA-256 `8bfdf9d20a659b4c4eeb7f49d547f4b086b548f92b8211d7dbb0b981a25ae91c`。固定配置为 F16/F16 KV、context=4096、batch/ubatch=512、GPU layers=99、Flash Attention=on、MODE_30W。

## 排名方法

仅统计 `phase=measured && valid=true`。每个 S/L/G 内独立比较十项均值：Decode tokens/s 高者获胜，其余时间、RAM、温度和 VDD_GPU_SOC 低者获胜。随后累计分组内胜负；**不**把长短 workload 的原始时间作无意义平均。完整的 count、mean、median、min、max、Q4-Q8 绝对差和 Q4 相对 Q8 百分比位于同名 JSON 的 `.statistics`。

| 分组 | Q4 指标胜场 | Q8 指标胜场 | 工程性能第一 |
|---|---:|---:|---|
| S，短输入/短输出 | 7 | 3 | Q4_K_M |
| L，长输入/短输出 | 6 | 4 | Q4_K_M |
| G，短输入/长输出 | 7 | 3 | Q4_K_M |
| 总体 | 20 | 10 | Q4_K_M |

## 直观性能对比

以下均为 5 次有效 measured 的**均值**。差值是 `Q4 - Q8`：对时间、RAM、温度、功耗，负数表示 Q4 更低；对 Decode tokens/s，正数表示 Q4 更高。`first_token_ms` 是 Runtime 本地计时，**不是服务 TTFT**。

### S：短输入 / 短输出（45 prompt tokens）

| 指标 | Q4 | Q8 | Q4 - Q8 | 更优 |
|---|---:|---:|---:|---|
| 模型就绪时间 ms | 2047.4 | 3352.0 | -1304.6 | Q4 |
| Prefill ms | 230.6 | 217.6 | +13.0 | Q8 |
| Runtime first_token_ms | 246.0 | 236.2 | +9.8 | Q8 |
| 总时间 ms | 3137.6 | 3211.4 | -73.8 | Q4 |
| Decode ms | 2905.0 | 2992.4 | -87.4 | Q4 |
| Decode tokens/s | 11.0156 | 10.6939 | +0.3217 | Q4 |
| Peak RAM MB | 17402.2 | 17019.0 | +383.2 | Q8 |
| Peak GPU / TJ C | 54.0 / 55.6 | 54.8 / 56.2 | -0.8 / -0.6 | Q4 |
| Peak VDD_GPU_SOC mW | 8408.2 | 9929.0 | -1520.8 | Q4 |

### L：长输入 / 短输出（2031 prompt tokens）

| 指标 | Q4 | Q8 | Q4 - Q8 | 更优 |
|---|---:|---:|---:|---|
| 模型就绪时间 ms | 2150.6 | 3384.6 | -1234.0 | Q4 |
| Prefill ms | 5206.0 | 4580.6 | +625.4 | Q8 |
| Runtime first_token_ms | 5230.2 | 4606.6 | +623.6 | Q8 |
| 总时间 ms | 8193.2 | 7608.2 | +585.0 | Q8 |
| Decode ms | 2977.2 | 3018.2 | -41.0 | Q4 |
| Decode tokens/s | 10.7484 | 10.6024 | +0.1460 | Q4 |
| Peak RAM MB | 17775.6 | 17114.8 | +660.8 | Q8 |
| Peak GPU / TJ C | 55.0 / 56.2 | 55.6 / 57.0 | -0.6 / -0.8 | Q4 |
| Peak VDD_GPU_SOC mW | 8790.2 | 10159.2 | -1369.0 | Q4 |

### G：短输入 / 长输出（59 prompt tokens，256 output-token 上限）

| 指标 | Q4 | Q8 | Q4 - Q8 | 更优 |
|---|---:|---:|---:|---|
| 模型就绪时间 ms | 2211.8 | 3404.6 | -1192.8 | Q4 |
| Prefill ms | 257.8 | 239.4 | +18.4 | Q8 |
| Runtime first_token_ms | 273.8 | 257.6 | +16.2 | Q8 |
| 总时间 ms | 23483.8 | 23658.2 | -174.4 | Q4 |
| Decode ms | 23224.2 | 23416.8 | -192.6 | Q4 |
| Decode tokens/s | 11.0230 | 10.9323 | +0.0907 | Q4 |
| Peak RAM MB | 18035.8 | 17232.2 | +803.6 | Q8 |
| Peak GPU / TJ C | 56.2 / 57.6 | 57.4 / 59.0 | -1.2 / -1.4 | Q4 |
| Peak VDD_GPU_SOC mW | 8791.0 | 10311.0 | -1520.0 | Q4 |

### 部署视角总览

| 关注点 | 更适合的版本 | 依据 |
|---|---|---|
| 冷启动 / 单请求加载 | Q4_K_M | 三组模型就绪时间均低约 1.19--1.30 s。 |
| Decode 吞吐 / 长输出 | Q4_K_M | 三组 Decode tokens/s 均更高，Decode ms 均更低。 |
| 热与 GPU/SOC rail | Q4_K_M | 三组 GPU/TJ 温度和 VDD_GPU_SOC 均更低。 |
| 长 prompt Prefill | Q8_0 | L 的 Prefill 低 625.4 ms，L 总时间低 585.0 ms。 |
| 本次 UMA RAM 峰值 | Q8_0 | 三组均低 383--804 MB；这不是离散显存。 |
| 高精度对照 | Q8_0 | 量化位宽更高，但本报告不将其当作已验证质量优势。 |

## 最终结论

**工程性能排名：Q4_K_M 第一，Q8_0 第二。** Q4 是当前 Jetson 端侧部署性能优先版本，原因是更快的模型就绪时间、三组均略高的 Decode 吞吐，以及更低的温度和 VDD_GPU_SOC。Q8 仍是高精度对照候选，并在本次固定 workload 的 Prefill、Runtime `first_token_ms` 和峰值 RAM 上占优。

这不是模型质量或精度排名。本轮没有 TTFT、TPOT、精度、显存或独立质量数据；`first_token_ms` 是 Runtime 本地计时，不得称为服务 TTFT。所有最终样本为 `finish_reason=length`，不代表自然完成质量。

最终目录没有失败记录；历史 `final-q4` 和 `final-q8` 分别有 5/2 条 `oom_or_allocation_failed`，与本次完整结果分开，不纳入排名。部署选择仍应同时考虑质量、Decode、启动时间、功耗、内存和 OOM 风险。

机器可读的逐指标统计与排名见 [qwen3-q4-q8-edge-performance-ranking-20260728.json](/home/nvidia/Desktop/llm/vlmllm-main/docs/evaluation/qwen3-q4-q8-edge-performance-ranking-20260728.json)。
