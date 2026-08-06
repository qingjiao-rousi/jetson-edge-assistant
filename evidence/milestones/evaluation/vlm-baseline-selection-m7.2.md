# M7.2b VLM 本地资产校验与候选冻结

日期：2026-07-30。结论：`Qwen2.5-VL-3B-Instruct Q4_K_M` 与配套 `Q8_0 mmproj` 的本地文件存在、字节数和 SHA-256 均严格匹配固定来源值，GGUF metadata 已冻结。本文不代表模型已加载、已运行推理或已达到 Jetson 部署要求。

## 审计边界

- 未下载任何模型，未运行推理，未构建 `llama-mtmd-cli`，未修改 Runtime 源码或既有 M6 benchmark 结果。
- 主资产来源为 `ggml-org/Qwen2.5-VL-3B-Instruct-GGUF`，固定 revision `5037fcf163dd95d1e41d1974465f0898ed108ca2`，license `Apache-2.0`。
- 第二候选只做远程审计，仓库固定为 `ggml-org/Qwen2.5-VL-7B-Instruct-GGUF`，revision 固定为 `508edd0afaa66bb9e9f40587acc2184f02daf1f6`；没有下载 7B 文件。
- 2026-07-30 对 Hugging Face API 的只读远程查询因网络连接超时未完成，本机也没有该 7B revision 的缓存 metadata。因此 7B 的精确远程文件名、大小、SHA-256 和 license 不作推断，保持待远程复核。

## 本地文件严格校验

| 角色 | 本地路径 | 预期 / 实际大小（bytes） | 预期 / 本地 SHA-256 | 结论 |
| --- | --- | ---: | --- | --- |
| 主模型 | `models/Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf` | `1929901056` / `1929901056` | `d02fe9b69ad8cadbbd228e387667af66612c44bed29ffc8eb1e7caf9ac486c12` / 相同 | `VERIFIED` |
| mmproj | `models/mmproj-Qwen2.5-VL-3B-Instruct-Q8_0.gguf` | `844757728` / `844757728` | `980c9b2f78c04e6cff93d277ada09e768394f112d75db3b4e9dea8a69f9fb904` / 相同 | `VERIFIED` |

校验顺序为文件存在性、`stat` 字节数、完整本地 SHA-256。两项均通过后才执行 metadata 审计；未触发 `HASH_MISMATCH` 停止条件。

## GGUF metadata

两个文件均使用仓库内 `gguf-py` 读取：

```bash
PYTHONPATH=third_party/llama.cpp-omni/gguf-py \
python3 -m gguf.scripts.gguf_dump --json --no-tensors <file>
```

### 主模型

| metadata | 值 |
| --- | --- |
| `GGUF.version` | `3` |
| `GGUF.tensor_count` | `434` |
| `general.architecture` | `qwen2vl` |
| `general.type` | `model` |
| `general.name` / `general.basename` | `Qwen2.5 VL 3B Instruct` / `Qwen2.5-VL` |
| `general.file_type` | `15`（`Q4_K_M`） |
| `general.quantization_version` | `2` |
| `qwen2vl.context_length` | `128000` |
| `qwen2vl.embedding_length` | `2048` |
| `qwen2vl.block_count` | `36` |
| `tokenizer.ggml.model` / `tokenizer.ggml.pre` | `gpt2` / `qwen2` |
| `tokenizer.chat_template` | 存在；UTF-8 `1017` bytes；SHA-256 `a0bc6f6fc7a29a80017a433e8f03a1cc1236e838a944a2d034295a60c4f2fddb` |

聊天模板正文不在审计文档或 manifest 中复制，只冻结存在性、字节数和摘要。

### mmproj

| metadata | 值 |
| --- | --- |
| `GGUF.version` | `3` |
| `GGUF.tensor_count` | `519` |
| `general.architecture` / `general.type` | `clip` / `clip-vision` |
| `general.name` / `general.basename` | `Qwen2.5 VL 3B Instruct` / `Qwen2.5-VL` |
| `general.file_type` | `7`（`Q8_0`） |
| `general.quantization_version` | `2` |
| `clip.projector_type` | `qwen2.5vl_merger` |
| `clip.has_vision_encoder` | `true` |
| `clip.vision.projection_dim` | `2048` |
| `clip.vision.embedding_length` | `1280` |
| `clip.vision.image_size` / `clip.vision.patch_size` | `560` / `14` |
| `clip.vision.block_count` / `clip.vision.attention.head_count` | `32` / `16` |
| `clip.vision.feed_forward_length` | `3420` |
| `clip.use_silu` / `clip.vision.n_wa_pattern` | `true` / `8` |

绑定关系通过 metadata 冻结：两个文件的 `general.name` 和 `general.basename` 完全一致；mmproj 的 `qwen2.5vl_merger` projector 对应主模型 `qwen2vl` 架构；`clip.vision.projection_dim=2048` 与 `qwen2vl.embedding_length=2048` 相等。当前 fork 还明确包含 `PROJECTOR_TYPE_QWEN25VL` 以及 Qwen2-VL graph 分派（`third_party/llama.cpp-omni/tools/mtmd/clip-impl.h:303-323`、`clip.cpp:878-881`）。这些证据足以冻结资产配对，不等同于 Runtime 加载或推理验证。

## Context 结论边界

远程仓库/模型 metadata 声明以及本地主 GGUF 的 `qwen2vl.context_length` 都记录为 `128000`。该数值只表示模型资产声明的 context 上限，不能直接认定为 Jetson 可部署长度，也不替代显存、KV、图片 token、OOM 和稳定性实测。

项目实测矩阵保持不变：

| context | 用途 | 状态 |
| ---: | --- | --- |
| `4096` | 冒烟 | 仅冒烟基线 |
| `8192` | 默认候选 | 须实测后确认 |
| `16384` | 长手册和多轮图文 | 须实测后确认 |
| `32768` | 风险验证 | 不承诺部署 |

## 候选冻结

| 顺位 | 候选 | 冻结状态 | 说明 |
| ---: | --- | --- | --- |
| 1 | `Qwen2.5-VL-3B-Instruct Q4_K_M` + `Q8_0 mmproj` | `LOCAL_ASSETS_VERIFIED` | 主模型与 projector 本地完整性及 metadata 配对已闭合；后续仍须按 context 矩阵实测。 |
| 2 | `Qwen2.5-VL-7B-Instruct Q4_K_M` | `REMOTE_AUDIT_ONLY` | 固定仓库与 revision；当前 fork 的大模型测试矩阵含该候选（`third_party/llama.cpp-omni/tools/mtmd/tests.sh:104-113`）。远程 API 连接超时，文件级远程 metadata 待复核，不下载。 |
| 3 | `InternVL3-8B-Instruct Q4_K_M` | `THIRD_AUDIT_CANDIDATE` | 保留为第三审计候选；当前 fork 的大模型测试矩阵含该候选（同上）。 |

第二候选不是自动 Runtime fallback，也不因主候选失败而自动加载。Qwen3 是独立的纯文本基线或显式文本 fallback；它与 VLM 第二候选在角色、资产和切换策略上完全分离。旧的 SmolVLM2/Gemma 候选口径不再用于 M7.2b 冻结结果。

完整机器可读记录见 `manifests/vlm-assets-v1.json`。
