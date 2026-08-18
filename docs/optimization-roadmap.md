# EdgeOmni 深入优化路线与实时状态

最后更新：2026-08-17
公开作品集基线：`d11617e` (`docs(benchmark): publish paired VLM stage timings`)
当前阶段：**OPT-1 已在实验分支 VALIDATED；未合入 main**

本文是基线之后性能优化工作的唯一状态源。`README.md` 只展示摘要，`ROADMAP.md` 只保留里程碑。每次实验更新本页的状态、证据和决策记录，不用未审核结果覆盖既有 reviewed baseline。

## `d11617e` 基线是什么

`d11617e` 是一个**可公开展示和复核的作品集基线**，不是生产完成版本，也不是性能优化终点。它冻结了以下内容：

- C++17 文本/单图 Runtime、HTTP/JSON/SSE、`/health`/`/ready`、超时/取消和单活动请求保护。
- Qwen2.5-VL `MtmdBackend` 单图路径及 preprocessing、vision encode、image embedding 的显式测量状态。
- SQLite/FTS5 Hybrid RAG、引用/拒答门禁、受限只读 Agent、终端和实验性半双工适配。
- 固定 `llama.cpp-omni` gitlink、模型/MMProj/SQLite SHA-256 合同和离线预检。
- Jetson AGX Orin MODE_30W 锁频下的 Q4/Q8 文本、固定单图 E2E 和视觉阶段 reviewed baseline。
- README、架构/限制、LICENSE、第三方声明、CI、benchmark 协议和公开仓库检查。

基线证据包括：Q4/Q8 各 15 次配对文本、各 15 次固定单图请求、37/37 layer offload，以及 raw evidence 的 SHA-256 绑定。它能支持“完成一个边界清楚、可审计的 Jetson 离线原型”这一结论，但不能支持准确率、长稳、高并发或生产 SLA 声明。

## 当前完成度

| 维度 | 状态 | 已有证据 | 尚缺内容 |
| --- | --- | --- | --- |
| 公开作品集 P0 | **完成** | 首屏、所有权、许可证、CI、验证入口、reviewed benchmark | 真实截图/GIF 会继续提升展示效果，但不阻塞基线成立 |
| 核心离线原型 | **完成（按声明范围）** | 文本/单图 Runtime、RAG/Agent、离线合同、Jetson load/ready/请求 | 不包含视频、多图、批处理和高并发 |
| Jetson 短时性能证据 | **完成** | Q4/Q8 文本、固定单图 E2E/阶段计时和资源遥测 | 不代表长稳、墙插功耗、质量或生产尾延迟 |
| RAG/VLM 质量 | **部分完成** | 引用/拒答合同；RAG R2.5 明确为 PARTIAL | 新独立 RAG eval、真实 VLM 小型质量集 |
| 部署运维 | **部分完成** | 原生离线构建/启动/校验流程、OPT-1 30 分钟 serial soak | clean-clone 演练、无 skip HTTP CTest、systemd、日志轮转、120 分钟/故障注入 |
| 深入性能优化 | **OPT-1 VALIDATED（实验分支）** | 709-token correctness、四档 Runtime-length matrix、paired 30 分钟 soak | Q8 对照、RAG LCP 分布、Agent/RAG 映射 |
| 生产化 | **未实现且非当前目标** | 无 | 鉴权、审计、多用户调度、故障注入、生产 SLA |

不使用一个笼统百分比描述整个项目，因为“作品集完整度”和“生产完整度”不是同一分母。当前可以准确表述为：**作品集 P0 和声明范围内的核心原型已完成；质量、长稳和生产化仍未完成。**

## 必须先澄清的 KV 边界

当前仓库已有 Token LCP Prefix reuse，但它位于 `DirectBackend` 的冻结 Qwen3 验证路径：

- `runtime/src/direct_backend.cpp`：已有 token LCP、KV 范围删除、prompt KV 保留及异常失效。
- `runtime/src/mtmd_backend.cpp`：实际 Qwen2.5-VL 服务路径仍在每次请求退出时清空 llama memory。
- `app/qa/manual_qa.py`：当前 RAG 模型请求发送 `session_id: null`。

