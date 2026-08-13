# Jetson 验证摘要

以下是可对外复述的冻结摘要，不包含原始模型、私有 holdout 或大型原始 benchmark 日志。

| 项目 | 已验证范围 | 结论 |
| --- | --- | --- |
| 平台 | Jetson AGX Orin、ARM64、CUDA Release 构建 | 37/37 layer CUDA offload 已记录 |
| 量化 | Q4_K_M 与 Q8_0，各 15 次有效基线测量 | Q4 为部署优先候选；Q8 为对照 |
| KV | 文本单热 session、Token LCP、分叉/回滚与异常失效 | 仅单热 Prefix reuse，不是生产缓存 |
| VLM | 固定 Qwen2.5-VL 主模型/MMProj、单图 API | Q4/Q8 固定单图 E2E 已验证；不宣称准确率、通用多图/视频能力 |
| RAG | SQLite/FTS5 hybrid、引用和拒答门禁 | M9.1B R2.5 为 PARTIAL，最终质量门未通过 |

性能数字只在原始环境、固定模型、功耗模式、上下文、采样和测量口径相同的前提下可比较。本仓库不把未随 clone 提供的本机日志作为运行依赖，也不将上述摘要外推为高并发、长稳、生产 SLA 或多用户结论。

## 公开证据状态

| 证据 | 当前公开状态 | 下一步 |
| --- | --- | --- |
| 37/37 CUDA layer offload | clean Q4 Runtime 日志已核对，公开报告绑定其 SHA-256 | 原始长日志仍保留在 Git-ignored 本地证据目录 |
| Q4/Q8 各 15 次基线 | 同 clean commit 锁频配对文本数值已公开 | 速度近似持平；Q4 的部署优先理由是资源效率，不外推到单图、长上下文或质量 |
| Q4/Q8 固定单图 E2E | 同 clean commit、同图同 prompt 各 15 次数值已公开 | 最新阶段计时 commit 中 Q8 E2E median 低 4.44%，但统一 RAM 多 1,403 MB；不是质量或通用 VLM 结论 |
| 功耗、RAM/GPU 内存、温度 | Q4/Q8 报告包含板载 rail、统一 RAM、CUDA model buffer 和温度统计 | 不是墙插功耗、独立 GPU 内存遥测或长期峰值；长稳仍待实测 |
| 单图阶段拆分 | clean commit、同图同 prompt 各 15 次，三个字段均为 `measured` | Q4/Q8 vision encode median 305/277 ms，embedding 注入 31/28 ms；预处理为低于整数毫秒精度的 `0 ms measured` |
| 长稳与错误率 | 不足以证明 | 待定义 30-60 分钟串行 soak 并记录请求数/错误/资源趋势 |
| 生产并发/SLA | 未实现且不足以证明 | 不应由当前单活动请求原型外推 |

因此，“Q4 是部署优先候选”现在可由 clean-commit 配对文本结果支持：稳定 decode 速度近似持平，而 Q4 使用更少统一 RAM、CUDA model buffer，并具有更短 model-ready 时间。该结论仍不能外推到单图、长上下文、质量或长稳。

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

## 2026-08-12 Q4 锁频文本基线（clean commit）

在 clean commit `376134149939cabd783bcd293d3bb465da8d2e55`、MODE_30W、CPU 1.728 GHz 固定、GPU 612 MHz 固定、EMC override 开启的条件下完成 1 次预热和 15 次非流式文本请求。15/15 为 HTTP 200、无结构化错误、22 prompt token、128 output token；decode throughput 中位数为 15.098 token/s（min 15.084，max 15.231），TTFT 中位数 112 ms（min 112，max 113）。`tegrastats` 的 136 个一秒采样中，统一 RAM 中位数 11,849 MB，GPU 温度中位数 55.593 C。

完整合同、分位数和各功耗 rail 的独立口径见 [Q4 reviewed 汇总](../benchmarks/q4-k-m-locked-20260812.md)。报告绑定 Runtime、collector 和本地 raw artifact hash。该结论只覆盖当前 Q4 文本协议，不是 Q8 对照、VLM 图像性能、长稳或生产 SLA。

## 2026-08-12 Q8 资产与加载冒烟

