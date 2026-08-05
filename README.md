# EdgeOmni Jetson 端侧离线多模态项目

本仓库是在 `llama.cpp-omni` Runtime 基础上进行的 Jetson AGX Orin
ARM64/CUDA 二次开发，目标是形成离线文本/图片推理、设备手册检索、受限工具和
可部署的工业设备故障辅助后端。项目没有从零实现 GGUF、GGML、CUDA kernel、
KV Cache 或 `mtmd`；自研范围主要是 Jetson 适配、Runtime/Service 封装、资产
门禁、评测、应用 API、RAG 集成和部署验证。

## 当前阶段

状态日期：2026-08-05。

项目已完成第 1～8 周的 Jetson 基线、文本 Runtime、量化评测、VLM 图片链路和
应用单图 API、M9.2 手册问答原型和 M10.1 单热文本 KV Prefix 复用。M9.1B 已完成多文档索引、经审计的
Qwen3-Embedding-0.6B Q8_0、本地向量/FTS5 混合检索、设备/故障码约束、引用和
一次性最终评测流程。最新 R2.5 的 calibration 与 diagnostic 均通过，但独立
holdout 的无答案拒绝率为 `0.50`、误命中为 `1`，未通过冻结质量门，M9.1B 仍为
`PARTIAL`，不得重跑或用该 holdout 调参。M9.2 已完成“本地手册检索 + citation + 本地模型带来源回答”的原型闭环。M10.1 已完成单热文本 session 的 Token 级 KV Prefix 复用并完成 Jetson 冷/热/分叉验证。当前阶段为项目交付归档/演示准备，定位仍是“可集成的端侧 LLM/VLM Runtime 与 RAG 检索原型”，不是生产版本、完整工业全双工音视频系统或多用户会话系统。

| 模块 | 状态 | 已有证据 |
| --- | --- | --- |
| Jetson/CUDA 基线 | 已完成 | ARM64 Release 构建、37/37 CUDA offload、环境与构建 manifest |
| 文本 Runtime/Service | 已完成阶段验收 | DirectBackend、HTTP/JSON/SSE、timeout/cancel/reset、单元与真实模型集成记录 |
| Q4/Q8 与 KV 基线 | 已完成 M6 冻结 | Q4/Q8 各 15 次有效测量；部署优先 Q4；KV 固定 F16/F16 |
| VLM Runtime/应用 API | 已完成 M8 冻结 | 固定 VLM/mmproj、4096/8192 冒烟、16384 实验、单常驻三图及应用 API 单图闭环 |
| RAG | M9.1B PARTIAL | R2.5 校准/诊断通过；最终 12 题 holdout R@1/3/MRR=0.875/0.875/0.875，但拒绝率=0.50、误命中=1，质量门失败 |
| 手册问答原型 | M9.2 已实现 | 检索有证据才调用本地 `/v1/chat`；回答保留检索引用，无证据不生成 |
| KV 多轮/Prefix 复用 | M10.1 已完成 | 单热文本 session、Token LCP、分叉回滚、异常失效；冷/热输出一致 |
| 工具/Agent/多会话 | 未交付 | 不属于当前收口范围；没有多用户会话、LRU/TTL 或缓存池 |
| Docker/systemd/长稳 | 未开始 | 仅有部署设计，无配置、镜像或恢复记录 |

完整判断、证据边界、测试结果和下一步见 [项目状态总结](md/总结.md)。

## 文档导航

- [项目状态总结](md/总结.md)：当前状态的唯一权威入口；回答“完成了什么、做到哪一步”。
- [三个月计划与执行清单](md/三个月开发计划与执行清单.md)：周次、阶段门和待办。
- [项目交付文档](md/项目交付文档.md)：范围、架构、验收状态和交接边界。
- [第 8 周周报](md/week/第08周周报-VLM应用API与阶段冻结.md)：最近一个已冻结阶段。
- [第 7 周 VLM 报告](docs/evaluation/vlm-week-7-report.md)：VLM 资产、context、服务实测证据。
- [M9.1A RAG 设计](docs/design/rag-markdown-m9.1a.md)：当前 RAG MVP 的明确能力边界。
- [M9.1B 混合检索设计](docs/design/rag-hybrid-m9.1b.md)：多文档、向量/混合检索和资产门禁。
- [M9.1B R2.5 最终评测](docs/evaluation/rag-hybrid-m9.1b-r2.5-holdout-public.md)：最新质量门结论与公开审计信息。
- [项目方向复盘](docs/reviews/project-direction-20260805.md)：主线一致性、当前偏差风险与收口后的下一步。
- [M10.1 KV Prefix 复用设计](docs/design/kv-prefix-reuse-m10.1.md)：单热文本会话的
  Token 级复用、失效策略、指标和验收门。
- [M10.1 KV Prefix 实机评测](docs/evaluation/kv-prefix-reuse-m10.1.md)：固定 Qwen3 模型上的冷、热和分叉结果。
- `docs/design/`：设计协议；`docs/evaluation/`：冻结评测结论；
  `benchmark-results/`：原始运行证据；`manifests/`：环境、模型和部署决策。

历史设计文档记录当时的阶段状态，出现“待实现”时不代表当前仍未实现；当前判断
以本页和 `md/总结.md` 的状态日期为准，性能与功能结论仍以对应冻结报告为准。

## 本地验证

```bash
cmake -S . -B build-audit \
  -DEDGEOMNI_BUILD_TESTS=ON \
  -DEDGEOMNI_BUILD_BENCHMARK_TOOLS=ON \
  -DEDGEOMNI_BUILD_INTEGRATION=OFF
cmake --build build-audit -j2
ctest --test-dir build-audit --output-on-failure
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

`edgeomni_service_unit_test` 需要绑定本机 loopback；受限沙盒中会明确返回
`BLOCKED_LOOPBACK`，应在允许本机回环网络的宿主环境复跑。测试命令不等同于
真实 GGUF/VLM 集成测试；实机结论应查阅 `docs/evaluation/` 和
`benchmark-results/`。
