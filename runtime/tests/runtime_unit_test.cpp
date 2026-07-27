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
    expect(first.text != second.text, "FakeBackend preserves request sequence");
    expect(first.finish_reason == "stop", "FakeBackend reports normal stop");

    std::vector<std::string> streamed;
    request.request_id = "stream";
    auto streamed_response = backend.generate_text(request, [&](const edgeomni::StreamToken & token) {
        streamed.push_back(token.text);
        return true;
    });
    expect(streamed_response.code == edgeomni::RuntimeErrorCode::kOk, "FakeBackend streams normal response");
    expect(streamed == std::vector<std::string>({"fake", "-response-", "3"}), "stream callback preserves token order");

    request.request_id = "callback-cancel";
    streamed.clear();
    auto callback_cancel = backend.generate_text(request, [&](const edgeomni::StreamToken & token) {
        streamed.push_back(token.text);
        return false;
    });
    expect(callback_cancel.code == edgeomni::RuntimeErrorCode::kCancelled && callback_cancel.finish_reason == "cancelled",
           "callback may cancel request");
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
    expect(backend.generate_text(request).code == edgeomni::RuntimeErrorCode::kOk,
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
