# EdgeOmni 秋招作品集评审（2026-08-12）

本报告基于当前源码、文档、测试、Git 状态和固定 submodule 审查。没有公开证据的性能、功耗、资源、准确率和稳定性结论均标为“待实测”或“不足以证明”。

## 第一阶段：问题清单

| 优先级 | 问题 | 证据 | 招聘影响 | 修复 | 可立即修改 |
| --- | --- | --- | --- | --- | --- |
| P0 | 首屏缺少贡献/上游对照、验证矩阵和证据入口 | 旧 `README.md`；所有权原仅见 `docs/architecture.md` 概述 | 容易误归属上游能力，真实性判断成本高 | 重构 README，首屏披露 PARTIAL、单热 KV 和证据缺口 | 已完成 |
| P0 | Q4/Q8 原只有冻结摘要，缺少公开数值和完整口径 | `docs/jetson-validation.md`；原始 evidence 被忽略 | TTFT/TPS/功耗/内存追问无法公开复核 | 增加协议、采集器和 reviewed CSV | Q4/Q8 clean-commit 配对文本基线已完成 |
| P0 | 根目录无许可证和第三方声明 | 旧仓库无 `LICENSE`/notice；submodule 自带 MIT | 公开使用和贡献边界不明 | Apache-2.0 + 独立上游/模型声明 | 已完成 |
| P0 | 无 CI 和统一验证入口 | 旧仓库无 `.github/workflows/` | clean clone 工程质量不可持续复核 | 模型无关 CI + 一键只读验证 | 已完成 |
| P0 | Demo 只有 fixture/文字记录，没有公开截图/GIF | `tests/fixtures/vlm-service/`、`docs/jetson-validation.md` | 不能快速展示实际交互 | 建证据规范；真实素材待 Jetson 脱敏补充 | 规范已完成，素材待补 |
| P0 | 默认 RAG importer 曾指向未跟踪文件，且混有 R2.6 实验 | `app/qa/manual_qa.py`、`app/retrieval/active_pipeline.py` | 若只提交 tracked diff，发布即缺模块；实验/主线结论混淆 | 原子提交 active pipeline；R2.6 独立实验提交 | 已按 `e097c63`/`2fdb604` 隔离 |
| P0 | 子模块固定 commit，但 URL 使用 SSH | 旧 `.gitmodules`；gitlink `19cc269...` | 无 GitHub SSH key 时 clone 摩擦 | 改 HTTPS，commit 仍由 gitlink/合同固定 | 已完成 |
| P0 | “最短启动”其实预设 Runtime/模型/SQLite 已存在 | 旧 `README.md`；`runtime/CMakeLists.txt` 导入冻结 build tree | clone 后照抄不能运行 | 分开 clone 后验证与资产齐备运行 | 已完成 |
| P0 | 架构缺完整数据流、所有权表和验证边界图 | 旧 `docs/architecture.md` | 二次开发深度不直观 | 增加 Mermaid、所有权矩阵、KV 状态边界 | 已完成 |
| P0 | `.gitignore` 缺 `.env`、coverage、core/log 等 | 旧 `.gitignore` | 演示/调试产物有误提交风险 | 扩充规则并检查可发布文件 | 已完成 |
| P1 | 未记录独立 clean clone + 离线资产包演练 | `docs/jetson-offline-setup.md` | 只能称“合同已定义”，不能称跨机器可复现 | 新目录/第二设备演练并保存脱敏记录 | 需 Jetson/资产 |
| P1 | 当前 C++ HTTP 测试因沙箱回环限制 skip | CTest 的 `edgeomni_service_unit_test` | 不能表述为 5/5 全通过 | 在允许 loopback 的 runner/Jetson 重跑 | 需合适环境 |
| P1 | Docker/systemd、鉴权、高并发未完成 | `docs/limitations.md` | 不影响原型核心，强行列 P0 会过度包装 | systemd 可 P1；Docker/生产化按目标岗位放 P1/P2 | 不应作为 P0 |
| P1 | 缺贡献、Issue、Roadmap、Release 入口 | 旧根目录和 `.github/` | 治理成熟度较弱 | 增加轻量模板和 changelog | 已完成 |

硬编码检查未发现用户目录绝对路径。`127.0.0.1:18086` 是显式 loopback 合同，不是机器路径。模型、SQLite、构建树和本地 evidence 均被忽略，未发现被主仓库跟踪的大模型文件。

