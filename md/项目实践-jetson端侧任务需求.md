# Jetson 端侧离线多模态推理与设备故障辅助系统
## 任务需求与技术设计说明

项目背景：[项目背景](./项目背景.md)

项目概述：[项目实践：Jetson 端侧离线多模态推理与设备故障辅助系统](./项目实践-jetson端侧离线多模态智能助手.md)

> 本文档定义三个月项目的功能需求、技术边界、接口、测试和验收标准。
>
> `llama.cpp-omni` 是上游 Runtime；自有代码通过 Adapter 隔离上游 API。上游已有能力不得表述为个人从零实现。
>
> 当前源码快照缺少 `.git` 元数据，正式二次开发前必须恢复可追溯 fork/commit，或记录源码快照哈希与 patch。

## 1. 业务目标

为工业设备现场提供运行在 Jetson AGX Orin 32GB 上的离线知识与故障辅助服务。系统接收故障描述、设备图片、告警截图、本地维修手册和日志，输出带来源引用的原因候选、排查步骤和结构化报告。

业务约束：

- 核心推理完全离线；
- 敏感图片、文档和日志不离开设备；
- 单机统一内存、功耗和温度受限；
- 输出需要可追溯和可复现；
- 服务需要可启动、可停止、可恢复；
- 性能结论必须来自目标 Jetson 实测。

## 2. 项目目标与优先级

### 2.1 P0：端侧 Runtime 主线

1. Jetson CUDA/ARM64 构建和版本记录；
2. GGUF LLM 加载、哈希和 metadata 校验；
3. 文本生成和流式输出；
4. 模型只加载一次；
5. 请求超时、取消和错误处理；
6. Q4_K_M/Q8_0 权重量化对比；
7. KV Cache 类型、大小和上下文实验；
8. Prefill/Decode、TTFT、TPOT 和 tokens/s；
9. Jetson RAM、GPU、温度和功耗采集；
10. systemd 或 ARM64 Docker 离线部署。

### 2.2 P1：多模态业务闭环

1. 图片和告警截图输入；
2. VLM/mtmd 实际支持链路；
3. vision encode latency 和 image token；
4. 本地维修手册 RAG；
5. 2～3 个受限工具；
6. 带引用来源的 Markdown/JSON 故障报告。

### 2.3 P2：可选扩展

- 离线音频文件输入；
- 多 session；
- Docker 与 systemd 双交付；
- 更长 context 和更多 KV Cache 类型；
- Ollama-compatible API，前提是实际实现并验证。

### 2.4 独立研究项

蒸馏或结构化剪枝选择一个作为个人研究实验，不纳入三个月业务验收。研究项必须独立记录数据、训练、checkpoint、质量和 Jetson 部署结果。

## 3. 已确认基线

截至文档更新时，以下结果已有本地文件或日志证据：

| 项目 | 已确认结果 |
| --- | --- |
| 设备 | NVIDIA Jetson AGX Orin Developer Kit，32GB 级统一内存 |
| 系统 | Ubuntu 22.04.5，L4T R36.4.7，Kernel 5.15.148-tegra |
| CUDA | CUDA Toolkit 12.6.68 |
| 编译器 | GCC/G++ 11.4.0，CMake 3.22.1 |
| Runtime | `llama-cli` Release、Linux aarch64、GGML_CUDA=ON |
| 上游修复 | `tools/server/CMakeLists.txt` 将 mtmd include 由 PRIVATE 调整为 PUBLIC |
| 模型 | Qwen2.5-3B-Instruct Q4_K_M |
| 模型 SHA-256 | `626b4a6678b86442240e33df819e00132d3ba7dddfe1cdc4fbb18e0a9615c62d` |
| GGUF | v3，architecture=qwen2，file_type=MOSTLY_Q4_K_M |
| Tokenizer | tokens、merges 和 chat template 已嵌入 |
| GPU | CUDA0: Orin，可见显存约 30GB |
| Offload | 37/37 可 offload 层分配到 CUDA0 |
| KV Cache | 4096 cells，K/V F16，CUDA0 144 MiB |
| 冒烟性能 | Prompt 170.56 tokens/s；Decode 12.34 tokens/s，仅作为单次观测 |

单次冒烟性能不是正式基线。正式结果必须固定配置、warmup、重复运行并给出统计。

## 4. 技术栈和版本要求

### 4.1 硬件

- Jetson AGX Orin 32GB；
- NVMe 存储；
- 稳定电源和散热；
- USB 摄像头仅在图片业务需要时启用。

### 4.2 软件

- Ubuntu for Jetson / L4T；
- JetPack 组件和 CUDA；
- C/C++17；
- CMake；
- Python 3，仅用于测试、RAG、脚本或服务编排；
- `llama.cpp-omni` fork；
- GGUF；
- systemd；
- Docker 为可选部署目标。

