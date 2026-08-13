#include "edgeomni/mtmd_backend.h"

#include <atomic>
#include <chrono>
#include <memory>
#include <mutex>
#include <string>
#include <utility>
#include <vector>

#include "edgeomni/vlm_asset_verifier.h"
#include "edgeomni/vlm_input_validator.h"
#include "llama_backend_lifecycle.h"
#include "llama.h"
#include "mtmd-helper.h"
#include "mtmd.h"

namespace edgeomni {
namespace {
struct ModelDeleter { void operator()(llama_model * v) const { if (v) llama_model_free(v); } };
struct ContextDeleter { void operator()(llama_context * v) const { if (v) llama_free(v); } };
struct SamplerDeleter { void operator()(llama_sampler * v) const { if (v) llama_sampler_free(v); } };
struct BitmapDeleter { void operator()(mtmd_bitmap * v) const { if (v) mtmd_bitmap_free(v); } };
struct ChunksDeleter { void operator()(mtmd_input_chunks * v) const { if (v) mtmd_input_chunks_free(v); } };
struct VisionDeleter { void operator()(mtmd_context * v) const { if (v) mtmd_free(v); } };
struct BatchOwner { explicit BatchOwner(int n) : value(llama_batch_init(n, 0, 1)) {} ~BatchOwner() { llama_batch_free(value); } llama_batch value{}; };

int64_t now_ns() { return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count(); }
uint64_t elapsed_ms(const std::chrono::steady_clock::time_point & begin) {
    return static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - begin).count());
}
Status piece_for(const llama_vocab * vocab, llama_token token, std::string * out) {
    std::vector<char> bytes(128);
    for (;;) {
        const int n = llama_token_to_piece(vocab, token, bytes.data(), static_cast<int>(bytes.size()), 0, false);
        if (n >= 0) { out->assign(bytes.data(), static_cast<size_t>(n)); return Status::Ok(); }
        if (-n <= 0 || -n > 1024 * 1024) return {RuntimeErrorCode::kTokenToTextFailed, "token conversion buffer is invalid"};
        bytes.resize(static_cast<size_t>(-n));
    }
}
}  // namespace

class MtmdBackend::Impl {
  public:
    std::mutex lifecycle_mutex;
    std::mutex generation_mutex;
    std::mutex control_mutex;
    std::unique_ptr<llama_model, ModelDeleter> model;
    std::unique_ptr<llama_context, ContextDeleter> context;
    std::unique_ptr<mtmd_context, VisionDeleter> vision;
    const llama_vocab * vocab = nullptr;
    RuntimeConfig config;
    bool initialized = false;
    bool backend_acquired = false;
    uint64_t model_ready_ms = 0;
    std::string active_request_id;
    std::atomic_bool cancelled{false};
    std::atomic<std::atomic_bool *> external_cancel{nullptr};
    std::atomic<int64_t> deadline_ns{0};
    std::string hot_session_id;
    std::vector<llama_token> hot_prompt_tokens;
};

MtmdBackend::MtmdBackend() : impl_(std::make_unique<Impl>()) {}
MtmdBackend::~MtmdBackend() { shutdown(); }

