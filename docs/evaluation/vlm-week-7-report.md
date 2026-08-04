# 第七周 VLM 周报

日期：2026-07-30。第七周完成了 Qwen2.5-VL-3B 的资产冻结、CLI context 冒烟、长上下文合成输入验证，以及 EdgeOmni Runtime Adapter 到 HTTP/SSE 单常驻服务的三图端到端冒烟。本周证据均为固定资产、固定 Runtime 与单次或单 suite 执行事实；不构成稳定性、并发能力、平均性能或 Jetson 生产部署结论。

## 本周结论

- 主 VLM 候选冻结为 `Qwen2.5-VL-3B-Instruct Q4_K_M` 与 `Qwen2.5-VL-3B-Instruct Q8_0 mmproj` 配对。两个本地 GGUF 的文件大小、SHA-256 和 metadata binding 均已校验。
- 默认开发 context 保持 `8192`。它已完成固定短 prompt 单图、合成长手册加单图、以及单常驻服务三图顺序请求的事实验证。
- `16384` 完成一次 host-CUDA recovery 冒烟，只作为实验事实保留，不改变 `8192` 默认选择。`32768` 未执行且继续禁用。
- EdgeOmni 已具备纯内存单图 VLM 输入、资产校验、MtmdBackend、HTTP JSON 图片传输及 SSE `metadata -> token* -> done` 服务路径。

## 资产与候选

| 项目 | 冻结值 | 状态 |
| --- | --- | --- |
| Runtime | `third_party/llama.cpp-omni@19cc26967140407efe34006a355ab445b35b16ac` | 固定 |
| 主模型 | `models/Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf`，`1929901056` bytes，SHA-256 `d02fe9b69ad8cadbbd228e387667af66612c44bed29ffc8eb1e7caf9ac486c12` | 已验证 |
| 视觉组件 | `models/mmproj-Qwen2.5-VL-3B-Instruct-Q8_0.gguf`，`844757728` bytes，SHA-256 `980c9b2f78c04e6cff93d277ada09e768394f112d75db3b4e9dea8a69f9fb904` | 已验证 |
| 主候选 | Qwen2.5-VL-3B Q4_K_M + Q8_0 mmproj | 已冻结 |
| 第二候选 | Qwen2.5-VL-7B Q4_K_M | 仅远程审计，不是自动 Runtime fallback |
| 文本 fallback | Qwen3 文本模型 | 与 VLM 第二候选分离 |

主模型为 GGUF v3、`qwen2vl`、Q4_K_M（`general.file_type=15`）、434 tensors；mmproj 为 GGUF v3、`clip` / `clip-vision`、Q8_0（`general.file_type=7`）、519 tensors，projector 为 `qwen2.5vl_merger`。mmproj projection dimension `2048` 与主模型 embedding length `2048` 一致。详细 metadata、远程来源 revision 和许可证记录见 [M7.2b 资产冻结](vlm-baseline-selection-m7.2.md)。

模型 metadata 中的 `qwen2vl.context_length=128000` 仅为资产声明，未作为 Jetson 可部署长度结论。

## Context 验证

| Context | 工作负载 | 结果 | 关键直接证据 |
| ---: | --- | --- | --- |
| 4096 | 单图短 prompt CLI 冒烟 | 成功 | exit `0`；37/37 CUDA offload；391 image tokens；KV `144 MiB` |
| 8192 | 单图短 prompt CLI 冒烟 | 成功 | exit `0`；37/37 CUDA offload；391 image tokens；KV `288 MiB` |
| 8192 | 合成长手册加单图 CLI | 成功 | exit `0`；6735 prompt tokens；391 image tokens；严格 JSON 四项答案通过 |
| 16384 | 合成长手册加单图 recovery CLI | 成功 | 第二次且最后允许的 attempt；exit `0`；13702 prompt tokens；391 image tokens；KV `576 MiB`；严格 JSON 四项答案通过 |
| 32768 | 未执行 | 禁用 | 风险验证档，不承诺部署 |

