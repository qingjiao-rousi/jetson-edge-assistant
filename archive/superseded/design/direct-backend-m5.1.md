# M5.1 DirectBackend 源码审计与 EdgeOmniRuntime 接口设计（草案）

状态：待确认；本文件只定义设计，不创建 `runtime/` 或 `app/` 源码。

## 1. 范围与冻结输入

本设计仅面向文本 DirectBackend。固定依赖为
`third_party/llama.cpp-omni` 的 `jetson-runtime-dev@19cc26967140407efe34006a355ab445b35b16ac`（本次审计通过 `git rev-parse HEAD` 核验）。

固定部署模型来自 `manifests/deployment-baseline-v1.json`：

| 字段 | 固定值 |
| --- | --- |
| 模型 | `models/Qwen3-4B-Q4_K_M.gguf` |
| SHA-256 | `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5` |
| 模型架构 | `qwen3` |
| reasoning | `off` |
| 构建 | Release，`BUILD_SHARED_LIBS=ON`、`GGML_CUDA=ON`、SM 87、`GGML_CUDA_NCCL=OFF`（`manifests/build.json:15-21`） |

本轮不实现 HTTP/SSE、VLM、RAG、Agent、Docker 或模型启动；不修改 fork。

## 2. 实际源码审计

以下均为固定 commit 中的实际声明或示例，不采用已废弃 API。

### 2.1 生命周期、tokenizer、模板

| 主题 | 核实结果 | 依据 |
| --- | --- | --- |
| 后端生命周期 | `llama_backend_init()` 是程序开始时调用一次，`llama_backend_free()` 是结束时调用一次。 | `include/llama.h:447-453`；CLI 初始化见 `tools/cli/cli.cpp:368-369`。 |
| 动态后端 | simple 示例在加载模型前调用 `ggml_backend_load_all()`。 | `examples/simple/simple.cpp:80-89`。 |
| 模型 | `llama_model_default_params()` 后使用 `llama_model_load_from_file(path, params)`；释放为 `llama_model_free(model)`。 | `include/llama.h:442,485-508`；示例 `examples/simple/simple.cpp:86-96,218-220`。 |
| context | `llama_context_default_params()` 后使用 `llama_init_from_model(model, params)`；释放为 `llama_free(ctx)`。`n_ctx/n_batch/n_ubatch/n_threads/n_threads_batch/type_k/type_v/offload_kqv` 均为实际字段。 | `include/llama.h:337-390,510-520`。 |
| vocab/tokenizer | vocab 由 `llama_model_get_vocab(model)` 取得；`llama_tokenize` 的首次长度查询可传 `tokens=NULL,n_tokens_max=0`，负值表示所需 token 数。 | `include/llama.h:554,1115-1133`；示例 `examples/simple/simple.cpp:96-105`。 |
| 模板 | 模型默认模板由 `llama_model_chat_template(model, NULL)` 返回；公开 C API `llama_chat_apply_template()` 接受模板、消息、`add_ass` 和输出缓冲区。 | `include/llama.h:607-609,1167-1183`；缓冲区扩容模式见 `examples/simple-chat/simple-chat.cpp:170-197`。 |

**Qwen3 non-thinking 风险门：** `llama_chat_apply_template()` 的公开签名没有 `enable_thinking` 参数（`include/llama.h:1177-1183`），且声明明确说明其不使用 Jinja parser（`:1167-1170`）。当前 CLI 的 `--reasoning off` 是向 `common_params.default_template_kwargs` 写入 `enable_thinking=false`（`common/arg.cpp:3171-3187`），再由 `common_chat_templates_apply_jinja()` 传给 `params.enable_thinking`（`common/chat.cpp:2342-2356`；输入字段定义于 `common/chat.h:189-207`）。

