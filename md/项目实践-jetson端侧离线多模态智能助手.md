# 项目实践：Jetson 端侧离线多模态智能助手

详细任务需求和技术设计入口：[任务需求与技术设计说明](./项目实践-jetson端侧离线多模态智能助手-任务需求与技术设计说明.md)

> 这是知识库之外的第二个独立实践项目，不替代现有 YOLO/TensorRT/DeepStream 项目，也不要求与其强关联。
>
> 当前状态：项目方向已确定，暂不进入具体代码实现和模型选型。先完成通用模型部署和服务能力，具体业务场景在核心代码基本稳定后再确定。

## 1. 项目定位

面向隐私敏感环境，构建运行在 Jetson AGX Orin 32GB 上的离线多模态智能助手。

项目重点补充：

- LLM/VLM 端侧推理；
- GGUF/权重量化；
- KV Cache；
- Prefill/Decode；
- C++ Runtime；
- 本地 RAG；
- Agent 工具调用；
- 蒸馏和剪枝；
- Docker、systemd、离线部署；
- 模型版本、监控和回滚。

项目不以替代第一个 YOLO/TensorRT/DeepStream 项目为目标，也不强制引入 DeepStream、RTSP、RTMP 或多路视频。

## 2. 推荐应用场景

项目初始场景：

> 面向隐私敏感环境的 Jetson 端侧离线多模态知识与设备辅助助手。

可处理的输入取决于 llama.cpp-omni 和实际模型支持范围：

- 文本；
- 图片；
- 截图；
- 本地 PDF/文档；
- 设备故障描述；
- 日志和配置文件；
- 其他实际支持的模态。

可提供：

- 本地多模态问答；
- 图片内容理解；
- 设备截图分析；
- 维修手册检索；
- 本地日志分析；
- 文档摘要；
- JSON 结构化输出；
- 工具调用；
- 多步任务规划。

## 3. 场景示例

### 3.1 设备维修辅助

输入设备照片、故障代码和维修手册，输出可能原因、相关章节、排查步骤和维修报告。

~~~text
图片/故障描述
    ↓
VLM 识别现象
    ↓
RAG 检索维修手册
    ↓
LLM 生成排查建议
    ↓
输出 Markdown/JSON 报告
~~~

### 3.2 离线多模态知识助手

用户上传图片或 PDF，提问：

- 图片中的报警是什么意思；
- 手册中如何处理该问题；
- 文档的关键结论是什么；
- 根据资料生成检查清单。

### 3.3 本地代码和日志助手

输入 C++/Python 源码、TensorRT/GStreamer 日志、tegrastats 和配置文件，输出故障原因、排查命令和修复建议。

### 3.4 具体场景后置

设备文档、故障辅助、代码日志分析、离线知识助手等都作为候选场景。当前不提前绑定某个行业或硬件，待模型后端、量化、服务接口和部署流程基本完成后，根据实际能力和数据条件选择最终场景。

## 4. 总体架构

~~~mermaid
flowchart TD
    A["文本、图片、文档、日志"] --> B["输入适配层"]
    B --> C["Tokenizer / Vision Preprocess"]
    C --> D["llama.cpp-omni 本地 VLM/LLM Runtime"]
    D --> E["Prefill / Decode"]
    E --> F["KV Cache"]
    D --> G["Agent 编排层"]
    G --> H["本地知识库 / RAG"]
    G --> I["工具调用层"]
    G --> J["对话记忆与任务状态"]
    G --> K["JSON/Markdown/流式输出"]
    D --> L["Runtime Metrics"]
    L --> M["延迟、吞吐、显存、温度、功耗"]
    N["Docker / systemd / 日志 / 回滚"] --> D
~~~

## 5. 模块设计

### 5.1 输入适配层

负责输入类型统一、大小校验、图片预处理、文档解析和请求 ID。它不负责管理模型内部 KV Cache 和 CUDA 指针。

### 5.2 模型后端层

核心后端使用 llama.cpp-omni，负责：

- 模型加载；
- Tokenizer；
- VLM/LLM 推理；
- 量化模型加载；
- CUDA offload；
- 采样；
- 流式输出；
- KV Cache；
- Prefill/Decode。

上层只依赖抽象接口：

~~~text
generate_text()
generate_with_image()
stream_generate()
reset_context()
get_runtime_metrics()
~~~

具体函数名以后以仓库实际 API 为准。

### 5.3 Agent 编排层