Status MtmdBackend::initialize(const RuntimeConfig & config) {
    const auto started = std::chrono::steady_clock::now();
    std::lock_guard<std::mutex> lock(impl_->lifecycle_mutex);
    if (impl_->initialized) return {RuntimeErrorCode::kAlreadyInitialized, "MtmdBackend is already initialized"};
    if (config.context_tokens == 0U || config.batch_tokens == 0U || config.ubatch_tokens == 0U) {
        return {RuntimeErrorCode::kInvalidArgument, "context, batch, and ubatch token counts must be non-zero"};
    }
    const VlmAssetSet assets{{"qwen25_vl_3b_main_q4_k_m", config.model_path, config.expected_model_size_bytes, config.expected_model_sha256},
                             {"qwen25_vl_3b_mmproj_q8_0", config.mmproj_path, config.expected_mmproj_size_bytes, config.expected_mmproj_sha256},
                             {"qwen25_vl_3b_main_mmproj_binding", "qwen25_vl_3b_main_q4_k_m", "qwen25_vl_3b_mmproj_q8_0"}};
    const Status verified = verify_vlm_assets(assets);
    if (!verified.ok()) return verified;
    const Status backend = acquire_llama_backend();
    if (!backend.ok()) return {RuntimeErrorCode::kBackendUnavailable, backend.message};
    impl_->backend_acquired = true;
    llama_model_params model_params = llama_model_default_params();
    model_params.n_gpu_layers = config.gpu_layers;
    model_params.use_mmap = config.use_mmap;
    impl_->model.reset(llama_model_load_from_file(config.model_path.c_str(), model_params));
    if (!impl_->model) { release_llama_backend(); impl_->backend_acquired = false; return {RuntimeErrorCode::kModelLoadFailed, "llama model load returned null"}; }
    if (!llama_model_chat_template(impl_->model.get(), nullptr)) {
        impl_->model.reset(); release_llama_backend(); impl_->backend_acquired = false;
        return {RuntimeErrorCode::kTemplateUnsupported, "model has no default chat template"};
    }
    llama_context_params params = llama_context_default_params();
    params.n_ctx = config.context_tokens; params.n_batch = config.batch_tokens; params.n_ubatch = config.ubatch_tokens;
    params.n_threads = config.generation_threads; params.n_threads_batch = config.batch_threads; params.offload_kqv = true;
    params.flash_attn_type = config.flash_attention ? LLAMA_FLASH_ATTN_TYPE_ENABLED : LLAMA_FLASH_ATTN_TYPE_DISABLED;
    impl_->context.reset(llama_init_from_model(impl_->model.get(), params));
    if (!impl_->context) { impl_->model.reset(); release_llama_backend(); impl_->backend_acquired = false; return {RuntimeErrorCode::kContextCreateFailed, "llama context creation returned null"}; }
    impl_->vocab = llama_model_get_vocab(impl_->model.get());
    mtmd_context_params vision_params = mtmd_context_params_default();
    vision_params.use_gpu = true; vision_params.n_threads = config.generation_threads;
    vision_params.flash_attn_type = params.flash_attn_type; vision_params.warmup = false;
    impl_->vision.reset(mtmd_init_from_file(config.mmproj_path.c_str(), impl_->model.get(), vision_params));
    if (!impl_->vision || !mtmd_support_vision(impl_->vision.get())) {
        impl_->vision.reset(); impl_->context.reset(); impl_->model.reset(); impl_->vocab = nullptr;
        release_llama_backend(); impl_->backend_acquired = false;
        return {RuntimeErrorCode::kMmprojLoadFailed, "mmproj initialization did not provide vision support"};
    }
    impl_->config = config; impl_->model_ready_ms = elapsed_ms(started); impl_->initialized = true;
    return Status::Ok();
}

