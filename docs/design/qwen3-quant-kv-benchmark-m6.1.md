# M6.1 Qwen3 主模型量化、KV Cache 与性能评测协议

状态：DESIGN ONLY。未下载模型、未修改 Runtime、未启动正式 benchmark。本协议只覆盖固定 Qwen3 文本模型和 frozen Runtime，不覆盖 VLM、RAG、Agent 或 Docker。

## 1. 冻结对象与门禁

主基线是 `models/Qwen3-4B-Q4_K_M.gguf`，SHA-256 为
`7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5`；Runtime 为
`third_party/llama.cpp-omni` 的 `jetson-runtime-dev@19cc269`。Q4_K_M 的权重类型编号由
`LLAMA_FTYPE_MOSTLY_Q4_K_M=15` 定义（`third_party/llama.cpp-omni/include/llama.h:117-149`）；
同一 ABI 也定义 Q8_0、F16、BF16 文件类型；loader 读取 `general.file_type`
（`third_party/llama.cpp-omni/src/llama-model-loader.cpp:776`）。公开量化接口存在
`llama_model_quantize()`（`include/llama.h:404-420,633-637`），但本协议**不授权本轮量化或
生成任何 GGUF**。

每个候选（Q4_K_M、Q8_0、F16、BF16）在 preflight 前必须同时满足：文件本地存在；完整
SHA-256 已写入本次 run manifest；GGUF `general.architecture=qwen3`；`general.file_type` 与
候选类型一致；`tokenizer.chat_template` 的 SHA-256 为冻结
`57f1fd00f0013a2be96aa79b857391f27e23df5b5f847072b524c897e24d0361`；并记录
`general.name`、`general.size_label`、GGUF version、文件字节数和 runtime commit。可经
`llama_model_meta_val_str()` 读取 string metadata（`include/llama.h:580-605`），但数值
`general.file_type` 应由离线 GGUF reader/metadata dump 记录原值。任何候选缺失、hash 不符或
模板不符记为 `preflight_unavailable`，不下载、不补造，也不计入性能统计。

## 2. 当前 fork 能力审计

冻结 CLI 的实际 `--help` 已确认：`--ctx-size`（默认 0 使用模型 context）、`--batch-size`
（logical）、`--ubatch-size`（physical）、`--flash-attn on|off|auto`、`--gpu-layers`、
`--kv-offload/--no-kv-offload` 与 `--cache-type-k/v`。对应解析在
`third_party/llama.cpp-omni/common/arg.cpp:1267-1298,1375-1382,2042-2066,2341-2352`。

公开 `llama_context_params` 同样具有 `n_ctx`、`n_batch`、`n_ubatch`、`flash_attn_type`、
`type_k`、`type_v` 字段（`third_party/llama.cpp-omni/include/llama.h:335-372`），模型参数有
`n_gpu_layers`（`include/llama.h:291-305`）。当前 common/CLI 可接受的 K/V cache type **仅**为
`f32,f16,bf16,q8_0,q4_0,q4_1,iq4_nl,q5_0,q5_1`
（`third_party/llama.cpp-omni/common/arg.cpp:397-415`）；本协议只测 `f16/f16`、`q8_0/q8_0`
与可选 `q4_0/q4_0`，不把 ggml enum 的其他类型误称为 CLI 可配类型。

DirectBackend 目前把 RuntimeConfig 的 context/batch/ubatch/GPU layers/Flash Attention 映射到
公开 context/model 参数（`runtime/src/direct_backend.cpp:132,150-158`），但没有把 `type_k/type_v`
暴露为 RuntimeConfig。因此 M6.1 的 KV sweep 在 CLI 参考路径执行；未来 DirectBackend 扩展必须
显式增加受控 KV config 和同等 metadata/run record，不能暗中采用 common API。

KV cache 会按 K/V tensor type 创建并在初始化日志报告 backend buffer、cells/layers/seqs 和 K/V
MiB（`third_party/llama.cpp-omni/src/llama-kv-cache.cpp:211-212,269-282`）。默认公开 context
params 是 F16/F16（`src/llama-context.cpp:3357-3358`）。开启 Flash Attention 时，量化 K/V 有
head dimension/block-size 可用性检查；量化 V 在 Flash Attention 关闭时直接被拒绝
（`src/llama-context.cpp:3412-3436`）。任何不支持组合以
`unsupported_kv_flash_attention` 失败记录，不自动改为另一组参数。

## 3. 比较矩阵和固定配置

比较分两阶段，避免把权重量化差异、KV 类型差异和 workload 混为同一结论。

