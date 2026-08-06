# M7.4A Qwen2.5-VL-3B 8192 Context 单图冒烟事实

日期：2026-07-30。固定 `Qwen2.5-VL-3B-Instruct Q4_K_M` 与 `Q8_0 mmproj` 在固定 `llama-mtmd-cli` 上完成一次 8192 context 单图冒烟。进程 exit code 为 `0`，runner 的成功门全部通过；证据目录为 `benchmark-results/vlm-context/20260730-042019-350385-0400/`。

## 固定执行

完整 argv 保存在证据目录的 `command.txt`。本次使用 context `8192`、batch `512`、ubatch `512`、GPU layers `99`、Flash Attention `on`、temperature `0`、seed `424242` 和最大新 token `128`，沿用 M7.3R 的固定图片与 prompt。命令包含 `--offline` 和 `--no-warmup`，不使用 chat mode、Hugging Face 参数或 `/usr/bin/time`；外部 `timeout` 为 900 秒，未触发。模型进程仅启动一次，`inference_run_count=1`、`retry_count=0`。

| 项目 | 本次事实 |
| --- | --- |
| Runtime | commit `19cc26967140407efe34006a355ab445b35b16ac`；worktree clean |
| Project | commit `2d72b69bbafd0ff27e88d0de3c7bbfe6a6d5d5e3`；运行时 worktree dirty |
| 主模型 | SHA-256 校验通过；加载成功；37/37 layers offload 到 CUDA0 |
| mmproj | SHA-256 校验通过；加载成功；519 tensors；CLIP 使用 CUDA0 |
| Context / batch / ubatch | `8192 / 512 / 512`，均由 CLI 日志确认 |
| Flash Attention | `enabled` |
| 图片 | SHA-256 校验通过；解码、视觉预处理、vision encode 和 embedding 注入成功 |
| Image grid / tokens | `23 x 17` / `391`；token 数从本次 CLI 日志读取 |
| Image positions | `null`；CLI 未直接输出，不估算 |
| Prompt / output | `415` prompt tokens；`67` eval runs 作为 output token 记录，CLI 未另报 sampled token count |
| Exit / finish / failure | `0` / `eog` / `null` |

日志未发现 OOM、CUDA error、context overflow 或崩溃，输出非空。输出识别了 1969-07-21 的 *The New York Times* 月球登陆头版，并将 publisher 识别为 *The New York Times*。

## KV、Timing 与 Telemetry

KV allocation 由 CLI 日志直接给出：`288.00 MiB`、`8192 cells`、`36 layers`，其中 K `(f16)` 为 `144.00 MiB`，V `(f16)` 为 `144.00 MiB`。

| 指标 | 本次值 |
| --- | ---: |
| Vision preprocess | `null`；CLI 未独立计时，不倒推 |
| Vision encode | `2846 ms` |
| Image embedding decode/injection | `42 ms` |
| Prompt eval | `4709.92 ms` |
| Decode | `8911.74 ms` |
| CLI total | `15696.67 ms` |
| Wall-clock | `17245 ms`，由 `date +%s%N` 测量 |
| tegrastats samples | `68` |
| Peak UMA used | `10562 MB / 30697 MB` |
| Peak GR3D | `99%` |
| Peak temperature | `56.968 C` |
| Peak `VDD_CPU_CV` | `3445 mW` |
| Peak `VDD_GPU_SOC` | `6888 mW` |
| Peak `VIN_SYS_5V0` | `6562 mW` |

## 4096 参考事实

M7.3R 的 4096 证据仍位于 `benchmark-results/vlm-smoke/20260730-035616-0400/`，本轮校验确认该目录的 11 个历史文件未改变。它也是一次单图冒烟：KV `144.00 MiB`，image grid `23 x 17`，image tokens `391`，vision encode `1597 ms`，embedding decode `59 ms`，prompt eval `2574.04 ms`，decode `4613.04 ms`，CLI total `8242.29 ms`，wall-clock `11477 ms`，peak UMA `10425 MB`，peak GR3D `99%`，peak temperature `56.343 C`。

这些是两次独立执行的原始值，不计算性能提升或退化百分比。M7.4A 按明确要求禁用了 warmup，因此也不把两组 timing 解释为严格受控的性能对比。

## 结论边界

本次事实仅说明固定资产与 Runtime 在该设备上通过一次 8192 context、固定短 prompt、单图冒烟，因而 8192 保留为默认候选容量。它没有验证长手册或多轮图文，也不能形成平均性能、稳定性、长稳或部署结论。16384 和 32768 均未执行；32768 仍是风险验证档且不承诺部署。模型 metadata 的 `128000` context 声明不作为 Jetson 可部署长度证据。
