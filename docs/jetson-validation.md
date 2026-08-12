# Jetson 验证摘要

以下是可对外复述的冻结摘要，不包含原始模型、私有 holdout 或大型原始 benchmark 日志。

| 项目 | 已验证范围 | 结论 |
| --- | --- | --- |
| 平台 | Jetson AGX Orin、ARM64、CUDA Release 构建 | 37/37 layer CUDA offload 已记录 |
| 量化 | Q4_K_M 与 Q8_0，各 15 次有效基线测量 | Q4 为部署优先候选；Q8 为对照 |
| KV | 文本单热 session、Token LCP、分叉/回滚与异常失效 | 仅单热 Prefix reuse，不是生产缓存 |
| VLM | 固定 Qwen2.5-VL 主模型/MMProj、单图 API | 单图链路已验证；不宣称通用多图/视频能力 |
| RAG | SQLite/FTS5 hybrid、引用和拒答门禁 | M9.1B R2.5 为 PARTIAL，最终质量门未通过 |

性能数字只在原始环境、固定模型、功耗模式、上下文、采样和测量口径相同的前提下可比较。本仓库不把未随 clone 提供的本机日志作为运行依赖，也不将上述摘要外推为高并发、长稳、生产 SLA 或多用户结论。

## 公开证据状态

| 证据 | 当前公开状态 | 下一步 |
| --- | --- | --- |
| 37/37 CUDA layer offload | 冻结摘要；完整脱敏加载日志未随仓库提供 | 待 Jetson 复核并发布小型脱敏记录 |
| Q4/Q8 各 15 次基线 | Q4 已有 dirty-worktree 锁频暂定数值；Q8 仍只有冻结摘要 | 提交代码后复跑 Q4，再按同协议采集 Q8，禁止用当前数据计算 Q4/Q8 收益 |
| 功耗、RAM/GPU 内存、温度 | Q4 暂定报告包含板载 rail、RAM 和温度统计；不是墙插功耗或长期峰值 | clean commit 复跑并保留相同口径；GPU 专用内存不足以从统一内存遥测中单独证明 |
| 长稳与错误率 | 不足以证明 | 待定义 30-60 分钟串行 soak 并记录请求数/错误/资源趋势 |
| 生产并发/SLA | 未实现且不足以证明 | 不应由当前单活动请求原型外推 |

因此，“Q4 是部署优先候选”可以作为冻结对照中的选择复述；在 Q8 同协议公开表格完成前，仍不能写成具体加速比、内存节省或功耗收益。

## M12 终端单图冒烟

在 Jetson ARM64 环境中，统一入口成功启动 Runtime 并通过 `/ready`。对
`tests/fixtures/vlm-service/synthetic-alarm-panel.png` 执行一次
`/image`：单图、单请求、`stream:false` 返回非空文本，终端明确标识结果
“未经过 RAG 检索或引用校验”，且未回显 Base64。`/image ../README.md`
在客户端仓库相对路径校验阶段被拒绝，未发送给 Runtime。`/quit` 后入口以
退出码 0 结束，端口释放且无残留进程。

这只是一项固定 fixture 的单图、单请求、非流式端到端冒烟证据；不构成 VLM
准确率、CUDA/GPU 指标、视频、多图、批处理、并发、RAG 融合、生产或长稳验证。
它不改变 M9.1B R2.5 为 PARTIAL 的冻结结论。

## 2026-08-12 当前工作区启动复核

在仓库根目录 `/home/nvidia/Desktop/llm/vlmllm-main` 执行了以下只读/构建检查：

- `build-inputs` profile 通过：固定 submodule commit 与 `libllama`、`libmtmd`、`libggml`、`libggml-cuda` 的 AArch64 ELF 检查通过。
- `assistant` profile 通过：Runtime host、Q4 main GGUF、MMProj、embedding GGUF 的大小/SHA-256，以及 RAG SQLite/source binding/read-only 检查通过。
- CMake 重新配置和增量构建成功；CTest 为 4 passed、1 skipped、0 failed。跳过项仍是当前受限沙箱不能绑定临时 loopback 的 HTTP service test。
- 在允许本机 loopback 的执行环境启动统一入口：Runtime 完成当前 Q4 + MMProj 加载并通过 `/ready`，终端出现 `EdgeOmni [manual] >`；输入 `/quit` 后 launcher 退出。

这次复核没有发送 RAG、VLM 或性能请求，成功运行的详细 Runtime 日志按 launcher 设计被删除。因此它只证明当前资产/构建/加载/ready/终端/退出路径，不新增 CUDA layer 数、准确率、延迟、功耗、内存或长稳结论。

## 2026-08-12 动态时钟探索性采集

一次 MODE_30W、`jetson_clocks --show` 但未实际执行 `jetson_clocks` 的 15 样本文本运行完成。日志显示 CPU governor 仍为 `schedutil`、GPU min/max 不同且 EMC `FreqOverride=0`；decode throughput 在同一批次后段出现约 7.2-7.6 tok/s 到约 14.4 tok/s 的明显台阶，同时板载 GPU_SOC rail 档位变化。因此该批次仅保留为 ignored raw diagnostic，**不进入公开 Q4 基线表，也不能用于 Q4/Q8 对照**。采集器现已默认要求锁频状态。

## 2026-08-12 Q4 锁频文本基线（暂定）

随后在 MODE_30W、CPU 1.728 GHz 固定、GPU 612 MHz 固定、EMC override 开启的条件下完成 1 次预热和 15 次非流式文本请求。15/15 为 HTTP 200、无结构化错误、22 prompt token、128 output token；decode throughput 中位数为 15.110 token/s（min 15.089，max 15.222），TTFT 中位数 113 ms（min 110，max 119）。`tegrastats` 的 136 个一秒采样中，RAM 中位数 11,655 MB，GPU 温度中位数 59.5 C。

完整合同、分位数和各功耗 rail 的独立口径见 [Q4 暂定汇总](../benchmarks/q4-k-m-locked-20260812.md)。该结果来自 dirty worktree，虽已绑定 Runtime/collector/raw artifact hash，仍应在整理并提交代码后复核一次，才能升级为最终 clean-commit 可复现基线。它不是 Q8 对照、VLM 图像性能、长稳或生产 SLA。
