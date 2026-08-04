#pragma once

#include <cstdint>
#include <vector>

#include "edgeomni/runtime.h"

namespace edgeomni {

// Decoder output supplied by a future mtmd backend. Declared request dimensions are
// deliberately not accepted here as a substitute for these authoritative values.
struct DecodedImageInfo {
    uint32_t width = 0;
    uint32_t height = 0;
};

struct ImageInputLimits {
    uint64_t max_encoded_bytes = 10U * 1024U * 1024U;
    uint32_t max_width = 4096;
    uint32_t max_height = 4096;
    uint64_t max_pixels = 16U * 1024U * 1024U;
};

Status validate_image_input(const ImageInput & image, const DecodedImageInfo & decoded,
                            const ImageInputLimits & limits = {});
Status validate_image_inputs(const std::vector<ImageInput> & images,
                             const std::vector<DecodedImageInfo> & decoded_images,
                             const ImageInputLimits & limits = {});

}  // namespace edgeomni
