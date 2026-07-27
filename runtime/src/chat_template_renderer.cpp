#include "edgeomni/chat_template_renderer.h"

#include <array>
#include <cstdint>
#include <iomanip>
#include <sstream>
#include <vector>

namespace edgeomni {
namespace {

constexpr std::array<uint32_t, 64> kSha256RoundConstants = {
    0x428a2f98U, 0x71374491U, 0xb5c0fbcfU, 0xe9b5dba5U, 0x3956c25bU, 0x59f111f1U, 0x923f82a4U, 0xab1c5ed5U,
    0xd807aa98U, 0x12835b01U, 0x243185beU, 0x550c7dc3U, 0x72be5d74U, 0x80deb1feU, 0x9bdc06a7U, 0xc19bf174U,
    0xe49b69c1U, 0xefbe4786U, 0x0fc19dc6U, 0x240ca1ccU, 0x2de92c6fU, 0x4a7484aaU, 0x5cb0a9dcU, 0x76f988daU,
    0x983e5152U, 0xa831c66dU, 0xb00327c8U, 0xbf597fc7U, 0xc6e00bf3U, 0xd5a79147U, 0x06ca6351U, 0x14292967U,
    0x27b70a85U, 0x2e1b2138U, 0x4d2c6dfcU, 0x53380d13U, 0x650a7354U, 0x766a0abbU, 0x81c2c92eU, 0x92722c85U,
    0xa2bfe8a1U, 0xa81a664bU, 0xc24b8b70U, 0xc76c51a3U, 0xd192e819U, 0xd6990624U, 0xf40e3585U, 0x106aa070U,
    0x19a4c116U, 0x1e376c08U, 0x2748774cU, 0x34b0bcb5U, 0x391c0cb3U, 0x4ed8aa4aU, 0x5b9cca4fU, 0x682e6ff3U,
    0x748f82eeU, 0x78a5636fU, 0x84c87814U, 0x8cc70208U, 0x90befffaU, 0xa4506cebU, 0xbef9a3f7U, 0xc67178f2U,
};

uint32_t rotr(uint32_t value, uint32_t shift) {
    return (value >> shift) | (value << (32U - shift));
}

uint32_t load_be(const uint8_t * bytes) {
    return (static_cast<uint32_t>(bytes[0]) << 24U) | (static_cast<uint32_t>(bytes[1]) << 16U) |
           (static_cast<uint32_t>(bytes[2]) << 8U) | static_cast<uint32_t>(bytes[3]);
}

void append_message(const ChatMessage & message, std::string * prompt) {
    *prompt += "<|im_start|>" + message.role + "\n" + message.content + "<|im_end|>\n";
}

bool contains_multimodal_marker(const std::string & content) {
    return content.find("<|vision_start|>") != std::string::npos ||
           content.find("<|image_pad|>") != std::string::npos ||
           content.find("<image>") != std::string::npos;
}

std::string trim_newlines(const std::string & value, bool trim_left, bool trim_right) {
    size_t first = 0;
    size_t last = value.size();
    if (trim_left) while (first < last && value[first] == '\n') ++first;
    if (trim_right) while (last > first && value[last - 1U] == '\n') --last;
    return value.substr(first, last - first);
}

}  // namespace

std::string ChatTemplateRenderer::sha256_hex(const std::string & input) {
    std::vector<uint8_t> bytes(input.begin(), input.end());
    const uint64_t bit_length = static_cast<uint64_t>(bytes.size()) * 8U;
    bytes.push_back(0x80U);
    while ((bytes.size() % 64U) != 56U) {
        bytes.push_back(0U);
    }
    for (int shift = 56; shift >= 0; shift -= 8) {
        bytes.push_back(static_cast<uint8_t>(bit_length >> shift));
    }

    uint32_t h0 = 0x6a09e667U;
    uint32_t h1 = 0xbb67ae85U;
    uint32_t h2 = 0x3c6ef372U;
    uint32_t h3 = 0xa54ff53aU;
    uint32_t h4 = 0x510e527fU;
    uint32_t h5 = 0x9b05688cU;
    uint32_t h6 = 0x1f83d9abU;
    uint32_t h7 = 0x5be0cd19U;

    for (size_t offset = 0; offset < bytes.size(); offset += 64U) {
        std::array<uint32_t, 64> words{};
        for (size_t i = 0; i < 16U; ++i) {
            words[i] = load_be(bytes.data() + offset + i * 4U);
        }
        for (size_t i = 16U; i < words.size(); ++i) {
            const uint32_t s0 = rotr(words[i - 15U], 7U) ^ rotr(words[i - 15U], 18U) ^ (words[i - 15U] >> 3U);
            const uint32_t s1 = rotr(words[i - 2U], 17U) ^ rotr(words[i - 2U], 19U) ^ (words[i - 2U] >> 10U);
            words[i] = words[i - 16U] + s0 + words[i - 7U] + s1;
        }

        uint32_t a = h0, b = h1, c = h2, d = h3, e = h4, f = h5, g = h6, h = h7;
        for (size_t i = 0; i < words.size(); ++i) {
            const uint32_t s1 = rotr(e, 6U) ^ rotr(e, 11U) ^ rotr(e, 25U);
            const uint32_t choice = (e & f) ^ ((~e) & g);
            const uint32_t temp1 = h + s1 + choice + kSha256RoundConstants[i] + words[i];
            const uint32_t s0 = rotr(a, 2U) ^ rotr(a, 13U) ^ rotr(a, 22U);
            const uint32_t majority = (a & b) ^ (a & c) ^ (b & c);
            const uint32_t temp2 = s0 + majority;
            h = g; g = f; f = e; e = d + temp1; d = c; c = b; b = a; a = temp1 + temp2;
        }
        h0 += a; h1 += b; h2 += c; h3 += d; h4 += e; h5 += f; h6 += g; h7 += h;
    }

    std::ostringstream output;
    output << std::hex << std::setfill('0');
    for (uint32_t word : {h0, h1, h2, h3, h4, h5, h6, h7}) {
        output << std::setw(8) << word;
    }
    return output.str();
}

Status ChatTemplateRenderer::validate_template(const std::string & template_source) const {
    if (sha256_hex(template_source) != kQwen3TemplateSha256) {
        return {RuntimeErrorCode::kTemplateFingerprintMismatch,
                "Qwen3 tokenizer.chat_template fingerprint does not match the frozen deployment model"};
    }
    return Status::Ok();
}

Status ChatTemplateRenderer::render(const std::vector<ChatMessage> & messages, bool add_generation_prompt,
                                    std::string * prompt) const {
    if (prompt == nullptr || messages.empty()) {
        return {RuntimeErrorCode::kInvalidArgument, "a non-empty text message list and output prompt are required"};
    }
    prompt->clear();
    size_t last_user = messages.size() - 1U;
    for (size_t i = messages.size(); i > 0U; --i) {
        if (messages[i - 1U].role == "user") {
            last_user = i - 1U;
            break;
        }
    }
    for (size_t index = 0; index < messages.size(); ++index) {
        const auto & message = messages[index];
        if (message.role != "system" && message.role != "user" && message.role != "assistant") {
            return {RuntimeErrorCode::kTemplateUnsupported,
                    "Qwen3 DirectBackend supports only system, user, and assistant text messages"};
        }
        if (contains_multimodal_marker(message.content)) {
            return {RuntimeErrorCode::kTemplateUnsupported, "Qwen3 DirectBackend does not support image or multimodal messages"};
        }
        if (message.role != "assistant" || index <= last_user) {
            append_message(message, prompt);
            continue;
        }

        std::string content = message.content;
        std::string reasoning;
        const size_t think_end = content.rfind("</think>");
        if (think_end != std::string::npos) {
            const size_t think_start = content.rfind("<think>", think_end);
            if (think_start != std::string::npos) {
                reasoning = trim_newlines(content.substr(think_start + 7U, think_end - think_start - 7U), true, true);
                content = trim_newlines(content.substr(think_end + 8U), true, false);
            }
        }
        *prompt += "<|im_start|>assistant\n";
        if (index + 1U == messages.size() || !reasoning.empty()) {
            *prompt += "<think>\n" + reasoning + "\n</think>\n\n" + content;
        } else {
            *prompt += content;
        }
        *prompt += "<|im_end|>\n";
    }
    if (add_generation_prompt) {
        *prompt += "<|im_start|>assistant\n<think>\n\n</think>\n\n";
    }
    return Status::Ok();
}

}  // namespace edgeomni
