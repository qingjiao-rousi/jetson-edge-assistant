#include "edgeomni/vlm_input_validator.h"

#include <limits>

namespace edgeomni {
namespace {

bool supported_mime(const std::string & mime_type) {
    return mime_type == "image/jpeg" || mime_type == "image/png" || mime_type == "image/webp";
}

}  // namespace

Status validate_image_input(const ImageInput & image, const DecodedImageInfo & decoded,
                            const ImageInputLimits & limits) {
    if (image.id.empty()) {
        return {RuntimeErrorCode::kInvalidArgument, "image id is required"};
    }
    if (!supported_mime(image.mime_type)) {
        return {RuntimeErrorCode::kImageMimeUnsupported, "image MIME type is unsupported"};
    }
    if (image.encoded_bytes.empty()) {
        return {RuntimeErrorCode::kImageBytesEmpty, "image encoded bytes are empty"};
    }
    if (image.encoded_bytes.size() > limits.max_encoded_bytes) {
        return {RuntimeErrorCode::kImageTooLarge, "image encoded bytes exceed configured limit"};
    }
    if (decoded.width == 0U || decoded.height == 0U) {
        return {RuntimeErrorCode::kImageDecodeFailed, "image decoder did not provide positive dimensions"};
    }
    // decoded dimensions are authoritative; declared_width/declared_height are never used for safety.
    if (decoded.width > limits.max_width || decoded.height > limits.max_height) {
        return {RuntimeErrorCode::kImageDimensionsExceeded, "decoded image dimensions exceed configured limit"};
    }
    const uint64_t width = decoded.width;
    const uint64_t height = decoded.height;
    if (height != 0U && width > std::numeric_limits<uint64_t>::max() / height) {
        return {RuntimeErrorCode::kImagePixelsExceeded, "decoded image pixel calculation overflows"};
    }
    if (width * height > limits.max_pixels) {
        return {RuntimeErrorCode::kImagePixelsExceeded, "decoded image pixel count exceeds configured limit"};
    }
    return Status::Ok();
}

Status validate_image_inputs(const std::vector<ImageInput> & images,
                             const std::vector<DecodedImageInfo> & decoded_images,
                             const ImageInputLimits & limits) {
    if (images.size() > 1U) {
        return {RuntimeErrorCode::kImageCountExceeded, "at most one image is supported"};
    }
    if (images.empty()) {
        return decoded_images.empty() ? Status::Ok()
                                      : Status{RuntimeErrorCode::kInvalidArgument, "decoded image info without an image"};
    }
    if (decoded_images.size() != images.size()) {
        return {RuntimeErrorCode::kInvalidArgument, "exactly one decoded image info value is required"};
    }
    return validate_image_input(images.front(), decoded_images.front(), limits);
}

}  // namespace edgeomni
