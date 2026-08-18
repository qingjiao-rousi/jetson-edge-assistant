# 当前开发指南

本项目的日常开发只修改主线目录。`tools/`、`evidence/` 和 `archive/` 分别用于开发辅助、冻结证据和历史实验，不应承载新的应用功能。

| 想优化的内容 | 主要目录 |
| --- | --- |
| 模型推理、KV Cache、并发、HTTP 服务 | `runtime/` |
| 检索、引用、工具调用、多会话 | `app/agent/`、`app/retrieval/`、`app/qa/` |
| 终端 UI、后续 Web UI | `app/ui/` |
| ASR、VAD、TTS、音频播放 | `app/audio/` |
| 模型路径、阈值、音频设备 | `configs/` |
| 手册内容、故障码事实 | `knowledge/`、`configs/fault-codes.json` |
| 改动验证 | `tests/` |

## 运行边界

- `runtime/` 是 C++ LLM/VLM Runtime，负责模型推理和 HTTP/SSE 服务；`MtmdBackend` 主路径已整合 text-only 单热 KV Prefix reuse，按完整 batch 边界复用。
- `app/` 是 Python 应用层，负责 RAG、受限 Agent、UI 和语音编排。
- `app/assistant/` 是统一应用编排层：它连接独立常驻的 C++ Runtime HTTP 服务与进程内
  Agent/RAG/ReadOnlyTools/SessionStore，再由终端与半双工音频适配器使用。
- `scripts/` 只保留薄启动器，不能再放完整业务实现。
- `tests/` 只验证 `runtime/` 与 `app/` 的行为；测试代码不是运行服务实现。
- `configs/` 只保留当前运行配置；冻结阶段配置应在 `evidence/`，旧实验配置应在 `archive/`。

## 当前能力边界

M10.1 在实际 Qwen2.5-VL `MtmdBackend` 提供 text-only 单热 Session 的 KV Prefix reuse：只保留一个 hot session，按完整 batch 边界复用；图像请求、session 切换、timeout、cancel 和 reset 会失效。底层 KV memory/API 由 `llama.cpp-omni` 提供。M10.2 提供受限、进程内多会话 Agent：最多 8 个 Session、每 Session 最多 20 轮、只读工具与 citation 门禁；RAG/Agent 尚未向 Runtime 传递 `session_id`。它不是生产级多用户系统，不支持 Runtime 层多 Session KV、持久化、鉴权、LRU/TTL 或跨进程共享。

每个 Runtime 和 Agent 进程仅记录最近 256 个**已完成** request-id；活动 ID 和这 256 个 ID 会被拒绝为重复，达到容量后最早完成的 ID 被遗忘并可再次提交。该机制只限制单进程内存增长并便于诊断，不是生产幂等服务，不提供 TTL、LRU、多租户隔离、持久化或跨进程共享。

## 活动 RAG 路径

业务层只经 `app/retrieval/active_pipeline.py` 查询 RAG；`app/qa/manual_qa.py` 是该入口的应用消费者。当前入口保留冻结的 R2.5 query-time fact-family gate 和全部原有阈值、参数与响应合同。它读取的是 R2.2 SQLite index 合同：R2.2 负责已生成 SQLite 的索引元数据，R2.5 不重建或改写索引，只在查询时在冻结 R2 基础排序结果之上执行 gate。

`core.py`、`retrieval.py`、`embedding.py`、`hybrid.py`、`lexical.py` 和 `engine.py` 是保留的历史/基础实现，其中阶段名称只用于实现溯源与冻结证据。不要让新的业务模块直接依赖这些带 R2.1/R2.2/R2.4/R2.5 阶段名称的文件。M9.1B R2.5 仍为 PARTIAL；holdout 已消费，不能重跑、修改或用于调参。

## 统一 Assistant

默认入口由启动器管理 Runtime 和终端 Assistant：

```bash
python3 scripts/run_local_assistant.py
python3 scripts/run_local_assistant.py --speak
```

顶层 `configs/assistant.json` 拥有 Runtime endpoint/端口/资产与活动 RAG SQLite；模块配置只保留其
专属参数。启动器拒绝被占用的端口，启动 C++ Runtime、轮询 `/ready`，再运行 Assistant，退出时按
Assistant 后 Runtime 的顺序清理。它只读检查 Runtime 模型、MMProj、可执行文件和 RAG SQLite，不下载、
构建或改写资产。Runtime 的底层 CUDA/ggml 输出保存到临时诊断日志；ready 前失败时启动器会报告其路径。`--speak` 首次实际播放时才检查 TTS 模型和输出设备，失败不会中止文本会话；首次
`/listen` 才检查 ASR、VAD 与输入设备。语音路径仍是半双工原型，未完成外接麦克风实测、AEC、打断、
流式 TTS 或全双工。M9.1B R2.5 为 PARTIAL，M10.1 不是生产多用户 KV，M10.2 没有持久化/鉴权，
Docker/systemd 与长稳运行也未完成。

`scripts/run_assistant.py` 可继续用于已自行启动的 Runtime；`run_agent.py`、`run_chat_console.py`、
`run_voice_gateway.py` 是兼容入口。详见 [架构与配置所有权](../architecture.md)。

每次修改主线代码后，至少运行：

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
git diff --check
```
