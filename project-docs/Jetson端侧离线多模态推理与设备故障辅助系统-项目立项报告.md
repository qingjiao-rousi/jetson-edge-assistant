# Jetson 端侧离线多模态推理与设备故障辅助系统

## 项目立项报告

| 项目项 | 立项内容 |
| --- | --- |

| 项目性质 | 基于 `llama.cpp-omni` 的 Jetson Runtime 二次开发与业务验证 |
| 项目最终功能 | 工业现场实时音视频全双工多模态交互，以及离线设备知识检索与故障辅助 |
| 目标设备 | NVIDIA Jetson AGX Orin 32GB |
| 目标环境 | L4T R36.4.7、CUDA 12.6、GCC 11.4、CMake 3.22、ARM64 |
| 交付形态 | 可集成 Runtime 模块、性能基线报告、离线部署包、问题清单与模块技术交接文档 |
| 立项边界 | 个人负责 Jetson Runtime 适配、模型服务、算力优化、可观测性和离线故障排查 POC；音视频采集、VAD/AEC、ASR、TTS、播放及全双工流控由团队其他成员负责 |
| 生产状态 | **不承诺生产上线、最终客户验收或大规模商业化** |

## 1. 项目摘要

研发面向工业现场运维的端侧实时音视频全双工多模态系统，使用的是开源的`llama.cpp-omni`。最终系统包括音视频采集与流控、VAD/AEC、ASR、LLM/VLM、TTS、播放和故障辅助等能力。本项目不是从零实现新的大模型推理框架；在既有 Runtime 上完成 **Jetson AGX Orin 32GB 的 ARM64/CUDA 适配、C++ Runtime Adapter、模型服务化、算力与 UMA 内存性能评测、离线 RAG/受限工具集成及演示部署**。音视频全双工链路属于项目最终功能，但其业务实现不计入个人负责范围。

项目面向弱网、无网和敏感数据不能出端的工业现场，形成如下可验证闭环：
```text
故障描述 / 设备照片 / 告警截图 / 本地维修手册 / 日志
                         ↓
             Jetson 本地 LLM/VLM Runtime
                         ↓
              本地 RAG 检索与来源引用
                         ↓
             受限只读工具查询与日志统计
                         ↓
            原因候选、排查步骤和结构化报告
```
实习期结束时，个人阶段性成果界定为：**可供上层系统集成的 Runtime 模块、目标 Jetson 实测的性能基线报告、ARM64 Docker/systemd 离线部署包，以及接口说明、问题清单和模块技术交接文档**。客户演示和最终系统集成由其他成员继续推进，不纳入个人交付判据；这些成果不等同于整个项目结束、生产级长稳、正式商业化或全零自研推理框架。

实习工作采用“在原项目阶段内深化”的方式落地：不改变工业故障辅助业务闭环，不重排 VLM、RAG、工具和部署顺序，也不另建一套 Runtime 产品。模型管理、量化测试、长上下文、CMake/CUDA 和服务可靠性分别挂接到原计划中的构建、Runtime、性能、VLM 接入和部署验收任务。

## 2. 立项背景与业务价值

### 2.1 现场约束

| 约束 | 对系统的要求 |
| --- | --- |
| 弱网或无网 | 核心模型推理、RAG 和工具调用必须在设备本地完成 |
| 数据敏感 | 图片、维修手册和日志不离开 Jetson，不依赖云端 embedding |
| UMA 统一内存 | 同一 32GB 内存池同时承载 CPU、CUDA 模型、KV Cache 和应用，必须监控峰值 RAM 与 OOM |
| 功耗与散热受限 | 记录功耗模式、温度、降频和 `tegrastats` 采样，避免只看模型输出速度 |
| 现场可维护 | 需要模型 hash/metadata 校验、健康检查、日志、异常重启和离线导入能力 |
| 结果需追溯 | 故障结论引用本地文档 ID/片段 ID，检索失败不得伪造来源 |

### 2.2 业务价值

公司项目最终形成可在工业现场运行的 **实时音视频全双工多模态交互系统**：持续接收麦克风、摄像头和设备侧数据，通过团队负责的 VAD/AEC、ASR、视频输入编排、TTS、播放与全双工流控链路，调用本地 LLM/VLM Runtime，并结合维修手册和设备日志完成离线故障辅助。

