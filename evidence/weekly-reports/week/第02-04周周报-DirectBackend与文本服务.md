# Jetson 端侧离线多模态推理项目第 2--4 周周报

## 一、基本信息

| 项目 | 内容 |
| --- | --- |
| 报告周期 | 第 2--4 周：DirectBackend、流式 Runtime 与最小文本服务 |
| 归档日期 | 2026-07-27 |
| 固定 Runtime | `third_party/llama.cpp-omni`，`jetson-runtime-dev@19cc269` |
| 固定模型 | `models/Qwen3-4B-Q4_K_M.gguf` |
| 模型 SHA-256 | `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5` |
| 当前阶段 | M5.2--M5.4 完成；不进入后续周期 |

## 二、完成项

| 里程碑 | 状态 | 结果 |
| --- | --- | --- |
| M5.1a Qwen3 template 审计 | 完成 | 公开 `llama_chat_apply_template` 无 template variables，不能字节等价实现 CLI `--reasoning off`；决策为引入独立 renderer。 |
| M5.2 最小文本闭环 | 完成 | 新建 C++17 Runtime、Qwen3 ChatTemplateRenderer、DirectBackend、FakeBackend 和 CMake；模型仅在 initialize 加载一次。 |
| M5.3 流式/取消/超时 | 完成 | request ID、TokenCallback、协作 cancel、deadline、恢复 context/sampler/batch，以及结构化 finish_reason 与 Runtime 指标。 |
| M5.4a 服务契约 | 完成 | 定义 HTTP/JSON/SSE、状态码、单 active/429、metrics 与 TTFT/TPOT 边界。 |
| M5.4b 最小服务 | 完成 | 实现 health、ready、model/info、metrics、generate/chat、cancel；复用 vendored cpp-httplib 与 nlohmann JSON。 |
| M5.4b 宿主机测试修复 | 完成 | 并发请求使用独立 client，轮询 active 状态，测试专用确定性 FakeBackend 延迟；修正 shutdown 语义断言。 |

## 三、关键设计结论

- Qwen3 `enable_thinking=false` 必须显式渲染空 `<think>\n\n</think>\n\n` prefill；不把 CLI/common 的 Jinja 能力表述为公开 libllama API。详见 `docs/design/qwen3-direct-template-decision.md`。
- `DirectBackend` 是单模型、单 context、单请求串行模型。服务最大队列长度为 0，busy 请求返回 429。
- cancel 只针对真实 active request；它经 request-local atomic 协作传播。CUDA abort callback 不承诺即时中断。
- Runtime `first_token_ms` 是本地 `generate_text` 时间，不能称作正式 TTFT。服务 TTFT 从 HTTP 接收至首个 token 成功写入客户端；TPOT 也在服务层独立记录。
- `shutdown()` 停止 HTTP server。停止后连接不可用，不能期待 HTTP 503；通过 `ready()==false`、`running()==false` 与 restart 拒绝确认终态。

## 四、验证记录

```bash
cmake -S . -B build-runtime -DEDGEOMNI_BUILD_TESTS=ON -DEDGEOMNI_BUILD_INTEGRATION=ON
cmake --build build-runtime --parallel 2
ctest --test-dir build-runtime --output-on-failure
./build-runtime/runtime/edgeomni_service_unit_test
./build-runtime/runtime/edgeomni_qwen3_integration_test
git diff --check
```

结果：configure/build 通过；`ctest` 2/2 通过；宿主机 `edgeomni_service_unit_test` 通过；Qwen3 integration 实际加载固定 GGUF 并生成 `Ready.`，通过。沙箱内本地 socket 不可用时，服务测试明确输出 `BLOCKED_SANDBOX`；宿主机验证已完成，未将该限制归因于服务故障或 GPU 故障。

## 五、范围与已知限制

- 已实现：纯文本消息、Qwen3 固定 template 门禁、同步 JSON、SSE、单 active cancel/timeout、FakeBackend 契约测试。
- 未实现：VLM、RAG、Agent、多 session、HTTP 鉴权、持久队列、Docker、systemd。
- 服务 `request_id` 在当前进程生命周期内去重；无会话状态与服务重启后的去重持久化。
- M5.4 到此收口；下一周期开始前不再扩展服务功能。