| 阶段 | weights | KV K/V | workload | 目的 |
| --- | --- | --- | --- | --- |
| A 权重量化 | Q4_K_M、Q8_0、F16、BF16（仅现存且通过门禁） | f16/f16 | S、L、G | 量化对性能、资源和固定任务输出的影响 |
| B KV cache | 固定 Q4_K_M | f16/f16、q8_0/q8_0、q4_0/q4_0（可用时） | L，另加 context sweep | KV 内存/长 prompt trade-off |
| C 容量边界 | 固定 Q4_K_M | B 阶段可用项 | 4k、8k、16k、32k context | OOM/稳定性边界；不是质量排名 |

固定值：`context=4096`（A/B 默认）、`batch=512`、`ubatch=512`、`gpu_layers=99`、Flash
Attention=`on`、KV offload=`on`、`n_parallel=1`、`reasoning=off`、seed=`424242`、top_k=`1`、
top_p=`1.0`、min_p=`0.0`、temperature=`0.0`。Jetson 功耗模式沿用部署基线的
`MODE_30W`/ID 2；每 run 记录实际 `nvpmodel -q` 输出、风扇/环境说明和时钟条件，不把预期值
当作观测结果。任何参数变更创建新的 protocol revision，不与本矩阵汇总。

任务固定为同一 Qwen3 `enable_thinking=false` ChatTemplateRenderer 语义：

| ID | 输入/输出目标 | `max_new_tokens` |
| --- | --- | ---: |
| S 短入短出 | 实测渲染后 45 prompt tokens；配置门禁范围 40--50；固定设备状态问答 | 32 |
| L 长入短出 | 约 2048 prompt tokens；确定性重复的设备日志模板 + 同一问答 | 32 |
| G 短入长出 | 实测渲染后 59 prompt tokens；配置门禁范围 55--65；固定结构化诊断说明 | 256 |

Run manifest 必须保存每个完整 prompt、渲染后 prompt SHA-256、token 数、预期最大输出和实际
输出 SHA-256。L 的原始日志文本由 runner 根据配置中的固定 template/repeat count 生成，并在
开始前验证 token count 落入目标范围；不得将不同实际 prompt token 数合并为同一组吞吐统计。

每个 cell 先做 1 次独立 preconditioning（仅检查可运行，不统计），之后做 5 次有效重复。每次
重复是新的进程/新的模型初始化，单独目录保存 argv、stdout、stderr、runtime JSON、telemetry
原始日志与结果 JSON；顺序应以固定 seed 随机化并保存顺序，避免温度漂移与某一候选绑定。

## 4. 时间与吞吐的正式定义

| 指标 | 正式定义 |
| --- | --- |
| model_ready_ms | `initialize` 开始至模型/context 成功可接受请求；每个独立进程 run 单独记录，不混入 request latency。 |
| prefill_ms | renderer/tokenize 完成后，首个 prompt batch decode 开始至全部 prompt token prefill 完成。 |
| decode_ms | 首次 sampling 开始至 generation loop 返回；保留 Runtime 已有定义。 |
| Runtime first_token_ms | `generate_text` 入口至首个可交付 token callback；是本地时间，不是正式 TTFT。 |
| 服务 TTFT | HTTP request accepted monotonic timestamp 至首个 token 字节成功写入/flush client；仅服务模式报告。 |
| TPOT | 服务首 token 成功写入至最后一个 token 成功写入的差值除以 `max(output_tokens-1,1)`；无输出为 null。 |
| Prompt tokens/s | `prompt_tokens / (prefill_ms / 1000)`；`prefill_ms=0` 记 null。 |
| Decode tokens/s | `output_tokens / (decode_ms / 1000)`；与 Runtime `decode_tokens_per_second` 对照但以原始字段复算。 |

DirectBackend 的 `model_ready_ms` 写入每个 response（`runtime/src/direct_backend.cpp:184-190`）；
prefill 由 batch decode 循环计时（`267-309`）；首 token 在 callback 前记录（`356-366`）；decode/total
在 request 尾部记录（`394-403`）。服务已有独立 `service_ttft_ms/service_tpot_ms`，以成功 sink
write 为边界（`runtime/src/service.cpp:129,136`）。因此报告必须把 Runtime local
`first_token_ms` 与服务 TTFT 分列，不能互相替代。

## 5. UMA、KV 与 tegrastats

