#include <cstdlib>
#include <fstream>
#include <iostream>
#include <iterator>
#include <string>
#include <vector>

#include "edgeomni/mtmd_backend.h"

namespace {
std::string escape(const std::string & value) { std::string out; for (char c : value) { if (c == '\\' || c == '"') out += '\\'; if (c == '\n') out += "\\n"; else out += c; } return out; }
void result(const edgeomni::GenerateResponse & r) {
    std::cout << "{\"request_id\":\"" << escape(r.request_id) << "\",\"code\":" << static_cast<int>(r.code)
              << ",\"finish_reason\":\"" << escape(r.finish_reason) << "\",\"error_message\":\"" << escape(r.error_message)
              << "\",\"text\":\"" << escape(r.text) << "\",\"prompt_tokens\":" << r.prompt_tokens
              << ",\"output_tokens\":" << r.generated_tokens << ",\"image_tokens\":" << r.image_tokens
              << ",\"metrics\":{\"model_ready_ms\":" << r.metrics.model_ready_ms << ",\"image_preprocess_ms\":" << r.metrics.image_preprocess_ms
              << ",\"vision_encode_ms\":" << r.metrics.vision_encode_ms << ",\"image_embedding_ms\":" << r.metrics.image_embedding_ms
              << ",\"prefill_ms\":" << r.metrics.prefill_ms << ",\"first_token_ms\":" << r.metrics.first_token_ms
              << ",\"ttft_ms\":" << r.metrics.ttft_ms << ",\"decode_ms\":" << r.metrics.decode_ms << ",\"total_ms\":" << r.metrics.total_ms << "}}\n";
}
}
int main(int argc, char ** argv) {
    if (argc != 4) { std::cerr << "usage: " << argv[0] << " MODEL MMPROJ IMAGE\n"; return 2; }
    std::ifstream input(argv[3], std::ios::binary);
    if (!input) { std::cerr << "fixed image cannot be opened\n"; return 2; }
    std::vector<uint8_t> bytes((std::istreambuf_iterator<char>(input)), {});
    edgeomni::RuntimeConfig config;
    config.model_path = argv[1]; config.expected_model_size_bytes = 1929901056ULL;
    config.expected_model_sha256 = "d02fe9b69ad8cadbbd228e387667af66612c44bed29ffc8eb1e7caf9ac486c12";
    config.mmproj_path = argv[2]; config.expected_mmproj_size_bytes = 844757728ULL;
    config.expected_mmproj_sha256 = "980c9b2f78c04e6cff93d277ada09e768394f112d75db3b4e9dea8a69f9fb904";
    config.context_tokens = 8192; config.batch_tokens = 512; config.ubatch_tokens = 512; config.gpu_layers = 99; config.flash_attention = true;
    edgeomni::MtmdBackend backend;
    const auto init = backend.initialize(config);
    if (!init.ok()) { edgeomni::GenerateResponse failure; failure.code = init.code; failure.error_message = init.message; failure.finish_reason = "error"; result(failure); return 1; }
    edgeomni::GenerateRequest request;
    request.request_id = "m7.5b-8192-single-image"; request.messages = {{"user", "Describe the image and identify the newspaper publisher. Answer in concise English."}};
    request.images = {{"test-1.jpeg", std::move(bytes), "image/jpeg", {}, {}}}; request.max_new_tokens = 128; request.sampling.seed = 424242; request.sampling.temperature = 0.0F;
    const auto response = backend.generate_text(request);
    result(response);
    backend.shutdown();
    return response.code == edgeomni::RuntimeErrorCode::kOk ? 0 : 1;
}
