# EdgeOmni Jetson 端侧离线多模态项目

本仓库是在 `llama.cpp-omni` Runtime 基础上进行的 Jetson AGX Orin
ARM64/CUDA 二次开发，目标是形成离线文本/图片推理、设备手册检索、受限工具和
可部署的工业设备故障辅助后端。项目没有从零实现 GGUF、GGML、CUDA kernel、
KV Cache 或 `mtmd`；自研范围主要是 Jetson 适配、Runtime/Service 封装、资产
门禁、评测、应用 API、RAG 集成和部署验证。

## 当前阶段

状态日期：2026-08-04。

项目已完成第 1～8 周的 Jetson 基线、文本 Runtime、量化评测、VLM 图片链路和
应用单图 API，当前进入第 9 周 RAG 阶段。M9.1A 已完成单份合成 Markdown 手册
的 SQLite FTS5 关键词检索 MVP；本地 embedding/向量检索、RAG 与 VLM 的回答
生成闭环仍未完成。因此当前定位是“可集成的端侧 LLM/VLM Runtime 与 RAG
检索原型”，还不是完整设备故障辅助系统，也不是生产部署版本。

| 模块 | 状态 | 已有证据 |
| --- | --- | --- |
| Jetson/CUDA 基线 | 已完成 | ARM64 Release 构建、37/37 CUDA offload、环境与构建 manifest |
| 文本 Runtime/Service | 已完成阶段验收 | DirectBackend、HTTP/JSON/SSE、timeout/cancel/reset、单元与真实模型集成记录 |
| Q4/Q8 与 KV 基线 | 已完成 M6 冻结 | Q4/Q8 各 15 次有效测量；部署优先 Q4；KV 固定 F16/F16 |
| VLM Runtime/应用 API | 已完成 M8 冻结 | 固定 VLM/mmproj、4096/8192 冒烟、16384 实验、单常驻三图及应用 API 单图闭环 |
| RAG | 进行中 | M9.1A 单文档 Markdown + FTS5 关键词检索、稳定引用、无命中返回 |
| KV 多轮/Prefix 复用 | 计划中 | M10.1 已有设计；当前仍逐请求清空 KV，无命中证据 |
| 工具/Agent/多会话 | 未开始 | 仅有需求与验收设计；真正多 session 在 M10.1 后评估 |
| Docker/systemd/长稳 | 未开始 | 仅有部署设计，无配置、镜像或恢复记录 |

完整判断、证据边界、测试结果和下一步见 [项目状态总结](md/总结.md)。

## 文档导航

- [项目状态总结](md/总结.md)：当前状态的唯一权威入口；回答“完成了什么、做到哪一步”。
- [三个月计划与执行清单](md/三个月开发计划与执行清单.md)：周次、阶段门和待办。
- [项目交付文档](md/项目交付文档.md)：范围、架构、验收状态和交接边界。
- [第 8 周周报](md/week/第08周周报-VLM应用API与阶段冻结.md)：最近一个已冻结阶段。
- [第 7 周 VLM 报告](docs/evaluation/vlm-week-7-report.md)：VLM 资产、context、服务实测证据。
- [M9.1A RAG 设计](docs/design/rag-markdown-m9.1a.md)：当前 RAG MVP 的明确能力边界。
- [M10.1 KV Prefix 复用设计](docs/design/kv-prefix-reuse-m10.1.md)：单热文本会话的
  Token 级复用、失效策略、指标和验收门。
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
