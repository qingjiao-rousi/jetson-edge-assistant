# 第七周 VLM 周报

日期：2026-07-30。第七周完成了 Qwen2.5-VL-3B 的资产冻结、CLI context 冒烟、长上下文合成输入验证，以及 EdgeOmni Runtime Adapter 到 HTTP/SSE 单常驻服务的三图端到端冒烟。本周证据均为固定资产、固定 Runtime 与单次或单 suite 执行事实；不构成稳定性、并发能力、平均性能或 Jetson 生产部署结论。

## 本周结论

- 主 VLM 候选冻结为 `Qwen2.5-VL-3B-Instruct Q4_K_M` 与 `Qwen2.5-VL-3B-Instruct Q8_0 mmproj` 配对。两个本地 GGUF 的文件大小、SHA-256 和 metadata binding 均已校验。
- 默认开发 context 保持 `8192`。它已完成固定短 prompt 单图、合成长手册加单图、以及单常驻服务三图顺序请求的事实验证。
- `16384` 完成一次 host-CUDA recovery 冒烟，只作为实验事实保留，不改变 `8192` 默认选择。`32768` 未执行且继续禁用。
- EdgeOmni 已具备纯内存单图 VLM 输入、资产校验、MtmdBackend、HTTP JSON 图片传输及 SSE `metadata -> token* -> done` 服务路径。

## 本周目标与任务拆解

本周没有改变工业故障辅助应用主线，而是把 VLM 从“候选模型和 CLI 能力”推进到“可由 EdgeOmni Runtime 管理的单图服务”。执行顺序和完成状态如下：

| 里程碑 | 工作内容 | 本周状态 |
| --- | --- | --- |
| M7.1 | 审计 fork 的 VLM/mtmd 支持、候选资产、mmproj、image token API 和 context 矩阵 | 完成 |
| M7.2b | 校验本地主模型/mmproj 的 size、SHA-256、GGUF metadata、license/revision 与绑定关系 | 完成 |
| M7.3R | 构建冻结 Runtime，并完成第一次 4096 单图真实 CLI inference | 完成 |
| M7.4A | 验证 8192 默认候选的单图容量路径 | 完成 |
| M7.4B | 以合成长手册加单图验证 8192 长输入和严格 JSON 事实提取 | 完成 |
| M7.4C/C-D/C-R | 保留 16384 首次失败、完成 CUDA 环境审计，并执行一次受控 recovery | 完成；仅保留实验事实 |
| M7.5A | 将 VLM contract、图片门禁和 model/mmproj 资产绑定落到 C++ Runtime | 完成 |
| M7.5B | 实现进程内 MtmdBackend 和一次 Adapter 单图冒烟 | 完成 |
| M7.5C-R | 通过一个常驻 RuntimeService 顺序处理三张固定图片，验证 HTTP/SSE 闭环 | 完成 |

候选审计覆盖 Qwen2.5-VL-3B 主候选、Qwen2.5-VL-7B 第二候选和 InternVL3-8B 第三候选。7～8B 候选用于满足能力与资源审计范围，不因参数更大而推断 context 更长或性能更好；未闭合字段继续保留为未知，不编造结论。

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

### M7.3 启动器失败

M7.3 的第一次启动尝试在模型进程前失败，因为系统不存在 wrapper 使用的 `/usr/bin/time`，shell exit code 为 `127`。该记录的 `inference_run_count=0`，不能写成模型加载失败。M7.3R 改用 `date +%s%N` 记录墙钟，并在运行前以 `/bin/true` 验证计时和 exit-code 捕获，随后完成唯一一次真实 4096 inference。

### M7.4C CUDA 环境失败

16384 的首次 M7.4C attempt 未进入 prompt eval 或 decode。直接原因是受限执行沙盒隔离了 `/dev`，导致 `ggml_cuda_init` 无法初始化 CUDA，KV 落在 CPU。该 attempt 没有取得模型 child exit code 或输出，不能被归类为模型 OOM、16384 context 不可用或性能失败。

M7.4C-D 对主机进行了只读 CUDA 审计：Jetson R36.4.7、NVIDIA 540.4.0、设备节点和 `CUDA0: Orin` 均正常，且没有遗留 llama 或 tegrastats 进程。随后 recovery runner 在可见 GPU 的主机执行环境中完成一次、也是最后允许的一次 16384 attempt。恢复执行成功不抹除首次失败证据，也不增加第三次尝试。

### 工程复盘

- “launcher 启动次数”和“真实 inference 次数”必须分开记账；dependency、shell 或 sandbox 失败不能自动算作模型失败。
- Jetson 使用 UMA，tegrastats 的 RAM 是系统统一内存观测，不能直接称为独立显存，也不能把全部 RAM 增长归因于 KV Cache。
- context 能力必须由实际 context、KV allocation、prompt/image token、OOM 和输出完整性共同确认；GGUF metadata 的 `128000` 不能代替部署实测。
- mtmd helper 同时包含 vision encode、embedding 注入和 text prefill 路径。只有上游直接输出的独立 timing 才单独填写；无法拆分的字段保持 `null` 或 `not_measured`。
- 受限沙盒与 Jetson 主机不是同一 CUDA 执行环境。后续真实运行必须在同一环境先做 `--list-devices`，并以独立进程组监管模型和 tegrastats。

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

## 代码与工程交付

