# M5.4a EdgeOmniRuntime HTTP/JSON/SSE 服务契约设计

状态：IMPLEMENTED（M5.4b），宿主机 FakeBackend 服务契约测试与 Qwen3 DirectBackend integration 已通过。实现保持不下载、不安装依赖，不链接 `llama-common`、CLI 或上游 server。当前服务为单 context、单 active request、最大队列长度 0；未实现 VLM、RAG、Agent、多 session、Docker 或 systemd。

## 1. 审计结论

仓库已 vendored `cpp-httplib` 0.46.0（`third_party/llama.cpp-omni/vendor/cpp-httplib/httplib.h:1-30`），其 CMake target 名为 `cpp-httplib`，构建为静态库并依赖 `Threads::Threads`（`third_party/llama.cpp-omni/vendor/cpp-httplib/CMakeLists.txt:1-19`）。vendored nlohmann JSON 头文件位于 `third_party/llama.cpp-omni/vendor/nlohmann/json.hpp:1-15`（3.12.0）。未发现独立 SSE 依赖；SSE 可由 HTTP chunked response 实现，上游示例使用 `set_chunked_content_provider`（`third_party/llama.cpp-omni/tools/server/server-voxcpm2.cpp:388-390`）。

当前自有 CMake 只导入 frozen `libllama.so`（`runtime/CMakeLists.txt:1-18`），Runtime 只链接 `edgeomni_llama`（`runtime/CMakeLists.txt:20-25`），没有服务 target、`cpp-httplib`、nlohmann include 或 Threads 链接。因此当前构建不能声称已支持 HTTP/JSON；未来服务 target 应复用仓库内 vendored 依赖，不下载、不安装，并独立于 `llama-common`、CLI 和上游 server。

DirectBackend 的 `generate_text` 持有同一 `impl_->mutex`（`runtime/src/direct_backend.cpp:184-186`）；initialize、reset 和 shutdown 也使用该 mutex（`runtime/src/direct_backend.cpp:415-437`）。所以当前模型实例只有一个 active request，不支持并发 context 或多 session。`cancel_request` 只匹配活动 request ID 并设置 request-local atomic（`runtime/src/direct_backend.cpp:406-412`）。服务层不得把 CUDA abort 描述为即时取消：公开参数注释明确 abort callback 当前只对 CPU execution 生效（`third_party/llama.cpp-omni/include/llama.h:368-372`）。

## 2. 服务边界与生命周期

服务只包装 `RuntimeBackend`：`GenerateRequest` 已有 `request_id`、`timeout_ms`（0 为无 deadline）、cancel flag 和 sampling（`runtime/include/edgeomni/runtime.h:69-76`）；同步生成同时接受 `TokenCallback`（`runtime/include/edgeomni/runtime.h:108-115`）。服务线程负责 JSON 校验、排队决策、SSE 写入和断开检测，生成线程调用 backend；不得重入同一个 backend context。

默认并发策略是单 active、最大队列长度 `0`：有请求运行时新请求立即返回 `429 busy`，不在 HTTP worker 中无限阻塞。后续若明确启用队列，必须配置有限 `max_queue_length`，入队返回 `202`，并为排队取消定义状态；本版本契约不启用该模式。shutdown 开始后拒绝新请求并令 `ready()` 返回 false。`shutdown()` 会停止 HTTP server；server 已停止后不能期待收到 HTTP 503，因为连接不可用。HTTP 层面的 `/ready` 503 只适用于 server 仍在运行但 backend 未初始化或正在 stop-but-not-shutdown 状态；本实现不额外引入该状态。

## 3. HTTP API

| 方法 | 路径 | 成功语义 |
|---|---|---|
| GET | `/health` | 进程/HTTP 层存活，返回 200；不代表模型可推理 |
| GET | `/ready` | 模型已初始化、模板/模型 hash 通过且未 shutdown，返回 200；否则 503 |
| GET | `/model/info` | 返回模型名称、固定 SHA-256、模板 fingerprint、context capacity |
| GET | `/metrics` | 返回服务计数及最近/累计 runtime 指标 |
| POST | `/v1/generate` | 文本生成；`stream=false` 返回 JSON，`stream=true` 返回 `text/event-stream` |
| POST | `/v1/chat` | 与 generate 相同的消息契约和执行语义，路径用于 chat 语义 |
| POST | `/v1/cancel/{request_id}` | 取消 active request；成功返回 200，否则 404/409 |

状态码约定：`400` JSON/字段/消息非法；`404` 未知 cancel request；`409` 重复 request ID 或状态冲突；`429` active 或队列已满；`408` deadline 超时；`499` 客户端断开导致的取消（非标准约定）；`500` backend/internal error；`503` not ready/shutting down；可用 `413` 表示请求超出 context 容量。正常完成为 `200`。

## 4. JSON Schema（契约级）

`GenerateRequest`：

