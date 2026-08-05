#include "edgeomni/direct_backend.h"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <filesystem>
#include <memory>
#include <mutex>
#include <string>
#include <utility>
#include <vector>

#include "edgeomni/chat_template_renderer.h"
#include "llama_backend_lifecycle.h"
#include "llama.h"

namespace edgeomni {
namespace {

// The benchmark admits only the two locally audited Qwen3 weight artifacts.
// The expected hash is still supplied by the caller and checked against this
// allow-list; arbitrary model files cannot enter the DirectBackend path.
constexpr const char * kQwen3Q4ModelSha256 = "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5";
constexpr const char * kQwen3Q8ModelSha256 = "8c2f07f26af9747e41988551106f149b03eb9b5cb6df636027b6bf6278473300";

struct ModelDeleter {
    void operator()(llama_model * model) const { if (model) llama_model_free(model); }
};
struct ContextDeleter {
    void operator()(llama_context * context) const { if (context) llama_free(context); }
};
struct SamplerDeleter {
    void operator()(llama_sampler * sampler) const { if (sampler) llama_sampler_free(sampler); }
};
struct BatchOwner {
    explicit BatchOwner(int32_t capacity) : batch(llama_batch_init(capacity, 0, 1)) {}
    ~BatchOwner() { llama_batch_free(batch); }
    llama_batch batch{};
};

struct RequestControl {
    std::atomic_bool cancelled{false};
    std::atomic<std::atomic_bool *> external_cancel{nullptr};
    std::atomic<int64_t> deadline_ns{0};
};

int64_t steady_now_ns() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();
}

bool abort_callback(void * data) {
    auto * control = static_cast<RequestControl *>(data);
    if (control->cancelled.load()) return true;
    auto * external = control->external_cancel.load();
    if (external != nullptr && external->load()) return true;
    const int64_t deadline = control->deadline_ns.load();
    return deadline != 0 && steady_now_ns() >= deadline;
}

RuntimeErrorCode decode_code(int32_t result) {
    if (result == 1) return RuntimeErrorCode::kDecodeNoKvSlot;
    if (result == 2) return RuntimeErrorCode::kDecodeAborted;
    return RuntimeErrorCode::kDecodeFailed;
}

Status token_to_piece(const llama_vocab * vocab, llama_token token, std::string * piece) {
    std::vector<char> buffer(128);
    for (;;) {
        const int32_t count = llama_token_to_piece(vocab, token, buffer.data(), static_cast<int32_t>(buffer.size()), 0, false);
        if (count >= 0) {
            piece->assign(buffer.data(), static_cast<size_t>(count));
            return Status::Ok();
        }
        const int32_t required = -count;
        if (required <= 0 || required > 1024 * 1024) {
            return {RuntimeErrorCode::kTokenToTextFailed, "invalid token-to-piece buffer size"};
        }
        buffer.resize(static_cast<size_t>(required));
    }
}

std::string runtime_config_fingerprint(const RuntimeConfig & config) {
    return config.model_path + "\n" + config.expected_model_sha256 + "\n" +
           std::to_string(config.expected_model_size_bytes) + "\n" + config.mmproj_path + "\n" +
           config.expected_mmproj_sha256 + "\n" + std::to_string(config.expected_mmproj_size_bytes) + "\n" +
           std::to_string(config.context_tokens) + "\n" + std::to_string(config.batch_tokens) + "\n" +
           std::to_string(config.ubatch_tokens) + "\n" + std::to_string(config.gpu_layers) + "\n" +
           std::to_string(config.generation_threads) + "\n" + std::to_string(config.batch_threads) + "\n" +
           std::to_string(config.use_mmap) + "\n" + std::to_string(config.flash_attention) + "\n" +
           std::to_string(config.max_image_bytes) + "\n" + std::to_string(config.max_image_width) + "\n" +
           std::to_string(config.max_image_height) + "\n" + std::to_string(config.max_image_pixels);
}

}  // namespace