因此，M5.2 不能声称“仅 libllama C API 已实现 `--reasoning off`”。在写任何 DirectBackend 前必须用冻结 GGUF 做一项独立接口验证：确认公开 C template 路径产生的 prompt 是否等价于已验证的 `--reasoning off` prompt。若不等价，需在用户确认后才选择以下之一：仅将必要的 `common` chat-template 组件作为受控构建依赖，或将经验证的 non-thinking prompt renderer 放在自有 adapter 中。两者都不是本 M5.1 的实现内容。

### 2.2 Prefill、decode、采样与停止

1. `llama_batch_init()` 分配的 batch 必须由 `llama_batch_free()` 释放（`include/llama.h:917-930`）。M5.2 的 prompt prefill 应使用显式 batch，将最后一个 prompt token 的 `batch.logits` 置为非零；batch 中 `logits` 的语义见 `include/llama.h:230-249`。
2. `llama_decode(ctx, batch)` 的返回值 `0` 成功，`1` 无 KV slot，`2` abort，`-1` 无效 batch，`<-1` fatal；abort/fatal 后已处理的 ubatch 仍可能保留在 context memory（`include/llama.h:942-956`）。不能将任何非零值笼统归为可重试。
3. 在一次成功 decode 后，`llama_sampler_sample(sampler, ctx, -1)` 从最后一行 logits 选 token；此用法由 API 示例明确给出（`include/llama.h:1191-1220,1476-1486`），并由 simple 示例实际使用（`examples/simple/simple.cpp:171-203`）。
4. 停止条件至少为 `llama_vocab_is_eog(vocab, token)` 和 `max_new_tokens`；前者定义为 EOG/EOS/EOT 等（`include/llama.h:1051-1069`），示例在采样后即检查（`examples/simple/simple.cpp:182-186`）。M5.2 不加入自定义 stop-string 或 grammar。
5. 通过 `llama_token_to_piece(vocab, token, ...)` 把 token 追加为字节串；负值表示缓冲区不足，必须扩容重试，不能截断（`include/llama.h:1135-1146`）。示例使用返回长度构造 `std::string`（`examples/simple/simple.cpp:189-200`）。
6. sampler chain 取得所加入 sampler 的所有权，最终只对 chain 调用 `llama_sampler_free()`（`include/llama.h:1284-1306`）。最小固定采样参数可建为 `top_k(1)`、`top_p(1.0, 1)`、`min_p(0.0, 1)`、`temp(0.0)`、`dist(seed)`；这是一项自有映射设计，必须在 M5.2 单测中与冻结参数核对，非上游默认声明。

### 2.3 KV、取消和日志

| 主题 | 设计约束 | 源码依据 |
| --- | --- | --- |
| reset | 本 commit 不应调用不存在的旧 `llama_kv_cache_clear`。调用 `llama_memory_clear(llama_get_memory(ctx), false)`，并 reset 当前 request sampler；decode 失败/abort 后也必须 reset，因为 API 明示已处理 ubatch 可能留存。 | `include/llama.h:550-552,702-706,942-953`。 |
| context 容量 | prefill 前和每次 decode 前，以 `llama_memory_seq_pos_max(memory, 0)` 计算已用位置；超过 `llama_n_ctx(ctx)` 返回稳定错误。 | `include/llama.h:536-540,762-767`；示例 `examples/simple-chat/simple-chat.cpp:104-128`。 |
| abort | 以 `llama_set_abort_callback(ctx, callback, data)` 注册。该 callback 的注释明确写明目前只对 CPU execution 生效；Jetson CUDA 不能承诺即时中断。 | `include/llama.h:368-372,981-982`。 |
| 日志 | `llama_log_set(callback, user_data)` 是全局状态且 API 明确标记为非线程安全；只允许进程内唯一 Runtime 在初始化/关闭边界设置和恢复 callback。 | `include/llama.h:1508-1512`；回调示例 `examples/simple-chat/simple-chat.cpp:61-66`。 |

## 3. 建议的最小自有目录与 CMake

本节是 M5.2 将创建的最小结构，当前不创建文件。

