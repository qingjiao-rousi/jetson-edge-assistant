#include <cstdlib>
#include <iostream>

#include "edgeomni/mtmd_backend.h"

namespace {
int failures = 0;
void expect(bool value, const char * message) { if (!value) { ++failures; std::cerr << "FAIL: " << message << '\n'; } }
edgeomni::GenerateRequest request() { edgeomni::GenerateRequest value; value.request_id = "unit"; value.messages = {{"user", "hello"}}; return value; }
}

int main() {
    edgeomni::MtmdBackend backend;
    expect(backend.generate_text(request()).code == edgeomni::RuntimeErrorCode::kInvalidState, "uninitialized request is rejected");
    edgeomni::RuntimeConfig missing;
    missing.model_path = "missing.gguf"; missing.mmproj_path = "missing-mmproj.gguf";
    missing.expected_model_size_bytes = 1; missing.expected_mmproj_size_bytes = 1;
    missing.expected_model_sha256 = std::string(64, '0'); missing.expected_mmproj_sha256 = std::string(64, '0');
    expect(backend.initialize(missing).code == edgeomni::RuntimeErrorCode::kModelNotFound, "missing main model is rejected before GPU work");
    auto image = request(); image.images = {{"img", {'x'}, "image/gif", {}, {}}};
    expect(backend.generate_text(image).code == edgeomni::RuntimeErrorCode::kInvalidState, "invalid image does not bypass state gate");
    expect(backend.shutdown().ok(), "shutdown before initialization succeeds");
    expect(backend.reset_context().code == edgeomni::RuntimeErrorCode::kInvalidState, "reset after shutdown is rejected");
    if (failures) return EXIT_FAILURE;
    std::cout << "MtmdBackend offline state and asset-gate tests: PASS\n";
    return EXIT_SUCCESS;
}