个人实习阶段负责为该总体系统补齐 Jetson 端侧推理后端：稳定承接文本、图片及团队上游模块形成的结构化请求，提供流式生成、取消、上下文管理、性能指标和部署接口，并完成可独立验收的离线故障排查 POC。个人价值集中在 **C++ Runtime 解耦、模型服务化、端侧性能优化、可观测性、可复现构建和离线交付**；不将音视频采集处理、ASR/TTS 或全双工调度表述为个人实现。

## 3. 目标与成功标准

### 3.1 总体目标

公司总体目标是在 Jetson 上实现实时音视频全双工多模态交互与设备故障辅助。个人子模块目标是在 NVIDIA Jetson AGX Orin 32GB、L4T R36.4.7、CUDA 12.6 环境上，基于固定版本的 `llama.cpp-omni`，完成从模型与 Tokenizer 校验、C++ Runtime、模型服务、CUDA Offload、性能评测到离线业务演示的端侧工程闭环，并向团队音视频模块提供稳定的请求与流式输出边界。

### 3.2 个人实习期成功标准

| 维度 | 成功标准 |
| --- | --- |
| 构建与追溯 | Runtime fork/commit、CMake patch、环境 manifest、模型来源与 SHA-256 可查询，干净环境可按脚本重建 |
| 模型与输入一致性 | 校验 GGUF v3、Tokenizer、tokens/merges、BOS/EOS/停止词和 chat template；对齐 Prompt Token 计数、截断策略与 Context 占用 |
| C++ Runtime | `EdgeOmniRuntime` 统一封装模型单例加载、文本/图片请求、流式 Callback、Cancel、上下文重置和结构化错误码 |
| 模型服务化 | 提供 HTTP/JSON/SSE 请求边界、request/session ID、队列与并发上限、背压、Timeout/Cancel、`/health`、`/ready`、`/model/info` 和 `/metrics` |
| 算力优化 | 完成 37/37 层 CUDA Offload 验证；区分 Prefill/Decode，分别报告 TTFT、TPOT 和 Throughput (tokens/s) |
| 量化与缓存 | 在同一主模型、同一 revision 和同一评测条件下比较 Q4_K_M/Q8_0；按实际支持情况比较 KV Cache F16/Q8_0 与不同 Context 长度 |
| 可观测性 | 对齐 request_id 和时间戳，保存 JSONL/CSV 及 `tegrastats` 原始数据，记录 RAM/GPU/功耗/温度 |
| 多模态与 Agent 闭环 | 接入一个实际支持的 VLM，记录 Vision Encode Latency 和 image token；实现本地 RAG、来源引用、2～3 个受限只读工具及受控 Agent 编排 |
| 端侧部署 | 固化 L4T/CUDA/ARM64 兼容矩阵、功耗与运行参数、模型 Ready 门禁和 active/previous 版本；交付 Docker/systemd 脚本并验证离线启停和异常恢复 |
| 交付状态 | Runtime 模块、接口契约测试、性能基线、部署包和模块技术交接完成；客户演示不作为个人交付项 |

## 4. 当前立项基线与证据边界

### 4.1 已验证基线

| 项目 | 当前记录 |
| --- | --- |
| 硬件/系统 | Jetson AGX Orin Developer Kit，32GB 级 UMA；Ubuntu 22.04.5；Kernel 5.15.148-tegra |
| 软件 | L4T R36.4.7；CUDA Toolkit 12.6.68；GCC/G++ 11.4.0；CMake 3.22.1 |
| 构建 | `llama.cpp-omni` Release、Linux aarch64、`GGML_CUDA=ON` |
| 构建修复 | 修复 `mtmd` include 传递依赖（`PRIVATE` 调整为 `PUBLIC`）；已固定 fork 分支 `jetson-runtime-dev` 和修复 commit `19cc269` |
| 模型 | Qwen2.5-3B-Instruct Q4_K_M；GGUF v3；`architecture=qwen2`；`file_type=MOSTLY_Q4_K_M` |
| 模型校验 | 已记录 SHA-256：`626b4a6678b86442240e33df819e00132d3ba7dddfe1cdc4fbb18e0a9615c62d`；tokenizer、merges、chat template 已嵌入 |
| CUDA | `CUDA0: Orin`；37/37 可 offload 层分配到 GPU |
| 资源 | 已记录 CUDA model/KV/compute buffer 以及 `tegrastats` 的 GPU、RAM、温度、功耗采样 |