```json
{
  "type":"object", "required":["request_id","messages","max_new_tokens"],
  "additionalProperties":false,
  "properties":{
    "request_id":{"type":"string","minLength":1},
    "session_id":{"type":["string","null"]},
    "messages":{"type":"array","minItems":1,"items":{"type":"object","required":["role","content"],"additionalProperties":false,"properties":{"role":{"enum":["system","user","assistant"]},"content":{"type":"string"}}}},
    "max_new_tokens":{"type":"integer","minimum":1},
    "timeout_ms":{"type":"integer","minimum":0,"default":0},
    "stream":{"type":"boolean","default":false},
    "model_sha256":{"type":"string","pattern":"^[0-9a-fA-F]{64}$"},
    "sampling":{"type":"object","additionalProperties":false,"properties":{"seed":{"type":"integer"},"top_k":{"type":"integer","minimum":0},"top_p":{"type":"number","exclusiveMinimum":0,"maximum":1},"min_p":{"type":"number","minimum":0,"maximum":1},"temperature":{"type":"number","exclusiveMinimum":0}}}
  }
}
```

`session_id` 当前必须为空或 null；非空值返回 400，明确不提供多 session。若 `model_sha256` 提供，必须匹配部署冻结 hash，否则 400。`content` 只接受文本；图片、tools、未知 role 返回明确 400。

`GenerateResponse`：

```json
{
  "request_id":"r-1", "session_id":null,
  "model_sha256":"<sha256>", "text":"...",
  "finish_reason":"stop",
  "prompt_tokens":12, "output_tokens":7,
  "metrics":{"model_ready_ms":0,"prefill_ms":0,"decode_ms":0,"total_ms":0,"first_token_ms":0,"decode_tokens_per_second":0.0},
  "error":null
}
```

`finish_reason` 仅为 `stop|length|cancelled|timeout|error`；错误时 `error={"code":string,"message":string}`。Runtime 对应字段和枚举承载于 `GenerateResponse`（`runtime/include/edgeomni/runtime.h:97-106`）。

## 5. SSE

每条消息为 UTF-8，`data` 是单个 JSON 对象，以空行结束；token 的 `index` 按 `StreamToken.index`（`runtime/include/edgeomni/runtime.h:78-82`）严格递增。终止事件只发送一次：

```text
event: token
data: {"request_id":"r-1","session_id":null,"index":0,"text":"Hi"}

event: done
data: {"request_id":"r-1","finish_reason":"stop","text":"Hi","metrics":{}}

event: error
data: {"request_id":"r-1","finish_reason":"error","error":{"code":"backend","message":"..."}}

event: cancelled
data: {"request_id":"r-1","finish_reason":"cancelled"}

event: timeout
data: {"request_id":"r-1","finish_reason":"timeout"}
```

服务 callback 返回 false 或 `/v1/cancel/{request_id}` 设置 cancel flag 后，映射为 `cancelled`；deadline 映射为 `timeout`。客户端断开时停止写入并设置 cancel flag，通常无法再发送终止 SSE，但服务端仍记录 499 和最终 backend 状态。背压由 chunked sink 的写入返回值表示；写失败即视为客户端断开，不得继续产生无界 token 缓冲。取消不是 CUDA decode 的即时中断，backend 在协作检查点结束请求。

## 6. 指标边界

`/metrics` 至少提供请求计数（accepted/completed/cancelled/timeout/errors）、active/queue 深度、token 计数，以及 backend 的 `model_ready_ms`、`prompt_tokens`、`output_tokens`、`prefill_ms`、`decode_ms`、`total_ms`、`first_token_ms`、`decode_tokens_per_second`（字段来源：`runtime/include/edgeomni/runtime.h:86-95`）。

- `first_token_ms`：`generate_text` 入口到首次调用 `TokenCallback` 的本地 wall-clock，非正式 TTFT。
- 服务 TTFT：HTTP 请求被接受到首个 token 字节成功写入/flush 客户端，包含解析、排队、模板、prefill 和网络写入开销。
- 服务 TPOT：首 token 写入到末 token 写入的服务时间差除以 `max(output_tokens-1,1)`；不能用 backend `decode_tokens_per_second` 代替。
- 若无 token（error/cancel before output），TTFT/TPOT 记 null 或 0，并在 schema 中固定约定。

## 7. FakeBackend 服务契约测试

覆盖：health/ready 生命周期；正常 JSON generate/chat；schema、空/重复 request ID、session_id 拒绝、model hash 不匹配；active 时 `429`（最大队列 0）；SSE token 顺序和恰好一个终止事件；cancel active/unknown 的 200/404；callback 中途取消、timeout、客户端断开映射；取消/错误后再次请求；shutdown 后通过 `ready()==false`、`running()==false` 和再次启动拒绝验证状态（不对已停止 server 期待 HTTP 503）；响应中的 model hash、finish_reason、token 数和指标字段；服务 TTFT 与 backend first_token_ms 分离。

## 8. 依赖缺失时的最小方案

不安装、不下载。服务 target 优先在未来 CMake 中接入现有 vendored `cpp-httplib` target、`Threads::Threads` 和 `vendor/nlohmann` include；SSE 使用 httplib chunked provider。不得链接 `llama-common`、CLI 或把上游 server 当业务 Backend。若构建环境无法复用该 target，暂保留服务契约和 FakeBackend 测试，服务实现标记 unavailable；不在本阶段重写 HTTP 栈。

本设计不包含 VLM、RAG、Agent、Docker、systemd 或多 session；完成设计后等待确认。
