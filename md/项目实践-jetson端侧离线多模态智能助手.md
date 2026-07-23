# 项目实践：Jetson 端侧离线多模态推理与设备故障辅助系统

项目背景与表述边界：[项目背景](./项目背景.md)

任务需求与技术设计：[任务需求与技术设计说明](./项目实践-jetson端侧离线多模态智能助手-任务需求与技术设计说明.md)

三个月开发执行：[三个月开发计划与执行清单](./三个月开发计划与执行清单.md)

> 项目周期：三个月。
>
> 项目性质：基于 `llama.cpp-omni` 的 Jetson Runtime 二次开发与业务验证。
>
> 当前状态：LLM 基线和 CUDA 全层 offload 已验证；自有 Runtime、VLM、RAG、服务化和部署仍待实现。

## 1. 项目定位

面向工业设备现场的隐私、弱网和离线需求，在 Jetson AGX Orin 32GB 上构建可量化、可观测、可扩展的本地 LLM/VLM 推理系统。

项目从公司已有的 Ollama 形态文本助手原型出发，保留上层应用需求和接口思路，使用 `llama.cpp-omni` 构建可控的 Jetson Runtime Backend，重点解决：

- ARM64/CUDA 构建与上游适配；
- GGUF LLM/VLM 模型接入；
- 权重量化和 KV Cache；
- Prefill/Decode 和流式生成；
- Jetson 内存、温度和功耗观测；
- 本地维修手册 RAG；
- 受限工具调用；
- 离线服务部署与异常恢复。

项目不是从零实现 llama.cpp/GGML，也不把上游源码计为个人原创。个人贡献集中在 Jetson 适配、自有接口、运行时管理、指标链路、实验和业务交付。

## 2. 业务场景

目标产品形态：

> Jetson 端侧离线设备知识与故障辅助终端。

输入：

- 故障文字描述；
- 设备照片和告警截图；
- 本地维修手册；
- 日志、JSON 配置和状态信息；
- 可选离线音频文件。

输出：

- 故障现象摘要；
- 可能原因；
- 维修手册引用；
- 分步排查建议；
- 检查清单；
- Markdown/JSON 维修报告。

业务闭环：

~~~text
设备照片 / 告警截图 / 故障描述 / 日志
                    ↓
        LLM/VLM 本地理解与结构化
                    ↓
          维修手册 RAG 检索与引用
                    ↓
        文件、故障码、日志等受限工具
                    ↓
          排查步骤、检查清单和报告
~~~

## 3. 技术架构

~~~mermaid
flowchart TD
    A["文本 / 图片 / 文档 / 日志"] --> B["Request Adapter"]
    B --> C["EdgeOmni Runtime API"]
    C --> D["llama.cpp-omni Adapter"]
    D --> E["Tokenizer / mtmd Vision Preprocess"]
    E --> F["LLM/VLM Prefill / Decode"]
    F --> G["KV Cache / Sampling / Stream"]
    C --> H["Model Registry"]
    C --> I["Request Lifecycle"]
    C --> J["Runtime Metrics"]
    K["Local RAG"] --> C
    L["Restricted Tools"] --> C
    J --> M["tegrastats / JSONL / CSV"]
    N["systemd / Docker / Health Check"] --> C
~~~

架构分为五层：

1. **上游 Runtime 层**：`llama.cpp-omni`、`libllama`、`libmtmd` 和 GGML CUDA backend；
2. **自有 Runtime 层**：统一模型加载、文本/图片生成、流式回调、取消和指标接口；
3. **服务层**：请求校验、会话、超时、错误码、HTTP/JSON/SSE；
4. **应用层**：本地 RAG、受限工具和故障报告；
5. **部署层**：模型版本、日志、systemd/Docker、健康检查和恢复。

## 4. 核心模块

### 4.1 EdgeOmni Runtime

自有 Runtime API 隔离上游变化：

~~~text
initialize(config)
generate_text(request)
generate_with_image(request)
stream_generate(request, callback)
cancel(request_id)
reset_context(session_id)
get_model_info()
get_runtime_metrics()
shutdown()
~~~

这些是项目接口边界，不假设上游存在同名函数。实现时必须基于固定 commit 的实际 API。

### 4.2 模型与版本管理

记录：

- 模型仓库和 revision；
- GGUF 文件 SHA-256；
- architecture、quantization 和 chat template；
- Runtime fork、branch、commit 和 patch；
- JetPack/L4T/CUDA/GCC/CMake；
- context、batch、KV Cache 和 sampling 配置；
- 实验和部署状态。

### 4.3 请求生命周期

负责：

- request/session ID；
- 参数校验；
- 模型只加载一次；
- 流式输出；
- 超时和取消；
- 正常退出；
- 错误分类；
- 原始日志关联。

### 4.4 多模态输入

P1 支持图片和截图：

- 文件类型和大小限制；
- 图片解码与预处理；
- mtmd/mmproj 或目标模型实际视觉模块；
- vision encode latency；
- image token；
- 文本和图片统一请求。

音频作为 P2，不承诺实时全双工。

### 4.5 RAG 和工具

RAG 限定本地 PDF、Markdown、纯文本和日志，必须返回来源引用。

工具初期只实现 2～3 个：