class DirectBackend::Impl {
  public:
    std::mutex mutex;
    std::unique_ptr<llama_model, ModelDeleter> model;
    std::unique_ptr<llama_context, ContextDeleter> context;
    const llama_vocab * vocab = nullptr;
    RuntimeConfig config;
    bool initialized = false;
    bool backend_acquired = false;
    uint64_t model_ready_ms = 0;
    RequestControl request_control;
    std::mutex request_mutex;
    std::string active_request_id;
    std::string hot_session_id;
    std::vector<llama_token> hot_prompt_tokens;
    std::string hot_model_hash;
    std::string hot_template_fingerprint;
    std::string hot_runtime_config_fingerprint;
};

DirectBackend::DirectBackend() : impl_(std::make_unique<Impl>()) {}
DirectBackend::~DirectBackend() { shutdown(); }

Status DirectBackend::initialize(const RuntimeConfig & config) {
    const auto started = std::chrono::steady_clock::now();
    std::lock_guard<std::mutex> lock(impl_->mutex);
    if (impl_->initialized) return {RuntimeErrorCode::kAlreadyInitialized, "DirectBackend is already initialized"};
    if (config.model_path.empty() || !std::filesystem::exists(config.model_path)) {
        return {RuntimeErrorCode::kModelNotFound, "configured model does not exist"};
    }
    if (config.expected_model_sha256 != kQwen3Q4ModelSha256 && config.expected_model_sha256 != kQwen3Q8ModelSha256) {
        return {RuntimeErrorCode::kModelHashMismatch, "expected model hash is not an audited Qwen3 benchmark artifact"};
    }
    if (config.context_tokens == 0U || config.batch_tokens == 0U || config.ubatch_tokens == 0U) {
        return {RuntimeErrorCode::kInvalidArgument, "context, batch, and ubatch token counts must be non-zero"};
    }

    const Status backend_status = acquire_llama_backend();
    if (!backend_status.ok()) return backend_status;
    impl_->backend_acquired = true;

    llama_model_params model_params = llama_model_default_params();
    model_params.n_gpu_layers = config.gpu_layers;
    model_params.use_mmap = config.use_mmap;
    impl_->model.reset(llama_model_load_from_file(config.model_path.c_str(), model_params));
    if (!impl_->model) {
        release_llama_backend(); impl_->backend_acquired = false;
        return {RuntimeErrorCode::kModelLoadFailed, "llama_model_load_from_file returned null"};
    }

    const char * template_source = llama_model_chat_template(impl_->model.get(), nullptr);
    ChatTemplateRenderer renderer;
    const Status template_status = template_source ? renderer.validate_template(template_source)
                                                   : Status{RuntimeErrorCode::kTemplateUnsupported, "model has no default chat template"};
    if (!template_status.ok()) {
        impl_->model.reset();
        release_llama_backend(); impl_->backend_acquired = false;
        return template_status;
    }

    llama_context_params context_params = llama_context_default_params();
    context_params.n_ctx = config.context_tokens;
    context_params.n_batch = config.batch_tokens;
    context_params.n_ubatch = config.ubatch_tokens;
    context_params.n_threads = config.generation_threads;
    context_params.n_threads_batch = config.batch_threads;
    context_params.offload_kqv = true;
    context_params.flash_attn_type = config.flash_attention ? LLAMA_FLASH_ATTN_TYPE_ENABLED : LLAMA_FLASH_ATTN_TYPE_DISABLED;
    impl_->context.reset(llama_init_from_model(impl_->model.get(), context_params));
    if (!impl_->context) {
        impl_->model.reset();
        release_llama_backend(); impl_->backend_acquired = false;
        return {RuntimeErrorCode::kContextCreateFailed, "llama_init_from_model returned null"};
    }
    impl_->vocab = llama_model_get_vocab(impl_->model.get());
    if (!impl_->vocab) {
        impl_->context.reset();
        impl_->model.reset();
        release_llama_backend(); impl_->backend_acquired = false;
        return {RuntimeErrorCode::kInternal, "llama_model_get_vocab returned null"};
    }
    impl_->config = config;
    llama_set_abort_callback(impl_->context.get(), abort_callback, &impl_->request_control);
    impl_->model_ready_ms = static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now() - started).count());
    impl_->initialized = true;
    return Status::Ok();
}

