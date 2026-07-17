
# Jetson 端侧离线多模态智能助手
## 任务需求与技术设计说明

> 本文档是拉取 llama.cpp-omni 源码后的改造入口，不修改上游仓库文档。
>
> 当前状态：需求已确定，尚未完成源码适配。具体目录、API、模型和模态支持以实际 commit 为准。

## 1. 项目背景

现有视觉部署项目已经覆盖 YOLO、ONNX、TensorRT、FP16/INT8、DeepStream、GStreamer、多路视频和 Jetson 部署。

第二个项目用于补充：

- LLM/VLM 端侧推理；
- GGUF 或实际支持的模型格式；
- 大模型权重量化；
- KV Cache；
- Prefill/Decode；
- Tokenizer 和流式生成；
- C++ Runtime；
- RAG 和工具调用；
- 蒸馏和剪枝；
- Docker、systemd、离线部署和回滚。

本项目不替代第一个项目，也不强制与第一个项目关联。先完成通用模型部署能力，场景在核心代码稳定后再确定。

## 2. 项目定位

项目名称：

Jetson 端侧离线多模态智能助手

项目定位：

> 在 Jetson AGX Orin 32GB 上实现可离线运行、可量化、可观测、可扩展的本地 LLM/VLM 推理和工具调用系统。

核心闭环：

~~~text
模型加载 → 多模态输入 → 本地推理
→ 量化/KV Cache → 流式输出
→ RAG/工具 → 监控和离线部署
~~~

## 3. 目标设备和技术栈

### 硬件

- Jetson AGX Orin 32GB；
- USB 摄像头作为可选图片输入；
- 稳定电源和散热；
- 不需要机器人、机械臂、底盘或复杂传感器。

### 软件

- Ubuntu for Jetson；
- JetPack；
- CUDA；
- Python；
- C/C++；
- CMake；
- llama.cpp-omni；
- llama.cpp 或其实际 Runtime；
- GGUF 或仓库实际支持的格式；
- Docker；
- systemd；
- OpenCV，按实际输入需求决定。

拉取源码后必须记录：

~~~text
仓库 URL、branch、commit
JetPack/L4T、CUDA、Python、GCC、CMake
模型 hash、Tokenizer hash
Docker image hash
~~~

## 4. 功能需求

### 4.1 模型加载

- 模型路径配置；
- 文件存在检查；
- hash 校验；
- tokenizer 加载；
- CUDA offload 配置；
- context length 配置；
- 加载失败错误；
- 模型只加载一次。

### 4.2 文本和多模态推理

- 文本输入；
- 图片输入，前提是模型和 Runtime 支持；
- 多轮上下文；
- 流式输出；
- 生成参数；
- 上下文重置；
- 请求取消；
- 超时控制。

### 4.3 RAG

后续支持：

~~~text
本地文档 → 解析 → 切分 → Embedding
→ 索引 → 检索 → 上下文拼接 → 本地模型
~~~

### 4.4 工具调用

初期工具：

- 文件搜索；
- 文档读取；
- OCR；
- 计算器；
- JSON 查询；
- 日志统计；
- 报告生成。

每个工具需要输入 Schema、输出 Schema、超时、错误码、权限和日志。

### 4.5 模型压缩

根据实际支持情况实现：

- Q8/Q6/Q5/Q4；
- W8A16/W4A16；
- AWQ/GPTQ 模型适配；
- KV Cache 精度对比；
- Teacher-Student 蒸馏；
- Attention Head/FFN/Projector 剪枝。

## 5. 非功能需求

- 可完全离线运行；
- 可重复加载相同模型；
- 记录模型和 Runtime 版本；
- 记录 TTFT、TPOT、tokens/s；
- 记录 RAM、GPU、温度和功耗；
- 支持服务退出和重启；
- 支持异常恢复；
- 支持 Docker；
- 支持 systemd；
- 支持模型版本和回滚；
- 不允许用未实测的性能数据作为结论。

## 6. 总体架构

~~~text
文本/图片/文档/日志
        ↓
Request Adapter
        ↓
Tokenizer/Vision Preprocess
        ↓
llama.cpp-omni Backend
        ├── Model Loader
        ├── Context Manager
        ├── KV Cache
        ├── Prefill
        ├── Decode
        ├── Sampler
        └── Stream Output
        ↓
Response Processor
        ├── Text
        ├── JSON
        ├── Markdown
        └── Metrics
        ↓
CLI/HTTP/JSONL Service
~~~

后续可扩展 RAG、Tool Dispatcher 和本地 Agent，但不提前绑定具体行业场景。

## 7. 后端接口设计