### 4.2 必须保持的真实性边界

| 内容 | 立项报告中的表述 |
| --- | --- |
| Prompt 170.56 tokens/s、Decode 12.34 tokens/s | **单次冒烟观测**，仅证明一次运行成功，不代表平均性能、P95 或稳定性 |
| 固定参数、warmup、5 次以上重复统计 | 立项后的正式 Benchmark 任务，完成后才可写入性能结论 |
| `llama.cpp-omni`、GGUF、GGML CUDA、KV Cache、Tokenizer、mtmd 基础实现 | 公司或上游已有能力，不计为个人从零原创 |
| Runtime Adapter、VLM、RAG、受限工具、Docker/systemd 恢复 | 计划交付，必须以代码、日志、样例和验收记录标记完成 |
| 实时全双工语音/音视频 | 团队总体目标；个人仅在有实际接口设计或联调证据时计入贡献 |
| 蒸馏、剪枝 | 个人后续探索方向，不纳入本周期主线成果 |

## 5. 范围与职责边界

### 5.1 个人负责范围

1. 审计 Jetson AGX Orin 的 L4T、CUDA、GCC、CMake 和 ARM64 依赖，建立宿主机、Runtime 与容器基础镜像兼容矩阵，完成 `mtmd` 传递依赖修复及可复现构建。
2. 建立模型 Manifest 与启动校验门禁，核验来源、revision、SHA-256、GGUF v3 metadata、Tokenizer tokens/merges、BOS/EOS/停止词和 chat template；验证 Prompt Token 计数、截断策略与 Context 占用一致性。
3. 设计并实现 `EdgeOmniRuntime` C++ LLM/VLM Runtime 抽象层及 Backend Adapter，隔离上层业务与 `llama.cpp-omni` 内部对象，统一模型单例生命周期、文本/图片多模态推理、流式 Token Callback、Cancel、Context Reset 和结构化错误码。
4. 构建模型服务接口，定义 HTTP/JSON/SSE 请求响应 Schema、request/session ID、Timeout/Cancel、请求队列、并发上限、背压和输入资源限制，并提供健康、就绪、模型信息和指标端点。
5. 验证 37/37 层 CUDA Offload，基于 UMA 分析模型、KV Cache 和 compute buffer，完成 Prefill/Decode 插桩以及 TTFT、TPOT、Throughput 与 `tegrastats` 关联采集。
6. 在固定主模型上执行 Q4_K_M/Q8_0 权重量化及 KV Cache F16/Q8_0、Context 长度矩阵实验，完成 warmup、至少 5 次重复 Benchmark、JSONL/CSV 数据和统计报告。
7. 接入一个实际支持的 VLM 图片链路，校验 vision/mmproj，完成文本与图片联合多模态推理，记录 image token、Vision Encode Latency 和端到端时延，并执行固定设备图片/告警截图集测试。
8. 集成本地 PDF/Markdown/日志 RAG、文档 ID/片段 ID 引用和 2～3 个受限只读工具；实现仅负责检索决策、工具选择和带引用报告生成的受控 Agent，并保留 Schema、权限和审计日志。
9. 固化 `nvpmodel`、时钟/散热、Context、batch/ubatch、GPU layers、Flash Attention 和 KV Cache 推荐配置；交付 ARM64 Docker/systemd、模型只读挂载、active/previous 版本、Ready 门禁、日志轮转和异常恢复验证材料。

### 5.2 团队协作但不归入个人主线

公司最终系统包含实时音视频全双工交互。麦克风/摄像头采集、VAD/AEC、ASR、视频流输入编排、TTS、播放控制、打断检测和全双工流控由团队其他成员负责。个人子模块负责定义可被这些模块调用的 Runtime 请求、流式输出、Cancel 和 Context 接口，并通过 Mock/契约测试验证边界；客户演示和最终音视频联调不作为个人模块的完成条件。