### 4.3 必须记录的版本

~~~text
主项目 URL、branch、commit
llama.cpp-omni fork URL、branch、commit
patch 或源码快照 hash
JetPack/L4T、CUDA、GCC、CMake、Python
模型仓库、revision、文件名、SHA-256
tokenizer/chat template metadata
Docker image digest（如使用）
~~~

## 5. 总体架构

~~~text
文本 / 图片 / 文档 / 日志
            ↓
      Request Adapter
            ↓
      EdgeOmni Runtime
        ├── Model Registry
        ├── Backend Adapter
        ├── Context Manager
        ├── Request Lifecycle
        ├── Stream Output
        └── Runtime Metrics
            ↓
      llama.cpp-omni
        ├── GGUF Loader
        ├── Tokenizer
        ├── libmtmd/Vision
        ├── Prefill/Decode
        ├── KV Cache
        ├── Sampling
        └── GGML CUDA Backend
            ↓
      Jetson AGX Orin

Local RAG / Restricted Tools
            ↓
      EdgeOmni Runtime

systemd / Docker / Health / Logs
            ↓
      Service Lifecycle
~~~

## 6. 代码与仓库边界

推荐结构：

~~~text
vlmllm-main/
  app/
    backend/
    request/
    response/
    metrics/
    service/
    rag/
    tools/
  runtime/
    include/
    src/
    CMakeLists.txt
  third_party/
    llama.cpp-omni/       # 指向个人 fork 的 submodule
  patches/
  models/
  configs/
  scripts/
  tests/
    unit/
    integration/
    benchmark/
  docker/
  systemd/
  docs/
~~~

规则：

- 正式开发使用带 Git 元数据的个人 fork；
- 主项目通过 submodule 或明确构建配置固定 Runtime commit；
- 上游通用修复进入 fork commit 或 `patches/`；
- 应用层不直接持有上游内部 CUDA 指针；
- `autonomous-intelligence` 只借鉴架构，不整仓复制、不直接修改；
- 模型大文件不默认纳入 Git，提交 metadata 和下载/校验说明。

## 7. 自有 Runtime 接口

接口是项目设计边界，最终签名以实际 C++ 实现为准：

~~~cpp
struct RuntimeConfig;
struct GenerateRequest;
struct GenerateResponse;
struct RuntimeMetrics;

class EdgeOmniRuntime {
public:
    RuntimeStatus initialize(const RuntimeConfig & config);
    GenerateResponse generate_text(const GenerateRequest & request);
    GenerateResponse generate_with_image(const GenerateRequest & request);
    RuntimeStatus stream_generate(
        const GenerateRequest & request,
        TokenCallback callback);
    RuntimeStatus cancel(const std::string & request_id);
    RuntimeStatus reset_context(const std::string & session_id);
    ModelInfo get_model_info() const;
    RuntimeMetrics get_runtime_metrics() const;
    void shutdown();
};
~~~

### 7.1 Backend 演进

1. `LlamaCliBackend`：subprocess 原型，用于快速验证统一请求和错误边界；
2. `ServerBackend`：如目标 fork 的 HTTP server 稳定，验证流式与进程隔离；
3. `DirectBackend`：直接链接 `libllama/libmtmd`，作为最终 C++ Runtime 目标。

上层 Request/Response 不因 Backend 更换而改变。

## 8. 数据结构

### 8.1 RuntimeConfig

至少包含：

- Runtime/backend 类型；
- 二进制或共享库路径；
- 模型和多模态模块路径；
- context、batch、ubatch；
- GPU layers 和 device；
- KV Cache K/V 类型；
- Flash Attention；
- timeout；
- 日志和指标输出目录。

### 8.2 GenerateRequest

~~~json
{
  "request_id": "req-001",
  "session_id": "session-001",
  "text": "请根据图片和手册分析故障",
  "images": [],
  "max_new_tokens": 256,
  "temperature": 0.0,
  "top_p": 0.9,
  "seed": 42,
  "stream": true,
  "timeout_ms": 30000
}
~~~

### 8.3 GenerateResponse

至少包含：

- request/session ID；
- 文本或结构化结果；
- prompt/image/output tokens；
- finish reason；
- Runtime metrics；
- 模型 ID 和 hash；
- 来源引用；
- 工具调用记录；
- 错误码和错误信息。

## 9. 功能需求

### 9.1 模型生命周期

- 配置化模型路径；
- 文件存在、大小和 SHA-256；
- GGUF metadata 校验；
- 模型只加载一次；
- 启动失败返回明确错误；
- 正常 shutdown；
- 模型版本可查询；
- 不在请求之间无故重复加载。

### 9.2 文本推理

- 中文/英文文本；
- chat template；
- 固定和可配置 sampling；
- 单轮和基础多轮；
- 流式与非流式；
- 超时；
- 取消；
- context 重置。