4096、8192 和 16384 的原始 CLI 证据分别见 [M7.3R](vlm-qwen25-3b-smoke-m7.3.md)、[M7.4A](vlm-qwen25-3b-context-8192-m7.4a.md)、[M7.4B](vlm-qwen25-3b-long-context-8192-m7.4b.md) 与 [M7.4C-R](vlm-qwen25-3b-long-context-16384-m7.4c-r.md)。本周未对这些单次执行计算性能百分比或平均值。

## 失败与恢复

16384 的首次 M7.4C attempt 未进入 prompt eval 或 decode。直接原因是受限执行沙盒隔离了 `/dev`，导致 `ggml_cuda_init` 无法初始化 CUDA，KV 落在 CPU。该 attempt 没有取得模型 child exit code 或输出，不能被归类为模型 OOM、16384 context 不可用或性能失败。

M7.4C-D 对主机进行了只读 CUDA 审计：Jetson R36.4.7、NVIDIA 540.4.0、设备节点和 `CUDA0: Orin` 均正常，且没有遗留 llama 或 tegrastats 进程。随后 recovery runner 在可见 GPU 的主机执行环境中完成一次、也是最后允许的一次 16384 attempt。恢复执行成功不抹除首次失败证据，也不增加第三次尝试。

## Runtime Adapter 与服务

M7.5A 建立 `ImageInput`、单图限制、JPEG/PNG/WebP 内存图片门禁、regular-file/size/流式 SHA-256 资产校验和明确 model/mmproj binding。图片不通过路径传给 Adapter；调用方声明尺寸不作为安全依据。

M7.5B 将该 contract 接入冻结的 `libmtmd`：模型 chat template、mtmd chunk 注入和 image token 均由实际 Runtime 路径直接读取。MtmdBackend 仅允许一个 active request，并在终止路径清理 LLM KV。M7.5B 的一次 Adapter 驱动单图冒烟成功，模型 37/37 layers offload 至 CUDA0。

M7.5C-R 完成一个常驻 MtmdBackend/RuntimeService 进程的三次顺序独立 HTTP/SSE 图像请求：

| 请求 | Image tokens | Prompt tokens | Output tokens | 结果 |
| --- | ---: | ---: | ---: | --- |
| `new-york-times` | 391 | 415 | 67 | 成功，输出包含 `The New York Times` |
| `synthetic-alarm` | 77 | 96 | 79 | 成功 |
| `synthetic-device` | 77 | 96 | 20 | 成功 |

服务仅启动一次，`inference_run_count=3`、`retry_count=0`、child exit code 为 `0`。三次事件均通过 `metadata -> token* -> done` 顺序验证。全部请求使用 8192 context，KV 为 `288 MiB`，并有 37/37 CUDA offload 证据。完整事实与原始目录见 [M7.5C-R](vlm-qwen25-3b-service-image-suite-m7.5c.md)。

## 质量与可观测性边界

- 固定图片和合成 fixture 不含真实客户信息；合成长手册不是 RAG、实际多轮 session 或生产手册质量评测。
- timing 只记录 Runtime 或 CLI 直接给出的值。没有独立输出的 image position、vision 或 embedding 字段为 `null` 并附 measurement status，不倒推估算。
- M7.5C-R 的 50 个 telemetry 样本中，峰值 UMA 为 `11971 / 30697 MB`、峰值 GR3D 为 `99%`、峰值温度为 `57.343 C`。这些是单一 suite 的原始观测，不代表热稳、功耗预算或容量保证。
- 本周未下载模型、未修改上游 Runtime 源码、未修改冻结的 M6 benchmark 结果，也未提交 git commit。

## 下周入口

下一阶段可进入 M8.1：将已验证的单图 HTTP/SSE VLM service 接入上层应用 API，并以离线契约测试验证请求转换、稳定错误映射、SSE 顺序和敏感图片数据不泄露。该阶段不应自动扩大到并发压测、16384/32768、RAG、Agent、多 session、音频或生产部署结论。
