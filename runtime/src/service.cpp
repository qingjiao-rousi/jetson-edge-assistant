#include "edgeomni/service.h"

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <mutex>
#include <set>
#include <thread>
#include <utility>

#include "httplib.h"
#include "nlohmann/json.hpp"

namespace edgeomni {
namespace {
using json = nlohmann::json;

constexpr const char * kFrozenHash = "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5";

int http_code(RuntimeErrorCode code) {
    switch (code) {
    case RuntimeErrorCode::kInvalidArgument: return 400;
    case RuntimeErrorCode::kInvalidState: return 409;
    case RuntimeErrorCode::kContextLimit: return 413;
    case RuntimeErrorCode::kCancelled: return 499;
    case RuntimeErrorCode::kTimeout: return 408;
    case RuntimeErrorCode::kModelHashMismatch: return 400;
    case RuntimeErrorCode::kModelNotFound: return 503;
    default: return 500;
    }
}

const char * code_name(RuntimeErrorCode code) {
    switch (code) {
    case RuntimeErrorCode::kCancelled: return "cancelled";
    case RuntimeErrorCode::kTimeout: return "timeout";
    case RuntimeErrorCode::kOk: return "ok";
    default: return "error";
    }
}

json metrics_json(const RuntimeMetrics & m) {
    return {{"model_ready_ms", m.model_ready_ms}, {"prompt_tokens", m.prompt_tokens},
            {"output_tokens", m.output_tokens}, {"prefill_ms", m.prefill_ms},
            {"decode_ms", m.decode_ms}, {"total_ms", m.total_ms},
            {"first_token_ms", m.first_token_ms},
            {"decode_tokens_per_second", m.decode_tokens_per_second}};
}

json response_json(const GenerateResponse & r, const std::string & hash) {
    json out = {{"request_id", r.request_id}, {"session_id", nullptr}, {"model_sha256", hash},
                {"text", r.text}, {"finish_reason", r.finish_reason},
                {"prompt_tokens", r.prompt_tokens}, {"output_tokens", r.generated_tokens},
                {"metrics", metrics_json(r.metrics)}, {"error", nullptr}};
    if (r.code != RuntimeErrorCode::kOk) out["error"] = {{"code", code_name(r.code)}, {"message", r.error_message}};
    return out;
}

bool has_only(const json & object, std::initializer_list<const char *> allowed) {
    for (auto it = object.begin(); it != object.end(); ++it) {
        bool found = false;
        for (const char * key : allowed) if (it.key() == key) found = true;
        if (!found) return false;
    }
    return true;
}

bool parse_request(const json & body, GenerateRequest * request, bool * stream, const std::string & expected_hash,
                  std::string * error) {
    if (!body.is_object() || !has_only(body, {"request_id", "session_id", "messages", "max_new_tokens", "timeout_ms", "stream", "model_sha256", "sampling"})) {
        *error = "invalid JSON object or unknown field"; return false;
    }
    if (!body.contains("request_id") || !body["request_id"].is_string() || body["request_id"].get<std::string>().empty()) {
        *error = "request_id is required"; return false;
    }
    if (body.contains("session_id") && !body["session_id"].is_null() && (!body["session_id"].is_string() || !body["session_id"].get<std::string>().empty())) {
        *error = "non-empty session_id is unsupported"; return false;
    }
    if (!body.contains("messages") || !body["messages"].is_array() || body["messages"].empty()) { *error = "messages must be non-empty array"; return false; }
    request->request_id = body["request_id"].get<std::string>();
    for (const auto & message : body["messages"]) {
        if (!message.is_object() || !has_only(message, {"role", "content"}) || !message.contains("role") || !message.contains("content") || !message["role"].is_string() || !message["content"].is_string()) { *error = "invalid message"; return false; }
        const std::string role = message["role"].get<std::string>();
        if (role != "system" && role != "user" && role != "assistant") { *error = "unsupported message role"; return false; }
        request->messages.push_back({role, message["content"].get<std::string>()});
    }
    if (!body.contains("max_new_tokens") || !body["max_new_tokens"].is_number_unsigned() || body["max_new_tokens"].get<uint64_t>() == 0 || body["max_new_tokens"].get<uint64_t>() > UINT32_MAX) { *error = "invalid max_new_tokens"; return false; }
    request->max_new_tokens = body["max_new_tokens"].get<uint32_t>();
    if (body.contains("timeout_ms")) { if (!body["timeout_ms"].is_number_unsigned() || body["timeout_ms"].get<uint64_t>() > UINT64_MAX) { *error = "invalid timeout_ms"; return false; } request->timeout_ms = body["timeout_ms"].get<uint64_t>(); }
    *stream = body.value("stream", false);
    if (body.contains("model_sha256") && (!body["model_sha256"].is_string() || body["model_sha256"].get<std::string>() != expected_hash)) { *error = "model_sha256 mismatch"; return false; }
    if (body.contains("sampling")) {
        const auto & s = body["sampling"]; if (!s.is_object() || !has_only(s, {"seed", "top_k", "top_p", "min_p", "temperature"})) { *error = "invalid sampling"; return false; }
        if (s.contains("seed") && !s["seed"].is_number_integer()) { *error = "invalid seed"; return false; } if (s.contains("seed")) request->sampling.seed = s["seed"].get<uint32_t>();
        if (s.contains("top_k") && (!s["top_k"].is_number_integer() || s["top_k"].get<int64_t>() < 0)) { *error = "invalid top_k"; return false; } if (s.contains("top_k")) request->sampling.top_k = s["top_k"].get<int32_t>();
        if (s.contains("top_p")) request->sampling.top_p = s["top_p"].get<float>(); if (s.contains("min_p")) request->sampling.min_p = s["min_p"].get<float>(); if (s.contains("temperature")) request->sampling.temperature = s["temperature"].get<float>();
    }
    request->cancel_flag = std::make_shared<std::atomic_bool>(false);
    return true;
}
}  // namespace

class RuntimeService::Impl {
  public:
    explicit Impl(std::shared_ptr<RuntimeBackend> b) : backend(std::move(b)), server(std::make_unique<httplib::Server>()) {}
    void finish(const GenerateResponse & out);
    std::shared_ptr<RuntimeBackend> backend;
    ServiceConfig config;
    std::unique_ptr<httplib::Server> server;
    std::thread thread;
    mutable std::mutex mutex;
    std::condition_variable idle;
    std::set<std::string> seen;
    std::string active;
    bool initialized = false;
    bool stopping = false;
    bool running = false;
    std::atomic<uint64_t> accepted{0}, completed{0}, cancelled{0}, timed_out{0}, errors{0}, token_count{0};
    RuntimeMetrics last_metrics;
    uint64_t last_service_ttft_ms = 0;
    uint64_t last_service_tpot_ms = 0;
};

RuntimeService::RuntimeService(std::shared_ptr<RuntimeBackend> backend) : impl_(std::make_unique<Impl>(std::move(backend))) {
    auto & s = *impl_->server;
    s.Get("/health", [this](const httplib::Request &, httplib::Response & res) { res.set_content(R"({"status":"alive"})", "application/json"); });
    s.Get("/ready", [this](const httplib::Request &, httplib::Response & res) { if (!ready()) res.status = 503; res.set_content(json({{"ready", ready()}}).dump(), "application/json"); });
    s.Get("/model/info", [this](const httplib::Request &, httplib::Response & res) { std::lock_guard<std::mutex> l(impl_->mutex); res.set_content(json({{"model_name", impl_->config.model_name}, {"model_sha256", impl_->config.model_sha256}, {"template_fingerprint", impl_->config.template_fingerprint}, {"context_capacity", impl_->config.context_capacity}}).dump(), "application/json"); });
    s.Get("/metrics", [this](const httplib::Request &, httplib::Response & res) { std::lock_guard<std::mutex> l(impl_->mutex); auto m = json({{"accepted", impl_->accepted.load()}, {"completed", impl_->completed.load()}, {"cancelled", impl_->cancelled.load()}, {"timeout", impl_->timed_out.load()}, {"errors", impl_->errors.load()}, {"active", impl_->active.empty() ? 0 : 1}, {"queue_depth", 0}, {"token_count", impl_->token_count.load()}, {"service_ttft_ms", impl_->last_service_ttft_ms}, {"service_tpot_ms", impl_->last_service_tpot_ms}, {"last", metrics_json(impl_->last_metrics)}}); res.set_content(m.dump(), "application/json"); });
    s.Post(R"(/v1/cancel/(.*))", [this](const httplib::Request & req, httplib::Response & res) { const std::string id = req.matches.size() > 1 ? req.matches[1].str() : ""; const Status st = impl_->backend->cancel_request(id); if (!st.ok()) { res.status = 404; } else { res.set_content(json({{"request_id", id}, {"cancelled", true}}).dump(), "application/json"); } });
    auto handler = [this](const httplib::Request & req, httplib::Response & res) {
        json body; try { body = json::parse(req.body); } catch (...) { res.status = 400; res.set_content(R"({"error":{"code":"invalid_json","message":"invalid JSON"}})", "application/json"); return; }
        GenerateRequest request; bool stream = false; std::string error;
        if (!parse_request(body, &request, &stream, impl_->config.model_sha256, &error)) { res.status = 400; res.set_content(json({{"error", {{"code", "invalid_argument"}, {"message", error}}}}).dump(), "application/json"); return; }
        { std::lock_guard<std::mutex> l(impl_->mutex); if (!impl_->initialized || impl_->stopping) { res.status = 503; return; } if (impl_->seen.count(request.request_id)) { res.status = 409; return; } if (!impl_->active.empty()) { res.status = 429; return; } impl_->seen.insert(request.request_id); impl_->active = request.request_id; impl_->accepted.fetch_add(1); }
        if (stream) { res.set_chunked_content_provider("text/event-stream", [this, request](size_t, httplib::DataSink & sink) mutable { bool disconnected = false; bool got_token = false; uint64_t first_write = 0; uint64_t last_write = 0; const auto accepted_at = std::chrono::steady_clock::now(); auto emit = [&](const char * event, const json & data) { if (disconnected) return false; const std::string payload = std::string("event: ") + event + "\ndata: " + data.dump() + "\n\n"; if (!sink.write(payload.data(), payload.size())) { disconnected = true; request.cancel_flag->store(true); return false; } return true; }; GenerateResponse out = impl_->backend->generate_text(request, [&](const StreamToken & t) { const bool written = emit("token", json({{"request_id", t.request_id}, {"session_id", nullptr}, {"index", t.index}, {"text", t.text}})); if (written) { const uint64_t now = static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - accepted_at).count()); if (!got_token) { first_write = now; got_token = true; } last_write = now; impl_->token_count.fetch_add(1); } return written; }); if (!disconnected) { const char * event = out.finish_reason == "cancelled" ? "cancelled" : out.finish_reason == "timeout" ? "timeout" : out.code == RuntimeErrorCode::kOk ? "done" : "error"; emit(event, response_json(out, impl_->config.model_sha256)); } { std::lock_guard<std::mutex> l(impl_->mutex); impl_->last_service_ttft_ms = got_token ? first_write : 0; impl_->last_service_tpot_ms = got_token && out.generated_tokens > 1 ? (last_write - first_write) / (out.generated_tokens - 1) : 0; } impl_->finish(out); sink.done(); return true; }); res.set_header("Cache-Control", "no-cache"); res.set_header("Connection", "keep-alive"); return; }
        GenerateResponse out = impl_->backend->generate_text(request); impl_->finish(out); res.status = out.code == RuntimeErrorCode::kOk ? 200 : http_code(out.code); res.set_content(response_json(out, impl_->config.model_sha256).dump(), "application/json");
    };
    s.Post("/v1/generate", handler); s.Post("/v1/chat", handler);
}