```text
runtime/
  CMakeLists.txt
  include/edgeomni/runtime.h          # 公共 DTO、错误码、EdgeOmniRuntime
  include/edgeomni/direct_backend.h   # DirectBackend 声明
  src/direct_backend.cpp              # 仅文本、单 context 适配
  src/direct_backend_internal.h       # llama RAII deleter 和私有状态
tests/runtime/
  direct_backend_contract_test.cpp    # fake backend，不链接 CUDA/模型
  direct_backend_jetson_test.cpp      # integration，默认不进单元测试
```

根项目仅在 M5.2 明确 `add_subdirectory(runtime)`；runtime 目标不链接 `llama-common`、server 或 CLI。首选将 fork 作为源码子目录并链接 target `llama`：

```cmake
add_library(edgeomni_runtime STATIC src/direct_backend.cpp)
target_compile_features(edgeomni_runtime PUBLIC cxx_std_17)
target_include_directories(edgeomni_runtime PUBLIC include)
target_link_libraries(edgeomni_runtime PRIVATE llama)
```

这与 fork 的实际 target 相符：`src/CMakeLists.txt:11-55` 创建 target `llama`、公开 `../include` 并公开链接 `ggml`。现有冻结构建为 shared，实物为 `build-jetson-release/bin/libllama.so.0.0.259`；`BUILD_SHARED_LIBS` 时 fork 为 `llama` 定义 `LLAMA_SHARED`（`src/CMakeLists.txt:57-60`）。安装包 `find_package(Llama)` 也导入 target `llama`，并将 `ggml::ggml;ggml::ggml-base` 作为接口依赖（`cmake/llama-config.cmake.in:12-28`）。

运行时动态库搜索路径必须由部署脚本/loader 处理，不在 adapter 中硬编码 build 路径；CUDA backend 构建产物记录为 `build-jetson-release/bin/libggml-cuda.so.0.13.1`（`manifests/build.json:52-55`）。不直接手工 `-lggml-cuda`：ggml 的 backend CMake 会依 `GGML_BACKEND_DL` 选择模块或 PUBLIC 链接（`ggml/src/CMakeLists.txt:265-289`）。

## 4. 自有接口与数据模型

以下是待确认的 C++17 公共接口；所有 `Result<T>` 均为自有错误传递类型，不暴露 llama 指针、枚举或异常。