### 5.3 明确不纳入个人实习主线

音视频采集与编解码、VAD/AEC、ASR/TTS、播放和全双工调度，通用无限权限 Agent、从零实现 GGML/CUDA Kernel 和未经目标 Jetson 实测的性能、功耗、蒸馏或剪枝结论。上述音视频能力仍属于公司项目最终范围，只是不纳入个人实习成果。

### 5.4 实习内容深化与证据要求

| 实习经历方向 | 在原计划中的落点 | 深化交付 |
| --- | --- | --- |
| Jetson 多模型部署 | W1 模型选型/构建，W7～W8 VLM 接入 | 模型与 mmproj manifest、revision/hash/metadata、参数记录、成功与失败日志 |
| C++ 模型加载与生命周期 | W2～W4 Runtime/服务 | `ModelSpec`/模型资产门禁、初始化/释放/失败清理、状态查询和生命周期测试 |
| Q4/Q8/F16 自动化测试 | W5～W6 量化评测 | 矩阵配置、结果 schema、正确性门禁、吞吐/UMA 统计和 provenance；F16 仅在资产实际可用时进入结论 |
| 长 context/KV/OOM | W6 KV Cache，W8 图文 context | KV/compute/model buffer 记录、context/batch 边界、OOM 分类和受控配置建议 |
| CMake/CUDA 与可靠性 | W1 构建、W2～W4 服务、W11～W12 部署回归 | 可复现构建、流式/Timeout/Cancel、结构化日志、异常后恢复和交接记录 |

深化项服从原阶段门：不能为了抽象 `ModelManager`、`ContextPlanner` 等内部模块暂停 VLM/RAG 业务主线。只有当抽象能消除当前硬编码、支撑下一阶段资产或形成可测试的错误边界时才引入。

## 6. 技术方案与架构
```text
团队音视频层：麦克风 / 摄像头 → VAD/AEC / ASR / 视频编排 ─┐
个人 POC 输入：文本 / 图片 / 文档 / 日志 ───────────────────┤
                                                            ↓
                                                      Request Adapter
                                                            ↓
      EdgeOmniRuntime
      ├─ Model Registry（路径、hash、metadata）
      ├─ DirectBackend（libllama/libmtmd 核心 Runtime）
      ├─ Context Manager（session/reset/KV）
      ├─ Request Lifecycle（queue/backpressure/stream/timeout/cancel）
      ├─ Model Service（HTTP/JSON/SSE/health/ready/metrics）
      └─ Runtime Metrics（TTFT/TPOT/资源）
            ↓
      llama.cpp-omni
      ├─ GGUF Loader / Tokenizer
      ├─ libmtmd / Vision Preprocess
      ├─ Prefill / Decode / KV Cache
      └─ GGML CUDA Backend / Offload
            ↓
      Jetson AGX Orin UMA

Local RAG + Restricted Tools → EdgeOmniRuntime → Markdown/JSON 故障报告
systemd / ARM64 Docker + Health Check + Logs → 离线服务生命周期
EdgeOmniRuntime 流式输出 / Cancel → 团队 TTS / 播放 / 全双工流控
```
### 6.1 Runtime 接口边界
```cpp
initialize(config)
generate_text(request)
generate_with_image(request)
stream_generate(request, token_callback)
cancel(request_id)
reset_context(session_id)
get_model_info()
get_runtime_metrics()
shutdown()
```
接口是本项目的设计边界，最终签名以固定 Runtime commit 的实际 C++ 实现为准。上层不直接持有上游 CUDA 指针。`DirectBackend` 是唯一核心实现，直接链接 `libllama`，后续图片能力再接入 `libmtmd`，负责模型单例、Context/KV Cache、Tokenize、Prefill/Decode、Sampling、流式回调和取消。HTTP/JSON/SSE 服务构建在该接口之上；如确需进程隔离，再增加可选 `ServerBackend`，但它不是 Direct Runtime 的前置步骤。`llama-cli` 仅用于上游基线、参数核验和故障对照，不作为业务 Backend。

