# Jetson 端侧离线多模态推理与设备故障辅助系统 — CLAUDE.md

> 本文档供 Claude Code 及其他 AI 编码助手使用，自动加载为会话上下文。

## 项目身份

**项目名称**: Jetson 端侧离线多模态推理与设备故障辅助系统
**硬件平台**: Jetson AGX Orin 32GB
**核心能力**: 离线 LLM/VLM 推理、GGUF/量化、KV Cache、Prefill/Decode、本地 RAG、受限工具和 systemd/Docker 部署
**当前状态**: LLM、CUDA 全层 offload 和 Jetson 指标基线已验证；固定 benchmark、自有 Runtime、VLM、RAG 和部署待实现
**项目周期**: 三个月业务主线；蒸馏或剪枝仅作为独立个人研究扩展

## 设计文档

对话中可按需读取：

- [业务背景、范围和成果表述边界](md/项目背景.md)
- [项目概述与模块设计](md/项目实践-jetson端侧离线多模态智能助手.md)
- [任务需求与技术设计说明](md/项目实践-jetson端侧离线多模态智能助手-任务需求与技术设计说明.md)
- [三个月开发计划与执行清单](md/三个月开发计划与执行清单.md)

## 参考上游项目

### llama.cpp-omni（核心 Runtime 后端）

```
路径: ../llama.cpp-omni-master/
关键目录:
  examples/    — 官方示例（simple, simple-chat, server, llava 等）
  tools/       — 命令行工具（main, server, omni, mtmd, quantize, perplexity 等）
  src/         — C++ 核心源码
  include/     — 公共头文件
  ggml/        — 底层张量计算库
  common/      — 公共工具代码
  gguf-py/     — Python GGUF 读写工具
  models/      — 模型支持（qwen2vl, internvl, llama 等）
  docs/        — 文档（build.md, 模型添加指南等）
  AGENTS.md    — 上游的 AI 助手协作规范（务必先读）
```

当前 `../llama.cpp-omni-master/` 是已验证但缺少 `.git` 元数据的源码快照，除已记录的 CMake 修复外不再直接扩展。正式二次开发应使用带 Git 元数据的个人 fork，并由主项目通过 submodule 或固定 commit 接入。

### autonomous-intelligence（借鉴应用层架构）

```
路径: ../autonomous-intelligence-main/
关键目录:
  TauLegacy/   — 主对话循环、记忆、事件通信、语音/视觉服务
  baby-tau/    — 简化版实现
  Vision/      — 视觉服务模块
  qq/          — 编码助手 Agent
  jetson-super/— Jetson Orin Nano 上手指南
  AGENTS.md    — 开发的 Python 代码规范（lint/test/type check）
```

### 参考项目的使用原则

- **llama.cpp-omni** — 当前快照只用于基线；正式 Runtime 修改进入个人 fork，自有接口位于 `runtime/` 或 `app/backend/`
- **autonomous-intelligence** — 借鉴其持续对话、记忆摘要、事件驱动服务拆分的架构思路，用本地组件替代云端依赖（Pinecone→本地向量库、OpenAI→本地模型、Whisper→faster-whisper 等）

## 项目代码组织（设计阶段）

```
vlmllm-main/
  md/              — 设计文档
  runtime/         — 自有 C++ Runtime Adapter
  third_party/     — 固定个人 fork/submodule
  patches/         — 上游修复和快照补丁
  app/             — 自有代码（后续创建）
    backend/       — llama.cpp-omni 适配层
    request/       — 请求处理
    response/      — 响应处理
    metrics/       — 性能指标
    tools/         — 工具调用
    rag/           — 本地 RAG
  models/          — 模型文件
  configs/         — 配置文件
  scripts/         — 部署脚本
  tests/           — 测试
  docker/          — Docker 相关
  docs/            — 自有文档
```

## 架构原则

1. **上游隔离** — 不修改上游仓库代码；通过 Adapter 层隔离上游 API 变化
2. **先基线再优化** — 先跑通上游官方最小示例，记录性能基线，再开始二开
3. **离线优先** — 所有云端依赖必须有本地替代方案；暂时无法替代的标注为"开发期 fallback"
4. **实测说话** — 不允许用未实测的性能数据作为结论；每个量化格式/模型都要记录实际 TTFT、TPOT、显存
5. **接口先于实现** — 先定接口签名（如 `initialize(config)`, `generate_text(request)`, `stream_generate()`），再基于实际 API 写适配器
6. **渐进式拆分** — 初期先在单进程中跑通模块接口，确认功能后再拆成独立进程/服务

## 研发阶段

| 阶段 | 内容 | 当前状态 |
|------|------|---------|
| 一：基线 | 环境、构建、模型、CUDA offload、原始日志 | 基本完成，待固定 benchmark 和源码追溯 |
| 二：自有 Runtime | Backend、生命周期、流式、超时、取消、metrics | 待开始 |
| 三：量化性能 | Q4/Q8、KV Cache、Prefill/Decode | 待开始 |
| 四：业务闭环 | VLM 图片、本地 RAG、受限工具 | 待开始 |
| 五：生产化 | systemd/Docker、健康检查、回滚、长稳 | 待开始 |
| 独立研究 | 蒸馏或结构化剪枝二选一 | 非业务承诺，待选题 |

## 关键非功能需求

- 完全离线运行
- 记录 TTFT、TPOT、tokens/s、GPU/RAM/温度/功耗
- 支持服务退出、重启、异常恢复
- Docker + systemd 部署
- 模型版本管理和回滚

## 项目边界（不做的事）

- 机器人、ROS2、SLAM、机械臂
- DeepStream 多路视频、RTSP/RTMP
- YOLO 主检测 pipeline（这些属于另一个项目）
- 不预先承诺 TensorRT-LLM 一定支持 Jetson

---

## 与 Claude 的协作约定

本节告诉 Claude **每次对话应该如何展开**，确保输出质量和可控性。

1. **分步执行** — 每次只推进阶段规划中的一个步骤；完成一步、确认结果后，再进行下一步
2. **修改前告知** — 在创建或修改任何文件之前，先说明会动哪些文件、为什么
3. **引用上游代码必须精确** — 引用 llama.cpp-omni 或 autonomous-intelligence 中的代码时，必须标注文件路径和行号
4. **不假设 API** — 不确定的函数签名先去上游仓库搜索确认，不能用"应该"、"可能是"来猜测
5. **标注文件类型** — 输出代码时明确标注是"新建文件"还是"修改已有文件"
6. **离线替换提醒** — 如果拟议的方案中出现了云端依赖（OpenAI API、Pinecone 等），主动提醒并给出本地替代建议
7. **性能结论要实测** — 涉及模型速度、显存、精度等性能判断时，必须基于实际测量数据，不能推测
8. **先设计再实现** — 涉及新模块或多文件修改时，先输出接口设计让用户确认，再写实现代码
9. **保持上游分离** — 自有代码写在 `app/` 下，不修改 `../llama.cpp-omni-master/` 或 `../autonomous-intelligence-main/`
