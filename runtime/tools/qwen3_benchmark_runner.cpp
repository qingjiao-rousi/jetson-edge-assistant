#include <cstdlib>
#include <iostream>
#include <string>

#include "edgeomni/direct_backend.h"
#include "nlohmann/json.hpp"

namespace {
using json = nlohmann::json;

void usage() {
    std::cout << "qwen3_benchmark_runner --model PATH --sha256 HASH --prompt TEXT --max-new-tokens N [options]\n"
                 "  DirectBackend-only single request runner; emits one JSON response.\n";
}

const char * code_name(edgeomni::RuntimeErrorCode code) {
    switch (code) {
    case edgeomni::RuntimeErrorCode::kOk: return "ok";
    case edgeomni::RuntimeErrorCode::kCancelled: return "cancelled";
    case edgeomni::RuntimeErrorCode::kTimeout: return "timeout";
    case edgeomni::RuntimeErrorCode::kContextLimit: return "context_limit";
    case edgeomni::RuntimeErrorCode::kModelHashMismatch: return "model_hash_mismatch";
    case edgeomni::RuntimeErrorCode::kModelNotFound: return "model_not_found";
    default: return "error";
    }
}

bool take(int & i, int argc, char ** argv, const char * name, std::string * value) {
    if (std::string(argv[i]) != name || i + 1 >= argc) return false;
    *value = argv[++i];
    return true;
}
}

int main(int argc, char ** argv) {
    if (argc == 1 || (argc == 2 && std::string(argv[1]) == "--help")) { usage(); return EXIT_SUCCESS; }
    std::string model, hash, prompt, request_id = "benchmark";
    uint32_t max_new_tokens = 32, context = 4096, batch = 512, ubatch = 512, gpu_layers = 99, seed = 424242;
    int32_t top_k = 1, threads = 8, batch_threads = 8;
    float top_p = 1.0F, min_p = 0.0F, temperature = 0.0F;
    uint64_t timeout_ms = 0;
    for (int i = 1; i < argc; ++i) {
        std::string value;
        if (take(i, argc, argv, "--model", &value)) model = value;
        else if (take(i, argc, argv, "--sha256", &value)) hash = value;
        else if (take(i, argc, argv, "--prompt", &prompt)) {}
        else if (take(i, argc, argv, "--request-id", &request_id)) {}
        else if (take(i, argc, argv, "--max-new-tokens", &value)) max_new_tokens = static_cast<uint32_t>(std::stoul(value));
        else if (take(i, argc, argv, "--context", &value)) context = static_cast<uint32_t>(std::stoul(value));
        else if (take(i, argc, argv, "--batch", &value)) batch = static_cast<uint32_t>(std::stoul(value));
        else if (take(i, argc, argv, "--ubatch", &value)) ubatch = static_cast<uint32_t>(std::stoul(value));
        else if (take(i, argc, argv, "--gpu-layers", &value)) gpu_layers = static_cast<uint32_t>(std::stoul(value));
        else if (take(i, argc, argv, "--threads", &value)) threads = std::stoi(value);
        else if (take(i, argc, argv, "--batch-threads", &value)) batch_threads = std::stoi(value);
        else if (take(i, argc, argv, "--seed", &value)) seed = static_cast<uint32_t>(std::stoul(value));
        else if (take(i, argc, argv, "--top-k", &value)) top_k = std::stoi(value);
        else if (take(i, argc, argv, "--top-p", &value)) top_p = std::stof(value);
        else if (take(i, argc, argv, "--min-p", &value)) min_p = std::stof(value);
        else if (take(i, argc, argv, "--temperature", &value)) temperature = std::stof(value);
        else if (take(i, argc, argv, "--timeout-ms", &value)) timeout_ms = std::stoull(value);
        else { std::cerr << "unknown or incomplete argument: " << argv[i] << '\n'; return EXIT_FAILURE; }
    }
    if (model.empty() || hash.empty() || prompt.empty() || max_new_tokens == 0) { usage(); return EXIT_FAILURE; }

    edgeomni::RuntimeConfig config;
    config.model_path = model; config.expected_model_sha256 = hash; config.context_tokens = context;
    config.batch_tokens = batch; config.ubatch_tokens = ubatch; config.gpu_layers = static_cast<int32_t>(gpu_layers);
    config.generation_threads = threads; config.batch_threads = batch_threads; config.flash_attention = true;
    edgeomni::DirectBackend backend;
    const auto initialized = backend.initialize(config);
    if (!initialized.ok()) {
        std::cout << json{{"code", "initialize_error"}, {"error_message", initialized.message}}.dump() << '\n';
        return EXIT_FAILURE;
    }
    edgeomni::GenerateRequest request;
    request.request_id = request_id; request.messages = {{"user", prompt}}; request.max_new_tokens = max_new_tokens;
    request.timeout_ms = timeout_ms; request.sampling.seed = seed; request.sampling.top_k = top_k;
    request.sampling.top_p = top_p; request.sampling.min_p = min_p; request.sampling.temperature = temperature;
    const auto response = backend.generate_text(request);
    const json output = {
        {"request_id", response.request_id}, {"code", code_name(response.code)},
        {"error_message", response.error_message}, {"finish_reason", response.finish_reason},
        {"text", response.text}, {"prompt_tokens", response.prompt_tokens},
        {"output_tokens", response.generated_tokens},
        {"metrics", {{"model_ready_ms", response.metrics.model_ready_ms}, {"prompt_tokens", response.metrics.prompt_tokens},
                      {"output_tokens", response.metrics.output_tokens}, {"prefill_ms", response.metrics.prefill_ms},
                      {"decode_ms", response.metrics.decode_ms}, {"first_token_ms", response.metrics.first_token_ms},
                      {"total_ms", response.metrics.total_ms}, {"decode_tokens_per_second", response.metrics.decode_tokens_per_second}}}
    };
    std::cout << output.dump() << '\n';
    backend.shutdown();
    return response.code == edgeomni::RuntimeErrorCode::kOk ? EXIT_SUCCESS : EXIT_FAILURE;
}