Tokenizer 工程任务限定为模型与 Runtime 的输入一致性验证：核验 tokens/merges、特殊 Token、chat template、Prompt Token 计数、截断和停止条件，不将上游 Tokenizer 算法表述为个人从零实现。

### 6.2 多模态、RAG 与工具约束

- VLM 仅接入实际支持的模型及 vision/mmproj，记录来源、revision 和 hash。
- RAG 仅处理本地 PDF、Markdown、纯文本和日志，引用文档 ID 与片段 ID；无命中时明确返回，不生成虚假引用。
- 工具限定为文件搜索/读取、故障码或 JSON 查询、日志统计/报告生成中的 2～3 个，只读、限根目录、带 Schema、超时、错误码和审计日志。
- Agent 仅做受控编排，不实现无限循环或无限权限执行。

### 6.3 模型服务与受控 Agent

模型服务至少定义 `POST /v1/generate`、`POST /v1/chat`、`POST /v1/cancel/{request_id}`、`GET /health`、`GET /ready`、`GET /model/info` 和 `GET /metrics`。服务层负责请求校验、单例模型生命周期、队列、并发上限、背压、Session、Timeout/Cancel、Context/输出 Token/图片大小限制、正常关闭和错误映射。若提供兼容既有 API 的字段，只记录实际实现和验证范围，不使用“完全兼容”表述。

受控 Agent 只在固定流程内判断是否检索、选择白名单工具并生成带来源报告。工具调用必须经过 Schema 校验、允许根目录检查、超时控制和审计记录；不得开放 Shell、任意网络或无限循环执行权限。

### 6.4 Jetson 端侧部署工程

端侧部署不仅包含打包，还包括以下可验证任务：

- 建立 L4T、CUDA、ARM64 Runtime、容器基础镜像和目标 Runtime commit 的兼容矩阵，区分宿主机驱动、容器设备映射和应用构建问题；
- 固化 `nvpmodel`、时钟策略、散热条件、Context、batch/ubatch、GPU layers、Flash Attention 和 KV Cache 配置，记录冷启动、模型加载、Ready 时间、峰值 UMA、Swap、OOM 和降频；
- 模型存放在规划后的 NVMe 目录，并通过只读路径或卷挂载；使用 Manifest、SHA-256 和 GGUF metadata 作为启动门禁，维护 POC 级 active/previous 版本及加载失败回退记录；
- ARM64 Docker 记录 image digest、离线导入和 GPU/设备映射；systemd 使用非 root 用户、明确配置/模型路径、正常停止、异常重启和日志轮转；
- 验证断网安装、冷启动、连续请求、进程异常退出、模型损坏和 OOM 场景；交付一键安装、启动、停止、卸载、状态检查和问题定位说明。

## 7. 个人实习期十二周实施计划与阶段门

下表保持原开发顺序。实习工作深化项在对应周次内完成或形成后续 backlog，不新增一个先于 VLM/RAG 的重构阶段。