接口只是设计边界，不能假设上游仓库已经存在相同函数：

~~~text
initialize(config)
generate_text(request)
generate_with_image(request)
stream_generate(request, callback)
reset_context(session_id)
cancel(request_id)
get_runtime_metrics()
shutdown()
~~~

适配层负责隔离上游 API 变化，避免业务层直接依赖底层模型对象。

统一请求结构：

~~~json
{
  "request_id": "req-001",
  "session_id": "session-001",
  "text": "请分析输入内容",
  "images": [],
  "max_new_tokens": 256,
  "temperature": 0.7,
  "top_p": 0.9,
  "stream": true
}
~~~

实际字段必须以目标模型和仓库支持为准。

## 8. 性能指标

每次请求记录：

- prompt token 数；
- image token 数；
- output token 数；
- TTFT；
- TPOT；
- total latency；
- tokens/s；
- KV Cache 大小；
- 错误和超时。

系统记录：

- GPU；
- RAM；
- 温度；
- 功耗；
- OOM；
- 进程状态；
- 模型加载时间。

## 9. 研发阶段

### 阶段一：基线

1. 拉取并阅读上游 README、LICENSE 和目录；
2. 记录 commit；
3. 确认模型和模态支持；
4. 跑通官方最小示例；
5. 在 Jetson 编译或部署；
6. 保存原始输出和性能。

### 阶段二：适配层

新增独立的 backend、request、response、metrics 和 config 模块。先通过适配层接入，不要大面积修改上游核心代码。

### 阶段三：量化和 Runtime

完成模型量化对比、KV Cache 统计、Prefill/Decode 测试、流式输出、请求取消和超时。

### 阶段四：RAG 和工具

完成本地文档检索和少量工具调用，加入错误处理和结构化输出。

### 阶段五：蒸馏和剪枝

建立独立 train/compression 目录，训练 Student，完成剪枝和量化，再接入目标 Runtime。

### 阶段六：生产化

完成 ARM64 Docker、离线包、systemd、日志轮转、健康检查、模型版本和回滚。

## 10. 代码组织建议

拉取上游后，尽量保持上游代码和自有代码分离：

~~~text
upstream/
patches/
app/
  backend/
  request/
  response/
  metrics/
  tools/
  rag/
models/
configs/
scripts/
tests/
docker/
docs/
~~~

实际目录根据上游仓库调整，不预先假设上游结构。

## 11. 验收标准

### 最小验收

- Jetson 能加载模型；
- 文本或图片请求可以得到输出；
- 模型不重复加载；
- 能记录 TTFT、TPOT 和 tokens/s；
- 服务可以退出和重启；
- 错误有明确日志。

### 中期验收

- 至少两种量化格式对比；
- KV Cache 可观测；
- 流式输出可用；
- 有请求超时和取消；
- 有 Docker/离线部署；
- 有模型 hash 和 metadata。

### 完整验收

- VLM/LLM 多模态推理；
- RAG；
- 工具调用；
- 蒸馏或剪枝 Student；
- 量化后端侧部署；
- TTFT/TPOT/显存/温度/功耗记录；
- systemd 自动恢复；
- 模型升级和回滚；
- 核心能力稳定后确定最终业务场景。

## 12. 项目边界

当前不纳入：

- 机器人；
- ROS2；
- SLAM；
- 机械臂；
- DeepStream 多路视频；
- RTSP/RTMP；
- YOLO 主检测 pipeline。

当前也不预先承诺：

- 某个 TensorRT-LLM 版本一定支持 Jetson；
- 所有模态都能离线运行；
- 所有量化格式都一定加速；
- 大模型一定能在 32GB 内存中运行；
- 蒸馏或剪枝一定恢复原模型精度。

## 13. 项目介绍初稿

本项目面向 Jetson AGX Orin 32GB，基于 llama.cpp-omni 构建离线多模态大模型推理系统。项目研究本地 VLM/LLM 加载、低比特权重量化、KV Cache、Prefill/Decode、C++ Runtime、RAG、工具调用、模型蒸馏、结构化剪枝和 ARM64 离线部署。

项目最终目标不是实现一个简单聊天 Demo，而是建立一套可观测、可量化、可回滚的端侧多模态模型部署流程，并在核心能力稳定后选择合适的实际应用场景。
+
## 14. 应用层借鉴与 llama.cpp-omni 改造方案

根据提供的 autonomous-intelligence README，其成熟或已验证的应用层思路主要包括：

- 持续单会话对话；
- 即时记忆摘要；
- 长期记忆和向量数据库；
- 语音识别和语音合成；
- 视觉服务；
- 事件驱动的应用拆分；
- 自动启动；
- 工具调用；
- 本地设备上的模型和服务。