- 受限目录文件搜索/读取；
- 故障码或 JSON 查询；
- 日志统计；
- 报告生成。

工具需要 Schema、超时、错误码、权限根目录和审计日志。项目不实现无限权限的通用自主 Agent。

### 4.6 可观测性

请求指标：

- tokenize time；
- vision encode time；
- prompt/image/output tokens；
- Prefill time；
- TTFT；
- Decode time；
- TPOT；
- tokens/s；
- total latency；
- 错误和取消时间。

系统指标：

- 模型加载时间；
- CPU/CUDA model buffer；
- KV Cache；
- compute buffer；
- RAM/Swap；
- GPU 利用率；
- 温度；
- 功耗；
- OOM 和进程状态。

## 5. 量化和 KV Cache 路线

### 5.1 固定基线

在任何优化前固定：

- 模型版本和 SHA-256；
- tokenizer/chat template；
- prompt 和输出长度；
- sampling；
- context/batch/ubatch；
- GPU offload 和 Flash Attention；
- 功耗模式和散热条件；
- warmup 和重复次数。

### 5.2 权重量化

三个月主线只比较同一基础模型的：

- 高精度参考文件（F16 或实际可获得格式）；
- Q8_0；
- Q4_K_M。

记录模型大小、加载时间、TTFT、TPOT、RAM、温度、功耗和固定评测集质量。使用上游量化工具不等同于自研量化算法。

### 5.3 KV Cache

比较 Runtime 实际支持的 F16 与 Q8_0 等类型，关注：

- context 长度；
- KV Cache 大小；
- TTFT/TPOT；
- 长上下文稳定性；
- 输出质量变化；
- OOM 边界。

## 6. 三个月范围

### P0：必须完成

- LLM 文本推理；
- Jetson CUDA/C++ Runtime；
- GGUF 校验和模型 registry；
- Q4_K_M/Q8_0 对比；
- KV Cache 观测；
- Prefill/Decode 指标；
- 流式生成；
- 超时、取消和错误处理；
- tegrastats 指标；
- systemd 或 ARM64 Docker。

### P1：业务亮点

- VLM 图片输入；
- 本地维修手册 RAG；
- 2～3 个受限工具；
- 带引用的故障报告。

### P2：时间允许时

- 离线音频文件输入；
- 多 session；
- Docker/systemd 双交付；
- 更长上下文实验。

### 个人研究扩展

蒸馏或结构化剪枝只选择一个，独立于公司三个月主交付。只有具备训练代码、checkpoint、质量对比和 Jetson 重新部署结果后，才作为已完成成果。

## 7. 十二周计划

| 周期 | 工作 | 交付物 |
| --- | --- | --- |
| 第1～2周 | 环境、源码、模型和 CUDA 基线 | 环境清单、构建日志、模型 metadata |
| 第3周 | 固定参数 LLM benchmark | 原始日志、JSONL/CSV、基线报告 |
| 第4～5周 | 自有 Runtime Adapter | 接口、模型生命周期、文本生成、测试 |
| 第6周 | 流式、超时、取消、错误码 | 服务原型和异常测试 |
| 第7周 | Q4/Q8 与 KV Cache | 对比报告和固定评测结果 |
| 第8～9周 | VLM 图片输入 | 图片请求、vision 指标、样例集 |
| 第10周 | 本地 RAG 和受限工具 | 手册检索、引用、工具审计日志 |
| 第11周 | systemd/Docker、健康检查 | 离线部署包和恢复验证 |
| 第12周 | 回归、长稳和项目总结 | 验收报告、演示、风险清单 |

计划按验收门控制；上一步未稳定时，不提前堆叠下一层功能。

## 8. 当前进度

已验证：

- Jetson/L4T/CUDA 环境；
- `llama.cpp-omni` CUDA Release 构建；
- CMake 传递包含依赖修复；
- Qwen2.5-3B-Instruct Q4_K_M GGUF 校验；
- 中文文本生成；
- CUDA0: Orin；
- 37/37 层 GPU offload；
- CUDA KV Cache/model/compute buffer；
- tegrastats GPU、RAM、温度和功耗采样。

下一步：

1. 固定参数重复性能基线；
2. 恢复带 Git 元数据的 Runtime fork/submodule；
3. 设计并实现自有 Runtime Adapter；
4. 再进入量化、VLM、RAG 和部署。

## 9. 项目边界

不纳入三个月主线：

- ROS2、SLAM、机器人和机械臂；
- DeepStream 多路视频、RTSP/RTMP；
- YOLO 主检测 pipeline；
- 大规模并发和分布式推理；
- 实时全双工音视频；
- 从零实现 GGML/CUDA kernel；
- 未经实验的蒸馏或剪枝成果；
- 未经实测的性能结论。

## 10. 项目最终定位

> **基于 llama.cpp-omni 二次开发的 Jetson 端侧离线 LLM/VLM Runtime、量化评测与设备故障辅助系统。**

项目的核心价值不是复制上游源码，而是形成以下可复现闭环：

~~~text
模型与 GGUF 校验
        ↓
Jetson CUDA Runtime 与自有 Adapter
        ↓
LLM/VLM、Prefill/Decode、KV Cache
        ↓
量化、资源和质量评测
        ↓
本地 RAG 与受限工具业务验证
        ↓
离线服务、监控和异常恢复
~~~