## 第二阶段：P0 改造计划与验收

### P0-1：招聘者首屏与最短路径
- 目标：30 秒读懂场景、贡献、证据和边界。
- 文件：`README.md`。
- 实现：所有权摘要、验证矩阵、clean-clone 检查与资产运行路径。
- 不包装：不把上游 GGML/CUDA/mtmd 称为自研。
- 验证：`bash scripts/verify_public_repo.sh`。
- 验收：PARTIAL、单热 KV、单图与待实测在首屏可见。
- 展示提升：降低招聘者判断成本。

### P0-2：架构与贡献边界
- 目标：说明调用链与本人二开范围。
- 文件：`docs/architecture.md`。
- 实现：数据流、组件所有权、单热 KV 状态和验证边界图。
- 不包装：不画多用户缓存、视频或生产调度。
- 验证：Markdown 链接检查。
- 验收：关键能力均归属 EdgeOmni、上游或外部资产。
- 展示提升：突出 C++ 服务/适配/状态管理深度。

### P0-3：公开 Demo 证据
- 目标：建立 RAG 引用、拒答、单图和 SSE 的公开证据入口。
- 文件：`docs/demo.md`、`docs/assets/README.md`。
- 实现：命令、命名、脱敏和元数据要求。
- 不包装：不制作假截图，不用合成图冒烟代替准确率。
- 验证：fixture/链接存在检查。
- 验收：真实素材清楚标为待补。
- 展示提升：形成可执行录屏清单。

### P0-4：模型无关 CI 与本地验证
- 目标：一条命令复核安全范围。
- 文件：`scripts/verify_public_repo.sh`、`scripts/check_public_repo.py`、`.github/workflows/ci.yml`。
- 实现：Python 测试、合同、链接、产物和 whitespace 检查。
- 不包装：CI 不验证 Jetson/CUDA/模型/性能。
- 验证：`bash scripts/verify_public_repo.sh`。
- 验收：clean clone 不需要模型或账号。
- 展示提升：持续工程证据。

### P0-5：性能协议与采集骨架
- 目标：统一 Q4/Q8、TTFT/TPS、资源/功耗/KV/稳定性口径。
- 文件：`docs/benchmark-protocol.md`、`benchmarks/`、`scripts/run_jetson_benchmark.sh`。
- 实现：1 次 warm-up + 15 次测量、环境字段、raw ignored output、空白 reviewed CSV。
- 不包装：不生成伪数据，不把 15 样本写成生产 p99。
- 验证：`scripts/run_jetson_benchmark.sh --dry-run`。
- 验收：采集器 dry-run 由 CI 覆盖；Q4 clean-commit 实测具备 reviewed 汇总和 raw artifact hash 绑定。
- 展示提升：让量化选择具备可复现实验方法。

### P0-6：发布卫生与合规
- 目标：降低泄漏、误提交和 clone 摩擦。
- 文件：`.gitignore`、`.gitmodules`、`LICENSE`、`THIRD_PARTY_NOTICES.md`。
- 实现：安全忽略项、HTTPS submodule、上游/模型许可边界。
- 不包装：根许可证不替代模型与第三方许可。
- 验证：合同、submodule commit、publishable-file 检查。
- 验收：无模型/索引/日志被主仓库跟踪。
- 展示提升：达到公开项目基础合规标准。

### P0-7：Roadmap、Issue 与 Release
- 目标：把未完成能力转化为可追踪范围。
- 文件：`ROADMAP.md`、`CONTRIBUTING.md`、`CHANGELOG.md`、`.github/ISSUE_TEMPLATE/`。
- 实现：P1/P2、Bug/证据模板、Unreleased 记录。
- 不包装：Roadmap 不代表已交付。
- 验证：链接检查。
- 验收：治理入口完整。
- 展示提升：体现范围与证据管理能力。

### P0-8：当前工作区发布隔离
- 目标：避免主线 importer 缺失和 R2.6 实验混入发布结论。
- 文件：`docs/release-checklist.md`、`CLAUDE.md`。
- 实现：原子提交规则、候选实验隔离、pass/skip/待实测披露。
- 不包装：不删除用户实验，不宣称 R2.6 通过。
- 验证：`git status --short` 和全工作区测试。
- 验收：发布前能明确未提交项的归属。
- 展示提升：避免不可复现的公开 commit。

