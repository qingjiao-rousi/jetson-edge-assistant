# M7.4C-D CUDA 失败审计

日期：2026-07-30。M7.4C-D 只读取环境、日志、资源和资产身份；没有加载主模型、mmproj 或图片，也没有执行 inference，因此 inference attempt 增量为 `0`。

主机侧 CUDA 预检通过：`/dev/nvhost-gpu`、`/dev/nvmap`、`/dev/nvidiactl` 和 `/dev/nvidia0` 均存在；系统为 Jetson R36.4.7，驱动为 NVIDIA 540.4.0。相同 `llama-mtmd-cli --list-devices` 在主机侧报告 `CUDA0: Orin (30697 MiB, 20062 MiB free)`。

M7.4C 的失败根因属于 **环境不可用**，但范围仅限执行沙盒：该沙盒隔离了 `/dev`，GPU 设备节点不存在，因而同一 binary 记录 `ggml_cuda_init: failed to initialize CUDA: unknown error`。这与主机驱动/runtime 不可用不同。

M7.4C 前后的 Runtime commit 仍为 `19cc26967140407efe34006a355ab445b35b16ac`，Runtime worktree clean。`llama-mtmd-cli`、`llama-tokenize`、主模型和 mmproj 的 SHA-256 均与 M7.4C 配置一致。主机可用 UMA 为 `20141 MiB / 30697 MiB`，swap 已用为 `0`，没有遗留 llama 或 tegrastats 进程；资源占用不是本次失败的证据。系统日志可读取，但直接 `dmesg` 权限不足，未将缺少 dmesg 权限误判成 CUDA 故障。

M7.4C runner 在沙盒组终止后没有完成正常 result 写入，这不是 CUDA 根因，但暴露了监管缺口。新增 `scripts/run_vlm_recovery.py` 通过独立 session/process group、原子状态写入、SIGINT/SIGTERM 捕获、SIGTERM 后 SIGKILL 的清理过程来处理后续已授权运行。其测试使用 Python 子进程，不加载任何 VLM 资产；测试验证了真实非零 exit code `23` 的记录和 telemetry 清理。

决策门已满足“主机 CUDA 预检恢复且根因明确”的条件：M7.4C-R 可以在确认后另立为 **第二次** 16384 inference attempt，参数保持不变，且只能运行一次。它尚未执行。32768 不执行；开发阶段默认候选仍是已成功验证的 8192，下一产品工作仍应优先 Runtime Adapter 的离线资产绑定、命令构造、timeout/进程清理、结构化结果和错误分类，而不是 RAG、Agent 或多 session。