void RuntimeService::Impl::finish(const GenerateResponse & out) {
    std::lock_guard<std::mutex> l(mutex); active.clear(); last_metrics = out.metrics; if (out.code == RuntimeErrorCode::kOk) completed.fetch_add(1); else if (out.code == RuntimeErrorCode::kCancelled) cancelled.fetch_add(1); else if (out.code == RuntimeErrorCode::kTimeout) timed_out.fetch_add(1); else errors.fetch_add(1); idle.notify_all();
}

RuntimeService::~RuntimeService() { shutdown(); }
Status RuntimeService::initialize(const ServiceConfig & config) { std::lock_guard<std::mutex> l(impl_->mutex); if (impl_->initialized) return {RuntimeErrorCode::kAlreadyInitialized, "service already initialized"}; if (config.model_sha256 != kFrozenHash) return {RuntimeErrorCode::kModelHashMismatch, "service model hash mismatch"}; const Status st = impl_->backend->initialize(config.runtime); if (!st.ok()) return st; impl_->config = config; impl_->initialized = true; impl_->stopping = false; return Status::Ok(); }
Status RuntimeService::start(const std::string & host, int port) { std::lock_guard<std::mutex> l(impl_->mutex); if (!impl_->initialized || impl_->running) return {RuntimeErrorCode::kInvalidState, "service is not ready to start"}; if (!impl_->server->bind_to_port(host, port)) return {RuntimeErrorCode::kInternal, "failed to bind HTTP server"}; impl_->running = true; impl_->thread = std::thread([this] { impl_->server->listen_after_bind(); std::lock_guard<std::mutex> l(impl_->mutex); impl_->running = false; }); return Status::Ok(); }
Status RuntimeService::stop() { { std::lock_guard<std::mutex> l(impl_->mutex); if (!impl_->running) return Status::Ok(); impl_->stopping = true; } impl_->server->stop(); if (impl_->thread.joinable()) impl_->thread.join(); return Status::Ok(); }
Status RuntimeService::shutdown() { stop(); std::unique_lock<std::mutex> l(impl_->mutex); impl_->stopping = true; impl_->idle.wait(l, [this] { return impl_->active.empty(); }); if (!impl_->initialized) return Status::Ok(); const Status st = impl_->backend->shutdown(); impl_->initialized = false; return st; }
bool RuntimeService::ready() const { std::lock_guard<std::mutex> l(impl_->mutex); return impl_->initialized && !impl_->stopping; }
bool RuntimeService::running() const { std::lock_guard<std::mutex> l(impl_->mutex); return impl_->running; }
}  // namespace edgeomni
