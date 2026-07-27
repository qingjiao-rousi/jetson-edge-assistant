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