负责判断是否检索、是否调用工具、任务拆分、状态管理、失败重试、超时和最终输出。Agent 不应直接依赖 GGUF 文件和 CUDA 内部细节。

### 5.4 RAG 层

负责文档导入、切分、embedding、索引、Top-K 检索、重排、上下文拼接和来源引用。

### 5.5 工具层

初期工具：

- 文件搜索；
- 文档读取；
- OCR；
- 计算器；
- JSON 查询；
- 系统状态；
- 日志统计；
- 报告生成。

每个工具应定义输入 Schema、输出 Schema、超时、错误码和权限边界。

### 5.6 可观测层

记录：

- prompt token 数；
- 图片 token 数；
- output token 数；
- TTFT；
- TPOT；
- tokens/s；
- 总延迟；
- KV Cache；
- GPU/RAM；
- 温度；
- 功耗；
- OOM；
- 超时；
- 工具调用耗时。

## 6. 模型压缩路线

### 6.1 基线

先固定：

- 模型；
- tokenizer；
- prompt；
- chat template；
- 采样参数；
- 评测集；
- Jetson 软件版本。

建立 FP16 或项目支持的高精度 baseline。

### 6.2 量化

根据 Runtime 支持范围比较：

- Q8；
- Q6；
- Q5；
- Q4；
- W8A16；
- W4A16；
- AWQ/GPTQ 模型。

记录模型大小、显存、TTFT、TPOT、输出质量和长上下文稳定性。

### 6.3 KV Cache

比较 FP16、INT8 和混合 KV Cache，使用短、中、长上下文和多轮对话验证。不能只看显存下降，还要看 Attention 误差和生成质量。

### 6.4 蒸馏

~~~text
Teacher VLM/LLM
    ↓
logits、feature、attention
    ↓
Student
    ↓
蒸馏微调
    ↓
量化和 Jetson 部署
~~~

可研究 Token logits、Vision Encoder feature、Projector 输出和多模态 embedding 蒸馏。

### 6.5 剪枝

重点研究：

- Attention Head；
- FFN hidden dimension；
- Vision Encoder 通道；
- Projector 维度；
- 层数缩减；
- 剪枝后微调和量化。

剪枝后必须重新导出、量化和部署验证。

## 7. 性能指标

必须分别记录：

- TTFT；
- TPOT；
- tokens/s；
- total latency；
- P95/P99；
- KV Cache 显存；
- 峰值 RAM；
- GPU 利用率；
- 温度；
- 功耗；
- OOM；
- 请求取消和恢复时间。

TTFT 重点反映 tokenizer、图片编码、Prefill 和调度；TPOT 重点反映 Decode、KV Cache、内存带宽和采样。

## 8. 阶段规划

### 阶段一：最小推理

在 Jetson 上完成模型加载、文本/图片输入、正确输出和版本记录。

### 阶段二：多模态交互

完成统一请求、流式输出、多轮上下文、token 和延迟统计。

### 阶段三：量化对比

完成 Q4/Q8 或实际支持格式的量化，对比显存、TTFT、TPOT 和质量。

### 阶段四：RAG 和 Agent

导入本地文档，实现检索和 2～3 个工具，完成超时、失败和结构化输出。

### 阶段五：蒸馏和剪枝

训练 Student，完成 Transformer/视觉编码器压缩，再量化并部署。

### 阶段六：生产化

完成 Docker 离线镜像、systemd、日志轮转、健康检查、模型版本和回滚。

## 9. 部署和版本管理

模型 metadata 至少保存：

- 模型 hash；
- tokenizer 版本；
- 量化方法；
- 模型文件 hash；
- JetPack/CUDA/Runtime 版本；
- 输入限制；
- 上下文长度；
- 生成配置；
- 实验指标。

服务需要支持：

- 无网络运行；
- 自动启动；
- 异常恢复；
- 日志轮转；
- 模型回滚；
- 健康检查。

## 10. 项目边界

当前不强制纳入：

- DeepStream 多路视频；
- RTSP/RTMP；
- tracker/OSD；
- YOLO 主检测 pipeline；
- 多路视频解码。

这些属于第一个项目的核心范围。

本项目也不预先承诺某个 TensorRT-LLM 版本一定支持 Jetson、所有模态都可运行或所有量化格式都一定加速。具体能力必须以目标 Jetson、目标模型和 Runtime 实测为准。

## 11. 与知识库章节的对应关系

