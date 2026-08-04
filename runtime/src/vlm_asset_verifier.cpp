#include "edgeomni/vlm_asset_verifier.h"

#include <algorithm>
#include <array>
#include <cctype>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <memory>
#include <sstream>

#include <openssl/evp.h>

namespace edgeomni {
namespace {

bool valid_sha256(const std::string & value) {
    return value.size() == 64U &&
           std::all_of(value.begin(), value.end(), [](unsigned char c) { return std::isxdigit(c) != 0; });
}

Status verify_asset(const VlmAssetSpec & spec, bool is_mmproj) {
    const RuntimeErrorCode missing = is_mmproj ? RuntimeErrorCode::kMmprojNotFound : RuntimeErrorCode::kModelNotFound;
    const RuntimeErrorCode size_mismatch = is_mmproj ? RuntimeErrorCode::kMmprojSizeMismatch : RuntimeErrorCode::kModelSizeMismatch;
    const RuntimeErrorCode hash_mismatch = is_mmproj ? RuntimeErrorCode::kMmprojHashMismatch : RuntimeErrorCode::kModelHashMismatch;
    if (spec.asset_id.empty() || spec.path.empty() || spec.expected_size_bytes == 0U || !valid_sha256(spec.expected_sha256)) {
        return {RuntimeErrorCode::kInvalidArgument, "asset specification is incomplete"};
    }
    std::error_code error;
    if (!std::filesystem::is_regular_file(spec.path, error) || error) {
        return {missing, "configured asset is not a regular file"};
    }
    const uint64_t size = std::filesystem::file_size(spec.path, error);
    if (error || size != spec.expected_size_bytes) {
        return {size_mismatch, "configured asset size does not match expected size"};
    }
    std::ifstream input(spec.path, std::ios::binary);
    if (!input) return {missing, "configured asset cannot be opened"};

    std::unique_ptr<EVP_MD_CTX, decltype(&EVP_MD_CTX_free)> context(EVP_MD_CTX_new(), EVP_MD_CTX_free);
    if (!context || EVP_DigestInit_ex(context.get(), EVP_sha256(), nullptr) != 1) {
        return {RuntimeErrorCode::kBackendUnavailable, "SHA-256 initialization failed"};
    }
    std::array<uint8_t, 64U * 1024U> buffer{};
    while (input.read(reinterpret_cast<char *>(buffer.data()), static_cast<std::streamsize>(buffer.size())) || input.gcount() > 0) {
        if (EVP_DigestUpdate(context.get(), buffer.data(), static_cast<size_t>(input.gcount())) != 1) {
            return {RuntimeErrorCode::kBackendUnavailable, "SHA-256 streaming update failed"};
        }
    }
    std::array<uint8_t, EVP_MAX_MD_SIZE> bytes{};
    unsigned int digest_size = 0;
    if (input.bad() || EVP_DigestFinal_ex(context.get(), bytes.data(), &digest_size) != 1 || digest_size != 32U) {
        return {RuntimeErrorCode::kBackendUnavailable, "SHA-256 finalization failed"};
    }
    std::ostringstream actual;
    actual << std::hex << std::setfill('0');
    for (size_t index = 0; index < digest_size; ++index) actual << std::setw(2) << static_cast<unsigned int>(bytes[index]);
    if (actual.str() != spec.expected_sha256) {
        return {hash_mismatch, "configured asset SHA-256 does not match expected value"};
    }
    return Status::Ok();
}

}  // namespace

Status verify_vlm_assets(const VlmAssetSet & assets) {
    if (assets.binding.binding_id.empty() || assets.binding.main_model_asset_id != assets.main_model.asset_id ||
        assets.binding.mmproj_asset_id != assets.mmproj.asset_id) {
        return {RuntimeErrorCode::kMmprojBindingMismatch, "main model and mmproj asset binding does not match configured pair"};
    }
    const Status model = verify_asset(assets.main_model, false);
    if (!model.ok()) return model;
    return verify_asset(assets.mmproj, true);
}

}  // namespace edgeomni