| 周期 | 重点工作 | 主要输出 | 阶段验收门 |
| --- | --- | --- | --- |
| W1 | Jetson/L4T/CUDA/ARM64 审计；Runtime fork/commit；CMake `PRIVATE→PUBLIC` 修复；模型 Manifest、SHA-256、GGUF metadata；Tokenizer/chat template 校验；固定构建、Benchmark 脚本和四模型选型 | 环境与兼容矩阵、构建 Manifest、patch、模型清单、JSONL/CSV 基线、模型选择报告 | 干净环境可构建；模型与输入链路可追溯；同一配置完成 warmup + 至少 5 次有效重复；冻结文本部署基线 |
| W2～W4 | `EdgeOmniRuntime`；模型单例；文本生成；HTTP/JSON/SSE；request/session ID；队列、并发上限与背压；Cancel、Timeout、Context Reset、错误码；health/ready/model/metrics；fake backend 与 Jetson 集成测试 | C++ Runtime Adapter、API/请求响应 Schema、模型服务原型、单元测试与异常日志 | 上层不依赖上游内部对象；连续请求不重复加载；资源限制有效；取消/超时/异常有稳定错误码和可关联日志 |
| W5～W6 | UMA Prefill/Decode 分析；TTFT/TPOT/Throughput；`tegrastats`；冻结主模型的 Q4_K_M/Q8_0；KV Cache F16/Q8_0 与 Context 矩阵 | 性能基线报告、原始采样、量化/KV 对比报告 | 每项结论有固定配置、原始结果、统计值和失败/OOM 记录；不把墙钟时间冒充 TTFT/TPOT |
| W7～W8 | VLM 图片输入与 Vision Encode；固定设备图片/告警截图集与资源指标 | 图片推理、视觉指标、VLM 集成测试 | 固定图片集可稳定运行；视觉耗时和资源有结构化记录 |
| W9～W10 | 本地 PDF/Markdown/日志 RAG；文档片段引用；2～3 个受限只读工具；受控 Agent、Schema/权限校验和审计；基础 Session | 离线故障排查 POC、带引用报告、Agent/工具调用记录和审计日志 | 输出来源可定位；工具越权请求被拒绝；Agent 无任意执行权限 |
| W11 | L4T/CUDA/容器兼容矩阵；`nvpmodel` 与运行参数固化；模型只读挂载、Ready 门禁和 active/previous 回退；ARM64 Docker/systemd | 兼容矩阵、推荐配置、部署脚本、镜像 digest、启动/Ready/恢复记录 | 至少一个部署方式完成基础启停；另一个未完成项明确记录 |
| W12 | 冷启动、健康检查、日志、离线安装与异常恢复；接口契约测试、问题清单和模块交接 | 模块交接文档、接口测试、已知限制与后续建议 | 主路径可断网安装和重启验证；不宣称生产级长稳或最终验收 |

**模型范围控制：** W1～W3 可筛选 2～3 个 3B～4B 候选模型；正式 Q8_0、F16/BF16（如可加载）和 KV Cache 深度矩阵只对最终主模型开展。多测试几个模型用于选型是合理的，但不把所有模型都扩展到完整矩阵，以控制个人实习期工作范围并保证可比性。

## 8. 性能评测与数据治理

### 8.1 指标定义

| 指标 | 统一定义 |
| --- | --- |
| Vision Encode Latency | 图片预处理与视觉编码耗时 |
| Prefill | Prompt/image embedding 进入首轮解码前的计算阶段，重点观察 Compute-Bound 特征 |
| TTFT | 请求进入服务到首个输出 Token 可见的时延 |
| Decode | 首 Token 后的自回归生成阶段，重点观察 Memory-Bandwidth Bound 特征 |
| TPOT | Decode 阶段平均每个输出 Token 的生成时延 |
| Throughput | 分别报告 Prompt 与 Generation 的 tokens/s |
| Total Latency | 请求进入到完成、取消或超时的总耗时 |
| Model Ready | 服务启动到模型完成校验、加载并可接收请求的时间 |
| `tegrastats` | 采集 RAM、GPU/GR3D、温度、功耗等硬件指标 |

### 8.2 规范化 Benchmark

固定模型 revision/hash、Tokenizer/chat template、Prompt、目标输出长度、sampling、Context、batch/ubatch、GPU layers、Flash Attention、KV 类型、`nvpmodel`/时钟策略、散热条件和 warmup。每个配置至少执行 **5 次有效重复**，保存每次原始 JSONL/CSV、标准差、均值、中位数，必要时提供 P95；`tegrastats` 通过 request_id/时间戳与运行记录对齐。模型加载和 Model Ready 单独报告冷启动数据，不与推理 TTFT 混合。

评测集至少包含短 Prompt/短输出、长 Prompt/短输出（观察 Prefill）、短 Prompt/长输出（观察 Decode）、中文/英文固定任务、固定 VLM 图片集和固定 RAG 问题集。发生 OOM、降频、超时、取消或服务重启时，保留失败记录，不从统计中静默删除。

### 8.3 量化与 KV Cache 矩阵