本项目借鉴这些架构思路，不修改上游仓库，也不把上游 README 中标记为 pending 的功能当作已经完成。

### 14.1 后端替换关系

| 上游应用层思路 | 本项目实现 |
| --- | --- |
| 主对话循环 | llama.cpp-omni Backend Adapter |
| OpenAI/Anthropic/Groq 模型调用 | Jetson 本地 LLM/VLM Runtime |
| OpenAI Vision | llama.cpp-omni 多模态输入 |
| OpenAI Whisper | 本地 faster-whisper，按资源情况启用 |
| OpenAI TTS | 本地 Piper/Kokoro，按资源情况启用 |
| VoyageAI Embedding | 本地 Embedding 模型 |
| Pinecone | 本地向量库 |
| Hailo/Raspberry Pi Vision | Jetson USB 摄像头和本地 Vision Adapter |
| 多服务事件通信 | Jetson 进程、Unix Socket 或事件队列 |
| 自动启动 | systemd |
| 云端依赖 | 离线模型和本地服务 |

### 14.2 应用层接口

应用层不直接依赖 llama.cpp-omni 内部类，而通过适配器调用：

~~~text
initialize(config)
generate_text(request)
generate_with_image(request)
stream_generate(request, callback)
reset_context(session_id)
cancel(request_id)
get_runtime_metrics()
shutdown()
~~~

这些是项目设计接口，不代表上游仓库当前已经提供同名函数。拉取源码后需要根据实际 API 编写适配器。

### 14.3 持续对话

区别于一次请求一次响应，系统维护一个长期会话：

~~~text
用户输入
    ↓
当前上下文
    ↓
即时记忆摘要
    ↓
长期记忆检索
    ↓
llama.cpp-omni
    ↓
回复和记忆更新
~~~

需要解决：

- 上下文长度；
- KV Cache；
- 记忆摘要触发条件；
- 旧消息归档；
- 会话重置；
- 多会话隔离；
- 隐私数据删除。

### 14.4 事件驱动服务

建议将应用拆成：

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

初期可以先在同一进程中使用模块接口，确认功能后再拆成独立进程。这样可以降低最初的调试成本，也避免过早引入分布式通信问题。

### 14.5 本地化改造要求

本项目正式目标是离线运行，因此必须逐步替换或隔离：

- OpenAI/Anthropic/Groq 云端模型；
- Pinecone 云端向量数据库；
- VoyageAI 云端 Embedding；
- 云端 Whisper；
- 云端 TTS；
- Raspberry Pi/Hailo 专用服务。

如果某个组件暂时只能使用云端，应在代码中做 Provider 抽象，并明确标记为开发期 fallback，不得把它当作最终离线能力。

### 14.6 模型后端与应用层边界

llama.cpp-omni Backend 负责：

- 模型和 tokenizer；
- VLM/LLM 推理；
- Prefill/Decode；
- KV Cache；
- Sampling；
- CUDA offload；
- 流式输出；
- 推理指标。

应用层负责：

- 会话；
- 记忆；
- RAG；
- 工具；
- 事件；
- 语音；
- 服务生命周期；
- 日志和 API。

这样后续更换模型、量化格式或 Runtime 时，不需要重写全部应用逻辑。

### 14.7 推荐开发顺序

1. 先跑通上游官方最小示例；
2. 保存上游功能和性能 baseline；
3. 写 Backend Adapter；
4. 实现本地文本对话；
5. 加入图片输入；
6. 加入流式输出和 TTFT/TPOT；
7. 加入即时记忆；
8. 加入本地长期记忆；
9. 加入本地语音服务；
10. 加入工具调用；
11. 加入 Docker/systemd；
12. 最后再根据能力选择实际业务场景。

### 14.8 许可证和借鉴边界

借鉴上游架构时需要检查：

- LICENSE；
- 第三方依赖许可证；
- 代码复制范围；
- 版权声明；
- 修改后发布要求；
- 云服务依赖；
- 模型和音频资源许可证。

本项目可以借鉴架构思想和接口设计，但不应在没有确认许可证的情况下直接复制大段代码或删除上游版权信息。

### 14.9 新增验收标准

除原有验收标准外，应用层还应满足：

- 单一持续会话可运行；
- 即时记忆可压缩上下文；
- 长期记忆可保存和检索；
- 语音和视觉服务可以独立启停；
- 事件错误不会导致主循环静默退出；
- 云端 Provider 可替换为本地 Provider；
- 应用层不直接依赖底层模型对象；
- systemd 重启后会话和服务状态符合设计；
- 所有云端依赖都有明确标识。