## 第四阶段：招聘与公开展示

### 评分与定位

- 当前评分：**8.8/10**。
- 是否适合作为主项目：**适合端侧 AI 部署/C++ Runtime/Jetson 岗位的主项目**。当前已有同 commit Q4/Q8 配对文本、固定单图 E2E 和视觉阶段计时结果；投递前最值得补的是 2-3 个真实 Demo 截图/GIF、VLM 小型质量集和长稳记录。
- 主要加分：C++ Runtime 并非薄命令包装；HTTP/SSE/取消超时、`DirectBackend` 单热 KV 状态、资产合同、RAG/Agent 门禁和测试都有代码证据。
- 主要扣分：准确率/长稳仍缺公开证据、RAG PARTIAL、HTTP 测试本环境 skip、clean-clone+离线包未独立演练。

推荐 GitHub 标题：**EdgeOmni: Offline Multimodal RAG Assistant on Jetson AGX Orin**

一句话卖点：**在 Jetson AGX Orin 上将固定 `llama.cpp-omni` 上游能力封装为可审计的 C++ 文本/单图推理服务，并用本地 Hybrid RAG、引用门禁和受限 Agent 完成离线工业知识问答闭环。**

### 简历描述：端侧 AI 部署 / 推理优化 / C++ Runtime

- 基于固定 commit 的 `llama.cpp-omni` 二次开发 C++17 Runtime 服务层，设计 HTTP/JSON/SSE、`/ready`、结构化错误、超时/取消、单活动请求保护与可观测指标合同。
- 基于上游 KV memory API 在 `DirectBackend` 验证路径实现单热文本 session 的 Token LCP Prefix reuse，覆盖同前缀、分叉、回滚以及图像/取消/超时/异常失效；实际 Qwen2.5-VL `MtmdBackend` 接入与 Prefill/TTFT 实测列为独立优化课题，不包装为生产多用户缓存。
- 为 Qwen2.5-VL-3B GGUF 建立模型/MMProj 大小与 SHA-256、AArch64 ELF、submodule commit 和 SQLite source binding 的离线资产合同与只读 preflight。
- 建立 Q4_K_M/Q8_0 可复现实验协议与 Jetson 采集器；同一 clean commit 下各完成 15 次锁频请求，decode 中位数 15.101/15.227 token/s、统一 RAM 中位数 12,458/13,928 MB，并通过 SHA-256 绑定 Runtime/collector/raw evidence。
- 为固定合成单图建立 Q4/Q8 clean-commit E2E 对照：15/15 请求成功，Runtime total 中位数 1,530/1,462 ms，同时明确 `not_measured` 视觉阶段零值不可当作 0 ms 结论。
- 在后续 clean commit 接入结构化阶段计时并重测：Q4/Q8 vision encode 中位数 305/277 ms、embedding 注入 31/28 ms，所有阶段均带显式 measured 状态和原始证据哈希。

### 简历描述：嵌入式 AI / 边缘计算 / Jetson

- 面向 Jetson AGX Orin ARM64/CUDA 构建无云网络工业知识助手原型，整合本地文本/单图 VLM、SQLite/FTS5 Hybrid RAG、终端和实验性半双工语音链路。
- 设计离线交付合同和统一启动器：拒绝端口复用，启动后轮询 `/ready`，按仓库相对路径校验模型/索引，失败保留诊断日志并回收子进程。
- 实现设备/故障码约束、无证据短路、引用保留/citation gate 以及有界只读 Agent/SessionStore，降低离线维护问答的无依据生成风险。
- 在 Jetson AGX Orin MODE_30W 锁频环境记录 37/37 CUDA layer offload 和 Q4 文本基线，并完成固定单图冒烟；明确视频、多图、高并发、生产鉴权和长稳仍未完成。

### 招聘者可能追问的 10 个问题与建议回答