GenerateResponse DirectBackend::generate_text(const GenerateRequest & request, const TokenCallback & on_token) {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    const auto started = std::chrono::steady_clock::now();
    GenerateResponse response;
    response.request_id = request.request_id;
    response.session_id = request.session_id;
    response.metrics.model_ready_ms = impl_->model_ready_ms;
    if (!request.images.empty()) {
        if (impl_->initialized) {
            llama_synchronize(impl_->context.get());
            llama_memory_clear(llama_get_memory(impl_->context.get()), false);
        }
        impl_->hot_session_id.clear(); impl_->hot_prompt_tokens.clear();
        response.metrics.cache_invalidation_reason = "image_request";
        response.code = RuntimeErrorCode::kInvalidArgument;
        response.error_message = "DirectBackend does not support images; use the VLM adapter backend";
        response.finish_reason = "error";
        return response;
    }
    if (!impl_->initialized) {
        response.code = RuntimeErrorCode::kInvalidState;
        response.error_message = "DirectBackend is not initialized";
        return response;
    }
    if (request.request_id.empty() || request.messages.empty() || request.max_new_tokens == 0U) {
        response.code = RuntimeErrorCode::kInvalidArgument;
        response.error_message = "request requires request_id, at least one message, and max_new_tokens";
        return response;
    }

    struct RequestGuard {
        Impl & impl;
        ~RequestGuard() {
            std::lock_guard<std::mutex> request_lock(impl.request_mutex);
            impl.request_control.external_cancel.store(nullptr);
            impl.request_control.deadline_ns.store(0);
            impl.request_control.cancelled.store(false);
            impl.active_request_id.clear();
        }
    } guard{*impl_};
    {
        std::lock_guard<std::mutex> request_lock(impl_->request_mutex);
        impl_->active_request_id = request.request_id;
        impl_->request_control.cancelled.store(false);
        impl_->request_control.external_cancel.store(request.cancel_flag.get());
        impl_->request_control.deadline_ns.store(request.timeout_ms == 0U ? 0 :
            steady_now_ns() + static_cast<int64_t>(request.timeout_ms) * 1000000LL);
    }
    const auto recover = [&]() {
        llama_synchronize(impl_->context.get());
        llama_memory_clear(llama_get_memory(impl_->context.get()), false);
    };
    const auto elapsed_ms = [&]() {
        return static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now() - started).count());
    };
    const auto cancelled = [&]() {
        auto * external = impl_->request_control.external_cancel.load();
        return impl_->request_control.cancelled.load() || (external != nullptr && external->load());
    };
    const auto timed_out = [&]() {
        const int64_t deadline = impl_->request_control.deadline_ns.load();
        return deadline != 0 && steady_now_ns() >= deadline;
    };

    ChatTemplateRenderer renderer;
    std::string prompt;
    const Status render_status = renderer.render(request.messages, true, &prompt);
    if (!render_status.ok()) {
        llama_synchronize(impl_->context.get());
        llama_memory_clear(llama_get_memory(impl_->context.get()), false);
        impl_->hot_session_id.clear(); impl_->hot_prompt_tokens.clear();
        response.metrics.cache_invalidation_reason = "prompt_render_failed";
        response.code = render_status.code;
        response.error_message = render_status.message;
        response.finish_reason = "error";
        return response;
    }
    const int32_t required = llama_tokenize(impl_->vocab, prompt.c_str(), static_cast<int32_t>(prompt.size()), nullptr, 0, true, true);
    if (required >= 0) {
        llama_synchronize(impl_->context.get());
        llama_memory_clear(llama_get_memory(impl_->context.get()), false);
        impl_->hot_session_id.clear(); impl_->hot_prompt_tokens.clear();
        response.metrics.cache_invalidation_reason = "tokenize_failed";
        response.code = RuntimeErrorCode::kTokenizeFailed;
        response.error_message = "llama_tokenize did not return required token count";
        response.finish_reason = "error";
        return response;
    }
    std::vector<llama_token> tokens(static_cast<size_t>(-required));
    if (llama_tokenize(impl_->vocab, prompt.c_str(), static_cast<int32_t>(prompt.size()), tokens.data(),
                       static_cast<int32_t>(tokens.size()), true, true) < 0) {
        llama_synchronize(impl_->context.get());
        llama_memory_clear(llama_get_memory(impl_->context.get()), false);
        impl_->hot_session_id.clear(); impl_->hot_prompt_tokens.clear();
        response.metrics.cache_invalidation_reason = "tokenize_failed";
        response.code = RuntimeErrorCode::kTokenizeFailed;
        response.error_message = "llama_tokenize failed";
        response.finish_reason = "error";
        return response;
    }
    const uint32_t context_capacity = llama_n_ctx(impl_->context.get());
    if (tokens.size() + request.max_new_tokens > context_capacity) {
        llama_synchronize(impl_->context.get());
        llama_memory_clear(llama_get_memory(impl_->context.get()), false);
        impl_->hot_session_id.clear(); impl_->hot_prompt_tokens.clear();
        response.metrics.cache_invalidation_reason = "context_limit";
        response.code = RuntimeErrorCode::kContextLimit;
        response.error_message = "prompt plus requested generation exceeds context";
        response.finish_reason = "error";
        return response;
    }
    const auto clear_hot = [&](const char * reason) {
        llama_synchronize(impl_->context.get());
        llama_memory_clear(llama_get_memory(impl_->context.get()), false);
        llama_synchronize(impl_->context.get());
        impl_->hot_session_id.clear();
        impl_->hot_prompt_tokens.clear();
        impl_->hot_model_hash.clear();
        impl_->hot_template_fingerprint.clear();
        impl_->hot_runtime_config_fingerprint.clear();
        response.metrics.cache_invalidation_reason = reason;
    };
    const auto remove_kv_range = [&](size_t begin) {
        llama_synchronize(impl_->context.get());
        const bool removed = llama_memory_seq_rm(llama_get_memory(impl_->context.get()), 0,
                                                 static_cast<llama_pos>(begin), -1);
        llama_synchronize(impl_->context.get());
        return removed;
    };
    size_t reused = 0;
    if (request.session_id.empty()) {
        clear_hot("no_session_id");
    } else if (!impl_->hot_session_id.empty() && impl_->hot_session_id != request.session_id) {
        clear_hot("session_id_changed");
    } else if (!impl_->hot_session_id.empty() &&
               (impl_->hot_model_hash != impl_->config.expected_model_sha256 ||
                impl_->hot_template_fingerprint != ChatTemplateRenderer::kQwen3TemplateSha256 ||
                impl_->hot_runtime_config_fingerprint != runtime_config_fingerprint(impl_->config))) {
        clear_hot("runtime_config_changed");
    } else if (!impl_->hot_prompt_tokens.empty()) {
        while (reused < impl_->hot_prompt_tokens.size() && reused < tokens.size() &&
               impl_->hot_prompt_tokens[reused] == tokens[reused]) ++reused;
        // Re-run one prompt token so llama logits always correspond to this request.
        if (reused == tokens.size() && reused > 0U) --reused;
        if (!remove_kv_range(reused)) {
            clear_hot("kv_rollback_failed");
            reused = 0;
        }
    } else {
        llama_memory_clear(llama_get_memory(impl_->context.get()), false);
    }
    response.metrics.cache_hit_tokens = static_cast<uint32_t>(reused);
    response.metrics.cache_miss_tokens = static_cast<uint32_t>(tokens.size() - reused);
    response.metrics.prefill_input_tokens = response.metrics.cache_miss_tokens;
    response.metrics.cache_hit_ratio = tokens.empty() ? 0.0 : static_cast<double>(reused) / tokens.size();
    response.metrics.cache_reused = reused > 0U;
    const auto prefill_started = std::chrono::steady_clock::now();

    const int32_t batch_capacity = static_cast<int32_t>(std::min<uint32_t>(impl_->config.batch_tokens, context_capacity));
    BatchOwner batch_owner(batch_capacity);
    for (size_t begin = reused; begin < tokens.size();) {
        const int32_t count = static_cast<int32_t>(std::min<size_t>(batch_capacity, tokens.size() - begin));
        auto & batch = batch_owner.batch;
        batch.n_tokens = count;
        for (int32_t i = 0; i < count; ++i) {
            batch.token[i] = tokens[begin + static_cast<size_t>(i)];
            batch.pos[i] = static_cast<llama_pos>(begin + static_cast<size_t>(i));
            batch.n_seq_id[i] = 1;
            batch.seq_id[i][0] = 0;
            batch.logits[i] = begin + static_cast<size_t>(i) + 1U == tokens.size();
        }
        const int32_t decode_result = llama_decode(impl_->context.get(), batch);
        if (decode_result != 0) {
            clear_hot("prefill_failed");
            if (cancelled()) {
                response.code = RuntimeErrorCode::kCancelled;
                response.finish_reason = "cancelled";
                response.error_message = "request cancelled during prefill";
            } else if (timed_out()) {
                response.code = RuntimeErrorCode::kTimeout;
                response.finish_reason = "timeout";
                response.error_message = "request timed out during prefill";
            } else {
                response.code = decode_code(decode_result);
                response.finish_reason = "error";
                response.error_message = "llama_decode failed during prefill";
            }
            response.metrics.prefill_ms = static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(
                std::chrono::steady_clock::now() - prefill_started).count());
            response.metrics.total_ms = elapsed_ms();
            return response;
        }
        begin += static_cast<size_t>(count);
    }
    response.prompt_tokens = static_cast<uint32_t>(tokens.size());
    response.metrics.prompt_tokens = response.prompt_tokens;
    response.metrics.prefill_ms = static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now() - prefill_started).count());

    llama_sampler_chain_params sampler_params = llama_sampler_chain_default_params();
    std::unique_ptr<llama_sampler, SamplerDeleter> sampler(llama_sampler_chain_init(sampler_params));
    if (!sampler) {
        response.code = RuntimeErrorCode::kInternal;
        response.error_message = "llama_sampler_chain_init returned null";
        response.finish_reason = "error";
        clear_hot("sampler_init_failed");
        response.metrics.total_ms = elapsed_ms();
        return response;
    }
    llama_sampler_chain_add(sampler.get(), llama_sampler_init_top_k(request.sampling.top_k));
    llama_sampler_chain_add(sampler.get(), llama_sampler_init_top_p(request.sampling.top_p, 1));
    llama_sampler_chain_add(sampler.get(), llama_sampler_init_min_p(request.sampling.min_p, 1));
    llama_sampler_chain_add(sampler.get(), llama_sampler_init_temp(request.sampling.temperature));
    llama_sampler_chain_add(sampler.get(), llama_sampler_init_dist(request.sampling.seed));

    const auto decode_started = std::chrono::steady_clock::now();
    for (uint32_t generated = 0; generated < request.max_new_tokens; ++generated) {
        if (cancelled()) {
            clear_hot("cancelled");
            response.code = RuntimeErrorCode::kCancelled;
            response.finish_reason = "cancelled";
            response.error_message = "request cancelled";
            break;
        }
        if (timed_out()) {
            clear_hot("timeout");
            response.code = RuntimeErrorCode::kTimeout;
            response.finish_reason = "timeout";
            response.error_message = "request timed out";
            break;
        }
        const llama_token token = llama_sampler_sample(sampler.get(), impl_->context.get(), -1);
        if (llama_vocab_is_eog(impl_->vocab, token)) {
            response.finish_reason = "stop";
            break;
        }
        std::string piece;
        const Status piece_status = token_to_piece(impl_->vocab, token, &piece);
        if (!piece_status.ok()) {
            response.code = piece_status.code;
            response.error_message = piece_status.message;
            response.finish_reason = "error";
            clear_hot("token_to_text_failed");
            return response;
        }
        if (on_token && !on_token({request.request_id, piece, response.generated_tokens})) {
            impl_->request_control.cancelled.store(true);
            clear_hot("cancelled");
            response.code = RuntimeErrorCode::kCancelled;
            response.finish_reason = "cancelled";
            response.error_message = "token callback cancelled request";
            break;
        }
        response.text += piece;
        ++response.generated_tokens;
        if (response.generated_tokens == 1U) {
            response.metrics.first_token_ms = elapsed_ms();
            response.metrics.ttft_ms = response.metrics.first_token_ms;
        }

        auto & batch = batch_owner.batch;
        batch.n_tokens = 1;
        batch.token[0] = token;
        batch.pos[0] = static_cast<llama_pos>(tokens.size() + generated);
        batch.n_seq_id[0] = 1;
        batch.seq_id[0][0] = 0;
        batch.logits[0] = 1;
        const int32_t decode_result = llama_decode(impl_->context.get(), batch);
        if (decode_result != 0) {
            clear_hot("decode_failed");
            if (cancelled()) {
                response.code = RuntimeErrorCode::kCancelled;
                response.finish_reason = "cancelled";
                response.error_message = "request cancelled during generation";
            } else if (timed_out()) {
                response.code = RuntimeErrorCode::kTimeout;
                response.finish_reason = "timeout";
                response.error_message = "request timed out during generation";
            } else {
                response.code = decode_code(decode_result);
                response.finish_reason = "error";
                response.error_message = "llama_decode failed during generation";
            }
            break;
        }
    }
    response.metrics.output_tokens = response.generated_tokens;
    response.metrics.decode_ms = static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now() - decode_started).count());
    response.metrics.total_ms = elapsed_ms();
    if (response.metrics.decode_ms > 0U) {
        response.metrics.decode_tokens_per_second = static_cast<double>(response.generated_tokens) * 1000.0 /
            static_cast<double>(response.metrics.decode_ms);
    }
    if (response.finish_reason.empty()) response.finish_reason = "length";
    if (response.code == RuntimeErrorCode::kOk) {
        // Decode adds generated tokens after the prompt. Keep only the complete prompt KV.
        if (!remove_kv_range(tokens.size())) {
            clear_hot("kv_rollback_failed");
        } else if (!request.session_id.empty()) {
            impl_->hot_session_id = request.session_id;
            impl_->hot_prompt_tokens = tokens;
            impl_->hot_model_hash = impl_->config.expected_model_sha256;
            impl_->hot_template_fingerprint = ChatTemplateRenderer::kQwen3TemplateSha256;
            impl_->hot_runtime_config_fingerprint = runtime_config_fingerprint(impl_->config);
        }
    } else {
        clear_hot("incomplete_request");
    }
    return response;
}