| 知识库章节 | 项目实践 |
| --- | --- |
| 01～03 | 模型导出、格式和 Runtime 对照 |
| 04～07 | 低精度、PTQ/QAT 和 profiling 思维 |
| 08～09 | CUDA、C++、服务和资源管理 |
| 11 | Transformer/视觉编码器剪枝 |
| 12 | Teacher-Student 蒸馏 |
| 13 | 稀疏模型扩展 |
| 15 | Docker、Linux、离线和回滚 |
| 18 | LLM/VLM 量化 |
| 19 | TensorRT-LLM 和大模型 Runtime |

## 12. 最终项目定位

> **基于 Jetson AGX Orin 的离线多模态模型压缩、推理和智能 Agent 服务。**

核心闭环：

~~~text
大模型/多模态模型
    ↓
量化、蒸馏、剪枝
    ↓
llama.cpp-omni Runtime
    ↓
Jetson 端侧推理
    ↓
RAG/Agent/工具调用
    ↓
Docker/systemd/监控/回滚
~~~

## 13. 借鉴 autonomous-intelligence 的应用层架构

根据提供的 README，autonomous-intelligence 的主要落地能力包括：

- 持续单会话对话；
- 即时记忆摘要；
- 长期记忆和向量检索；
- 语音输入和语音输出；
- 视觉服务；
- 人脸识别服务；
- 事件驱动的多服务拆分；
- 自动开机启动；
- 工具调用；
- 本地 Jetson/Raspberry Pi 设备适配。

本项目借鉴的是这些应用层架构和产品思路，不直接复制上游代码、目录或未完成功能。

### 13.1 应用层改造关系

~~~text
Tau 主对话循环
    ↓
llama.cpp-omni 本地 LLM/VLM Backend

即时记忆
    ↓
本地上下文摘要模块

长期记忆/Pinecone/Voyage
    ↓
本地 Embedding + 本地向量库

OpenAI Whisper
    ↓
本地 faster-whisper 或其他本地 STT

OpenAI TTS
    ↓
本地 Piper/Kokoro TTS

Hailo/Raspberry Pi Vision
    ↓
Jetson USB 摄像头 + 本地 Vision Adapter

事件驱动服务
    ↓
Jetson 本地进程/Unix Socket/事件队列
~~~

### 13.2 目标应用形态

本项目的应用形态调整为：

> **Jetson AGX Orin 上的离线语音视觉多模态个人智能助手。**

核心闭环：

~~~text
用户语音/文本/图片
    ↓
本地输入服务
    ↓
llama.cpp-omni VLM/LLM
    ↓
即时记忆和长期记忆
    ↓
工具调用/文档检索
    ↓
文本、JSON 或本地语音输出
~~~

### 13.3 借鉴范围

重点借鉴：

- 持续对话，而不是一次请求一次会话；
- 即时记忆摘要，控制上下文长度；
- 长期记忆归档和检索；
- 语音、视觉和主对话解耦；
- 事件驱动的服务通信；
- 自动启动和服务恢复；
- 工具调用框架；
- 后续可扩展的应用拆分。

不直接继承：

- Raspberry Pi 5 和 Hailo-8L 的硬件依赖；
- Pinecone/VoyageAI 云端依赖；
- OpenAI/Anthropic/Groq 云端推理；
- 上游未完成的 TensorRT/Hailo 集成；
- 上游的具体目录结构和实现细节。

### 13.4 预期服务拆分

第一阶段可拆分为：

~~~text
main_assistant
    ├── llama_backend
    ├── memory_service
    ├── vision_service
    ├── speech_input_service
    ├── speech_output_service
    ├── tool_service
    └── metrics_service
~~~

初始阶段可以先运行在同一 Jetson 进程或少量进程中，待接口稳定后再拆分为 Unix Socket、WebSocket 或独立服务。

### 13.5 对 llama.cpp-omni 的核心改造

llama.cpp-omni 作为模型后端，主要承担：

- 本地 LLM/VLM 加载；
- 文本和图片请求；
- Tokenizer；
- Prefill/Decode；
- KV Cache；
- 流式生成；
- Sampling；
- CUDA offload；
- TTFT/TPOT 统计。

Tau 风格的应用层负责：

- 持续会话；
- 记忆摘要；
- 长期记忆检索；
- 工具调用；
- 事件调度；
- 语音输入输出；
- 服务生命周期。

两层通过 Backend Adapter 隔离，避免让应用层直接依赖 llama.cpp-omni 的内部对象和 API。