1. **你与 llama.cpp-omni 的边界是什么？** 上游负责 GGUF/GGML、CUDA、加载、tokenizer/sampler 和 mtmd；我负责服务合同、适配、状态管理、RAG/Agent/启动与离线校验，证据在 `docs/architecture.md` 的所有权表。
2. **KV 优化是不是自己写了 KV Cache？** 不是。底层 KV 由上游提供；当前在 `DirectBackend` 实现的是单 hot session 的 Token LCP、KV 范围保留/回滚和失效策略，不是 paged KV 或多用户缓存。Qwen2.5-VL 主路径接入仍处于计划阶段，不能提前宣称收益。
3. **为什么只能单热 session？** 当前 Runtime 串行化 backend，并只保存一组 session_id/prompt tokens；这是为了受控内存和可验证状态。多 session 需要内存预算、调度与淘汰策略，不能用 Agent 的 8 个逻辑 session 代替。
4. **Q4 为什么优先于 Q8？快多少？** 配对文本结果中 Q8 decode 仅高 0.83%、总延迟低 0.81%，应视为近似持平；但 Q8 统一 RAM 多 1,470 MB、CUDA model buffer 多 1,292.78 MiB、model ready 慢 43.4%，所以 Q4 的优势是资源效率，不是速度更快。该结论不外推到图像或长上下文。
5. **37/37 offload 能说明什么？** 只说明模型层按记录被 CUDA offload，不证明全部算子、端到端性能、功耗或稳定性达标。
6. **RAG 为什么是 PARTIAL？** 冻结 holdout 已消费且最终质量门未通过，不能重跑调参。当前路径保留 R2.5 query gate 和引用/拒答合同；新候选必须使用独立 dev/eval 设计。
7. **怎样防止无依据回答？** 检索先做设备/故障码和 evidence admission；无证据时不调用模型。生成后校验引用是否属于该 session 的检索结果，失败会重试或拒绝。
8. **HTTP/SSE/取消如何验证？** FakeBackend C++ 合同覆盖路由、事件顺序、重复 ID、busy、cancel、timeout 和单图输入；本沙箱 loopback test skip，需在允许绑定的 CI/Jetson 重跑，不能把 skip 算 pass。
9. **离线部署如何确保资产一致？** 配置记录相对路径、revision、大小和 SHA-256；preflight 校验 submodule commit、AArch64 ELF、模型、SQLite 元数据和 source binding，全程不联网、不改资产。
10. **离生产还有什么？** systemd/日志轮转、独立 clean-clone 演练、鉴权/威胁模型、多会话调度、30-60 分钟以上 soak、错误恢复和真实音频设备验证；Docker不是当前 P0。

### 最值得继续优化的方面

1. 推理状态优化：把单热 Token LCP Prefix Reuse 接入实际 Qwen2.5-VL `MtmdBackend` text-only 路径，以正确性门和 256-2048 token A/B 实测证明 Prefill/TTFT 收益。
2. 真实 Demo：RAG 引用/拒答、单图诊断和 SSE 的 2-3 个短证据，展示价值高于新增 Web 前端。
3. VLM 性能与质量：冻结小型真实设备图质量集后，建立分辨率/image tokens/视觉阶段延迟/事实正确率的权衡。
4. 可复现部署：新路径或第二台 Jetson 做 clean clone + 离线 bundle 演练。
5. C++ 测试：在可绑定 loopback 的 CI/Jetson 完整执行 service contract，并明确禁止 silent skip。

### P1/P2

P1：按 [深入优化路线](optimization-roadmap.md) 先完成 `MtmdBackend` Prefix Reuse，再进行 Nsight decode 归因和 VLM 分辨率权衡；并行补齐小型 VLM 质量集、30-60 分钟串行 soak、HTTP service 全测试、clean-clone 离线演练、最小 systemd unit 和日志轮转。除文档/systemd 草案外均需要 Jetson/资产。

P2：在明确 SLA 后设计鉴权/审计、多 session KV/调度/内存预算、持久状态和故障注入；视频/多图与真实全双工语音必须先定义 API、资源预算、数据和实机验证，不应从当前单图/半双工能力外推。

## 最终证据清单

已具备：101 项模型无关 Python 测试、C++ FakeBackend 测试代码、离线资产合同、固定 submodule、合成手册/图片 fixture、同 commit Q4/Q8 `ready -> requests -> stopped` 配对文本、固定单图 E2E 与阶段计时基线、37/37 layer offload、公开验证入口、benchmark 协议和 Demo 规范。

待补：单图准确率、真实 Jetson CTest 无 skip、RAG 引用/拒答截图、单图 GIF/SSE 记录、clean-clone 离线交付记录、30-60 分钟 soak、systemd 运维证据。Q4/Q8 文本、固定单图 E2E 与阶段计时已有统一 RAM/温度/板载 rail；墙插功耗、生产 SLA、准确率和高并发目前不足以证明。
