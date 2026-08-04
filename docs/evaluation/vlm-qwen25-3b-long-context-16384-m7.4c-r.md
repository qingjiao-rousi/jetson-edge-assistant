# M7.4C-R Qwen2.5-VL-3B 16384 Recovery 冒烟事实

日期：2026-07-30。M7.4C-R 是 M7.4C 之后的第二次、也是最后允许的一次 16384 inference attempt。状态为 `SUCCESS`，证据目录为 `benchmark-results/vlm-long-context-16384-recovery/20260730-061237-155284-0400/`。账本为 `attempt_ordinal=2`、`previous_inference_attempt_count=1`、`retry_count=1`；没有第三次尝试。

在同一主机执行环境中，启动前 `--list-devices` 返回 `CUDA0: Orin (30697 MiB, 19862 MiB free)`。主模型、mmproj、图片、冻结 fixture、M7.4C failure、M7.4C-D audit、M7.4C config/runner 和 recovery runner 全部通过 size/SHA-256 门禁；Runtime commit 为 `19cc26967140407efe34006a355ab445b35b16ac`，worktree clean。

模型 child exit code 为 `0`。CLI 直接确认 context/batch/ubatch `16384 / 512 / 512`、37/37 layers offload 到 CUDA0、mmproj CUDA、image grid `23 x 17`、image tokens `391`、prompt tokens `13702` 和 output `41`。KV Cache 为 `576.00 MiB`、16384 cells、36 layers，K/V 各 `288.00 MiB` F16。图片解码、视觉编码和 embedding 注入均成功。

stdout 是严格合法 JSON，四项答案均通过：publisher 为 `The New York Times`，`start_code` 为 `A17`，`middle_torque_nm` 为 `42`，`reset_seconds` 为 `7`。本次日志给出的 timing 为 vision encode `2888 ms`、image embedding decode `43 ms`、prompt eval `57512.70 ms`、decode `5607.47 ms`、CLI total `65340.91 ms`。runner 未记录 wall-clock，保留为 `null`，不倒推。

tegrastats 有 260 个有效样本，峰值 UMA `12105 / 30697 MB`、GR3D `99%`、温度 `58.218 C`。model process 自然退出；tegrastats process group 收到 SIGTERM，以 `-15` 退出，未使用 SIGKILL，随后没有残留进程。

这是一次 host-CUDA recovery 冒烟事实，说明固定资产和 Runtime 在该主机完成了一次 16384 合成长手册加单图请求。它不改变 8192 的默认开发候选，不构成平均性能、稳定性、长稳、生产手册质量或部署结论。32768 未执行，RAG、Agent 和多 session 均未接入；下一阶段进入 Runtime Adapter 集成。
