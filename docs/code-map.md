# EdgeOmni 代码地图

这份地图用于从 GitHub clone 后快速区分默认运行主线、可选入口、实验工具和历史资料。

## 从哪里开始

模型无关验证：

```bash
bash scripts/verify_public_repo.sh
```

资产和 Runtime 已准备好时，默认启动入口只有一个：

```bash
python3 scripts/run_local_assistant.py
```

## 默认运行主线

```text
scripts/run_local_assistant.py       启动 Runtime，轮询 /ready，再启动 Assistant
  -> configs/assistant.json          绑定 Runtime、模型、MMProj、RAG 和模块配置
  -> runtime/tools/vlm_service_host.cpp
     -> runtime/src/service.cpp      HTTP/JSON/SSE、请求状态、超时与取消
     -> runtime/src/mtmd_backend.cpp Qwen2.5-VL 文本/单图推理与单热 Prefix reuse
     -> third_party/llama.cpp-omni   上游 GGUF/GGML/CUDA/mtmd 能力
  -> scripts/run_assistant.py
     -> app/assistant/application.py 终端应用装配、预检和单图请求
     -> app/agent/service.py         有界只读 Agent 与 SessionStore
     -> app/qa/manual_qa.py          RAG 问答、引用与拒答门禁
     -> app/retrieval/active_pipeline.py
        -> app/retrieval/engine.py   当前冻结的 R2.5 query-time 检索路径
```

建议按上述顺序阅读。接口声明位于 `runtime/include/edgeomni/`，测试位于
`runtime/tests/`、`tests/unit/` 和 `tests/integration/`。

## 可选入口

| 入口 | 用途 |
| --- | --- |
| `scripts/run_assistant.py` | 连接已经启动并 ready 的 Runtime |
| `scripts/run_agent.py` | 独立运行 Agent/JSONL 适配器 |
| `scripts/run_voice_gateway.py` | 实验性半双工语音适配器 |
| `scripts/verify_local_assets.py` | 校验 submodule、模型、ELF 和 SQLite 离线合同 |
| `scripts/verify_relocatable_bundle.py` | 审计可移动 bundle 的 ELF、RPATH、依赖和 manifest |

## 实验与历史材料

以下内容不属于默认启动链路：

- `scripts/*opt1*`、`scripts/validate_mtmd_prefix_reuse.py`：Prefix reuse 实验与审计；
- `scripts/run_jetson_benchmark.py`、`benchmarks/`：Jetson benchmark 工具和 reviewed 报告；
- `app/retrieval/r2_6_candidate.py`、对应配置和测试：未进入默认路径的 RAG 候选；
- `archive/`：已归档实验；
- `project-docs/`：立项、计划和阶段复盘资料。

当前事实以 `README.md`、`docs/architecture.md`、`docs/jetson-validation.md` 和
`docs/limitations.md` 为准；历史材料不能覆盖这些文档的状态结论。

## GitHub clone 的边界

GitHub 可以恢复源码、submodule、配置、文档、fixture 和模型无关测试。GGUF、MMProj、
embedding 模型、RAG SQLite、Jetson 上游构建产物及本地日志不会随 Git 分发，完整实机运行
仍需按 `docs/jetson-offline-setup.md` 准备离线资产。
