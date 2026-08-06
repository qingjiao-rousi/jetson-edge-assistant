# M7.3R Qwen2.5-VL-3B 单图冒烟事实

日期：2026-07-30。结果：固定 `Qwen2.5-VL-3B-Instruct Q4_K_M` 与 `Q8_0 mmproj` 在固定 `llama-mtmd-cli` 上完成第一次真实 4096 context 单图冒烟，进程 exit code 为 `0`，成功门全部通过。

## Launcher 修复记录

首次 launcher 证据保留在 `benchmark-results/vlm-smoke/20260730-033701-0400/`。该次因系统不存在 `/usr/bin/time` 而在模型进程启动前退出；`llama_mtmd_cli_invoked=false`、`inference_run_count=0`，不是一次推理。

M7.3R 没有安装软件，以 `date +%s%N` 替代 `/usr/bin/time`。预检确认 binary 可执行、`ldd` 无 `not found`、三个输入文件存在、两个模型资产 SHA-256 匹配、`date`/`timeout`/`tegrastats` 可用，并用 `/bin/true` 验证计时和 exit-code 捕获。修复后的运行是第一次真实 inference attempt，`inference_run_count=1`、`retry_count=0`。

## 固定运行

完整命令见 `benchmark-results/vlm-smoke/20260730-035616-0400/command.txt`。模型参数保持为 context `4096`、batch `512`、ubatch `512`、GPU layers `99`、Flash Attention `on`、temperature `0`、seed `424242`、最大新 token `128`；使用固定单图和 prompt，离线、非 chat mode。

| 项目 | 单次事实 |
| --- | --- |
| Runtime | commit `19cc26967140407efe34006a355ab445b35b16ac` |
| 主模型 | 加载成功；37/37 layers offload 到 `CUDA0: Orin` |
| mmproj | 加载成功；519 tensors；`qwen2.5vl_merger`；CLIP 使用 CUDA0 |
| Context / batch / ubatch | `4096 / 512 / 512` |
| Flash Attention | `enabled` |
| 图片路径 | `third_party/llama.cpp-omni/tools/mtmd/test-1.jpeg` |
| 图片处理 | 解码、视觉预处理、vision encode、embedding 注入均成功 |
| Image grid / tokens | `23 × 17` / `391` |
| Image positions | `null`；CLI 未直接输出，不估算 |
| Prompt / output | `415` prompt tokens；`67` eval runs 作为本次 output token 记录，CLI 未另报 sampled token count |
| Exit / timeout | `0` / `false` |

## 单次 Timing 与 Telemetry

| 指标 | 本次值 |
| --- | ---: |
| Vision preprocess | `null`；CLI 未独立计时，不倒推 |
| Vision encode | `1597 ms` |
| Image embedding decode/injection | `59 ms` |
| Prompt eval | `2574.04 ms` |
| Decode | `4613.04 ms` |
| CLI total | `8242.29 ms` |
| Wall-clock | `11477 ms`，由 `date +%s%N` 测量 |
| Peak UMA used | `10425 MB / 30697 MB` |
| Peak GR3D | `99%` |
| Peak temperature | `56.343 °C` |
| Peak `VIN_SYS_5V0` | `6663 mW` |

tegrastats 共记录 44 个样本；完整原始日志位于 `benchmark-results/vlm-smoke/20260730-035616-0400/`。

## 输出与边界

输出非空，正确识别图片为 1969-07-21 的 `The New York Times` 月球登陆头版，并识别 publisher 为 `The New York Times`。日志未发现 OOM、CUDA error、context overflow 或崩溃。

这是一条单次 4096 context 冒烟事实，不能形成平均性能、稳定性、长稳或 Jetson 部署结论，也不对 8192/16384/32768 context 作任何推断。