| 模块 | 交付内容 | 工程价值 |
| --- | --- | --- |
| Runtime contract | `ImageInput`、图片 request/response 字段、image/vision metrics 和稳定错误码 | 文本与图片请求使用同一 Runtime 接口 |
| 图片门禁 | JPEG/PNG/WebP、10 MiB、4096×4096、16 MiPixel、解码尺寸为安全事实源 | 阻止空数据、超限图片和调用方伪造尺寸 |
| 资产门禁 | 主模型/mmproj regular-file、size、流式 SHA-256 和固定 binding | 模型版本与视觉组件可追溯，避免错误配对 |
| MtmdBackend | 内存图片 decode、模型 chat template、mtmd chunks、image token 直接读取 | 不通过临时文件或硬编码 Qwen 模板接入视觉路径 |
| 生命周期 | DirectBackend/MtmdBackend 共用进程级 llama backend 引用计数 | 避免重复初始化和 double free |
| 请求恢复 | 单 in-flight、cancel/timeout 边界、终止后 KV/context 清理 | 错误或取消后仍可接受下一独立请求 |
| HTTP/SSE | 受控 base64 图片、metadata/token/terminal、脱敏错误 | 完成应用前的单常驻 VLM 服务底座 |
| 证据工具 | context/长输入/recovery/service suite runner 与结构化 JSON | 保留 command、hash、exit code、日志和 telemetry |

上游 `llama.cpp-omni` 源码未修改。项目实现属于基于公开 llama/mtmd API 的 Runtime 二次开发，不表述为从零实现 GGUF、视觉编码器、KV Cache 或 CUDA 推理内核。

## 与实习工作的对应关系

| 实习工作方向 | 本周项目体现 | 进一步理解 |
| --- | --- | --- |
| Jetson ARM64/CUDA 模型部署 | 冻结 aarch64 CUDA build，核验动态依赖、CUDA0 和 37/37 offload | 区分模型资产、Runtime binary、驱动环境和 launcher 四类故障 |
| C++ GGUF 加载与生命周期 | 主模型/mmproj 绑定、加载/释放、共享 backend 生命周期 | 模型管理不只是传路径，还包括版本、hash、模板和资源回收 |
| 量化资产选型 | Q4_K_M 主模型配 Q8_0 mmproj，记录 file type、大小与 hash | 主模型量化和视觉 projector 量化是两个独立选择，不能混称一个精度等级 |
| 长 context 与 KV | 4096/8192/16384 的 F16 KV 分别记录 144/288/576 MiB | context 翻倍带来 KV 容量增长，但 UMA 峰值还包含模型与计算 buffer |
| CMake/Runtime 接入 | 仅链接冻结 build 导出的 `libllama`、`libmtmd` 和公开头文件 | 先验证导出 API 与 ABI，再决定 Adapter 是否可实现 |
| 流式服务可靠性 | 单 active request、SSE、取消/timeout、错误分类、进程清理 | 服务成功门不仅是非空输出，还包括事件顺序、终态唯一和下一请求恢复 |

因此本周对实习内容的强化集中在现有 VLM Runtime 底座，没有另起一套模型管理或服务系统，也没有推迟后续 RAG、工具和 Agent 主线。

## 质量与可观测性边界

- 固定图片和合成 fixture 不含真实客户信息；合成长手册不是 RAG、实际多轮 session 或生产手册质量评测。
- timing 只记录 Runtime 或 CLI 直接给出的值。没有独立输出的 image position、vision 或 embedding 字段为 `null` 并附 measurement status，不倒推估算。
- M7.5C-R 原始 `tegrastats.log` 包含 140 行有效采样记录；峰值 UMA 为 `11971 / 30697 MB`、峰值 GR3D 为 `99%`、峰值温度为 `57.343 C`。这些是单一 suite 的原始观测，不代表热稳、功耗预算或容量保证。
- 模型资产由使用者显式准备；项目 runner 全程使用本地路径和 `--offline`，没有自动下载模型、图片或依赖。上游 Runtime 源码和冻结的 M6 benchmark 结果未修改，也未提交 git commit。

## 本周验收清单

- [x] 主模型和 mmproj 的来源、revision、license、size、SHA-256 与 metadata 有记录；
- [x] 主模型 embedding 与 mmproj projection binding 已核实；
- [x] 4096 单图、8192 单图和 8192 合成长输入均有原始成功证据；
- [x] 16384 首次失败、环境审计和最后一次 recovery 均保留独立账本；
- [x] 32768 未执行且未承诺部署；
- [x] C++ Runtime 支持纯内存单图 contract、门禁、资产校验与 MtmdBackend；
- [x] image token 来自 mtmd chunk API，不按分辨率估算；
- [x] 单常驻服务三张图片顺序请求全部成功，SSE terminal 唯一；
- [x] Runtime/FakeBackend 离线测试通过；HTTP/SSE 真实服务路径由 M7.5C-R 的主机 loopback suite 验证；
- [x] JSON 证据可解析，历史证据未覆盖，Runtime submodule 保持冻结 commit。

## 未完成与保留风险

- 8192 只有固定输入的单次/单 suite 事实，没有长时间稳定性、并发或生产图片分布验证；
- 16384 只有一次 recovery 成功，不是默认 context；32768 未执行；
- 当前 frozen mtmd helper 没有向 Adapter 独立暴露 vision encode 与 embedding injection timing；
- 多图、多 session、图片 KV 复用、RAG、Agent、音频、Docker 和 systemd 均未进入本周范围；
- Qwen2.5-VL-7B 与 InternVL3-8B 没有本地下载或 Jetson 推理结果，不是可自动切换的部署 fallback。

## 下周入口

下一阶段可进入 M8.1：将已验证的单图 HTTP/SSE VLM service 接入上层应用 API，并以离线契约测试验证请求转换、稳定错误映射、SSE 顺序和敏感图片数据不泄露。该阶段不应自动扩大到并发压测、16384/32768、RAG、Agent、多 session、音频或生产部署结论。