因此，基线只能声称“已有单热 Prefix reuse 原型和合同”，不能声称“实际 Qwen2.5-VL/RAG 主路径已经从 Prefix reuse 获得 Prefill/TTFT 收益”。OPT-1 的目标正是补齐并验证这一点。

底层 KV memory、KV 存储格式和相关 API 由 `llama.cpp-omni` 提供。EdgeOmni 拟实现的是 Runtime 层的 token LCP、KV 保留/回滚、生命周期、失效策略、观测合同和实机验证；不得包装成自研通用 KV Cache、Paged Attention 或多用户缓存。

## 总体执行顺序

| ID | 优化线 | 当前状态 | 主指标 | 招聘价值 | 进入条件 |
| --- | --- | --- | --- | --- | --- |
| OPT-1 | 真实 `MtmdBackend` Prefix Reuse | **VALIDATED** | Prefill、TTFT、hit tokens | 最高：Runtime 状态管理与正确性 | main 合入前复核；120 分钟/故障注入与整合后续独立进行 |
| OPT-2 | Nsight 驱动 decode 优化 | **PLANNED** | token/s、TPOT、GPU timeline | 高，但最终提速不确定 | OPT-1 数据稳定后 |
| OPT-3 | 多分辨率 VLM 权衡 | **PLANNED** | image tokens、vision latency、质量 | 中高：端侧视觉资源策略 | 先冻结质量集 |
| OPT-4 | RAG/HTTP/图片解码小开销 | **MEASURE FIRST** | 分阶段延迟、占比 | 中；只优化已证明瓶颈 | profiling 显示值得做 |

一次只改变一个主要变量。四条线使用独立实验 commit/branch和报告，不能把多个改动合并后归因给其中一项。

## OPT-1：真实 MtmdBackend Prefix Reuse

### 目标与非目标

目标是在 Qwen2.5-VL 的 **text-only** 请求上复用同一 hot session 的 token 前缀，降低长 prompt 的 `prefill_ms` 和 `ttft_ms`。任意单图请求都主动失效并在结束后保持 cold，避免视觉 embedding 或位置状态被文本请求错误复用。

第一阶段不整合 Agent/RAG session，不实现多 session、LRU/TTL、跨进程持久化或图像 KV reuse。先通过专用 Runtime workload 证明机制和收益；通过整合门后再设计 Agent session 到 Runtime session 的映射。

### 设计

当前实现已落在 `runtime/src/mtmd_backend.cpp`，由 `RuntimeConfig.prefix_reuse_mode` 控制；默认值和现有公开配置均为 `disabled`。`single_hot_text` 只通过显式配置启用。709-token Q4 exact prompt 已有 reviewed Prefill/TTFT 收益；该收益不外推到其他输入或会话模型。

本地检查入口：

```bash
cmake -S . -B build-runtime -DEDGEOMNI_BUILD_TESTS=ON -DEDGEOMNI_BUILD_INTEGRATION=OFF
cmake --build build-runtime -j"$(nproc)"
ctest --test-dir build-runtime --output-on-failure
python3 -m unittest discover -s tests/unit -p 'test_*.py'
```

Jetson 实测入口（需模型、MMProj 和已构建 Runtime）：

```bash
scripts/run_jetson_benchmark.sh --config configs/assistant.json \
  --label opt1-q4-disabled --repeats 30 --max-new-tokens 128
scripts/run_jetson_benchmark.sh --config configs/assistant-prefix-single-hot.json \
  --label opt1-q4-single-hot --repeats 30 --max-new-tokens 128
```

文本 benchmark 使用固定的 `benchmark-prefix-session` 发送连续请求，才能测到同一 hot session 的 LCP；单图 benchmark 仍使用独立诊断请求，不复用视觉 KV。

上述命令只产生 raw evidence；在复制 protocol 字段、检查 cold/hot 输出一致性和缓存失效场景前，结果必须保持 `UNREVIEWED`。709-token exact-prompt 的 correctness 和 Prefill/TTFT，以及 branch、session/image/timeout/cancel/reset 失效恢复，均已完成 reviewed Jetson 实测；RAM 长稳和更广泛 workload 仍为**待实测**。

实验配置应提供 `disabled` 与 `single_hot_text` 两种模式，使 A/B 使用同一代码和二进制，仅改变显式配置。