`configs/assistant-q8.json` 记录 Qwen2.5-VL-3B-Instruct Q8_0 主模型的真实大小 3,285,474,304 bytes 和 SHA-256 `fa8aeb3b6bf6152774e87d13e09892aa065f4e0c4abe90806cd8ab18ff72d9fe`，并继续使用同一 MMProj、context/batch/ubatch、GPU layers、Runtime、RAG 和 Agent 参数。Q8 `assistant` profile 已通过，Q4/Q8 配置差异检查确认实验变量只有主模型资产。

统一 launcher 随后用该 Q8 合同完成 `load -> /ready -> terminal -> /quit`，退出码 0，未发现残留 Runtime 进程。这只证明当前 Q8 资产和固定上游可以加载并进入 ready；尚未发送测量请求，不构成 Q4/Q8 延迟、吞吐、内存、功耗或质量对照。

## 2026-08-12 Q4/Q8 clean-commit 配对文本基线

在同一 clean commit `7a9d40eb262ca718352a00d3f6864da86dfb0571` 和相同锁频/输入/Runtime/MMProj 参数下，Q4 与 Q8 各完成 1 次预热和 15 次有效请求。两者均为 15/15 HTTP 200、37/37 layer offload 并正常停止。

Q4/Q8 decode throughput 中位数分别为 15.101/15.227 token/s，Runtime total 中位数为 8,491/8,422 ms，属于该短文本协议下的近似持平。Q8 的统一 RAM 中位数为 13,928 MB，相比 Q4 的 12,458 MB 增加 1,470 MB；CUDA model buffer 增加 1,292.78 MiB，单次 model ready 从 4,808 ms 增至 6,894 ms。因此当前选择 Q4_K_M 的公开理由是资源效率，不是宣称 Q4 速度更快。完整口径、telemetry 和 artifact hash 见 [配对报告](../benchmarks/q4-q8-paired-20260812.md)。

## 2026-08-13 Q4/Q8 clean-commit 固定单图 E2E 基线

在 clean commit `7415e0e6b7d1447addec2006f4540e0defb08bad` 上，Q4/Q8 使用同一 320x192 合成 PNG、prompt、MMProj、Runtime 和 MODE_30W 锁频配置，各完成 1 次预热和 15 次有效单图请求。两者均为 15/15 HTTP 200、37/37 layer offload、77 image tokens、14 output tokens，且输出文本一致。

Q4/Q8 Runtime total 中位数为 1,530/1,462 ms，TTFT 为 598/537 ms；Q8 在该固定请求下 E2E 低 4.44%。但 Q8 统一 RAM 中位数为 13,800 MB，比 Q4 的 12,344.5 MB 多 1,455.5 MB，model ready 也从 4,834 ms 增至 6,719 ms。因此仍以 Q4 作为部署优先候选；该选择基于资源效率，不是否认本次 Q8 的小幅 E2E 优势。

三个视觉阶段字段在结构化响应中均为 `not_measured`，对应零值不按 0 ms 解读。合成图仅用于端到端性能/链路证据，不构成诊断准确率或量化质量结论。完整口径与 artifact hash 见 [单图配对报告](../benchmarks/q4-q8-image-paired-20260813.md)。

## 2026-08-13 Q4/Q8 clean-commit 固定单图阶段计时

在 clean commit `f806e59e01b5275ed8a06e18b0e4ce53f7563425` 上，以相同单图协议重新完成 Q4/Q8 各 1 次预热和 15 次有效请求。两组均为 15/15 HTTP 200、37/37 layer offload，且 `image_preprocess_ms`、`vision_encode_ms`、`image_embedding_ms` 在全部响应中均明确标记为 `measured`。

Q4/Q8 vision encode 中位数为 305/277 ms，image embedding 注入为 31/28 ms，Runtime total 为 1,531/1,463 ms。两组 image preprocessing 都是 `0 ms measured`，表示低于当前整数毫秒精度，不是未测量。`prefill_ms` 是包含视觉子阶段的聚合区间，不能与子阶段求和。

Q8 在该固定请求中的视觉阶段和 E2E 延迟较低，但统一 RAM 中位数为 14,182 MB，比 Q4 的 12,779 MB 多 1,403 MB；Q4 仍作为 32 GB 目标的资源优先候选。完整分位数、计时边界和 artifact hash 见 [阶段计时报告](../benchmarks/q4-q8-image-stages-paired-20260813.md)。该合成 fixture 不构成准确率证据。