```cpp
namespace edgeomni {

enum class RuntimeErrorCode {
  kOk, kInvalidArgument, kInvalidState, kAlreadyInitialized,
  kModelNotFound, kModelHashMismatch, kBackendInitFailed, kModelLoadFailed,
  kContextCreateFailed, kTemplateUnsupported, kTokenizeFailed,
  kContextLimit, kDecodeNoKvSlot, kDecodeAborted, kDecodeFailed,
  kTokenToTextFailed, kCancelled, kShutdownInProgress, kInternal,
};

enum class RuntimeState { kNew, kInitializing, kReady, kGenerating, kShuttingDown, kStopped, kFailed };
enum class ReasoningMode { kOff };

struct SamplingConfig {
  uint32_t seed = 424242;
  int32_t top_k = 1;
  float top_p = 1.0F;
  float min_p = 0.0F;
  float temperature = 0.0F;
  float repeat_penalty = 1.0F; // M5.2 records it; sampler mapping is gated by test.
};
struct RuntimeConfig {
  std::string model_path;
  std::string expected_model_sha256;
  uint32_t context_tokens = 4096;
  uint32_t batch_tokens = 2048;
  uint32_t ubatch_tokens = 512;
  int32_t gpu_layers = 99;
  int32_t main_gpu = 0;
  int32_t generation_threads = 8;
  int32_t batch_threads = 8;
  bool use_mmap = true;
  bool flash_attention = true;
  ReasoningMode reasoning = ReasoningMode::kOff;
  SamplingConfig sampling;
};
struct ChatMessage { std::string role; std::string content; };
struct GenerateRequest {
  std::string request_id;
  std::vector<ChatMessage> messages;
  uint32_t max_new_tokens = 128;
  SamplingConfig sampling;
  std::shared_ptr<std::atomic_bool> cancel_flag;
};
struct GenerateResponse {
  std::string request_id;
  std::string text;
  RuntimeErrorCode code = RuntimeErrorCode::kOk;
  std::string error_message;
  std::string stop_reason; // eog, length, cancelled, decode_error
  uint32_t prompt_tokens = 0;
  uint32_t generated_tokens = 0;
};
struct RuntimeStatus {
  RuntimeState state = RuntimeState::kNew;
  std::string model_path;
  std::string model_sha256;
  std::string runtime_commit;
  uint32_t configured_context_tokens = 0;
  bool reasoning_off_required = true;
  bool reasoning_off_verified = false;
  std::string last_error;
};
struct RuntimeMetrics {
  uint64_t initialize_ms = 0;
  uint64_t request_total_ms = 0;
  uint64_t prefill_ms = 0;
  uint64_t ttft_ms = 0;
  uint64_t decode_ms = 0;
  double decode_tokens_per_second = 0.0;
  uint32_t prompt_tokens = 0;
  uint32_t generated_tokens = 0;
};

class EdgeOmniRuntime {
 public:
  virtual ~EdgeOmniRuntime() = default;
  virtual Result<void> initialize(const RuntimeConfig & config) = 0;
  virtual Result<GenerateResponse> generate_text(const GenerateRequest & request) = 0;
  virtual Result<void> reset_context() = 0;
  virtual Result<void> shutdown() = 0;
  virtual RuntimeStatus status() const = 0;
  virtual RuntimeMetrics last_metrics() const = 0;
};

class DirectBackend final : public EdgeOmniRuntime {
 public:
  Result<void> initialize(const RuntimeConfig &) override;
  Result<GenerateResponse> generate_text(const GenerateRequest &) override;
  Result<void> reset_context() override;
  Result<void> shutdown() override;
  RuntimeStatus status() const override;
  RuntimeMetrics last_metrics() const override;
};

} // namespace edgeomni
```

`GenerateRequest` 使用消息而不是 CLI 字符串，避免上层依赖命令行；同时 `reasoning_off_verified` 防止 template 验证未通过时被误报为可用。M5.2 不暴露 token callback 或 HTTP/SSE；`cancel_flag` 仅是预留契约，CUDA 路径的实际中断承诺受第 2.3 节限制。

## 5. RAII、线程与状态机

### 5.1 所有权

`DirectBackend` 私有成员按以下顺序声明和析构：

1. `std::unique_ptr<llama_model, ModelDeleter>`，deleter 调用 `llama_model_free`。
2. `std::unique_ptr<llama_context, ContextDeleter>`，deleter 调用 `llama_free`；context 必须先于 model 析构。
3. 每次请求创建 `std::unique_ptr<llama_sampler, SamplerDeleter>`，deleter 调用 `llama_sampler_free`；不得另行释放已加入 chain 的子 sampler。
4. 每次请求创建 `BatchOwner`，仅封装 `llama_batch_init` 和 `llama_batch_free`。仅初始化成功的 batch 可释放。
5. backend init/free 是进程级 guard，不属于每请求对象；最后一个 Runtime shutdown 后才可 `llama_backend_free`。

### 5.2 单模型、单 context 边界

M5.2 固定为一个 `DirectBackend`、一个已加载 model、一个 context、sequence id `0`。`generate_text`、`reset_context` 与 `shutdown` 通过同一互斥锁串行；没有并发 decode、批内多请求、session/KV 复用或请求队列。`status()`/`last_metrics()` 以独立短锁读取快照。

这既保护 context/KV/sampler，又符合 `llama_log_set` 的全局非线程安全限制。第二个 runtime 实例在同进程内返回 `kAlreadyInitialized`，直到本实例完整 shutdown；多模型或多 context 是后续显式设计，不由本草案暗中放开。

