# M7.4C-D Recovery Runner 设计

日期：2026-07-30。`scripts/run_vlm_recovery.py` 是为未来已授权的 M7.4C-R 准备的独立进程监管器，不修改已冻结的 `run_vlm_long_context_m7_4c.py`，也不构造或默认执行模型命令。

## 启动与记录

调用方必须先产出经审计的 model argv JSON 与 telemetry argv JSON。默认模式只输出计划；只有 `--execute` 才会启动两个子进程。runner 在任意子进程启动前原子写入 `result.json` 的 `STARTING` 状态，并在 telemetry、model 分别启动后再次原子写入 PID 和事件。因此模型一旦启动，记录中至少保留启动事实和 argv。

模型与 telemetry 都通过 `start_new_session=True` 启动，分别成为独立 process group。model 正常退出后，runner 记录实际 `Popen.wait()` return code，包括负值 signal return code；不会把 timeout、信号或普通非零退出伪装为成功。

## 清理与中断

无论 model 正常结束、非零结束、Python 例外、`SIGINT` 或 `SIGTERM`，runner 都先记录中断状态，再向每个 process group 发 `SIGTERM`；超过 grace period 后发 `SIGKILL`。清理动作、PID、信号和最终 return code 会写回 `result.json`，tegrastats 不会依赖父进程意外退出来停止。

用户态进程无法在自身收到 `SIGKILL`、宿主重启或文件系统失效时保证写入最终结果；该极端情形由启动前的原子 `STARTING` 记录保留“已尝试启动但未完成”的事实，不能伪造 exit code。

## 使用边界

M7.4C-D 只对 runner 使用 Python 测试子进程验证，不加载 GGUF、mmproj 或图片，且不计 inference attempt。未来 M7.4C-R 必须使用新的不可变 config 和证据目录，固定 `16384 / 512 / 512`、GPU layers `99`、Flash Attention `on`、temperature `0`、seed `424242`、predict `128`、`--offline` 和 `--no-warmup`。它将是第二次 inference attempt，而不是覆盖 M7.4C 的失败记录。
