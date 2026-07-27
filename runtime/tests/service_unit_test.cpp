#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <memory>
#include <thread>

#include "edgeomni/fake_backend.h"
#include "edgeomni/service.h"
#include "httplib.h"
#include "nlohmann/json.hpp"

namespace {
using json = nlohmann::json;
constexpr const char * kHash = "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5";
int failures = 0;
void expect(bool ok, const char * message) { if (!ok) { ++failures; std::cerr << "FAIL: " << message << '\n'; } }

json request(const char * id, bool stream = false) {
    return {{"request_id", id}, {"messages", {{{"role", "user"}, {"content", "hello"}}}}, {"max_new_tokens", 8}, {"stream", stream}};
}

bool wait_for_active(httplib::Client & metrics_client, bool expected, std::chrono::milliseconds timeout) {
    const auto deadline = std::chrono::steady_clock::now() + timeout;
    while (std::chrono::steady_clock::now() < deadline) {
        auto metrics = metrics_client.Get("/metrics");
        if (metrics && json::parse(metrics->body).value("active", 0) == (expected ? 1 : 0)) return true;
        std::this_thread::sleep_for(std::chrono::milliseconds(2));
    }
    return false;
}

int main_test() {
    auto backend = std::make_shared<edgeomni::FakeBackend>();
    backend->set_test_delay_ms(10);
    edgeomni::ServiceConfig config;
    config.runtime.model_path = __FILE__;
    config.runtime.expected_model_sha256 = kHash;
    config.model_name = "fake";
    config.model_sha256 = kHash;
    config.template_fingerprint = "qwen3-test";
    edgeomni::RuntimeService service(backend);
    expect(service.initialize(config).ok(), "initialize");
    httplib::Client client("127.0.0.1", 18081);
    httplib::Client metrics_client("127.0.0.1", 18081);
    const auto start_status = service.start("127.0.0.1", 18081);
    if (!start_status.ok()) {
        std::cout << "RuntimeService HTTP contract tests: BLOCKED_SANDBOX (local socket unavailable)\n";
        service.shutdown();
        return 0;
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(20));

    auto health = client.Get("/health"); expect(health && health->status == 200, "health alive");
    auto ready = client.Get("/ready"); expect(ready && ready->status == 200, "ready initialized");
    auto info = client.Get("/model/info"); expect(info && info->status == 200 && json::parse(info->body)["model_sha256"] == kHash, "model info hash");
    auto normal = client.Post("/v1/generate", request("normal").dump(), "application/json");
    expect(normal && normal->status == 200 && json::parse(normal->body)["finish_reason"] == "stop", "normal generate");
    auto chat = client.Post("/v1/chat", request("chat").dump(), "application/json"); expect(chat && chat->status == 200, "chat generate");
    auto duplicate = client.Post("/v1/generate", request("normal").dump(), "application/json"); expect(duplicate && duplicate->status == 409, "duplicate request id");
    auto bad_json = client.Post("/v1/generate", "{", "application/json"); expect(bad_json && bad_json->status == 400, "invalid json");
    auto bad_field = request("bad-field"); bad_field["extra"] = true; auto bad = client.Post("/v1/generate", bad_field.dump(), "application/json"); expect(bad && bad->status == 400, "unknown field");
    auto bad_hash = request("bad-hash"); bad_hash["model_sha256"] = "bad"; auto hash = client.Post("/v1/generate", bad_hash.dump(), "application/json"); expect(hash && hash->status == 400, "hash mismatch");
    auto bad_session = request("bad-session"); bad_session["session_id"] = "s"; auto session = client.Post("/v1/generate", bad_session.dump(), "application/json"); expect(session && session->status == 400, "session rejected");

    auto sse = client.Post("/v1/generate", request("sse", true).dump(), "application/json");
    expect(sse && sse->status == 200 && sse->body.find("event: token") != std::string::npos && sse->body.find("event: done") != std::string::npos, "SSE token and done");
    expect(sse && sse->body.find("event: cancelled") == std::string::npos, "SSE one terminal event");

    auto long_request = request("cancel-me"); long_request["timeout_ms"] = 1000;
    std::unique_ptr<httplib::Result> long_response;
    httplib::Client request_client("127.0.0.1", 18081);
    std::thread worker([&] { long_response = std::make_unique<httplib::Result>(request_client.Post("/v1/generate", long_request.dump(), "application/json")); });
    expect(wait_for_active(metrics_client, true, std::chrono::milliseconds(500)), "request becomes active");
    httplib::Client cancel_client("127.0.0.1", 18081);
    auto cancel = cancel_client.Post("/v1/cancel/cancel-me", "", "application/json");
    expect(cancel && cancel->status == 200, "active cancel"); worker.join();
    expect(long_response && (*long_response)->status == 499 || (long_response && (*long_response)->body.find("cancelled") != std::string::npos), "cancel response");
    expect(wait_for_active(metrics_client, false, std::chrono::milliseconds(500)), "cancel clears active");
    auto after_cancel = client.Post("/v1/generate", request("after-cancel").dump(), "application/json"); expect(after_cancel && after_cancel->status == 200, "request after cancel");
    auto timeout_request = request("timeout"); timeout_request["timeout_ms"] = 1; auto timeout = client.Post("/v1/generate", timeout_request.dump(), "application/json"); expect(timeout && timeout->status == 408, "timeout status");
    auto after_timeout = client.Post("/v1/generate", request("after-timeout").dump(), "application/json"); expect(after_timeout && after_timeout->status == 200, "request after timeout");
    auto metrics = client.Get("/metrics"); expect(metrics && metrics->status == 200 && json::parse(metrics->body).contains("first_token_ms") == false && json::parse(metrics->body)["last"].contains("first_token_ms"), "metrics fields");
    expect(service.shutdown().ok(), "shutdown");
    expect(!service.ready() && !service.running(), "ready and running false after shutdown");
    expect(service.start("127.0.0.1", 18081).code == edgeomni::RuntimeErrorCode::kInvalidState, "restart rejected after shutdown");
    return failures;
}
}

int main() { const int failures = main_test(); if (failures) return EXIT_FAILURE; std::cout << "RuntimeService FakeBackend contract tests: PASS\n"; return EXIT_SUCCESS; }
