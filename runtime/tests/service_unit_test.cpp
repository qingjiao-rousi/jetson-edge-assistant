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
constexpr const char * kLoopbackHost = "127.0.0.1";
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

int reserve_loopback_port() {
    httplib::Server probe;
    probe.Get("/probe", [](const httplib::Request &, httplib::Response & response) {
        response.set_content("ok", "text/plain");
    });
    const int port = probe.bind_to_any_port(kLoopbackHost);
    if (port <= 0) return 0;
    std::thread listener([&probe] { probe.listen_after_bind(); });
    probe.wait_until_ready();
    httplib::Client client(kLoopbackHost, port);
    client.set_connection_timeout(0, 500000);
    client.set_read_timeout(0, 500000);
    const auto response = client.Get("/probe");
    probe.stop();
    listener.join();
    return response && response->status == 200 ? port : 0;
}

bool wait_for_ready(httplib::Client & client, std::chrono::milliseconds timeout) {
    const auto deadline = std::chrono::steady_clock::now() + timeout;
    while (std::chrono::steady_clock::now() < deadline) {
        auto ready = client.Get("/ready");
        if (ready && ready->status == 200 && json::parse(ready->body).value("ready", false)) return true;
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
    const int port = reserve_loopback_port();
    if (port == 0) {
        std::cerr << "RuntimeService HTTP contract tests: BLOCKED_LOOPBACK "
                     "(cannot bind and reach a temporary 127.0.0.1 port)\n";
        return 77;
    }
    edgeomni::RuntimeService service(backend);
    expect(service.initialize(config).ok(), "initialize");
    httplib::Client client(kLoopbackHost, port);
    httplib::Client metrics_client(kLoopbackHost, port);
    const auto start_status = service.start(kLoopbackHost, port);
    if (!start_status.ok()) {
        std::cerr << "FAIL: RuntimeService failed to bind temporary loopback port " << port
                  << " after a successful loopback probe\n";
        service.shutdown();
        return EXIT_FAILURE;
    }
    if (!wait_for_ready(client, std::chrono::milliseconds(500))) {
        expect(false, "service becomes ready after start");
        service.shutdown();
        return failures;
    }

    auto health = client.Get("/health"); expect(health && health->status == 200, "health alive");
    auto ready = client.Get("/ready"); expect(ready && ready->status == 200, "ready initialized");
    auto info = client.Get("/model/info"); expect(info && info->status == 200 && json::parse(info->body)["model_sha256"] == kHash, "model info hash");
    auto normal = client.Post("/v1/generate", request("normal").dump(), "application/json");
    expect(normal && normal->status == 200 && json::parse(normal->body)["finish_reason"] == "stop", "normal generate");
    auto chat = client.Post("/v1/chat", request("chat").dump(), "application/json"); expect(chat && chat->status == 200, "chat generate");
    auto duplicate = client.Post("/v1/generate", request("normal").dump(), "application/json"); expect(duplicate && duplicate->status == 409 && json::parse(duplicate->body)["error"]["code"] == "duplicate_request_id", "duplicate request id");
    auto bad_json = client.Post("/v1/generate", "{", "application/json"); expect(bad_json && bad_json->status == 400, "invalid json");
    auto bad_field = request("bad-field"); bad_field["extra"] = true; auto bad = client.Post("/v1/generate", bad_field.dump(), "application/json"); expect(bad && bad->status == 400, "unknown field");
    auto images_field = request("images-field"); images_field["images"] = json::array(); auto images = client.Post("/v1/generate", images_field.dump(), "application/json"); expect(images && images->status == 200, "empty images preserves text route compatibility");
    auto bad_hash = request("bad-hash"); bad_hash["model_sha256"] = "bad"; auto hash = client.Post("/v1/generate", bad_hash.dump(), "application/json"); expect(hash && hash->status == 400, "hash mismatch");
    auto hot_session = request("hot-session"); hot_session["session_id"] = "s"; auto session = client.Post("/v1/generate", hot_session.dump(), "application/json");
    expect(session && session->status == 200 && json::parse(session->body)["session_id"] == "s", "non-empty session accepted and echoed");
    auto hot_session_again = request("hot-session-again"); hot_session_again["session_id"] = "s"; auto session_again = client.Post("/v1/chat", hot_session_again.dump(), "application/json");
    expect(session_again && session_again->status == 200 && json::parse(session_again->body)["metrics"]["cache_hit_tokens"] > 0,
           "chat route reports a hot prefix hit");

    auto sse = client.Post("/v1/generate", request("sse", true).dump(), "application/json");
    expect(sse && sse->status == 200 && sse->body.find("event: token") != std::string::npos && sse->body.find("event: done") != std::string::npos, "SSE token and done");
    expect(sse && sse->body.find("event: cancelled") == std::string::npos, "SSE one terminal event");

    const unsigned int before_diagnosis = backend->generate_call_count();
    json diagnosis = {{"request_id", "diagnosis"}, {"prompt", "Describe the image."}, {"stream", true},
                      {"images", {{{"id", "fixture.png"}, {"mime", "image/png"}, {"data_base64", "iVBORw0KGgo="}}}}};
    auto diagnosis_response = client.Post("/v1/diagnose/image", diagnosis.dump(), "application/json");
    if (!diagnosis_response || diagnosis_response->status != 200) {
        std::cerr << "DIAGNOSIS_HTTP status=" << (diagnosis_response ? diagnosis_response->status : 0)
                  << " body=" << (diagnosis_response ? diagnosis_response->body : "<connection failed>") << '\n';
    }
    expect(diagnosis_response && diagnosis_response->status == 200, "diagnosis route returns HTTP 200");
    if (diagnosis_response) {
        const auto & body = diagnosis_response->body;
        const auto metadata = body.find("event: metadata"); const auto token = body.find("event: token"); const auto done = body.find("event: done");
        expect(metadata != std::string::npos && token != std::string::npos && done != std::string::npos && metadata < token && token < done,
               "diagnosis SSE is metadata then tokens then done");
        expect(body.find("event: done", done + 1) == std::string::npos, "diagnosis SSE terminal is unique");
        expect(body.find("iVBORw0KGgo") == std::string::npos, "diagnosis response does not leak base64");
        expect(body.find("\"image_preprocess_ms\":\"measured\"") != std::string::npos,
               "zero-millisecond image preprocessing remains explicitly measured");
        expect(body.find("\"vision_encode_ms\":\"measured\"") != std::string::npos &&
                   body.find("\"image_embedding_ms\":\"measured\"") != std::string::npos,
               "zero-millisecond vision stages remain explicitly measured");
    }
    expect(backend->generate_call_count() == before_diagnosis + 1U, "diagnosis invokes FakeBackend exactly once");
    const auto captured = backend->last_request();
    expect(captured.request_id == "diagnosis" && captured.messages.size() == 1U && captured.messages[0].content == "Describe the image.",
           "diagnosis normalizes request id and prompt");
    expect(captured.images.size() == 1U && captured.images[0].id == "fixture.png" && captured.images[0].mime_type == "image/png",
           "diagnosis forwards one ImageInput");
    auto missing = diagnosis; missing.erase("images"); auto missing_response = client.Post("/v1/diagnose/image", missing.dump(), "application/json"); expect(missing_response && missing_response->status == 400, "diagnosis requires images");
    auto many = diagnosis; many["request_id"] = "many"; many["images"].push_back(many["images"][0]); auto many_response = client.Post("/v1/diagnose/image", many.dump(), "application/json"); expect(many_response && many_response->status == 400, "diagnosis rejects multiple images");
    auto bad_b64 = diagnosis; bad_b64["request_id"] = "bad-b64"; bad_b64["images"][0]["data_base64"] = "%%%="; auto bad_b64_response = client.Post("/v1/diagnose/image", bad_b64.dump(), "application/json"); expect(bad_b64_response && bad_b64_response->status == 400, "diagnosis rejects invalid base64");
    auto missing_route = client.Post("/v1/diagnose/missing", diagnosis.dump(), "application/json"); expect(missing_route && missing_route->status == 404, "unknown diagnosis route returns 404");

    auto long_request = request("cancel-me"); long_request["timeout_ms"] = 1000;
    std::unique_ptr<httplib::Result> long_response;
    httplib::Client request_client(kLoopbackHost, port);
    std::thread worker([&] { long_response = std::make_unique<httplib::Result>(request_client.Post("/v1/generate", long_request.dump(), "application/json")); });
    expect(wait_for_active(metrics_client, true, std::chrono::milliseconds(500)), "request becomes active");
    auto busy = client.Post("/v1/generate", request("busy").dump(), "application/json");
    expect(busy && busy->status == 429 && json::parse(busy->body)["error"]["code"] == "busy", "active request returns structured busy error");
    httplib::Client cancel_client(kLoopbackHost, port);
    auto cancel = cancel_client.Post("/v1/cancel/cancel-me", "", "application/json");
    expect(cancel && cancel->status == 200, "active cancel"); worker.join();
    expect(long_response && (*long_response)->status == 499 || (long_response && (*long_response)->body.find("cancelled") != std::string::npos), "cancel response");
    expect(wait_for_active(metrics_client, false, std::chrono::milliseconds(500)), "cancel clears active");
    auto cancelled_duplicate = client.Post("/v1/generate", request("cancel-me").dump(), "application/json"); expect(cancelled_duplicate && cancelled_duplicate->status == 409, "cancelled request id remains duplicate within bound");
    auto after_cancel = client.Post("/v1/generate", request("after-cancel").dump(), "application/json"); expect(after_cancel && after_cancel->status == 200, "request after cancel");
    auto timeout_request = request("timeout"); timeout_request["timeout_ms"] = 1; auto timeout = client.Post("/v1/generate", timeout_request.dump(), "application/json"); expect(timeout && timeout->status == 408, "timeout status");
    auto timeout_duplicate = client.Post("/v1/generate", request("timeout").dump(), "application/json"); expect(timeout_duplicate && timeout_duplicate->status == 409, "timed out request id remains duplicate within bound");
    auto after_timeout = client.Post("/v1/generate", request("after-timeout").dump(), "application/json"); expect(after_timeout && after_timeout->status == 200, "request after timeout");
    backend->set_test_delay_ms(0);
    for (int index = 0; index < 256; ++index) {
        auto bounded = client.Post("/v1/generate", request(("bounded-" + std::to_string(index)).c_str()).dump(), "application/json");
        expect(bounded && bounded->status == 200, "bounded request accepted");
    }
    auto recent_duplicate = client.Post("/v1/generate", request("bounded-255").dump(), "application/json"); expect(recent_duplicate && recent_duplicate->status == 409, "recent bounded request is rejected");
    auto evicted_request = client.Post("/v1/generate", request("normal").dump(), "application/json"); expect(evicted_request && evicted_request->status == 200, "old completed request id is evicted");
    auto metrics = client.Get("/metrics"); expect(metrics && metrics->status == 200 && json::parse(metrics->body).contains("first_token_ms") == false && json::parse(metrics->body)["last"].contains("first_token_ms") && json::parse(metrics->body)["completed_request_ids"] == 256 && json::parse(metrics->body)["completed_request_id_capacity"] == 256, "metrics fields and request id bound");
    expect(service.shutdown().ok(), "shutdown");
    expect(!service.ready() && !service.running(), "ready and running false after shutdown");
    expect(service.start(kLoopbackHost, port).code == edgeomni::RuntimeErrorCode::kInvalidState, "restart rejected after shutdown");
    return failures;
}
}

int main() {
    const int result = main_test();
    if (result == 77) return 77;
    if (result) return EXIT_FAILURE;
    std::cout << "RuntimeService FakeBackend contract tests: PASS\n";
    return EXIT_SUCCESS;
}
