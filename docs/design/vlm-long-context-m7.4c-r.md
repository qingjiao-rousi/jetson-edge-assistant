# M7.4C-R 16384 Sandbox Recovery 设计

日期：2026-07-30。M7.4C-R 是在 M7.4C-D 已确认“沙盒隔离 GPU `/dev` 节点、主机 CUDA 正常”后的独立第二次 inference attempt。它引用但不修改 M7.4C 的失败记录、M7.4C-D 审计、M7.4C config/runner 和 recovery runner。

固定输入包含同一主模型、Q8_0 mmproj、测试图片和 M7.4C 已生成 fixture；fixture 大小 `73703 bytes`、SHA-256 `4ddfe0e50411670bffefa87b2715df90a43ef4c99502f9dd6257978820eecdef`。固定推理参数为 `16384 / 512 / 512`、GPU layers `99`、Flash Attention `on`、temperature `0`、seed `424242`、predict `128`、mmproj offload、`--offline` 与 `--no-warmup`。

执行前，启动器在同一主机执行环境运行 `llama-mtmd-cli --list-devices`，只有返回 `CUDA0: Orin` 才允许模型启动。M7.4C-R 写入新的 `benchmark-results/vlm-long-context-16384-recovery/<timestamp>/`，并通过 `scripts/run_vlm_recovery.py` 将 model 与 tegrastats 置于独立 process group。supervisor 记录真实 child return code，并在结束时清理两组进程。

账本固定为 `attempt_ordinal=2`、`previous_inference_attempt_count=1` 和 `retry_count=1`。只允许一次 model 启动；无论结果如何都不允许第三次尝试或 32768 执行。成功不改变 8192 的默认开发候选，也不形成稳定性、部署或性能比较结论。
