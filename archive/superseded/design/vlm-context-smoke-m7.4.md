# M7.4 VLM Context 冒烟工具设计

日期：2026-07-30。`scripts/run_vlm_context_smoke.py` 是 Qwen2.5-VL 固定资产的显式执行工具。默认行为与 `--dry-run` 都只输出计划；只有 `--execute` 才能进入文件校验、telemetry 和模型启动路径。

## 固定矩阵

| Context | M7.4A 状态 | 边界 |
| ---: | --- | --- |
| `4096` | `REFERENCE_ONLY` | 已有 `benchmark-results/vlm-smoke/20260730-035616-0400/` 单图冒烟证据，不重复执行 |
| `8192` | `M7.4A_ONLY_EXECUTION` | 本轮唯一允许执行的默认候选容量冒烟 |
| `16384` | `NOT_EXECUTED_IN_M7.4A` | 本轮不执行 |
| `32768` | `NOT_EXECUTED_IN_M7.4A_NOT_A_DEPLOYMENT_COMMITMENT` | 风险验证档，本轮不执行且不承诺部署 |

完整机器配置位于 `evidence/milestones/configs/vlm/vlm-context-smoke-m7.4.json`。工具拒绝矩阵外 context；M7.4A 的 `--execute` 还会拒绝 4096、16384 和 32768。

## 执行门禁

`--execute` 按以下顺序工作：

1. 创建不可覆盖的微秒级时间戳目录并冻结 config 与实际 argv。
2. 校验 Runtime commit 和 Runtime dirty 状态。
3. 校验 binary、主模型、mmproj、图片的存在性、大小和 SHA-256。
4. 运行 `ldd` 并拒绝任何 `not found`，确认 `date`、`timeout` 和 `tegrastats` 可用。
5. 启动 tegrastats，取得至少一个有效样本后才把模型启动次数置为 1。
6. 以外部 `timeout` 启动一次 `llama-mtmd-cli`；不重试。
7. 仅用 `date +%s%N` 包围真实模型进程并计算 wall-clock；不依赖 `/usr/bin/time`。
8. 正常停止 tegrastats，解析原始日志并写入 `result.json`。

命令始终包含本地 `--model`、`--mmproj`、`--image` 和 `--offline`，不生成 `-hf`/URL 参数，因而没有自动下载路径。8192 命令沿用 M7.3R 的 batch、ubatch、GPU layers、Flash Attention、sampling、图片和 prompt；context 改为 8192，并按 M7.4A 明确要求加入 `--no-warmup`。

## 结果与失败

每个执行目录至少保存 `command.txt`、`config.snapshot.json`、`launcher-preflight.json`、`stdout.log`、`stderr.log`、`tegrastats.log`、`process-status.txt` 和 `result.json`。目录使用 `exist_ok=False`，不会覆盖历史证据。模型启动后的失败保留全部原始输出，不降级 context、模型、mmproj、图片或参数，也不触发第二次启动。

失败分类覆盖 launcher dependency/preflight、asset hash、模型/mmproj/image/vision load、context limit、OOM/allocation、CUDA、decode、timeout、telemetry missing 和 internal。result schema 在成功和失败记录中都保留 context、资产与 git 身份、KV、vision、timing、telemetry、process、finish reason、failure class 和 output 字段；CLI 未直接报告的独立 timing 或 image position 保持 `null`，不倒推。

## 测试与证据边界

`tests/test_vlm_context_smoke.py` 使用标准库 `unittest` 和临时小文件，不访问 GPU 或模型。它覆盖 context 门禁、hash mismatch、dry-run 零子进程、`/usr/bin/time` 禁令、failure mapping、result 必需字段和显式 `--execute` 门禁。

4096 与 8192 结果都只能作为各自一次单图冒烟事实。可以并列记录原始值，但不计算性能提升百分比；8192 成功不代表长手册、多轮图文、稳定性或部署能力已经验证。模型 metadata 的 `128000` context 声明不进入部署结论。