### 5.3 状态转换

```text
kNew -> kInitializing -> kReady -> kGenerating -> kReady
                 |                         |          |
                 +------ failure ----------+-> kFailed
kReady/kFailed -> kShuttingDown -> kStopped
```

- `initialize`：仅 `kNew` 可进入；先检查文件、SHA-256 和 `reasoning == kOff`，再设置进程级日志、初始化 backend、加载 model、取得 vocab、验证 template、创建 context。任何失败清理已获得资源并进入 `kFailed`。
- `generate_text`：仅 `kReady`；进入 `kGenerating` 后先 `reset_context` 语义地清空 memory，再 render/tokenize、prefill、decode/sample loop。所有退出路径都 reset sampler；正常、EOG、长度、取消或错误后回到 `kReady`，并在 decode abort/fatal 时清 context。
- `reset_context`：仅 `kReady`；调用 memory clear 并清空 request-local bookkeeping。`kGenerating` 调用返回 `kInvalidState`，不与 decode 竞争。
- `shutdown`：`kGenerating` 返回 `kShutdownInProgress`，调用方必须先等待 generate 返回；`kReady/kFailed` 可进入。按 context、model、backend 的顺序释放并到 `kStopped`；对 `kStopped` 幂等成功。

## 6. 错误、日志与测试边界

### 6.1 错误和日志

错误码必须稳定；原始 llama 返回值、路径、`errno`/loader 文本只进入 `error_message` 和日志，不能替代 `RuntimeErrorCode`。`llama_decode` 映射为：`1 -> kDecodeNoKvSlot`、`2 -> kDecodeAborted`、`<0 -> kDecodeFailed`；而 max token/EOG 是成功响应的 `stop_reason`，不是错误。

每条自有日志记录至少包含：`timestamp_utc`、`level`、`component=direct_backend`、`event`、`runtime_state`、`request_id`（仅请求期）、`model_sha256`、`runtime_commit`、`error_code`、`llama_decode_return`（适用时）、`prompt_tokens`、`generated_tokens`、`elapsed_ms`。llama 的全局 callback 只转发原始 `level/text` 并附 `component=libllama`，不可假造 request ID。

### 6.2 测试分层

| 层级 | M5.2 最小覆盖 | 不做 |
| --- | --- | --- |
| Fake unit | 状态机、非法状态、错误码映射、`reset_context` 调度、响应/metrics 字段、单请求互斥。无需 GPU、GGUF 或 llama 库。 | 不验证模型输出。 |
| libllama contract | tokenization 两阶段缓冲、batch/RAII、EOG、decode 返回值分支和 template buffer 重试。 | 不使用网络、下载或 HTTP。 |
| Jetson integration（显式标记） | 冻结模型 SHA 核验、Qwen3 `reasoning off` prompt 等价性门、单请求生成、连续两请求不重复加载、context reset、TTFT/Prefill/Decode 度量。 | 并发、取消时延承诺、VLM/RAG/Agent/SSE/Docker。 |

## 7. M5.2 最小实现范围与不做项

在确认本草案后，M5.2 只实现：上述 `runtime/` 的接口、`DirectBackend` 的单模型单 context 文本循环、冻结 config/hash 校验、EOG/长度停止、memory reset、结构化错误/metrics、进程级日志 callback 和 fake/unit + 标记 integration 测试。

M5.2 明确不做：HTTP、JSON service、SSE/stream callback、VLM/图片/mtmd、RAG、tool/Agent、Docker/systemd、多 session、多 context/并行请求、KV prompt cache、grammar、stop-string、性能结论、自动模型下载、依赖安装或对 `llama.cpp-omni` 的任何修改。

**继续条件：**先确认 Qwen3 `--reasoning off` 的 template-renderer 方案。本设计不会将 CLI 的 `common` 层行为错误地写成 libllama C API 已具备的参数。
