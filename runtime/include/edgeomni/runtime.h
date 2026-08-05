#pragma once

#include <atomic>
#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
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
    // VLM contract additions. Existing text-path values above remain stable.
    kImageCountExceeded,
    kImageBytesEmpty,
    kImageMimeUnsupported,
    kImageTooLarge,
    kImageDecodeFailed,
    kImageDimensionsExceeded,
    kImagePixelsExceeded,
    kModelSizeMismatch,
    kMmprojNotFound,
    kMmprojSizeMismatch,
    kMmprojHashMismatch,
    kMmprojBindingMismatch,
    kMmprojLoadFailed,
    kVisionEncodeFailed,
    kResourceExhausted,
    kBackendUnavailable,
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

struct ImageInput {
    std::string id;
    std::vector<uint8_t> encoded_bytes;
    std::string mime_type;
    // Caller-supplied values are diagnostic hints only. Safety checks use decoder output.
    std::optional<uint32_t> declared_width;
    std::optional<uint32_t> declared_height;
};

struct RuntimeConfig {
    std::string model_path;
    std::string expected_model_sha256;
    uint64_t expected_model_size_bytes = 0;
    std::string mmproj_path;
    std::string expected_mmproj_sha256;
    uint64_t expected_mmproj_size_bytes = 0;
    uint32_t context_tokens = 4096;
    uint32_t batch_tokens = 512;
    uint32_t ubatch_tokens = 512;
    int32_t gpu_layers = 99;
    int32_t generation_threads = 8;
    int32_t batch_threads = 8;
    bool use_mmap = true;
    bool flash_attention = true;
    uint64_t max_image_bytes = 10U * 1024U * 1024U;
    uint32_t max_image_width = 4096;
    uint32_t max_image_height = 4096;
    uint64_t max_image_pixels = 16U * 1024U * 1024U;
};

struct GenerateRequest {
    std::string request_id;
    // Optional non-empty key for the single hot text KV prefix.
    std::string session_id;
    std::vector<ChatMessage> messages;
    std::vector<ImageInput> images;  // M7.5A contract: 0..1 only.
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
    uint64_t image_preprocess_ms = 0;
    uint64_t vision_encode_ms = 0;
    uint64_t image_embedding_ms = 0;
    uint64_t decode_ms = 0;
    uint64_t total_ms = 0;
    uint64_t first_token_ms = 0;
    uint64_t ttft_ms = 0;
    uint64_t tpot_ms = 0;
    double decode_tokens_per_second = 0.0;
    uint32_t prefill_input_tokens = 0;
    uint32_t cache_hit_tokens = 0;
    uint32_t cache_miss_tokens = 0;
    double cache_hit_ratio = 0.0;
    bool cache_reused = false;
    std::string cache_invalidation_reason;
};

struct GenerateResponse {
    std::string request_id;
    std::string session_id;
    std::string text;
    RuntimeErrorCode code = RuntimeErrorCode::kOk;
    std::string error_message;
    std::string finish_reason;
    uint32_t prompt_tokens = 0;
    uint32_t generated_tokens = 0;
    uint32_t image_tokens = 0;
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