状态机：

```text
Cold
  -> 成功 text-only 请求 + session_id -> Hot(prompt tokens + prompt KV)

Hot
  -> 同 session：计算 LCP，删除分叉后的 KV，只 prefill miss tokens
  -> session 改变：clear -> cold request
  -> 任意图片：clear -> image request -> clear
  -> reset/shutdown/config change：clear

请求成功
  -> 删除生成 token KV，只保留完整 prompt KV

cancel/timeout/prefill/decode/rollback failure
  -> clear metadata + llama memory -> Cold
```

实现步骤：

1. 从 text-only `mtmd_input_chunks` 取得并拼接 `llama_token`。
2. 保存一个 hot session 的 `session_id`、prompt tokens、模型/模板/Runtime 配置 fingerprint。
3. 计算新旧 token LCP，并向下对齐到完整 cold-prefill batch；exact prompt 也重新计算最后一个完整或尾部 cold batch，保持产生 logits 的 batch 形状。
4. 使用上游 `llama_memory_seq_rm()` 删除 `[aligned LCP, end)`，从对齐后的 LCP 开始构造 text batch。
5. 成功生成后删除 `[prompt_tokens, end)`，保留完整 prompt KV。
6. 将所有异常路径汇入统一 `clear_hot(reason)`；同步 llama context 后再修改 memory。
7. 图片请求无条件标记 `image_request` 并清空；第一阶段不复用图像 embedding。
8. 输出 `cache_hit_tokens`、`cache_miss_tokens`、`cache_hit_ratio`、`prefill_input_tokens` 和 `cache_invalidation_reason`。

### 正确性门

- Exact hot 输出与相同 prompt 的 cold 输出逐字一致。
- Branch hot 输出与相同分叉 prompt 的独立 cold 输出一致。
- `hit + miss == prompt_tokens`，LCP 不超过真实公共 token 前缀。
- session 切换、图片、reset、cancel、timeout、callback disconnect 和 decode failure 后下一次请求为 cold。
- 连续请求没有上下文污染、KV 越界或 RAM 持续增长。
- disabled 模式维持 `d11617e` cold 行为，不产生隐式缓存。

任何一项未通过时不得进入正式性能报告。

真实 Runtime 的失效矩阵由 `scripts/validate_mtmd_prefix_reuse.py` 执行。它从 disabled/hot Runtime 配置读取并比对 `batch_tokens`，在独立 Runtime 进程间比较 cold/exact/branch 输出；exact/branch 的实际 `prompt_tokens < batch_tokens` 时要求零 hit、全量 miss 并分类为 `PASS_EXPECTED_NO_REUSE`，达到 batch 时要求正 hit 并分类为 `PASS_REUSE`。JSON 结果记录 batch 与两条分类。在 hot Runtime 内它仍验证 session switch、单图请求、timeout、HTTP cancel 和 `POST /v1/context/reset` 后下一文本请求为 cold。该 reset 路由只允许服务空闲时调用；它是实验和运维诊断接口，不是多用户会话 API。

```bash
python3 - <<'PY'
from pathlib import Path
source = Path('/tmp/edgeomni-opt1/p256.txt').read_text(encoding='utf-8')
Path('/tmp/edgeomni-opt1/t709-branch.txt').write_text(
    source + ' Branch-specific final instruction: state only the observed alarm.', encoding='utf-8')
PY

sudo jetson_clocks
sudo -v
python3 scripts/validate_mtmd_prefix_reuse.py \
  --prompt-file /tmp/edgeomni-opt1/p256.txt \
  --branch-prompt-file /tmp/edgeomni-opt1/t709-branch.txt \
  --output benchmarks/results/opt1-t709-correctness.json
```

`PASS` 只说明这一次 Runtime correctness matrix 通过。输出 JSON 是 local raw evidence，仍需绑定 clean commit、模型 hash 和运行日志后才能支持对外声明。

