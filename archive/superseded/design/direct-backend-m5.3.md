# M5.3 DirectBackend 流式、取消、超时与运行指标

状态：DONE（configure/build/unit test）；Jetson integration：`BLOCKED_SANDBOX`。

## 新接口

`GenerateRequest` 现包含稳定的非空 `request_id`、可选
`std::shared_ptr<std::atomic_bool> cancel_flag` 与 `timeout_ms`（0 表示没有 deadline）。
`RuntimeBackend::generate_text(request, on_token)` 接受 `TokenCallback`；每个
`StreamToken` 含 request ID、按顺序产生的文本片段和零基 index。callback 返回 false
等价于取消当前请求。`cancel_request(request_id)` 可从另一线程置当前请求的内部 cancel
flag；不匹配或没有活动请求返回 `kInvalidState`。

响应的 `finish_reason` 是 `stop`、`length`、`cancelled`、`timeout` 或 `error`。
取消/超时返回 `kCancelled`/`kTimeout`；其他失败返回已有结构化错误码并使用 `error`。

## Abort 与线程边界

`llama_set_abort_callback(ctx, callback, data)` 和 `llama_synchronize(ctx)` 是此 fork
实际公开声明（`third_party/llama.cpp-omni/include/llama.h:981-987`）。context 实现把
abort callback 交给支持它的 backend（`third_party/llama.cpp-omni/src/llama-context.cpp:1075-1089`）。
`llama_context_params` 注释明确 abort callback 当前只对 CPU execution 生效
（`third_party/llama.cpp-omni/include/llama.h:368-372`）。所以 CUDA 路径不能承诺
即时取消；timeout/cancel 在每次 decode 前后也会协作检查。

一个 DirectBackend 的 `generate_text`、`reset_context`、`initialize`、`shutdown` 使用同一
mutex，绝不并发访问同一个 llama context/KV/sampler。`cancel_request` 只写 request-local
atomic，不碰 context。stream callback 在 generation 线程、持有该 request mutex 时同步调用，
因此 callback 不得重入同一个 DirectBackend 的 lifecycle/generate 方法；它可返回 false 或写
传入的 `cancel_flag`。tokenizer 是头文件唯一明确标记 thread-safe 的 API
（`third_party/llama.cpp-omni/include/llama.h:1113-1116`），本实现不外推其他 context API
的线程安全性。

abort、timeout 或 decode 错误时调用公开 `llama_synchronize()`，然后调用
`llama_memory_clear(llama_get_memory(ctx), false)`；这处理 `llama_decode` 文档所述
abort/fatal 后仍可能存在的已处理 ubatch（`include/llama.h:942-956`）。batch 与 sampler
始终是 request-local RAII 对象，因此请求终止后可再次请求。

## 指标

`GenerateResponse.metrics` 包含：

| 字段 | 定义 |
| --- | --- |
| `model_ready_ms` | 当前 DirectBackend 最近一次成功 initialize 的时长。 |
| `prompt_tokens` / `output_tokens` | tokenizer 输出数 / 已交付输出 token 数。 |
| `prefill_ms` | prompt 的 decode 循环耗时。 |
| `decode_ms` | 自第一次 sample 起至生成循环退出的耗时。 |
| `total_ms` | `generate_text` 进入至返回的总耗时。 |
| `first_token_ms` | 进入 `generate_text` 至第一个可交付 token 片段的本地 wall-clock 时间。 |
| `decode_tokens_per_second` | `output_tokens / decode_ms`，`decode_ms == 0` 时为 0。 |

`first_token_ms` 只是本 Runtime 的局部时间点，尚未经过 Jetson 集成验证，**不称为正式 TTFT**。

## 测试与运行

```bash
cmake -S . -B build-runtime -DEDGEOMNI_BUILD_TESTS=ON -DEDGEOMNI_BUILD_INTEGRATION=ON
cmake --build build-runtime --parallel 2
ctest --test-dir build-runtime --output-on-failure
git diff --check
```

FakeBackend contract tests：PASS，覆盖 token 回调顺序、callback 中途取消、timeout、正常
`stop`、取消后请求、timeout 后请求、非法请求后请求，以及 shutdown 后拒绝请求。

Jetson integration target `edgeomni_qwen3_integration_test` 已编译，覆盖正常流式、callback
取消与取消后再次请求：

```bash
./build-runtime/runtime/edgeomni_qwen3_integration_test
```

当前环境没有 `/dev/nvidia*`，`nvidia-smi -L` 不能与 driver 通信，因此未运行该命令并记录为
`BLOCKED_SANDBOX`，不推断 GPU 故障。通过条件：正常流式回调至少收到一个片段，取消返回
`cancelled`，取消后的请求返回 `kOk`，并打印 token 数与本地 `first_token_ms`。

## 已知限制

- CPU abort callback 可中断 decode；CUDA 只提供协作检查，不能承诺立即中断。
- 单 context、单请求串行；没有多 session、排队或 HTTP/SSE。
- callback 同步执行，耗时 callback 会直接降低 decode 吞吐。
- 未实现正式 TTFT/TPOT 结论、prometheus/日志导出或服务层。