Status DirectBackend::cancel_request(const std::string & request_id) {
    std::lock_guard<std::mutex> request_lock(impl_->request_mutex);
    if (!impl_->initialized || request_id.empty() || impl_->active_request_id != request_id) {
        return {RuntimeErrorCode::kInvalidState, "no matching active request"};
    }
    impl_->request_control.cancelled.store(true);
    return Status::Ok();
}

Status DirectBackend::reset_context() {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    if (!impl_->initialized) return {RuntimeErrorCode::kInvalidState, "DirectBackend is not initialized"};
    llama_synchronize(impl_->context.get());
    llama_memory_clear(llama_get_memory(impl_->context.get()), false);
    llama_synchronize(impl_->context.get());
    impl_->hot_session_id.clear();
    impl_->hot_prompt_tokens.clear();
    impl_->hot_model_hash.clear();
    impl_->hot_template_fingerprint.clear();
    impl_->hot_runtime_config_fingerprint.clear();
    return Status::Ok();
}

Status DirectBackend::shutdown() {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    impl_->context.reset();
    impl_->model.reset();
    impl_->vocab = nullptr;
    impl_->initialized = false;
    impl_->hot_session_id.clear();
    impl_->hot_prompt_tokens.clear();
    impl_->hot_model_hash.clear();
    impl_->hot_template_fingerprint.clear();
    impl_->hot_runtime_config_fingerprint.clear();
    if (impl_->backend_acquired) {
        release_llama_backend();
        impl_->backend_acquired = false;
    }
    return Status::Ok();
}

}  // namespace edgeomni