长度矩阵与长稳验证（已在实验分支 `VALIDATED`）：`generate_opt1_prompts.py` 的 256/512/1024/2048 仅是 tokenizer 级 `user_prompt_tokens`，不能称为 HTTP Runtime 长度。disabled 校准得到实际 `runtime-p264`、`runtime-p520`、`runtime-p1032`、`runtime-p2056`；每档 1 warm-up（不计入）+ 30 measured。batch/ubatch=512 是收益下限：264-token 的零 hit 为 `PASS_EXPECTED_NO_REUSE`，只验证 cold-path 正确性，不声称优化收益；520/1032/2056 为 `PASS_REUSE`。paired 30-minute `runtime-p1032` soak 通过输出 hash、cache/error、stable-clock 和 duration gates；其资源趋势仅为观测，不能证明或否定 KV leak。见 `benchmarks/opt1-q4-length-matrix-20260814.md` 和 `benchmarks/opt1-q4-soak-20260817.md`。120 分钟 soak、故障注入、RAG LCP 分布和 Agent/RAG 映射仍待完成。

Soak 使用 `run_opt1_soak.py --minutes 30`（可选 120）分别运行 disabled 和 single-hot；Runtime ready 与 warm-up HTTP 200 后才开始计时。默认拒绝 dirty worktree、动态时钟和端口复用；显式允许时只能标记 `EXPLORATORY_UNREVIEWED`。raw 记录 commit、资产/config/prompt hash、可比 Runtime 参数、clocks、UTC 时间、请求时长、warm-up、失败原因和完整日志；异常仍保留已收集 raw。单侧 soak 审核要求输出 hash 唯一、disabled 零 hit、single-hot 默认 100% 正 hit 和完整 accounting。正式 paired 结论必须再经 `audit_opt1_soak_pair.py`：两侧都必须是 formal raw、provenance/Runtime 参数/clock 一致、duration 充分、response shape 和唯一 output hash 跨模式一致。它还报告 tegrastats 前/后 20% RAM 中位数与峰值作为短时资源趋势；统一 RAM、温度和该趋势都只是资源观测，不能单独证明或否定 KV leak。

### 性能协议

- Q4 作为主部署模型；Q8 只在 Q4 机制稳定后做有限对照。
- prompt 长度覆盖 256、512、1024、2048 tokens。
- 场景覆盖 cold、exact、branch、session switch、image invalidation 和 failure recovery。
- 每组至少 1 次 warm-up + 30 次配对测量；MODE_30W、固定 clocks、同 commit、同输入。
- 主指标：`prefill_ms`、`ttft_ms`、hit/miss tokens、hit ratio、Runtime total。
- 约束指标：输出一致性、decode token/s、RAM 首末/峰值、错误率和恢复结果。
- 额外记录真实 RAG prompt 的 LCP 分布；人工高复用 prompt 的收益不能直接代表 RAG 实际收益。

不预先承诺具体降幅。只有 clean-commit raw evidence 审核后才能填写结果。

### 整合门

OPT-1 只有同时满足以下条件才考虑回到主线：正确性门全部通过；长 prompt 上有可重复 Prefill/TTFT 收益；cold 路径无明显回退；异常恢复可证明；文档保留“单热、text-only、上游 KV API”边界。

## OPT-2：Nsight 驱动的 decode token/s 优化

该路线先做归因，不先改参数。用 Nsight Systems 观察稳态 decode 的 CUDA kernel、CPU sampling、同步、launch gap 和 memcpy；仅当证据定位到 EdgeOmni 或可维护的固定上游 patch 时才实现优化。

步骤：

1. 冻结 Q4、128/512 output-token workload 和功耗/时钟。
2. 采集未启用 profiling 的基线，量化 profiling overhead。
3. 用 NVTX 或稳定请求边界标记 prefill/decode，采集 Nsight Systems timeline。
4. 若为 kernel/带宽瓶颈，再用 Nsight Compute 针对少量代表 kernel 深挖。
5. 形成“证据 -> 假设 -> 单一改动 -> A/B -> 正确性/资源回归”闭环。

只调整 threads、batch/ubatch、Flash Attention 或 GPU layers，应称为 Jetson 参数调优。没有 profiling 和代码归因时，不宣称自研推理优化；若瓶颈完全属于上游且没有可靠改动，也允许以“无可归因优化”结束该路线。

## OPT-3：多分辨率 VLM 性能/质量权衡

目标不是证明低分辨率更快，而是建立：

