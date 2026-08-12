# Jetson Benchmark 协议

本协议用于补齐当前公开证据缺口。仓库提供采集器、空白表和一份来自 dirty worktree 的 [Q4 锁频暂定报告](../benchmarks/q4-k-m-locked-20260812.md)。该报告是有效实测但不是最终 clean-commit 基线；Q8、单图性能和长稳结果仍为**待 Jetson 实测**，不得从代码、Q4 数据或旧描述推算。

## 回答的问题

1. 在同一 AGX Orin、同一环境和输入下，Q4_K_M 与 Q8_0 的模型加载、TTFT、prefill、decode throughput、总延迟、内存和功耗差异是什么？
2. 单热 text session 的相同前缀与分叉前缀能复用多少 token，是否保持确定性输出？
3. 固定单图请求的端到端延迟和资源峰值是什么？
4. 30/60 分钟串行运行是否出现错误、内存持续增长或异常温度/降频？

第 3、4 项当前脚本未自动实现，属于待实测扩展；不得用单次文本 runner 替代。

## 固定环境字段

每份结果必须记录：Git commit、submodule commit、模型文件名/量化/SHA-256、MMProj SHA-256（VLM 时）、AGX Orin 型号与内存、L4T、CUDA、功耗模式、`jetson_clocks` 状态、温度起点、上下文/batch/ubatch、GPU layers、CPU threads、prompt SHA-256、输出 token 上限和采集时间。

如果这些字段不同，Q4/Q8 结果不得直接比较。37/37 CUDA layer offload 是加载证据，不等于全部算子均在 GPU，也不等于性能达标。

正式对照前必须先锁频；`--show` 只显示状态，不会锁频：

```bash
sudo nvpmodel -q
sudo jetson_clocks
sudo jetson_clocks --show
sudo -v
```

确认 CPU/GPU 的 `MinFreq=MaxFreq` 且 EMC `FreqOverride=1`。采集器默认拒绝动态时钟；`--allow-dynamic-clocks` 只能用于明确标记的探索性运行。MODE_30W 下未锁频的测试可能因 DVFS 在同一批次内出现明显性能台阶，不能作为 Q4/Q8 最终对照。

采集器也默认要求 `git status --short` 为空，并在环境记录中写入 commit、clean 状态、status 条目数及其 SHA-256。`--allow-dirty-worktree` 仅允许探索性运行；即使 label 含有 `clean`，也不能把 dirty-worktree 结果升级为公开可复现基线。

## 文本基线方法

- 每个量化先做 1 次不计入统计的 warm-up，再做 15 次有效测量。
- 固定 prompt、seed、greedy sampling、上下文和 `max_new_tokens`；若提前 EOG，记录实际输出 token。
- `scripts/run_jetson_benchmark.py` 为每份 config 启动一次持续 Runtime：先做 1 次 warm-up，再通过 HTTP 发送 15 次请求。该表测的是稳态服务请求；`model_ready_ms` 是同一次 Runtime 初始化值，不能当成 15 次独立冷启动样本。
- 报告 median、p90、min/max 和有效样本数；15 个样本不足以作生产 SLA 或高分位尾延迟声明。
- decode throughput 使用 Runtime 返回的 `decode_tokens_per_second`，同时保留 `decode_ms` 和实际 output tokens。
- 资源采样使用 `tegrastats` 原始日志；功耗报告必须声明取自哪组 rail、采样周期及聚合方式。没有外部功率计时应写“板载遥测”，不能写整机墙插功耗。

采集示例：

```bash
cd /home/nvidia/Desktop/llm/vlmllm-main
scripts/run_jetson_benchmark.sh --dry-run

scripts/run_jetson_benchmark.sh \
  --config configs/assistant-q4.json \
  --label q4-k-m \
  --tegrastats /usr/bin/tegrastats

scripts/run_jetson_benchmark.sh \
  --config configs/assistant-q8.json \
  --label q8-0 \
  --tegrastats /usr/bin/tegrastats
```

每份 config 必须包含匹配的 main model/MMProj path、size 和 SHA-256，并先通过 `assistant` preflight。当前仓库只固定提供默认 Q4 合同；`assistant-q8.json` 需要根据真实获准 Q8 资产创建，不能复制或猜测 hash。

原始输出写入被 Git 忽略的 `benchmarks/results/`。人工复核、脱敏和聚合后，填写 `benchmarks/results-template.csv`；不要直接提交长日志。HTTP collector 使用 `MtmdBackend`，不会把 Qwen2.5-VL 错交给仅接受冻结 Qwen3 hash 的 DirectBackend benchmark runner。

## KV Prefix reuse 方法

使用 `edgeomni_qwen3_benchmark_runner --session-id ... --prompt-2 ...` 固定同一 session：

- cold：第一条完整 prompt；
- exact/LCP：第二条相同或共享长前缀 prompt；
- branch：第三条共享前缀但末尾分叉的 prompt；
- invalidation：另测 session 切换、图像请求、取消、超时或 decode 失败后的 cache miss。

必须报告 `cache_hit_tokens`、`cache_miss_tokens`、`cache_hit_ratio`、`prefill_ms` 和 `cache_invalidation_reason`。只允许表述为“单热 session Token LCP Prefix reuse”，不得称作多用户缓存、paged KV、LRU/TTL 或生产缓存系统。

## 稳定性与 VLM 待实测项

稳定性测试需定义持续时间、请求间隔、总请求数、错误分类、RSS/GPU 内存首末与峰值、温度/频率/功耗采样，以及退出后的端口/进程回收。当前没有可公开长稳结果。

单图测试需固定仓库 fixture、prompt、图片 SHA-256、预处理与 vision 指标口径。合成 panel 冒烟只证明链路返回，不能作为视觉诊断准确率。任何真实设备图都要先完成版权和隐私审查。

## 发布判定

只有原始 JSON/遥测与聚合表可追溯、环境字段齐全、Q4/Q8 输入一致时，才可计算并发布量化对照。异常/缺失样本必须说明排除理由。当前对外状态为：**Q4 锁频文本基线暂定，clean commit 复跑和 Q8 同协议对照待实测，生产 SLA 不足以证明**。
