#pragma once

#include <atomic>
#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <vector>

namespace edgeomni {

enum class RuntimeErrorCode {
    kOk,
    kInvalidArgument,
    kInvalidState,
    kAlreadyInitialized,
    kModelNotFound,
    kModelHashMismatch,
    kBackendInitFailed,
    kModelLoadFailed,
    kContextCreateFailed,
    kTemplateFingerprintMismatch,
    kTemplateUnsupported,
    kTokenizeFailed,
    kContextLimit,
    kDecodeNoKvSlot,
    kDecodeAborted,
    kDecodeFailed,
    kTokenToTextFailed,
    kCancelled,
    kTimeout,
    kInternal,
};

struct Status {
    RuntimeErrorCode code = RuntimeErrorCode::kOk;
    std::string message;

    bool ok() const { return code == RuntimeErrorCode::kOk; }
    static Status Ok() { return {}; }
};

struct ChatMessage {
    std::string role;
    std::string content;
};

struct SamplingConfig {
    uint32_t seed = 424242;
    int32_t top_k = 1;
    float top_p = 1.0F;
    float min_p = 0.0F;
    float temperature = 0.0F;
};

struct RuntimeConfig {
    std::string model_path;
    std::string expected_model_sha256;
    uint32_t context_tokens = 4096;
    uint32_t batch_tokens = 512;
    uint32_t ubatch_tokens = 512;
    int32_t gpu_layers = 99;
    int32_t generation_threads = 8;
    int32_t batch_threads = 8;
    bool use_mmap = true;
    bool flash_attention = true;
};

struct GenerateRequest {
    std::string request_id;
    std::vector<ChatMessage> messages;
    uint32_t max_new_tokens = 128;
    uint64_t timeout_ms = 0;  // Zero disables the request deadline.
    std::shared_ptr<std::atomic_bool> cancel_flag;
    SamplingConfig sampling;
};

struct StreamToken {
    std::string request_id;
    std::string text;
    uint32_t index = 0;
};

using TokenCallback = std::function<bool(const StreamToken &)>;

struct RuntimeMetrics {
    uint64_t model_ready_ms = 0;
    uint32_t prompt_tokens = 0;
    uint32_t output_tokens = 0;
    uint64_t prefill_ms = 0;
    uint64_t decode_ms = 0;
    uint64_t total_ms = 0;
    uint64_t first_token_ms = 0;
    double decode_tokens_per_second = 0.0;
};

struct GenerateResponse {
    std::string request_id;
    std::string text;
    RuntimeErrorCode code = RuntimeErrorCode::kOk;
    std::string error_message;
    std::string finish_reason;
    uint32_t prompt_tokens = 0;
    uint32_t generated_tokens = 0;
    RuntimeMetrics metrics;
};

class RuntimeBackend {
  public:
    virtual ~RuntimeBackend() = default;
    virtual Status initialize(const RuntimeConfig & config) = 0;
    virtual GenerateResponse generate_text(const GenerateRequest & request, const TokenCallback & on_token = {}) = 0;
    virtual Status cancel_request(const std::string & request_id) = 0;
    virtual Status reset_context() = 0;
    virtual Status shutdown() = 0;
};

}  // namespace edgeomni
