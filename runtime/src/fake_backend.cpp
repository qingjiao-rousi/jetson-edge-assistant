#include "edgeomni/fake_backend.h"

#include <chrono>
#include <filesystem>
#include <thread>

namespace edgeomni {

Status FakeBackend::initialize(const RuntimeConfig & config) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (initialized_) {
        return {RuntimeErrorCode::kAlreadyInitialized, "FakeBackend is already initialized"};
    }
    if (config.model_path.empty() || !std::filesystem::exists(config.model_path)) {
        return {RuntimeErrorCode::kModelNotFound, "configured model does not exist"};
    }
    if (config.expected_model_sha256 != "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5") {
        return {RuntimeErrorCode::kModelHashMismatch, "configured model hash does not match frozen baseline"};
    }
    initialized_ = true;
    request_count_ = 0;
    return Status::Ok();
}

GenerateResponse FakeBackend::generate_text(const GenerateRequest & request, const TokenCallback & on_token) {
    GenerateResponse response;
    response.request_id = request.request_id;
    unsigned int sequence = 0;
    std::shared_ptr<std::atomic_bool> active_flag;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (!initialized_) {
            response.code = RuntimeErrorCode::kInvalidState;
            response.error_message = "FakeBackend is not initialized";
            return response;
        }
        if (request.messages.empty() || request.max_new_tokens == 0U) {
            response.code = RuntimeErrorCode::kInvalidArgument;
            response.error_message = "request requires messages and max_new_tokens";
            return response;
        }
        if (request.messages.size() > 32U) {
            response.code = RuntimeErrorCode::kContextLimit;
            response.error_message = "fake context limit exceeded";
            return response;
        }
        ++request_count_;
        sequence = request_count_;
        active_request_id_ = request.request_id;
        active_cancel_flag_ = request.cancel_flag ? request.cancel_flag : std::make_shared<std::atomic_bool>(false);
        active_flag = active_cancel_flag_;
        response.prompt_tokens = static_cast<uint32_t>(request.messages.size());
        response.metrics.prompt_tokens = response.prompt_tokens;
        response.metrics.model_ready_ms = 1;
    }
    {
        const auto started = std::chrono::steady_clock::now();
        const std::vector<std::string> chunks = {"fake", "-response-", std::to_string(sequence)};
        for (size_t i = 0; i < chunks.size(); ++i) {
            if (test_delay_ms_ != 0U) std::this_thread::sleep_for(std::chrono::milliseconds(test_delay_ms_));
            const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - started).count();
            if (active_flag->load()) {
                response.code = RuntimeErrorCode::kCancelled;
                response.finish_reason = "cancelled";
                break;
            }
            if (request.timeout_ms != 0U && static_cast<uint64_t>(elapsed) >= request.timeout_ms) {
                response.code = RuntimeErrorCode::kTimeout;
                response.finish_reason = "timeout";
                break;
            }
            if (on_token && !on_token({request.request_id, chunks[i], static_cast<uint32_t>(i)})) {
                active_flag->store(true);
                response.code = RuntimeErrorCode::kCancelled;
                response.finish_reason = "cancelled";
                break;
            }
            response.text += chunks[i];
            ++response.generated_tokens;
            if (response.generated_tokens == 1U) response.metrics.first_token_ms = static_cast<uint64_t>(elapsed);
        }
        if (response.code == RuntimeErrorCode::kOk) response.finish_reason = "stop";
        response.metrics.output_tokens = response.generated_tokens;
        response.metrics.total_ms = static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now() - started).count());
        std::lock_guard<std::mutex> lock(mutex_);
        if (active_request_id_ == request.request_id) { active_request_id_.clear(); active_cancel_flag_.reset(); }
    }
    return response;
}

Status FakeBackend::cancel_request(const std::string & request_id) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!initialized_ || active_request_id_ != request_id || !active_cancel_flag_) {
        return {RuntimeErrorCode::kInvalidState, "no matching active fake request"};
    }
    active_cancel_flag_->store(true);
    return Status::Ok();
}

Status FakeBackend::reset_context() {
    std::lock_guard<std::mutex> lock(mutex_);
    return initialized_ ? Status::Ok() : Status{RuntimeErrorCode::kInvalidState, "FakeBackend is not initialized"};
}

Status FakeBackend::shutdown() {
    std::lock_guard<std::mutex> lock(mutex_);
    initialized_ = false;
    return Status::Ok();
}

void FakeBackend::set_test_delay_ms(uint32_t delay_ms) {
    std::lock_guard<std::mutex> lock(mutex_);
    test_delay_ms_ = delay_ms;
}

}  // namespace edgeomni