| 轴 | 对比范围 | 记录内容 |
| --- | --- | --- |
| 权重量化 | Q4_K_M、Q8_0；F16/BF16 仅在实际可获得且可加载时作为参考 | 模型大小、加载时间、TTFT、TPOT、Throughput、RAM、温度、功耗、固定任务质量 |
| KV Cache | F16 与 Runtime 实际支持的 Q8_0 等类型 | Context 长度、KV 占用、TTFT/TPOT、输出稳定性、OOM 边界 |
| 模型选型 | 2～3 个候选模型的统一冒烟/基线 | 仅用于主模型选择；不把不同模型的结果混为量化结论 |

## 9. 交付物与验收证据

| 交付物 | 最低内容 | 完成证据 |
| --- | --- | --- |
| 可追溯源码与构建包 | Runtime fork/commit、patch、环境脚本、ARM64 构建说明 | commit、构建日志、干净环境复现记录 |
| 模型 Manifest 与输入校验 | 来源、revision、大小、SHA-256、GGUF metadata、Tokenizer tokens/merges、特殊 Token、template、截断策略 | Manifest、Token 计数与校验日志 |
| C++ Runtime Adapter | 初始化、模型单例、文本/图片、流式、取消、重置、错误码、指标 | 代码、单元测试、Jetson 集成日志 |
| 模型服务 | HTTP/JSON/SSE、队列/背压、资源上限、Session、health/ready/model/metrics | API Schema、服务日志、并发/取消/错误测试 |
| 性能基线报告 | 配置、5 次以上重复原始数据、统计、tegrastats、失败记录 | JSONL/CSV、脚本、报告、原始采样 |
| VLM/RAG/Agent POC | 图片集、Vision Encode、文档 ID/片段 ID、受控 Agent、工具 Schema/权限 | 离线样例、引用结果、工具调用与审计日志 |
| Jetson 离线部署包 | 兼容矩阵、推荐运行参数、模型 Ready/回退、ARM64 Docker/systemd、日志和恢复 | 镜像 digest、两套部署脚本、离线导入/启动/Ready/重启记录及兼容性说明 |
| 交接材料 | 架构、接口、构建、部署、排障、已知限制、未完成项、后续建议 | Markdown/PDF 文档、问题清单、模块验收与契约测试记录 |

## 10. 测试与质量策略

### 10.1 测试层级

| 层级 | 范围 | 真实性要求 |
| --- | --- | --- |
| 单元测试 | config、request/response、Tokenizer/截断、Backend mock、队列/背压、错误映射、metrics、工具权限、Agent 决策和引用格式 | 不依赖真实 GPU 和大模型 |
| Jetson 集成测试 | CUDA device、模型加载/Ready、Offload、文本/VLM、服务资源上限、Timeout/Cancel、Runtime 重启、tegrastats | 必须在目标 Jetson 环境执行并留存日志 |
| 故障注入 | 模型 hash 不符、GGUF 不支持、图片损坏、Context 超限、OOM、工具越权、进程异常退出 | 记录错误码、日志和恢复结果 |
| 长稳/回归 | 连续请求、长 Context、温度/降频、内存增长、服务重启 | 仅在实际运行时才可写成通过；不得用设计替代证据 |

### 10.2 Definition of Done

任务只有同时具备代码/配置/脚本、可重复命令、成功与失败测试、原始日志或结构化结果、版本/模型/环境信息、已知限制记录，并能说明上游能力与个人修改边界，才标记为 `DONE`。

## 11. 风险、假设与应对