```text
输入像素 -> image tokens -> vision encode/embedding/TTFT -> RAM/rail -> 事实正确率
```

先准备版权明确、与调参集隔离的小型真实设备图质量集，冻结可观察事实、文字/故障码可读性和拒答预期。随后比较多档输入分辨率或视觉 token 预算。保持模型、prompt、采样和 Runtime 配置不变，并同时报告性能与质量；不能用放大的合成图冒充质量实验，也不能只发布最快档位。

## OPT-4：RAG、HTTP 与图片解码

先增加端到端分阶段测量：query embedding、SQLite/FTS、向量/融合门禁、prompt 组装、JSON encode/decode、loopback HTTP、Runtime queue/service 和模型推理。

只有某阶段在目标 workload 中占比显著且可重复时才优化。当前固定 608-byte PNG 的 preprocessing 为 `0 ms measured`，HTTP 相对约 1.5 秒单图推理也很小，因此它们不是现阶段主优化目标。RAG 优化还必须保持检索结果、引用和拒答行为，不能用降低质量换取未披露的延迟收益。

## 分支、证据与更新规则

推荐分支：

```text
main                         # d11617e 及后续文档更新，公开基线不回写未验证数字
experiment/mtmd-prefix       # OPT-1
experiment/nsight-decode     # OPT-2
experiment/vlm-token-budget  # OPT-3
```

原始 trace、JSONL、模型、日志和私有图片保持 Git-ignored。公开报告只提交审核后的聚合值、协议、环境字段和 raw artifact SHA-256。每个实验必须记录：baseline commit、experiment commit、唯一变量、有效/排除样本、pass/fail/skip、Jetson 状态和结论边界。

状态只使用：`PLANNED`、`IN_PROGRESS`、`BLOCKED`、`VALIDATED`、`REJECTED`、`INTEGRATED`。`VALIDATED` 只表示独立实验通过；只有进入 main 且重新跑公开验证后才能标记 `INTEGRATED`。

## 决策记录

| 日期 | 决策 | 状态/证据 |
| --- | --- | --- |
| 2026-08-13 | 冻结 `d11617e` 为公开作品集基线；不把它称为生产版本 | 已有 reviewed 文本/单图报告，main clean |
| 2026-08-13 | 第一深入方向选择真实 `MtmdBackend` text-only Prefix Reuse | 已实现；exact-prompt 已实测，完整正确性矩阵待完成 |
| 2026-08-13 | 在实验分支实现显式 `disabled/single_hot_text` 配置、mtmd 文本 token LCP、KV 回滚和失效策略 | 本地 CMake/CTest 与 709-token exact-prompt Jetson 配对通过 |
| 2026-08-13 | Q4 短 prompt 首轮 disabled/single-hot 配对 | 后续长 prompt 正确性失败，报告已 RETRACTED，不作为性能证据 |
| 2026-08-13 | 709-token exact prompt 暴露 one-token rollback 数值偏差 | disabled 输出 22 tokens，hot 输出 11 tokens；暂停扩大 benchmark |
| 2026-08-13 | Prefix reuse 改为只保留完整 cold-prefill batch，并重算最后一个 cold batch | 709-token prompt 实测命中 512、重算 197；跨模式输出一致 |
| 2026-08-13 | batch-boundary 修复完成 709-token clean-commit 配对复验 | 30/30 每组成功且跨模式输出一致；Prefill 中位数 978 -> 84 ms，TTFT 1330 -> 439 ms；见 reviewed OPT-1 报告 |
| 2026-08-13 | 独立 Runtime correctness matrix 通过 | exact/branch 输出匹配 cold；session、image、timeout、cancel、reset 后文本 KV 均 cold；见 `benchmarks/opt1-t709-correctness-20260813.md` |
| 2026-08-13 | Agent/RAG session 映射暂不整合，先用专用 Runtime workload 验证 | 避免同时改变 Runtime 与应用生命周期 |
| 2026-08-13 | Nsight、多分辨率和小开销优化排在 OPT-1 之后 | 避免多变量和错误归因 |
| 2026-08-17 | OPT-1 实验分支收口为 VALIDATED | 四档 Runtime-length matrix 与 paired 30-minute soak 通过；不代表 main INTEGRATED、生产缓存或 SLA |
