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

- `runtime/` 是 C++ LLM/VLM Runtime，负责模型推理、KV Prefix 复用和 HTTP/SSE 服务。
- `app/` 是 Python 应用层，负责 RAG、受限 Agent、UI 和语音编排。
- `scripts/` 只保留薄启动器，不能再放完整业务实现。
- `tests/` 只验证 `runtime/` 与 `app/` 的行为；测试代码不是运行服务实现。
- `configs/` 只保留当前运行配置；冻结阶段配置应在 `evidence/`，旧实验配置应在 `archive/`。

## 当前能力边界

M10.1 提供单热文本 Session 的 KV Prefix 复用。M10.2 提供受限、进程内多会话 Agent：最多 8 个 Session、每 Session 最多 20 轮、只读工具与 citation 门禁。它不是生产级多用户系统，不支持 Runtime 层多 Session KV、持久化、鉴权、LRU/TTL 或跨进程共享。

每次修改主线代码后，至少运行：

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
git diff --check
```
