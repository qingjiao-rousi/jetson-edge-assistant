# Qwen3 M6.2 量化工件本地审计

审计状态：只读完成（Q8_0 provenance 已补齐）。未下载、未生成/转换/量化模型，未修改 Runtime，未运行模型或 benchmark。

结论状态仅使用 `READY`、`MISSING`、`REJECTED`、`PENDING_PROVENANCE`。

## 搜索范围与方法

对项目 `models/` 执行文件名搜索，结果有两个 Qwen3 GGUF：

```text
models/Qwen3-4B-Q4_K_M.gguf
models/Qwen3-4B-Q8_0.gguf
```

SHA-256 使用本地文件完整内容计算。GGUF metadata 使用 GGUF v3 header/KV 只读解析；没有调用
`llama_init_from_model`、`llama_decode` 或任何推理路径。解析结果与
`manifests/deployment-baseline-v1.json`、`manifests/model-selection.json` 交叉核对。

## 工件审计

| 工件 | 状态 | 路径/标识 | 大小 | SHA-256 | 结论 |
| --- | --- | --- | ---: | --- | --- |
| Q4_K_M | READY | `models/Qwen3-4B-Q4_K_M.gguf` | 2,497,280,256 bytes | `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5` | 可进入 benchmark |
| Q8_0 | READY | `models/Qwen3-4B-Q8_0.gguf` | 4,280,404,704 bytes | `8c2f07f26af9747e41988551106f149b03eb9b5cb6df636027b6bf6278473300` | metadata 与 provenance 均通过，可进入 benchmark |
| F16 | MISSING | 配置要求 `Qwen3-4B-F16.gguf` 工件；本地无对应 Qwen3 GGUF | null | null | 等待手动提供，不下载 |
| BF16 | MISSING | 配置要求 `Qwen3-4B-BF16.gguf` 工件；本地无对应 Qwen3 GGUF | null | null | 等待手动提供，不下载 |

F16/BF16 的文件名仅是配置中的精确工件标识；本次没有从远端推断实际命名、revision 或
hash。它们仍然缺失，不能进入 benchmark。Q8_0 文件已存在并完成本地 hash/metadata 复核；
用户提供的 Xet Pointer Details 补充了远端 Xet hash、远端大小、SHA-256、文件名和固定 revision，
完成了 provenance 门禁。

## Q4_K_M metadata

| 字段 | 实际值 |
| --- | --- |
| GGUF magic/version | `GGUF` / v3 |
| tensor count | 398 |
| `general.architecture` | `qwen3` |
| `general.name` | `Qwen3 4B Instruct Awq` |
| `general.size_label` | `4B` |
| `general.file_type` | 15 (`Q4_K_M`) |
| `general.quantization_version` | 2 |
| `qwen3.context_length` | 40960 |
| `qwen3.block_count` | 36 |
| `tokenizer.chat_template` | 存在，4100 UTF-8 bytes |
| chat template SHA-256 | `57f1fd00f0013a2be96aa79b857391f27e23df5b5f847072b524c897e24d0361` |

模板 hash 与 M6.1 配置及 M5.2 renderer 门禁一致。模板包含 `enable_thinking=false` 的空
`<think>\n\n</think>\n\n` 分支，因而与固定 reasoning-off 基线兼容。完整来源为
`Qwen/Qwen3-4B-GGUF` revision `a9a60d009fa7ff9606305047c2bf77ac25dbec49`，该 provenance
由 deployment baseline 记录；文件 hash 与大小也与 baseline 和 model-selection manifest 一致。

## 准入判定

Q4_K_M 满足：同一 Qwen3 系列、来源/revision 可追溯、hash 已记录、GGUF metadata 可解析、
tokenizer/chat template 存在且与基线兼容，因此状态为 `READY`。

## Q8_0 metadata 与来源门禁

| 字段 | 实际值 |
| --- | --- |
| GGUF magic/version | `GGUF` / v3 |
| tensor count | 398 |
| `general.architecture` | `qwen3` |
| `general.name` | `Qwen3 4B Instruct` |
| `general.size_label` | `4B` |
| `general.file_type` | 7 (`Q8_0`) |
| `general.quantization_version` | 2 |
| `qwen3.context_length` | 40960 |
| `qwen3.block_count` | 36 |
| `tokenizer.chat_template` | 存在，4100 UTF-8 bytes |
| chat template SHA-256 | `57f1fd00f0013a2be96aa79b857391f27e23df5b5f847072b524c897e24d0361` |

Q8_0 与 Q4_K_M 的 architecture、size label、context length、block count、quantization version
和 chat-template hash 兼容；文件 hash 和大小已记录。GGUF metadata 仅包含
`general.basename=Qwen3`/`general.finetune=Instruct`，不包含 source repo、revision 或 license。
用户提供的 provenance 证据为：source repo `Qwen/Qwen3-4B-GGUF`、revision
`a9a60d009fa7ff9606305047c2bf77ac25dbec49`、Apache-2.0、Xet hash
`c8aa2cf6a726855a9edbe70f6e372d351c51a48a69bfceecb070fe1d22b88f17`、远端 SHA-256 与本地
SHA-256 相同、远端大小约 4.28 GB。因此 Q8_0 状态更新为 `READY`，可进入 M6 benchmark。

F16/BF16 状态仍为 `MISSING`；不计入 M6.1 性能矩阵，也不改变已冻结的 Q4_K_M 主模型。

## 复核记录

本次完成：本地文件搜索、Q8_0 完整 SHA-256、两份 Qwen3 GGUF metadata 读取、deployment
baseline/model-selection 一致性核对、JSON manifest 更新和 `git diff --check`。没有执行模型加载、
KV 初始化、CUDA、tegrastats 或 benchmark。Q8_0 provenance 已由用户提供证据补齐；F16/BF16
仍为 `MISSING`，不进入 benchmark。
