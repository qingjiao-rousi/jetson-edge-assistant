#include <cstdlib>
#include <iostream>
#include <vector>

#include "edgeomni/direct_backend.h"

int main() {
    edgeomni::RuntimeConfig config;
    config.model_path = "models/Qwen3-4B-Q4_K_M.gguf";
    config.expected_model_sha256 = "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5";
    config.context_tokens = 1024;
    config.batch_tokens = 256;
    config.ubatch_tokens = 256;

    edgeomni::DirectBackend backend;
    const auto initialized = backend.initialize(config);
    if (!initialized.ok()) {
        std::cerr << "initialize failed: " << initialized.message << '\n';
        return EXIT_FAILURE;
    }
    edgeomni::GenerateRequest request;
    request.request_id = "qwen3-stream";
    request.messages = {{"user", "Reply with one word: ready"}};
    request.max_new_tokens = 8;
    std::vector<std::string> streamed;
    const auto response = backend.generate_text(request, [&](const edgeomni::StreamToken & token) {
        streamed.push_back(token.text);
        return true;
    });
    if (response.code != edgeomni::RuntimeErrorCode::kOk) {
        std::cerr << "generate failed: " << response.error_message << '\n';
        backend.shutdown();
        return EXIT_FAILURE;
    }
    if (streamed.empty() || response.finish_reason.empty()) {
        std::cerr << "streaming contract failed\n";
        backend.shutdown();
        return EXIT_FAILURE;
    }
    auto generate_with_first_token = [&](edgeomni::GenerateRequest value, std::string * first_token) {
        return backend.generate_text(value, [&](const edgeomni::StreamToken & token) {
            if (first_token->empty()) *first_token = token.text;
            return true;
        });
    };
    request.session_id = "qwen3-kv-prefix";
    request.request_id = "qwen3-kv-cold";
    std::string cold_first_token;
    const auto cold = generate_with_first_token(request, &cold_first_token);
    request.request_id = "qwen3-kv-hot";
    std::string hot_first_token;
    const auto hot = generate_with_first_token(request, &hot_first_token);
    if (cold.code != edgeomni::RuntimeErrorCode::kOk || hot.code != edgeomni::RuntimeErrorCode::kOk ||
        hot.metrics.cache_hit_tokens == 0U || cold_first_token != hot_first_token || cold.text != hot.text) {
        std::cerr << "KV cold/hot output equivalence failed\n";
        backend.shutdown();
        return EXIT_FAILURE;
    }
    request.request_id = "qwen3-kv-branch";
    request.messages = {{"user", "Reply with one word: stable"}};
    const auto branch = backend.generate_text(request);
    if (branch.code != edgeomni::RuntimeErrorCode::kOk || branch.metrics.cache_hit_tokens == 0U ||
        branch.metrics.cache_hit_tokens >= branch.prompt_tokens) {
        std::cerr << "KV prefix branch contract failed\n";
        backend.shutdown();
        return EXIT_FAILURE;
    }
    if (!backend.reset_context().ok()) {
        std::cerr << "KV reset failed\n";
        backend.shutdown();
        return EXIT_FAILURE;
    }
    request.request_id = "qwen3-kv-after-reset";
    const auto after_reset = backend.generate_text(request);
    if (after_reset.code != edgeomni::RuntimeErrorCode::kOk || after_reset.metrics.cache_hit_tokens != 0U ||
        after_reset.text != branch.text) {
        std::cerr << "KV reset output equivalence failed\n";
        backend.shutdown();
        return EXIT_FAILURE;
    }
    request.session_id.clear();
    request.messages = {{"user", "Reply with one word: ready"}};
    request.request_id = "qwen3-cancel";
    const auto cancelled = backend.generate_text(request, [](const edgeomni::StreamToken &) { return false; });
    if (cancelled.finish_reason != "cancelled") {
        std::cerr << "callback cancellation contract failed\n";
        backend.shutdown();
        return EXIT_FAILURE;
    }
    request.request_id = "qwen3-after-cancel";
    const auto recovered = backend.generate_text(request);
    backend.shutdown();
    if (recovered.code != edgeomni::RuntimeErrorCode::kOk) {
        std::cerr << "post-cancel request failed: " << recovered.error_message << '\n';
        return EXIT_FAILURE;
    }
    std::cout << "finish_reason=" << response.finish_reason << " prompt_tokens=" << response.prompt_tokens
              << " generated_tokens=" << response.generated_tokens << " first_token_ms=" << response.metrics.first_token_ms
              << " text=" << response.text << '\n';
    return EXIT_SUCCESS;
}
