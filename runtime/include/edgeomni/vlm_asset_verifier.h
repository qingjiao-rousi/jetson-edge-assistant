#pragma once

#include <cstdint>
#include <string>

#include "edgeomni/runtime.h"

namespace edgeomni {

struct VlmAssetSpec {
    std::string asset_id;
    std::string path;
    uint64_t expected_size_bytes = 0;
    std::string expected_sha256;
};

struct VlmAssetBinding {
    std::string binding_id;
    std::string main_model_asset_id;
    std::string mmproj_asset_id;
};

struct VlmAssetSet {
    VlmAssetSpec main_model;
    VlmAssetSpec mmproj;
    VlmAssetBinding binding;
};

// Performs regular-file, exact-size, streaming SHA-256, and explicit pair binding checks.
// It does not parse or load GGUF/model data through a Runtime backend.
Status verify_vlm_assets(const VlmAssetSet & assets);

}  // namespace edgeomni