Jetson 是 UMA；模型、CUDA buffer、KV cache 和进程其他分配共同消耗系统 RAM，不能把
tegrastats `RAM used` 等同于离散 GPU VRAM，也不能将其全部归因于 KV。每 run 采集启动前/后
RSS（如可用）、Runtime 的 model/KV/output/compute buffer 日志、以及 `tegrastats --interval 1000`
覆盖整个 CLI/request 生命周期。现有解析方式提取 `RAM used/total`、`GR3D_FREQ`、GPU/TJ 温度和
`VDD_GPU_SOC` 峰值（`scripts/benchmark_model_selection.py:313-333`）；`VDD_GPU_SOC` 是 GPU/SOC
rail，不是整机功耗。

每条结果包含：KV reported total/K/V MiB、context cells、K/V type、KV offload 状态、model file
bytes、peak RAM MB、peak GR3D percent、peak GPU/TJ C、peak VDD_GPU_SOC mW、采样条数和 raw log
路径。无 telemetry、无 buffer log 或无有效样本记 null，不填零。

## 6. 失败、输出完整性和统计

失败 run 永远写入 JSONL 和独立目录，但不进入 median/mean/p95 等有效性能统计。每条失败至少有：
`run_id`、阶段/cell、候选 hash、完整 argv、开始/结束 monotonic/wall timestamp、exit code、
`finish_reason`、Runtime error code/message、`failure_class`、输出 token 数、输出 SHA-256、
`output_complete`、telemetry/log 路径及 CUDA/llama error lines。

`failure_class` 枚举：`preflight_unavailable`、`metadata_mismatch`、`template_mismatch`、
`model_load_failed`、`context_limit`、`oom_or_allocation_failed`、`decode_failed`、`timeout`、
`cancelled`、`incomplete_output`、`unsupported_kv_flash_attention`、`telemetry_missing`、`internal`。
若生成达到 `max_new_tokens`，记录 `finish_reason=length` 和 `possible_truncation=true`；它不是成功
完整输出。timeout/cancel/OOM 均不自动重试为成功，最多按同一 cell 追加新 attempt，并独立保留。

汇总同时给出 `attempted`、`valid`、每类失败数量。有效性能统计要求 exit 成功、`finish_reason` 为
`stop` 或预先允许的 `length`、无 Runtime error、输出非空、token/timing 字段一致且 telemetry 存在。
若某 cell 少于 5 次有效重复，只报告样本数和失败表，不作横向结论。

## 7. 报告规则与下一步

主模型选择（Qwen3 相对其他模型的质量/许可/部署决策）已经冻结在
`manifests/deployment-baseline-v1.json`，不得因本协议单项吞吐改写。M6 的量化结论只在同一 Qwen3
权重 lineage 内比较：分别报告“可加载性/内存容量”、“性能/资源”和“固定任务输出”；不把 Q4
更快或 Q8/F16 更大直接写成主模型质量排名变化。

执行前须确认 Q8_0、F16、BF16 工件是否本地存在；缺失即保留矩阵行的 unavailable 状态。M6.2 才可在
确认后实现 runner 或 DirectBackend KV config，本 M6.1 到此停止。

## 8. M6.4a 结果可追溯性门禁

`scripts/benchmark_qwen3_quant_kv.py` 在任何 `--execute` 前均重新读取并 SHA-256 校验本地
Q4_K_M 和 Q8_0。因此即使一次调用只测其中一个权重，`plan.json`、每条 `records.jsonl`、每个
run 的 `record.json`、`summary.csv` 和 `summary.json` 仍绑定同一对实际本地模型，而不是仅引用
asset manifest 的旧记录。GGUF 记录仅包含版本、tensor 数、architecture、file type、quantization
version、context/block count 及 chat-template 的存在性、字节数与指纹；不复制 template 原文。

每个输出都包含同一不可变 `provenance` 和其 canonical JSON SHA-256。它记录主项目与 Runtime
submodule 的 branch/commit/dirty state，脚本与 runner binary SHA-256，config、asset manifest、
deployment baseline manifest SHA-256，以及两份模型的本地 SHA-256、字节数和上述 GGUF metadata。
CSV 以扁平列保留这些字段和每份 GGUF metadata 的 canonical JSON，便于不解析 JSON 的对比工具
筛选。runner 不存在或任何输入无法计算身份时，preflight 失败，不产生一个缺少 provenance 的 plan。

该工具的唯一可执行 KV 路径是 `F16/F16`：M6.3 DirectBackend 尚未公开 K/V type override。每个
产物明确写入该限制。`first_token_ms` 是 Runtime 本地 `generate_text` 的计时；服务 TTFT 仍定义为
HTTP 接收至首个 token 成功写入客户端，两者不得互换。S/L/G 分组继续输出 `complete`、有效 measured
样本数、要求的有效样本数、失败类别和逐次 prompt-token target 门禁结果；任一组不足 5 个有效样本
时，整个结果 `complete=false`。
