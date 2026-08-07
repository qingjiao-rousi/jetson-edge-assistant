# 架构与配置所有权

EdgeOmni 在 Jetson AGX Orin ARM64/CUDA 上离线运行。`runtime/` 是基于 `llama.cpp-omni` 的 C++ 二次开发层，负责模型调用、HTTP/JSON/SSE、取消/超时、单图 VLM 和单热文本 KV Prefix reuse；`app/` 负责本地检索、引用、受限 Agent 与终端/音频适配。没有重新实现 GGML、GGUF、CUDA kernel、`mtmd` 或 KV Cache。

## 配置合同

`configs/assistant.json` 是唯一顶层运行合同：

- `runtime`：127.0.0.1 endpoint、端口、Runtime 可执行文件、GGUF/MMProj 路径与校验元数据，以及服务上下文参数。
- `rag.database`：唯一活动 RAG SQLite 路径。
- `modules`：模块配置位置；`agent_command`：旧 JSONL/语音入口共用的兼容命令。

模块配置不再重复上述值：`manual-qa.json` 只拥有检索/embedding 配置引用与生成上限；`voice-gateway.json` 只拥有音频设备、模型和半双工参数；`embedding.json` 保留 embedding 资产和建库合同。所有配置路径都必须为仓库相对路径，解析层拒绝绝对路径和 `..`。

`edgeomni_vlm_service_host` 接收明确的 `--model`、`--mmproj`、哈希、大小和服务参数，不再内置模型路径。`scripts/run_local_assistant.py` 根据顶层合同传递这些参数，运行前只读检查可执行文件、模型大小和 SQLite，Runtime 继续在加载时验证资产哈希。

## 兼容与迁移

新默认入口是：

```bash
python3 scripts/run_local_assistant.py
python3 scripts/run_local_assistant.py --config configs/assistant.json
```

统一启动器会把传入的 `--config` 原样传给 Runtime 启动合同和终端 Assistant，二者不会回退到默认配置。旧 `run_assistant.py` 继续只连接已就绪 Runtime；`run_agent.py` 的 `--config` 现在应指向顶层 `configs/assistant.json`（默认已更新）；`run_voice_gateway.py` 保留 `--config configs/voice-gateway.json`，并通过 `--assistant-config` 取得唯一 Agent 命令。旧版 `manual-qa.json` 若仍含 `database` 或 `model_endpoint`，需要移除这两个字段并升级为 schema version 2。

终端 `/image <仓库内相对图片路径> [可选问题]` 直接调用 `<runtime.base_url>/v1/diagnose/image`，每次仅发送一张 PNG、JPEG 或 WebP，且固定使用非流式 JSON。该路径不进入 RAG、Agent 或 SessionStore，不产生引用，也不支持视频、多图、批处理、并发或生产服务语义。
