# 公开 Demo 指南

本页定义可公开复核的演示证据，不提供预先制作的假截图。`docs/assets/` 当前只有证据规范；文字版 Jetson smoke 已冻结，终端录屏、截图和对应脱敏文本仍为**可选展示增强**。

## Demo A：离线终端 RAG 问答

资产齐备并通过 `assistant` profile 后运行：

```bash
python3 scripts/run_local_assistant.py
```

建议使用已验证的问题 `What outlet pressure does BX-9 specify?` 或 `What does alarm E42 mean on the BX-9?`。公开证据必须同时显示：问题、回答中的 `[S1]` 引用、引用对应的 `document_id/chunk_id`，以及无证据问题的拒答。不得展示私有手册、真实设备序列号或未脱敏路径。

状态：已有 Jetson 文字版引用/拒答 smoke；截图/GIF 为可选增强。代码合同可由 `tests/integration/test_manual_qa.py` 和 Agent 单元测试复核；这不等于 RAG 最终质量门通过，R2.5 仍为 PARTIAL。

## Demo B：单图诊断

在同一终端执行：

```text
/image tests/fixtures/vlm-service/synthetic-alarm-panel.png
```

公开证据应显示 Runtime ready、图片相对路径、非空模型结果和“未经过 RAG 检索或引用校验”的提示。不得把该固定合成图冒烟写成故障诊断准确率，也不得暗示视频、多图、批处理或并发能力。

状态：已有文字版冻结冒烟记录，见 [Jetson 验证](jetson-validation.md)；截图/GIF 为可选增强。

## Demo C：Runtime API/SSE

运行一次文本 SSE 请求并保留 `metadata -> token -> done` 顺序、HTTP 状态和 request-id。请求体中的模型 hash 应与配置合同一致，日志不得包含模型权重、Base64 图像、账号或机器私有路径。

状态：FakeBackend 合同由 `runtime/tests/service_unit_test.cpp` 覆盖；真实 Jetson SSE 录屏**待实测**。

## 证据文件规范

将可公开材料放到 `docs/assets/`，推荐名称：

- `terminal-rag-citations.png`
- `terminal-rag-refusal.png`
- `single-image-diagnosis.gif`
- `runtime-sse-redacted.txt`
- `jetson-environment-redacted.txt`

每项证据旁应记录 commit、模型量化与 SHA-256 前 12 位、L4T/CUDA、功耗模式、命令、时间和已知限制。原始 `tegrastats`/benchmark 日志留在忽略目录，通过聚合后的 CSV/Markdown 对外发布。
