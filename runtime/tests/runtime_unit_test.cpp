#include <cstdlib>
#include <atomic>
#include <filesystem>
#include <iostream>
#include <string>
#include <vector>

#include "edgeomni/chat_template_renderer.h"
#include "edgeomni/fake_backend.h"

namespace {

int failures = 0;

void expect(bool condition, const std::string & message) {
    if (!condition) {
        ++failures;
        std::cerr << "FAIL: " << message << '\n';
    }
}

edgeomni::RuntimeConfig fake_config() {
    edgeomni::RuntimeConfig config;
    config.model_path = __FILE__;
    config.expected_model_sha256 = "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5";
    config.prefix_reuse_mode = edgeomni::PrefixReuseMode::kSingleHotText;
    return config;
}

void test_renderer() {
    edgeomni::ChatTemplateRenderer renderer;
    std::string prompt;

    expect(renderer.render({{"user", "hello"}}, true, &prompt).ok(), "single user render succeeds");
    expect(prompt == "<|im_start|>user\nhello<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n",
           "single user golden bytes");

    expect(renderer.render({{"system", "be concise"}, {"user", "status"}}, true, &prompt).ok(),
           "system and user render succeeds");
    expect(prompt == "<|im_start|>system\nbe concise<|im_end|>\n<|im_start|>user\nstatus<|im_end|>\n"
                     "<|im_start|>assistant\n<think>\n\n</think>\n\n",
           "system plus user golden bytes");

    expect(renderer.render({{"user", "one"}, {"assistant", "two"}, {"user", "three"}}, false, &prompt).ok(),
           "multi-turn render succeeds");
    expect(prompt == "<|im_start|>user\none<|im_end|>\n<|im_start|>assistant\ntwo<|im_end|>\n"
                     "<|im_start|>user\nthree<|im_end|>\n",
           "multi-turn golden bytes");

    expect(renderer.render({{"user", "plain"}}, false, &prompt).ok(), "generation prompt may be disabled");
    expect(prompt == "<|im_start|>user\nplain<|im_end|>\n", "no-generation-prompt golden bytes");
    expect(!renderer.render({{"tool", "{}"}}, true, &prompt).ok(), "tools are rejected");
    expect(!renderer.render({{"user", "<image>"}}, true, &prompt).ok(), "multimodal markers are rejected");
    expect(!renderer.validate_template("not the frozen Qwen3 template").ok(), "template fingerprint mismatch is rejected");
    expect(edgeomni::ChatTemplateRenderer::sha256_hex("abc") ==
               "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
           "SHA-256 implementation matches test vector");
}

void test_fake_backend() {
    edgeomni::FakeBackend backend;
    backend.set_test_delay_ms(2);
    edgeomni::RuntimeConfig config = fake_config();

    expect(backend.initialize(config).ok(), "FakeBackend initializes");
    expect(backend.initialize(config).code == edgeomni::RuntimeErrorCode::kAlreadyInitialized,
           "FakeBackend rejects duplicate initialization");
    expect(backend.reset_context().ok(), "FakeBackend resets context");

    edgeomni::GenerateRequest request;
    request.request_id = "first";
    request.messages = {{"user", "hello"}};
    auto first = backend.generate_text(request);
    auto second = backend.generate_text(request);
    expect(first.code == edgeomni::RuntimeErrorCode::kOk && second.code == edgeomni::RuntimeErrorCode::kOk,
           "FakeBackend accepts consecutive requests");
    expect(first.text == second.text, "FakeBackend has deterministic cold output");
    expect(first.finish_reason == "stop", "FakeBackend reports normal stop");

    std::vector<std::string> streamed;
    request.request_id = "stream";
    auto streamed_response = backend.generate_text(request, [&](const edgeomni::StreamToken & token) {
        streamed.push_back(token.text);
        return true;
    });
    expect(streamed_response.code == edgeomni::RuntimeErrorCode::kOk, "FakeBackend streams normal response");
    expect(streamed == std::vector<std::string>({"fake", "-response", "-stable"}), "stream callback preserves token order");

    // M10.1: one hot text session uses token IDs (FakeBackend byte-token stand-in)
    // and always re-prefills the final prompt token.
    request.request_id = "prefix-cold";
    request.session_id = "hot";
    request.messages = {{"user", "shared prefix"}};
    const auto cold = backend.generate_text(request);
    request.request_id = "prefix-hot";
    const auto hot = backend.generate_text(request);
    expect(cold.text == hot.text, "cold and hot output are identical");
    expect(hot.metrics.cache_hit_tokens > 0U && hot.metrics.cache_reused,
           "same session reuses prompt token prefix");
    expect(hot.metrics.cache_miss_tokens == 1U && hot.metrics.prefill_input_tokens == 1U,
           "full prompt hit re-prefills only the final token");

    request.request_id = "prefix-fork";
    request.messages = {{"user", "shared branch"}};
    const auto fork = backend.generate_text(request);
    expect(fork.metrics.cache_hit_tokens > 0U &&
               fork.metrics.cache_hit_tokens < fork.metrics.cache_hit_tokens + fork.metrics.cache_miss_tokens,
           "branch reuses only the common token prefix");
    expect(backend.reset_context().ok(), "reset clears hot KV state");
    request.request_id = "prefix-after-reset";
    const auto after_reset = backend.generate_text(request);
    expect(after_reset.metrics.cache_hit_tokens == 0U && !after_reset.metrics.cache_reused,
           "request after reset is cold");
    request.request_id = "prefix-other-session";
    request.session_id = "other";
    const auto other_session = backend.generate_text(request);
    expect(other_session.metrics.cache_hit_tokens == 0U &&
               other_session.metrics.cache_invalidation_reason == "session_id_changed",
           "session change invalidates the one hot cache");
    request.request_id = "prefix-image";
    request.images = {{"image", {1U}, "image/png", std::nullopt, std::nullopt}};
    const auto image = backend.generate_text(request);
    expect(image.metrics.cache_hit_tokens == 0U && image.metrics.cache_invalidation_reason == "image_request",
           "image request bypasses and clears the text KV cache");
    request.images.clear();
    request.request_id = "prefix-after-image";
    const auto after_image = backend.generate_text(request);
    expect(after_image.metrics.cache_hit_tokens == 0U, "image request leaves no reusable text KV");

    request.request_id = "callback-cancel";
    streamed.clear();
    auto callback_cancel = backend.generate_text(request, [&](const edgeomni::StreamToken & token) {
        streamed.push_back(token.text);
        return false;
    });
    expect(callback_cancel.code == edgeomni::RuntimeErrorCode::kCancelled && callback_cancel.finish_reason == "cancelled",
           "callback may cancel request");
    request.request_id = "after-callback-cancel";
    const auto after_callback_cancel = backend.generate_text(request);
    expect(after_callback_cancel.metrics.cache_hit_tokens == 0U,
           "cancelled request cannot leave reusable KV");
    request.request_id = "api-cancel";
    auto api_cancel = backend.generate_text(request, [&](const edgeomni::StreamToken &) {
        return backend.cancel_request("api-cancel").ok();
    });
    expect(api_cancel.code == edgeomni::RuntimeErrorCode::kCancelled && api_cancel.finish_reason == "cancelled",
           "cancel_request cancels the matching active request");
    request.request_id = "after-cancel";
    expect(backend.generate_text(request).code == edgeomni::RuntimeErrorCode::kOk,
           "FakeBackend recovers after cancellation");

    request.request_id = "timeout";
    request.timeout_ms = 1;
    auto timeout = backend.generate_text(request);
    expect(timeout.code == edgeomni::RuntimeErrorCode::kTimeout && timeout.finish_reason == "timeout",
           "FakeBackend reports timeout");
    request.timeout_ms = 0;
    request.request_id = "after-error";
    const auto after_timeout = backend.generate_text(request);
    expect(after_timeout.code == edgeomni::RuntimeErrorCode::kOk && after_timeout.metrics.cache_hit_tokens == 0U,
           "FakeBackend recovers after timeout");

    request.messages.clear();
    expect(backend.generate_text(request).code == edgeomni::RuntimeErrorCode::kInvalidArgument,
           "FakeBackend rejects empty request");
    request.messages.assign(33, {"user", "x"});
    expect(backend.generate_text(request).code == edgeomni::RuntimeErrorCode::kContextLimit,
           "FakeBackend reports context limit");
    request.messages = {{"user", "recovered"}};
    request.request_id = "after-error";
    expect(backend.generate_text(request).code == edgeomni::RuntimeErrorCode::kOk,
           "FakeBackend recovers after request error");
    expect(backend.shutdown().ok(), "FakeBackend shuts down");
    expect(backend.reset_context().code == edgeomni::RuntimeErrorCode::kInvalidState,
           "FakeBackend reset after shutdown is invalid");
    request.messages = {{"user", "hello"}};
    expect(backend.generate_text(request).code == edgeomni::RuntimeErrorCode::kInvalidState,
           "FakeBackend rejects new request after shutdown");

    edgeomni::FakeBackend missing_model;
    config.model_path = "does-not-exist.gguf";
    expect(missing_model.initialize(config).code == edgeomni::RuntimeErrorCode::kModelNotFound,
           "FakeBackend reports missing model");

    edgeomni::FakeBackend wrong_hash;
    config = fake_config();
    config.expected_model_sha256 = "bad";
    expect(wrong_hash.initialize(config).code == edgeomni::RuntimeErrorCode::kModelHashMismatch,
           "FakeBackend reports model hash mismatch");

    edgeomni::FakeBackend disabled;
    config = fake_config();
    config.prefix_reuse_mode = edgeomni::PrefixReuseMode::kDisabled;
    expect(disabled.initialize(config).ok(), "disabled Prefix Reuse config initializes");
    edgeomni::GenerateRequest disabled_request;
    disabled_request.request_id = "disabled-cold";
    disabled_request.session_id = "same";
    disabled_request.messages = {{"user", "same prompt"}};
    expect(disabled.generate_text(disabled_request).metrics.cache_hit_tokens == 0U,
           "disabled Prefix Reuse never reports a cache hit");
    disabled_request.request_id = "disabled-second";
    const auto disabled_second = disabled.generate_text(disabled_request);
    expect(disabled_second.metrics.cache_hit_tokens == 0U && !disabled_second.metrics.cache_reused,
           "disabled Prefix Reuse does not retain hot KV state");
    expect(disabled.shutdown().ok(), "disabled FakeBackend shuts down");
}

}  // namespace

int main() {
    test_renderer();
    test_fake_backend();
    if (failures != 0) {
        std::cerr << failures << " test assertion(s) failed\n";
        return EXIT_FAILURE;
    }
    std::cout << "ChatTemplateRenderer golden tests: PASS\nFakeBackend contract tests: PASS\n";
    return EXIT_SUCCESS;
}