GenerateResponse MtmdBackend::generate_text(const GenerateRequest & request, const TokenCallback & on_token) {
    GenerateResponse response; response.request_id = request.request_id; response.metrics.model_ready_ms = impl_->model_ready_ms;
    if (!impl_->generation_mutex.try_lock()) { response.code = RuntimeErrorCode::kResourceExhausted; response.finish_reason = "error"; response.error_message = "MtmdBackend accepts one in-flight request"; return response; }
    std::unique_lock<std::mutex> generation_lock(impl_->generation_mutex, std::adopt_lock);
    const auto started = std::chrono::steady_clock::now();
    {
        std::lock_guard<std::mutex> lock(impl_->lifecycle_mutex);
        if (!impl_->initialized) { response.code = RuntimeErrorCode::kInvalidState; response.error_message = "MtmdBackend is not initialized"; return response; }
    }
    if (request.request_id.empty() || request.messages.empty() || request.max_new_tokens == 0U) {
        response.code = RuntimeErrorCode::kInvalidArgument; response.finish_reason = "error"; response.error_message = "request requires request_id, messages, and max_new_tokens"; return response;
    }
    if (request.images.size() > 1U) { response.code = RuntimeErrorCode::kImageCountExceeded; response.finish_reason = "error"; response.error_message = "at most one image is supported"; return response; }
    struct Guard {
        Impl & impl;
        bool preserve_prompt = false;
        ~Guard() {
            llama_synchronize(impl.context.get());
            if (!preserve_prompt) {
                llama_memory_clear(llama_get_memory(impl.context.get()), false);
                impl.hot_session_id.clear();
                impl.hot_prompt_tokens.clear();
            }
            std::lock_guard<std::mutex> l(impl.control_mutex);
            impl.active_request_id.clear(); impl.cancelled.store(false); impl.external_cancel.store(nullptr); impl.deadline_ns.store(0);
        }
    } guard{*impl_};
    {
        std::lock_guard<std::mutex> lock(impl_->control_mutex);
        impl_->active_request_id = request.request_id; impl_->cancelled.store(false); impl_->external_cancel.store(request.cancel_flag.get());
        impl_->deadline_ns.store(request.timeout_ms == 0U ? 0 : now_ns() + static_cast<int64_t>(request.timeout_ms) * 1000000LL);
    }
    const auto cancelled = [&] { auto * value = impl_->external_cancel.load(); return impl_->cancelled.load() || (value && value->load()); };
    const auto timeout = [&] { const auto deadline = impl_->deadline_ns.load(); return deadline != 0 && now_ns() >= deadline; };
    auto stop = [&]() { if (cancelled()) { response.code = RuntimeErrorCode::kCancelled; response.finish_reason = "cancelled"; response.error_message = "request cancelled"; return true; } if (timeout()) { response.code = RuntimeErrorCode::kTimeout; response.finish_reason = "timeout"; response.error_message = "request timed out"; return true; } return false; };

    std::unique_ptr<mtmd_bitmap, BitmapDeleter> bitmap;
    const mtmd_bitmap * bitmap_ptr = nullptr;
    if (!request.images.empty()) {
        const ImageInput & image = request.images.front();
        if (image.id.empty() || image.encoded_bytes.empty() || image.encoded_bytes.size() > impl_->config.max_image_bytes ||
            (image.mime_type != "image/jpeg" && image.mime_type != "image/png" && image.mime_type != "image/webp")) {
            const Status status = validate_image_input(image, {}, {impl_->config.max_image_bytes, impl_->config.max_image_width, impl_->config.max_image_height, impl_->config.max_image_pixels});
            response.code = status.code; response.error_message = status.message; response.finish_reason = "error"; return response;
        }
        const auto decode_started = std::chrono::steady_clock::now();
        bitmap.reset(mtmd_helper_bitmap_init_from_buf(impl_->vision.get(), image.encoded_bytes.data(), image.encoded_bytes.size()));
        response.metrics.image_preprocess_ms = elapsed_ms(decode_started);
        response.metrics.image_preprocess_measured = true;
        if (!bitmap || mtmd_bitmap_is_audio(bitmap.get())) { response.code = RuntimeErrorCode::kImageDecodeFailed; response.finish_reason = "error"; response.error_message = "mtmd failed to decode image bytes"; return response; }
        const Status status = validate_image_input(image, {mtmd_bitmap_get_nx(bitmap.get()), mtmd_bitmap_get_ny(bitmap.get())},
                                                   {impl_->config.max_image_bytes, impl_->config.max_image_width, impl_->config.max_image_height, impl_->config.max_image_pixels});
        if (!status.ok()) { response.code = status.code; response.error_message = status.message; response.finish_reason = "error"; return response; }
        mtmd_bitmap_set_id(bitmap.get(), image.id.c_str()); bitmap_ptr = bitmap.get();
    }
    if (stop()) { response.metrics.total_ms = elapsed_ms(started); return response; }
    std::vector<llama_chat_message> chat; chat.reserve(request.messages.size());
    std::vector<std::string> contents; contents.reserve(request.messages.size());
    for (const auto & message : request.messages) { if (message.role.empty()) { response.code = RuntimeErrorCode::kInvalidArgument; response.error_message = "message role is required"; response.finish_reason = "error"; return response; } contents.push_back(message.content); }
    if (bitmap_ptr) contents.back() = std::string(mtmd_default_marker()) + contents.back();
    for (size_t i = 0; i < request.messages.size(); ++i) chat.push_back({request.messages[i].role.c_str(), contents[i].c_str()});
    const char * tmpl = llama_model_chat_template(impl_->model.get(), nullptr);
    int32_t required = llama_chat_apply_template(tmpl, chat.data(), chat.size(), true, nullptr, 0);
    if (required <= 0) { response.code = RuntimeErrorCode::kTemplateUnsupported; response.finish_reason = "error"; response.error_message = "model chat template could not format messages"; return response; }
    std::string prompt(static_cast<size_t>(required), '\0');
    if (llama_chat_apply_template(tmpl, chat.data(), chat.size(), true, prompt.data(), required) != required) { response.code = RuntimeErrorCode::kTemplateUnsupported; response.finish_reason = "error"; response.error_message = "model chat template formatting failed"; return response; }
    mtmd_input_text input{prompt.c_str(), true, true};
    std::unique_ptr<mtmd_input_chunks, ChunksDeleter> chunks(mtmd_input_chunks_init());
    if (!chunks) { response.code = RuntimeErrorCode::kInternal; response.finish_reason = "error"; response.error_message = "mtmd chunk allocation failed"; return response; }
    const mtmd_bitmap * bitmaps[] = {bitmap_ptr};
    const int tokenize = mtmd_tokenize(impl_->vision.get(), chunks.get(), &input, bitmap_ptr ? bitmaps : nullptr, bitmap_ptr ? 1 : 0);
    if (tokenize != 0) { response.code = tokenize == 2 ? RuntimeErrorCode::kImageDecodeFailed : RuntimeErrorCode::kTokenizeFailed; response.finish_reason = "error"; response.error_message = "mtmd prompt chunk tokenization failed"; return response; }
    const size_t prompt_tokens = mtmd_helper_get_n_tokens(chunks.get());
    const bool text_only = request.images.empty();
    std::vector<llama_token> prompt_token_ids;
    if (text_only) {
        prompt_token_ids.reserve(prompt_tokens);
        for (size_t index = 0; index < mtmd_input_chunks_size(chunks.get()); ++index) {
            const auto * chunk = mtmd_input_chunks_get(chunks.get(), index);
            if (mtmd_input_chunk_get_type(chunk) != MTMD_INPUT_CHUNK_TYPE_TEXT) {
                response.code = RuntimeErrorCode::kInternal; response.finish_reason = "error";
                response.error_message = "text-only request produced a non-text mtmd chunk"; return response;
            }
            size_t count = 0;
            const llama_token * values = mtmd_input_chunk_get_tokens_text(chunk, &count);
            if (!values || count != mtmd_input_chunk_get_n_tokens(chunk)) {
                response.code = RuntimeErrorCode::kTokenizeFailed; response.finish_reason = "error";
                response.error_message = "mtmd text chunk did not expose token ids"; return response;
            }
            prompt_token_ids.insert(prompt_token_ids.end(), values, values + count);
        }
        if (prompt_token_ids.size() != prompt_tokens) {
            response.code = RuntimeErrorCode::kTokenizeFailed; response.finish_reason = "error";
            response.error_message = "mtmd text token count disagrees with chunk total"; return response;
        }
    }
    for (size_t i = 0; i < mtmd_input_chunks_size(chunks.get()); ++i) { const auto * chunk = mtmd_input_chunks_get(chunks.get(), i); if (mtmd_input_chunk_get_type(chunk) == MTMD_INPUT_CHUNK_TYPE_IMAGE) response.image_tokens += static_cast<uint32_t>(mtmd_image_tokens_get_n_tokens(mtmd_input_chunk_get_tokens_image(chunk))); }
    if (prompt_tokens + request.max_new_tokens > llama_n_ctx(impl_->context.get())) { response.code = RuntimeErrorCode::kContextLimit; response.finish_reason = "error"; response.error_message = "prompt plus requested generation exceeds context"; return response; }
    const auto prefill_started = std::chrono::steady_clock::now(); llama_pos n_past = 0;
    int eval = 0;
    const size_t chunk_count = mtmd_input_chunks_size(chunks.get());
    size_t reused = 0;
    const auto clear_hot = [&](const char * reason) {
        llama_synchronize(impl_->context.get());
        llama_memory_clear(llama_get_memory(impl_->context.get()), false);
        impl_->hot_session_id.clear(); impl_->hot_prompt_tokens.clear();
        response.metrics.cache_invalidation_reason = reason;
    };
    const auto remove_kv_range = [&](size_t begin) {
        llama_synchronize(impl_->context.get());
        const bool removed = llama_memory_seq_rm(llama_get_memory(impl_->context.get()), 0, static_cast<llama_pos>(begin), -1);
        llama_synchronize(impl_->context.get());
        return removed;
    };
    const bool reuse_enabled = impl_->config.prefix_reuse_mode == PrefixReuseMode::kSingleHotText;
    if (!text_only) {
        clear_hot("image_request");
    } else if (!reuse_enabled) {
        clear_hot("disabled");
    } else if (request.session_id.empty()) {
        clear_hot("no_session_id");
    } else if (!impl_->hot_session_id.empty() && impl_->hot_session_id != request.session_id) {
        clear_hot("session_id_changed");
    } else if (!impl_->hot_prompt_tokens.empty()) {
        while (reused < impl_->hot_prompt_tokens.size() && reused < prompt_token_ids.size() && impl_->hot_prompt_tokens[reused] == prompt_token_ids[reused]) ++reused;
        if (reused == prompt_token_ids.size() && reused > 0U) --reused;
        if (!remove_kv_range(reused)) { clear_hot("kv_rollback_failed"); reused = 0; }
    } else {
        llama_memory_clear(llama_get_memory(impl_->context.get()), false);
    }
    response.metrics.cache_hit_tokens = static_cast<uint32_t>(reused);
    response.metrics.cache_miss_tokens = static_cast<uint32_t>(prompt_tokens - reused);
    response.metrics.prefill_input_tokens = response.metrics.cache_miss_tokens;
    response.metrics.cache_hit_ratio = prompt_tokens == 0U ? 0.0 : static_cast<double>(reused) / prompt_tokens;
    response.metrics.cache_reused = reused > 0U;
    if (text_only) {
        BatchOwner batch(static_cast<int>(std::min<uint32_t>(impl_->config.batch_tokens, impl_->config.context_tokens)));
        for (size_t begin = reused; begin < prompt_token_ids.size() && eval == 0;) {
            const int count = static_cast<int>(std::min<size_t>(impl_->config.batch_tokens, prompt_token_ids.size() - begin));
            batch.value.n_tokens = count;
            for (int i = 0; i < count; ++i) {
                batch.value.token[i] = prompt_token_ids[begin + static_cast<size_t>(i)];
                batch.value.pos[i] = static_cast<llama_pos>(begin + static_cast<size_t>(i));
                batch.value.n_seq_id[i] = 1; batch.value.seq_id[i][0] = 0;
                batch.value.logits[i] = begin + static_cast<size_t>(i) + 1U == prompt_token_ids.size();
            }
            eval = llama_decode(impl_->context.get(), batch.value);
            begin += static_cast<size_t>(count);
        }
    } else for (size_t index = 0; index < chunk_count && eval == 0; ++index) {
        const mtmd_input_chunk * chunk = mtmd_input_chunks_get(chunks.get(), index);
        const bool logits_last = index + 1U == chunk_count;
        if (mtmd_input_chunk_get_type(chunk) == MTMD_INPUT_CHUNK_TYPE_IMAGE) {
            const auto vision_started = std::chrono::steady_clock::now();
            eval = mtmd_encode_chunk(impl_->vision.get(), chunk);
            response.metrics.vision_encode_ms += elapsed_ms(vision_started);
            response.metrics.vision_encode_measured = true;
            if (eval != 0) break;
            const auto embedding_started = std::chrono::steady_clock::now();
            eval = mtmd_helper_decode_image_chunk(
                impl_->vision.get(), impl_->context.get(), chunk,
                mtmd_get_output_embd(impl_->vision.get()), n_past, 0,
                static_cast<int>(impl_->config.batch_tokens), &n_past);
            response.metrics.image_embedding_ms += elapsed_ms(embedding_started);
            response.metrics.image_embedding_measured = true;
        } else {
            eval = mtmd_helper_eval_chunk_single(
                impl_->vision.get(), impl_->context.get(), chunk, n_past, 0,
                static_cast<int>(impl_->config.batch_tokens), logits_last, &n_past);
        }
    }
    response.metrics.prefill_ms = elapsed_ms(prefill_started);
    if (eval != 0) { clear_hot("prefill_failed"); if (stop()) { response.metrics.total_ms = elapsed_ms(started); return response; } response.code = RuntimeErrorCode::kVisionEncodeFailed; response.finish_reason = "error"; response.error_message = "mtmd vision encode or prompt evaluation failed"; response.metrics.total_ms = elapsed_ms(started); return response; }
    response.prompt_tokens = static_cast<uint32_t>(prompt_tokens); response.metrics.prompt_tokens = response.prompt_tokens;
    if (stop()) { response.metrics.total_ms = elapsed_ms(started); return response; }
    llama_sampler_chain_params sampler_params = llama_sampler_chain_default_params();
    std::unique_ptr<llama_sampler, SamplerDeleter> sampler(llama_sampler_chain_init(sampler_params));
    if (!sampler) { response.code = RuntimeErrorCode::kInternal; response.finish_reason = "error"; response.error_message = "sampler initialization failed"; return response; }
    llama_sampler_chain_add(sampler.get(), llama_sampler_init_top_k(request.sampling.top_k)); llama_sampler_chain_add(sampler.get(), llama_sampler_init_top_p(request.sampling.top_p, 1)); llama_sampler_chain_add(sampler.get(), llama_sampler_init_min_p(request.sampling.min_p, 1)); llama_sampler_chain_add(sampler.get(), llama_sampler_init_temp(request.sampling.temperature)); llama_sampler_chain_add(sampler.get(), llama_sampler_init_dist(request.sampling.seed));
    BatchOwner batch(1); const auto decode_started = std::chrono::steady_clock::now();
    for (uint32_t i = 0; i < request.max_new_tokens; ++i) {
        if (stop()) break;
        const llama_token token = llama_sampler_sample(sampler.get(), impl_->context.get(), -1);
        if (llama_vocab_is_eog(impl_->vocab, token)) { response.finish_reason = "stop"; break; }
        std::string piece; const Status converted = piece_for(impl_->vocab, token, &piece);
        if (!converted.ok()) { response.code = converted.code; response.error_message = converted.message; response.finish_reason = "error"; break; }
        if (on_token && !on_token({request.request_id, piece, response.generated_tokens})) { impl_->cancelled.store(true); stop(); break; }
        response.text += piece; ++response.generated_tokens; if (response.generated_tokens == 1U) { response.metrics.first_token_ms = elapsed_ms(started); response.metrics.ttft_ms = response.metrics.first_token_ms; }
        auto & next = batch.value; next.n_tokens = 1; next.token[0] = token;
        next.pos[0] = text_only ? static_cast<llama_pos>(prompt_tokens + i) : n_past++;
        next.n_seq_id[0] = 1; next.seq_id[0][0] = 0; next.logits[0] = 1;
        if (llama_decode(impl_->context.get(), next) != 0) { if (!stop()) { response.code = RuntimeErrorCode::kDecodeFailed; response.finish_reason = "error"; response.error_message = "llama decode failed during generation"; } break; }
    }
    response.metrics.output_tokens = response.generated_tokens; response.metrics.decode_ms = elapsed_ms(decode_started); response.metrics.total_ms = elapsed_ms(started);
    if (response.generated_tokens > 1U && response.metrics.decode_ms > 0U) response.metrics.tpot_ms = response.metrics.decode_ms / response.generated_tokens;
    if (response.metrics.decode_ms > 0U) response.metrics.decode_tokens_per_second = static_cast<double>(response.generated_tokens) * 1000.0 / response.metrics.decode_ms;
    if (response.finish_reason.empty()) response.finish_reason = "length";
    if (response.code == RuntimeErrorCode::kOk && text_only && reuse_enabled && !request.session_id.empty()) {
        if (!remove_kv_range(prompt_tokens)) clear_hot("kv_rollback_failed");
        else { impl_->hot_session_id = request.session_id; impl_->hot_prompt_tokens = prompt_token_ids; guard.preserve_prompt = true; }
    } else if (response.code != RuntimeErrorCode::kOk || !text_only) {
        clear_hot(response.code == RuntimeErrorCode::kOk ? "image_request" : "incomplete_request");
    }
    return response;
}