| 风险 | 影响 | 应对与触发条件 |
| --- | --- | --- |
| 源码快照缺少 Git 元数据 | 无法复现或归因 | W1 恢复 fork/submodule 或记录快照 hash；未完成则冻结基线结论 |
| `llama.cpp-omni` API 变化 | Adapter 返工 | 固定 commit；上层仅依赖自有接口；保留 patch 与回滚方式 |
| L4T/CUDA/容器镜像不兼容 | 构建成功但容器内 GPU 不可用 | 固定兼容矩阵；分别验证宿主机 CUDA、设备节点、容器 Runtime 和应用依赖 |
| 模型 revision/量化来源不一致 | 性能和质量不可比 | Manifest 强制记录来源、revision、SHA-256、GGUF metadata |
| UMA 内存不足或 KV Cache OOM | 长 Context、VLM 请求失败 | 先做 Context 矩阵；记录 OOM 边界；限制并发和输出长度 |
| Jetson 温度/功耗导致降频 | Benchmark 波动 | 固定功耗模式、散热和 warmup；`tegrastats` 与结果对齐 |
| VLM/音频链路支持不稳定 | P1 延期 | 先锁定一个已支持 VLM；实时语音由团队其他模块负责 |
| 团队音视频接口变更 | Runtime 请求、流式输出或 Cancel 语义不兼容 | 固定请求/响应 Schema 和版本；使用 Mock/契约测试验证接口，实际系统联调由负责成员继续推进 |
| Docker 设备映射或隔离配置错误 | 容器内 CUDA 不可用 | 区分宿主机驱动与容器设备问题；保留 systemd 作为可演示备选 |
| 个人任务范围膨胀 | 实习期 12 周内无法形成阶段性闭环 | P0 优先；2～3 个候选模型只做选型；P2/研究项移交公司后续迭代或独立排期 |

## 12. 立项决策与变更控制

1. 以 P0（C++ Runtime、模型服务、性能、离线部署）为主线，P1（VLM/RAG/受控 Agent）在 P0 通过阶段门后接入。
2. 任何新增模型、量化类型、API 兼容范围或工具权限，必须说明对 Context、RAM、功耗、测试矩阵和交付日期的影响。
3. 未经目标 Jetson 实测的数据不得进入结论；未完成的模块使用“设计/计划/待验证”，不得使用“已实现/已上线”。
4. 蒸馏与剪枝只作为个人后续探索，若未具备训练、checkpoint、质量对照、转换和 Jetson 部署证据，不进入本周期成果。
5. 每周记录完成项、真实测试结果、失败与风险、未完成原因、下周任务和所需团队接口；个人实习第 12 周冻结阶段性交付版本、已知限制和后续移交项，公司项目继续按团队路线迭代。

## 13. 立项结论

公司项目具备明确的工业现场实时音视频全双工多模态交互与离线故障辅助需求。个人子模块拥有可验证的 Jetson 硬件环境和清晰职责边界，适合定位为 **“基于 `llama.cpp-omni` 的 Jetson 端侧 LLM/VLM C++ Runtime 适配、模型服务化、性能评测与离线设备故障辅助 POC”**。

个人核心交付不是完成公司的全部音视频系统或承担客户演示，而是把既有 Runtime 推进到目标设备，形成有版本、有输入一致性校验、有模型服务边界、有指标、有失败记录、可离线部署和可交接的工程闭环。个人阶段成功的最终判据是：**Runtime 模块能够在无外网的 Jetson 环境完成文本/图片故障辅助闭环，流式输出、Cancel 和 Context 接口通过 Mock/契约测试，上层负责成员可依据接口、Manifest、Benchmark 原始数据和部署文档继续集成、重建与排障。**

## 14. 当前实现补充（2026-08-06）

本报告为立项文件，前述目标、范围和验收条目保留为计划。当前已完成的阶段事实是：C++ Runtime/HTTP-SSE、量化与 VLM 原型、M9.2 本地手册检索与引用回答、M10.1 单热文本 KV Prefix 复用、M10.2 有界受限 Agent/进程内 session、M11 半双工语音网关原型，以及 M12 终端文本 UI。

M9.1B-R2.5 最终质量门仍为 `PARTIAL`：无答案拒绝率为 `0.50`，未达到 `0.75`；其 holdout 已消费，不得重跑或调参。M11 已验证本地模型资产加载和“键盘文本 -> Agent -> TTS 播放”，但没有外接麦克风的真实 ASR 验证，也没有 AEC、打断、流式 TTS 或全双工。Docker/systemd、恢复、长稳、生产鉴权和生产多用户会话同样未交付。

因此当前成果应表述为 Jetson 端侧离线 LLM/VLM 与设备知识辅助**原型**，不能表述为生产级、完整全双工系统或已完成 Docker/systemd 部署。代码职责见 [当前开发指引](../docs/current/development-guide.md)，冻结证据和历史报告见 `../evidence/`。
