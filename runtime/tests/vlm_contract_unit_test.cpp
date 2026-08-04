#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <string>
#include <vector>

#include "edgeomni/direct_backend.h"
#include "edgeomni/fake_backend.h"
#include "edgeomni/vlm_asset_verifier.h"
#include "edgeomni/vlm_input_validator.h"

namespace {

int failures = 0;

void expect(bool condition, const std::string & message) {
    if (!condition) {
        ++failures;
        std::cerr << "FAIL: " << message << '\n';
    }
}

edgeomni::ImageInput image(std::string bytes = "safe-image") {
    edgeomni::ImageInput result;
    result.id = "image-1";
    result.mime_type = "image/jpeg";
    result.encoded_bytes.assign(bytes.begin(), bytes.end());
    return result;
}

edgeomni::VlmAssetSet asset_set(const std::filesystem::path & model, const std::filesystem::path & mmproj,
                                 const std::string & model_bytes, const std::string & mmproj_bytes) {
    edgeomni::VlmAssetSet assets;
    // Independent standard SHA-256 vectors, not the existing Qwen3 template helper.
    const std::string model_sha = "43636adcc33c2a976312e95badaa5f191ba7c3fe57518b6e14c9cf7c1592620d";
    const std::string mmproj_sha = "ef1e91089b699606e24135f0d413eff9d79fff1d6e00fb153e50e2b24ef1ca14";
    assets.main_model = {"qwen25-vl-3b-main", model.string(), static_cast<uint64_t>(model_bytes.size()), model_sha};
    assets.mmproj = {"qwen25-vl-3b-mmproj", mmproj.string(), static_cast<uint64_t>(mmproj_bytes.size()), mmproj_sha};
    assets.binding = {"qwen25-vl-3b-binding", assets.main_model.asset_id, assets.mmproj.asset_id};
    return assets;
}

void test_image_inputs() {
    const edgeomni::DecodedImageInfo standard{4096, 4096};
    expect(edgeomni::validate_image_inputs({}, {}).ok(), "zero images are allowed");
    expect(edgeomni::validate_image_inputs({image()}, {standard}).ok(), "one image is allowed");
    expect(edgeomni::validate_image_inputs({image(), image()}, {standard, standard}).code == edgeomni::RuntimeErrorCode::kImageCountExceeded,
           "two images are rejected");

    auto empty = image(); empty.encoded_bytes.clear();
    expect(edgeomni::validate_image_input(empty, standard).code == edgeomni::RuntimeErrorCode::kImageBytesEmpty,
           "empty bytes are rejected");
    auto mime = image(); mime.mime_type = "image/gif";
    expect(edgeomni::validate_image_input(mime, standard).code == edgeomni::RuntimeErrorCode::kImageMimeUnsupported,
           "unknown MIME is rejected");
    auto large = image(); large.encoded_bytes.resize(10U * 1024U * 1024U + 1U);
    expect(edgeomni::validate_image_input(large, standard).code == edgeomni::RuntimeErrorCode::kImageTooLarge,
           "over 10 MiB is rejected");
    expect(edgeomni::validate_image_input(image(), {4097, 1}).code == edgeomni::RuntimeErrorCode::kImageDimensionsExceeded,
           "width limit is enforced");
    expect(edgeomni::validate_image_input(image(), {1, 4097}).code == edgeomni::RuntimeErrorCode::kImageDimensionsExceeded,
           "height limit is enforced");
    edgeomni::ImageInputLimits pixels; pixels.max_pixels = 16U * 1024U * 1024U - 1U;
    expect(edgeomni::validate_image_input(image(), standard, pixels).code == edgeomni::RuntimeErrorCode::kImagePixelsExceeded,
           "pixel limit is enforced");
    edgeomni::ImageInputLimits wide; wide.max_width = std::numeric_limits<uint32_t>::max(); wide.max_height = std::numeric_limits<uint32_t>::max(); wide.max_pixels = std::numeric_limits<uint64_t>::max();
    expect(edgeomni::validate_image_input(image(), {std::numeric_limits<uint32_t>::max(), std::numeric_limits<uint32_t>::max()}, wide).ok(),
           "large decoded dimensions use a non-overflowing pixel calculation");
    auto declared = image("secret-image-payload"); declared.declared_width = 1; declared.declared_height = 1;
    const auto declared_result = edgeomni::validate_image_input(declared, {4097, 4097});
    expect(declared_result.code == edgeomni::RuntimeErrorCode::kImageDimensionsExceeded,
           "declared dimensions do not override decoder dimensions");
    expect(declared_result.message.find("secret-image-payload") == std::string::npos,
           "image validation errors do not leak raw bytes");
}

void test_asset_verifier() {
    const auto root = std::filesystem::temp_directory_path() / "edgeomni-vlm-contract-assets";
    std::filesystem::remove_all(root);
    std::filesystem::create_directories(root);
    const auto model = root / "main.gguf";
    const auto mmproj = root / "mmproj.gguf";
    const std::string model_bytes = "small-main-model";
    const std::string mmproj_bytes = "small-mmproj";
    std::ofstream(model, std::ios::binary) << model_bytes;
    std::ofstream(mmproj, std::ios::binary) << mmproj_bytes;
    auto assets = asset_set(model, mmproj, model_bytes, mmproj_bytes);
    const auto verified = edgeomni::verify_vlm_assets(assets);
    expect(verified.ok(), "small temporary assets verify with streaming hash: code=" +
                              std::to_string(static_cast<int>(verified.code)) + " message=" + verified.message);
    assets.main_model.path = (root / "missing.gguf").string();
    expect(edgeomni::verify_vlm_assets(assets).code == edgeomni::RuntimeErrorCode::kModelNotFound, "missing model is rejected");
    assets = asset_set(model, mmproj, model_bytes, mmproj_bytes);
    ++assets.main_model.expected_size_bytes;
    expect(edgeomni::verify_vlm_assets(assets).code == edgeomni::RuntimeErrorCode::kModelSizeMismatch, "model size mismatch is rejected");
    assets = asset_set(model, mmproj, model_bytes, mmproj_bytes);
    assets.main_model.expected_sha256 = std::string(64, '0');
    expect(edgeomni::verify_vlm_assets(assets).code == edgeomni::RuntimeErrorCode::kModelHashMismatch, "model hash mismatch is rejected");
    assets = asset_set(model, mmproj, model_bytes, mmproj_bytes);
    assets.mmproj.path = (root / "missing-mmproj.gguf").string();
    expect(edgeomni::verify_vlm_assets(assets).code == edgeomni::RuntimeErrorCode::kMmprojNotFound, "missing mmproj is rejected");
    assets = asset_set(model, mmproj, model_bytes, mmproj_bytes);
    ++assets.mmproj.expected_size_bytes;
    expect(edgeomni::verify_vlm_assets(assets).code == edgeomni::RuntimeErrorCode::kMmprojSizeMismatch, "mmproj size mismatch is rejected");
    assets = asset_set(model, mmproj, model_bytes, mmproj_bytes);
    assets.mmproj.expected_sha256 = std::string(64, '0');
    expect(edgeomni::verify_vlm_assets(assets).code == edgeomni::RuntimeErrorCode::kMmprojHashMismatch, "mmproj hash mismatch is rejected");
    assets = asset_set(model, mmproj, model_bytes, mmproj_bytes);
    assets.binding.mmproj_asset_id = "wrong-mmproj";
    expect(edgeomni::verify_vlm_assets(assets).code == edgeomni::RuntimeErrorCode::kMmprojBindingMismatch, "wrong model/mmproj binding is rejected");
    std::filesystem::remove_all(root);
}

void test_text_backends() {
    edgeomni::DirectBackend direct;
    edgeomni::GenerateRequest image_request;
    image_request.request_id = "direct-image";
    image_request.images = {image()};
    expect(direct.generate_text(image_request).code == edgeomni::RuntimeErrorCode::kInvalidArgument,
           "DirectBackend rejects non-empty images without loading a model");

    edgeomni::FakeBackend fake;
    edgeomni::RuntimeConfig config;
    config.model_path = __FILE__;
    config.expected_model_sha256 = "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5";
    expect(fake.initialize(config).ok(), "FakeBackend text initialization remains compatible");
    edgeomni::GenerateRequest text_request;
    text_request.request_id = "fake-text";
    text_request.messages = {{"user", "hello"}};
    expect(fake.generate_text(text_request).code == edgeomni::RuntimeErrorCode::kOk,
           "FakeBackend text generation remains compatible");
    expect(fake.shutdown().ok(), "FakeBackend shutdown remains compatible");
}

}  // namespace

int main() {
    test_image_inputs();
    test_asset_verifier();
    test_text_backends();
    if (failures != 0) {
        std::cerr << failures << " test assertion(s) failed\n";
        return EXIT_FAILURE;
    }
    std::cout << "VLM contract validator, asset verifier, and text compatibility tests: PASS\n";
    return EXIT_SUCCESS;
}