Status MtmdBackend::cancel_request(const std::string & request_id) { std::lock_guard<std::mutex> lock(impl_->control_mutex); if (!impl_->initialized || request_id.empty() || impl_->active_request_id != request_id) return {RuntimeErrorCode::kInvalidState, "no matching active request"}; impl_->cancelled.store(true); return Status::Ok(); }
Status MtmdBackend::reset_context() { std::lock_guard<std::mutex> lock(impl_->generation_mutex); if (!impl_->initialized) return {RuntimeErrorCode::kInvalidState, "MtmdBackend is not initialized"}; llama_memory_clear(llama_get_memory(impl_->context.get()), false); impl_->hot_session_id.clear(); impl_->hot_prompt_tokens.clear(); return Status::Ok(); }
Status MtmdBackend::shutdown() { std::lock_guard<std::mutex> generation(impl_->generation_mutex); std::lock_guard<std::mutex> lifecycle(impl_->lifecycle_mutex); impl_->vision.reset(); impl_->context.reset(); impl_->model.reset(); impl_->vocab = nullptr; impl_->hot_session_id.clear(); impl_->hot_prompt_tokens.clear(); impl_->initialized = false; if (impl_->backend_acquired) { release_llama_backend(); impl_->backend_acquired = false; } return Status::Ok(); }
}  // namespace edgeomni