### 9.3 图片推理

- 仅接入实际 Runtime 支持的 VLM；
- 文件类型、大小和分辨率限制；
- 图片预处理错误；
- vision module/mmproj 校验；
- vision encode 和 image token 指标；
- 文本与图片联合生成。

### 9.4 RAG

~~~text
本地文档 → 解析 → 切分 → 本地 Embedding
→ 本地索引 → Top-K → 可选重排
→ 上下文拼接 → 本地 Runtime → 来源引用
~~~

要求：

- 正式运行不使用云端 embedding 或向量库；
- 文档范围限定 PDF、Markdown、纯文本和日志；
- 每个结论保留文档和片段 ID；
- 检索失败不能伪造来源。

### 9.5 工具调用

初期只实现：

- 文件搜索/读取；
- JSON 或故障码查询；
- 日志统计或报告生成。

每个工具定义：

- input/output Schema；
- 允许访问的根目录；
- 超时；
- 错误码；
- 是否只读；
- 审计日志。

## 10. 性能指标定义

| 指标 | 定义 |
| --- | --- |
| Model Load | 开始加载到模型可接收请求 |
| Tokenize | 输入文本到 token 序列完成 |
| Vision Encode | 图片预处理和视觉编码耗时 |
| Prefill | prompt/image embedding 进入首轮解码前的计算 |
| TTFT | 请求进入服务到第一个输出 token 可见 |
| Decode | 首 token 后的自回归生成阶段 |
| TPOT | Decode 阶段平均每输出 token 时间 |
| tokens/s | 分别报告 prompt 和 generation 吞吐 |
| Total Latency | 请求进入到完成或取消 |

系统指标：

- CPU/CUDA model buffer；
- KV Cache K/V 类型与大小；
- compute/output buffer；
- RAM/Swap；
- GR3D；
- CPU/GPU 温度；
- VDD_GPU_SOC、VDD_CPU_CV 等可用功耗轨；
- OOM、超时、取消和恢复时间。

禁止把墙钟总时间直接冒充 TTFT 或 TPOT。

## 11. Benchmark 设计

### 11.1 固定条件

- Jetson 功耗模式和时钟策略；
- 散热和测试环境；
- Runtime/model hash；
- context/batch/ubatch；
- GPU layers；
- Flash Attention；
- KV Cache 类型；
- prompt、sampling 和目标输出长度；
- prompt cache；
- warmup 次数。

### 11.2 运行规则

- 每个配置先 warmup；
- 至少 5 次有效重复；
- 保存每次原始结果，不只保存平均值；
- 报告 mean、median、standard deviation，必要时报告 P95；
- tegrastats 与 request_id/时间戳对齐；
- debug/verbose 日志与正式性能测试分开；
- 发生 OOM 或降频必须记录。

### 11.3 评测集

- 短 Prompt/短输出；
- 长 Prompt/短输出，观察 Prefill；
- 短 Prompt/长输出，观察 Decode；
- 中文与英文固定任务；
- VLM 固定图片集；
- RAG 固定问题与来源答案。

## 12. 量化与 KV Cache 实验

### 12.1 权重量化

同一基础模型、同一 revision、同一 tokenizer/template 下比较：

- F16 或实际高精度参考；
- Q8_0；
- Q4_K_M。

输出：

- 文件大小和 SHA-256；
- 模型加载时间；
- Prompt/Generation throughput；
- TTFT/TPOT；
- RAM、温度和功耗；
- 固定任务质量；
- 长上下文稳定性。

### 12.2 KV Cache

只比较目标 Runtime 实际支持的类型，例如 F16 与 Q8_0。不得在未确认支持前写入结论。

## 13. 服务与异常处理

服务至少提供：

~~~text
POST /v1/generate
POST /v1/chat
POST /v1/cancel/{request_id}
GET  /health
GET  /model/info
GET  /metrics
~~~

如果实现 Ollama-compatible API，需要单独列出已兼容字段和不兼容项，不使用“完全兼容”笼统表述。

错误分类：

- 配置错误；
- 模型不存在/hash 不符；
- GGUF/architecture 不支持；
- 图片或文档输入错误；
- CUDA/OOM；
- context 超限；
- 请求超时/取消；
- 工具权限错误；
- Runtime 异常退出。

## 14. 部署设计

### 14.1 systemd

- 非 root 服务用户；
- 明确工作目录和配置；
- 启动前模型检查；
- 异常重启策略；
- 正常停止超时；
- journald/文件日志和轮转；
- 健康检查。

### 14.2 Docker

如采用 Docker：

- ARM64 镜像；
- Jetson Runtime 和设备映射；
- 模型只读挂载；
- 离线导入和镜像 digest；
- 宿主机 CUDA/设备节点验证；
- 容器内 tegrastats 可见性说明。

