# 阶段一 Qwen2.5 Jetson CUDA 基线

## 收口范围

本基线只覆盖可追溯 Runtime、固定模型、CUDA 构建产物和可重复 benchmark 协议，不进入 DirectBackend、VLM、RAG 或部署实现。

## 固定资产

| 项目 | 固定值 |
| --- | --- |
| Runtime submodule | `third_party/llama.cpp-omni` |
| Runtime branch | `jetson-runtime-dev` |
| Runtime commit | `19cc26967140407efe34006a355ab445b35b16ac` |
| CLI version | `259 (19cc269)` |
| Model | `models/qwen2.5-3b-instruct-q4_k_m.gguf` |
| Model SHA-256 | `626b4a6678b86442240e33df819e00132d3ba7dddfe1cdc4fbb18e0a9615c62d` |
| Model size | `2104932768` bytes |
| Hugging Face repo | `Qwen/Qwen2.5-3B-Instruct-GGUF` |
| Hugging Face revision / LFS OID | `pending` / `pending` |
| Build | Release, shared libraries, CUDA/FA enabled, NCCL disabled, SM 87 |

完整环境、构建、Runtime 和模型事实分别记录在 `manifests/environment.json`、`manifests/build.json`、`manifests/runtime.json` 和 `manifests/model.json`。

## 构建结论

- `/usr/local/cuda/bin/nvcc` 被识别为 CUDA 12.6.68。
- `CMAKE_CUDA_ARCHITECTURES=87` 被显式固定，实际 `nvcc` 参数为 `--generate-code=arch=compute_87,code=[compute_87,sm_87]`。
- `GGML_CUDA_NCCL=OFF` 被显式固定；旧 NCCL 探测缓存已清除，配置日志没有“请求开启但未找到 NCCL”的警告。
- `llama-cli` 构建成功，目标为 Linux AArch64。
- `llama-cli` SHA-256 为 `e71f2d2695a33b68ca4ce4d2ff2cdc796c46c54a131f55cd4293e7cfc8230335`；该薄启动器未因 CUDA 架构变化而改变。
- `libggml-cuda.so.0.13.1` 是实际变化的 CUDA 后端，大小为 204379200 bytes，SHA-256 为 `b80e809306ba7a0d6c6d270fb5afd015704f9f5bc8a76edb8077966a891bc5fe`。
- `ldd` 可解析 `libggml-cuda.so.0`、`libcudart.so.12`、`libcublas.so.12`、`libcuda.so.1` 和 `libmtmd.so.0`，无缺失库。
- `--version` 与 `--help` 退出码均为 0。
- `mtmd` 的 PUBLIC include 路径已传递到 `llama-cli-impl` 的实际编译命令，`19cc269` 对应修复有效。
- 新配置、构建和验证日志分别为 `configure-sm87.log`、`build-sm87.log` 和 `verification-sm87.log`，其 SHA-256 记录在 build manifest。

编码助手沙箱内缺少 Jetson 设备节点时，CLI 可能报告 `/dev/nvmap` 或 CUDA 初始化失败。这只说明沙箱未透传设备，不能据此认定宿主机 CUDA 故障。

## 既有 GPU 冒烟证据

`gpu-offload-check.log` 是正式 benchmark 之前的单次宿主机冒烟检查，记录了：

- `CUDA0: Orin`，总显存 30697 MiB；
- `offloaded 37/37 layers to GPU`；
- prompt eval：257.98 ms / 44 tokens，Runtime 报告 170.56 tokens/s；
- decode eval：1378.12 ms / 17 tokens，Runtime 报告 12.34 tokens/s；
- Runtime total：1636.10 ms / 61 tokens。

该次检查的配置和 prompt 与本阶段固定 benchmark 不同，因此只用于证明 GPU offload，不作为 5 次统计基线。

## 固定 Benchmark 协议

脚本：`scripts/benchmark_qwen25.py`

| 参数 | 固定值 |
| --- | --- |
| Prompt | 工业电机过热诊断前置检查，固定英文文本 |
| Context | 4096 |
| Batch / ubatch | 2048 / 512 |
| GPU layers | 99，固定 CUDA0、split mode none、fit off |
| Threads | 8 |
| Flash Attention | on |
| Maximum output | 128 tokens |
| Seed | 424242 |
| Sampling | temperature 0, top-k 1, top-p 1.0, min-p 0, repeat penalty 1.0 |
| Preconditioning | 1 次独立 `llama-cli` 进程，不是被测进程内部 Runtime warmup |
| Effective runs | 至少 5 次；失败运行不计入有效次数，最多默认尝试 8 次 |
| Telemetry | 每次单独启停 tegrastats，1000 ms 间隔 |

正式执行命令：

```bash
python3 scripts/benchmark_qwen25.py
```

运行结果写入被 Git 忽略的 `benchmark-results/qwen2.5-3b-q4_k_m/<benchmark_run_id>/`：

- `runs.jsonl`：每次 preconditioning/有效或失败尝试一条记录；
- `summary.csv`：逐次测量结果；
- `summary.json`：有效次数和 mean/median/min/max/p95 汇总；
- `*.stdout.log`、`*.stderr.log`：每次原始 CLI 输出；
- `*.tegrastats.log`：含相同 run_id 和 UTC 起止时间的遥测。

## 指标语义

- `wall_time_ms` 是每个独立 `llama-cli` 进程的端到端墙钟时间，包含进程启动和模型加载；它不是 TTFT，也不是 TPOT。
- `runtime_prompt_tokens_per_second` 和 `runtime_decode_tokens_per_second` 来自 llama.cpp 自报 timing。
- 当前 CLI 路径不能从墙钟时间可靠拆出首 token 到达时间，因此本基线不输出 TTFT/TPOT 字段。
- 脚本向 CLI 传入 `--no-warmup`。所谓 preconditioning 是测量前另起的完整 CLI 进程，只可能预热文件缓存、CUDA 状态和设备频率，不能描述为同进程 Runtime warmup。
- config、每条 JSONL、CSV 和汇总均记录主项目 commit 及 benchmark 脚本 SHA-256。主仓库没有 HEAD 时只允许 `--validate-only`，正式 benchmark 会拒绝启动。

## 当前状态

`--validate-only` 已在 2026-07-23 执行并通过：`valid=true`、`errors=[]`。验证结果保存为 `docs/baselines/qwen2.5-3b-q4_k_m/validate-only.json`，其中记录的脚本 SHA-256 为 `da476a61de1cfd17a4f6b47aba2f151d248ec058ce21febaa110df4c4c69d9da`。

主项目当前仍是 unborn `main`，因此验证结果中的 project commit 为 `null`，并带有明确 warning。脚本在该状态下拒绝正式 benchmark。正式 1 次 preconditioning + 5 次有效宿主机测量尚未执行；应先创建阶段一首个 commit，再运行 benchmark，报告不伪造尚未采集的统计结果。