不得把 Bubblewrap/容器设备隔离造成的 CUDA 失败误判为宿主机驱动故障。

### 14.3 模型回滚

- 模型 manifest；
- 文件 SHA-256；
- active/previous 版本；
- 启动前校验；
- 加载失败回退；
- 回滚审计记录。

## 15. 测试策略

### 15.1 单元测试

不依赖真实 GPU 和大模型：

- config；
- request/response；
- 参数校验；
- subprocess/Backend mock；
- 超时和错误映射；
- metrics 计算；
- 工具权限；
- RAG 引用格式。

### 15.2 宿主机集成测试

必须在 Jetson 普通宿主机环境运行：

- CUDA device；
- 模型加载；
- 全层/部分 offload；
- 文本/VLM 生成；
- timeout/cancel；
- Runtime 重启；
- systemd/Docker；
- tegrastats。

### 15.3 长稳测试

- 连续请求；
- 长上下文；
- 内存泄漏；
- 温度和降频；
- OOM 恢复；
- 异常退出和自动重启。

## 16. 研发阶段与验收门

### 阶段一：基线——当前基本完成

- 环境和版本；
- 上游构建；
- 模型 metadata/hash；
- 文本生成；
- CUDA offload；
- 原始日志和 tegrastats。

退出条件：固定参数重复 benchmark 完成，并解决 Runtime 源码可追溯性。

### 阶段二：自有 Runtime

- Backend 接口；
- 模型生命周期；
- 文本请求；
- 流式；
- timeout/cancel；
- metrics；
- 单元测试。

退出条件：上层不依赖上游对象，真实模型集成测试通过。

### 阶段三：量化与性能

- Q4/Q8；
- KV Cache；
- Prefill/Decode；
- 固定评测集；
- 资源指标。

退出条件：有可复现实验配置、原始结果和结论边界。

### 阶段四：VLM 与业务闭环

- 图片输入；
- vision 指标；
- RAG；
- 受限工具；
- 结构化报告。

退出条件：固定样例能离线完成端到端任务并给出来源。

### 阶段五：生产化

- systemd 或 Docker；
- 健康检查；
- 日志轮转；
- 异常恢复；
- 模型版本和回滚；
- 长稳测试。

退出条件：离线重启后服务恢复，故障注入和回滚验证通过。

### 独立研究：蒸馏或剪枝

不得与业务阶段完成状态混合。只有实际完成训练、质量评测、转换和 Jetson 部署后，才进入项目成果。

## 17. 总体验收标准

### P0 验收

- Jetson 离线加载固定 GGUF；
- 文本流式/非流式生成；
- 模型不重复加载；
- timeout、cancel、shutdown 可验证；
- TTFT、TPOT、吞吐和资源指标可记录；
- Q4/Q8 或两种实际可用量化对比；
- systemd 或 Docker 恢复验证；
- 模型、Runtime 和环境版本可追溯。

### P1 验收

- VLM 图片输入；
- vision/image token 指标；
- 本地 RAG；
- 2～3 个受限工具；
- 带来源引用的故障报告；
- 端到端完全离线。

### 研究项验收

- 只选蒸馏或剪枝之一；
- 数据、代码、配置、checkpoint 完整；
- 有原模型对照；
- 有质量和压缩指标；
- 可转换到目标 Runtime；
- Jetson 实际加载和性能结果。

## 18. 风险与决策记录

主要风险：

- 当前源码快照无 Git commit；
- fork 与上游 API 变化；
- VLM/音频模型需要多组 GGUF；
- 量化文件来源和 revision 不一致；
- 长上下文导致 KV Cache/OOM；
- Jetson 温度和功耗模式影响性能；
- Bubblewrap/容器隐藏设备节点；
- 三个月范围膨胀。

每项技术决策必须记录：

~~~text
问题
候选方案
选择及理由
实际证据
未验证内容
回滚方式
~~~

## 19. 项目边界

不纳入本项目主线：

- ROS2、SLAM、机器人和机械臂；
- DeepStream 多路视频、RTSP/RTMP；
- YOLO 主检测 pipeline；
- 通用无限权限 Agent；
- 大规模分布式并发；
- 从零实现 GGML/CUDA kernel；
- 未经实测的 TensorRT-LLM、性能或压缩结论。

## 20. 最终交付物

- 可追溯的主项目与 Runtime fork；
- Jetson 构建和离线部署脚本；
- 自有 C++ Runtime Adapter；
- 文本和图片推理服务；
- 模型 manifest 与 hash；
- benchmark 工具、固定评测集和原始结果；
- Q4/Q8、KV Cache、Prefill/Decode 报告；
- RAG/工具业务样例；
- systemd/Docker 配置；
- 故障注入、恢复和验收报告；
- 蒸馏或剪枝的独立研究记录（如实际完成）。
