#include "edgeomni/service.h"

#include <atomic>
#include <cctype>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <deque>
#include <mutex>
#include <set>
#include <thread>
#include <utility>

#include "httplib.h"
#include "nlohmann/json.hpp"

namespace edgeomni {
namespace {
using json = nlohmann::json;
constexpr size_t kCompletedRequestIdCapacity = 256;
// EdgeOmni HTTP API defensive bounds, not llama.cpp-omni sampler limits.
constexpr uint64_t kMaxTopK = 100000;
constexpr double kMaxTemperature = 10.0;

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
            {"image_preprocess_ms", m.image_preprocess_ms}, {"vision_encode_ms", m.vision_encode_ms},
            {"image_embedding_ms", m.image_embedding_ms},
            {"decode_ms", m.decode_ms}, {"total_ms", m.total_ms},
            {"first_token_ms", m.first_token_ms}, {"ttft_ms", m.ttft_ms}, {"tpot_ms", m.tpot_ms},
            {"decode_tokens_per_second", m.decode_tokens_per_second},
            {"prefill_input_tokens", m.prefill_input_tokens}, {"cache_hit_tokens", m.cache_hit_tokens},
            {"cache_miss_tokens", m.cache_miss_tokens}, {"cache_hit_ratio", m.cache_hit_ratio},
            {"cache_reused", m.cache_reused}, {"cache_invalidation_reason", m.cache_invalidation_reason}};
}

json measurement_status(const RuntimeMetrics & m) {
    return {{"image_preprocess_ms", m.image_preprocess_measured ? "measured" : "not_measured"},
            {"vision_encode_ms", m.vision_encode_measured ? "measured" : "not_measured"},
            {"image_embedding_ms", m.image_embedding_measured ? "measured" : "not_measured"}};
}

json response_json(const GenerateResponse & r, const std::string & hash) {
    json out = {{"request_id", r.request_id}, {"session_id", r.session_id.empty() ? json(nullptr) : json(r.session_id)}, {"model_sha256", hash},
                {"text", r.text}, {"finish_reason", r.finish_reason},
                {"prompt_tokens", r.prompt_tokens}, {"output_tokens", r.generated_tokens},
                {"image_tokens", r.image_tokens},
                {"metrics", metrics_json(r.metrics)}, {"measurement_status", measurement_status(r.metrics)}, {"error", nullptr}};
    if (r.code != RuntimeErrorCode::kOk) out["error"] = {{"code", code_name(r.code)}, {"message", r.error_message}};
    return out;
}

void error_response(httplib::Response & response, int status, const char * code, const std::string & message) {
    response.status = status;
    response.set_content(json({{"error", {{"code", code}, {"message", message}}}}).dump(), "application/json");
}

bool has_only(const json & object, std::initializer_list<const char *> allowed) {
    for (auto it = object.begin(); it != object.end(); ++it) {
        bool found = false;
        for (const char * key : allowed) if (it.key() == key) found = true;
        if (!found) return false;
    }
    return true;
}

bool decode_base64_strict(const std::string & input, uint64_t maximum, std::vector<uint8_t> * output) {
    if (input.empty() || input.find("data:") == 0 || input.find("://") != std::string::npos) return false;
    if (input.size() % 4U != 0U || input.size() / 4U * 3U > maximum + 2U) return false;
    auto value = [](unsigned char c) -> int { if (c >= 'A' && c <= 'Z') return c - 'A'; if (c >= 'a' && c <= 'z') return c - 'a' + 26; if (c >= '0' && c <= '9') return c - '0' + 52; if (c == '+') return 62; if (c == '/') return 63; return -1; };
    output->clear(); output->reserve(input.size() / 4U * 3U);
    for (size_t i = 0; i < input.size(); i += 4U) {
        const int a = value(input[i]), b = value(input[i + 1U]); const int c = input[i + 2U] == '=' ? -2 : value(input[i + 2U]); const int d = input[i + 3U] == '=' ? -2 : value(input[i + 3U]);
        if (a < 0 || b < 0 || (c < 0 && c != -2) || (d < 0 && d != -2) || (c == -2 && d != -2) || ((c == -2 || d == -2) && i + 4U != input.size())) return false;
        output->push_back(static_cast<uint8_t>((a << 2) | (b >> 4)));
        if (c != -2) output->push_back(static_cast<uint8_t>((b << 4) | (c >> 2)));
        if (d != -2) output->push_back(static_cast<uint8_t>((c << 6) | d));
        if (output->size() > maximum) return false;
    }
    return true;
}

bool get_nonnegative_integer(const json & value, uint64_t maximum, uint64_t * output) {
    if (value.is_number_unsigned()) {
        const uint64_t parsed = value.get<uint64_t>();
        if (parsed > maximum) return false;
        *output = parsed;
        return true;
    }
    if (!value.is_number_integer()) return false;
    const int64_t parsed = value.get<int64_t>();
    if (parsed < 0 || static_cast<uint64_t>(parsed) > maximum) return false;
    *output = static_cast<uint64_t>(parsed);
    return true;
}

bool get_finite_float(const json & value, double minimum, double maximum, float * output) {
    if (!value.is_number()) return false;
    const double parsed = value.get<double>();
    if (!std::isfinite(parsed) || parsed < minimum || parsed > maximum) return false;
    *output = static_cast<float>(parsed);
    return std::isfinite(*output);
}

bool parse_request(const json & body, GenerateRequest * request, bool * stream, const std::string & expected_hash,
                  std::string * error) {
    if (!body.is_object() || !has_only(body, {"request_id", "session_id", "messages", "max_new_tokens", "timeout_ms", "stream", "model_sha256", "sampling", "images"})) {
        *error = "invalid JSON object or unknown field"; return false;
    }
    if (!body.contains("request_id") || !body["request_id"].is_string() || body["request_id"].get<std::string>().empty()) {
        *error = "request_id is required"; return false;
    }
    if (body.contains("session_id") && !body["session_id"].is_null() && !body["session_id"].is_string()) { *error = "session_id must be a string"; return false; }
    if (!body.contains("messages") || !body["messages"].is_array() || body["messages"].empty()) { *error = "messages must be non-empty array"; return false; }
    request->request_id = body["request_id"].get<std::string>();
    if (body.contains("session_id") && !body["session_id"].is_null()) request->session_id = body["session_id"].get<std::string>();
    for (const auto & message : body["messages"]) {
        if (!message.is_object() || !has_only(message, {"role", "content"}) || !message.contains("role") || !message.contains("content") || !message["role"].is_string() || !message["content"].is_string()) { *error = "invalid message"; return false; }
        const std::string role = message["role"].get<std::string>();
        if (role != "system" && role != "user" && role != "assistant") { *error = "unsupported message role"; return false; }
        request->messages.push_back({role, message["content"].get<std::string>()});
    }
    if (!body.contains("max_new_tokens") || !body["max_new_tokens"].is_number_unsigned() || body["max_new_tokens"].get<uint64_t>() == 0 || body["max_new_tokens"].get<uint64_t>() > UINT32_MAX) { *error = "invalid max_new_tokens"; return false; }
    request->max_new_tokens = body["max_new_tokens"].get<uint32_t>();
    if (body.contains("timeout_ms")) { if (!body["timeout_ms"].is_number_unsigned() || body["timeout_ms"].get<uint64_t>() > UINT64_MAX) { *error = "invalid timeout_ms"; return false; } request->timeout_ms = body["timeout_ms"].get<uint64_t>(); }
    if (body.contains("stream") && !body["stream"].is_boolean()) { *error = "invalid stream"; return false; }
    *stream = body.value("stream", false);
    if (body.contains("model_sha256") && (!body["model_sha256"].is_string() || body["model_sha256"].get<std::string>() != expected_hash)) { *error = "model_sha256 mismatch"; return false; }
    if (body.contains("sampling")) {
        const auto & s = body["sampling"]; if (!s.is_object() || !has_only(s, {"seed", "top_k", "top_p", "min_p", "temperature"})) { *error = "invalid sampling"; return false; }
        uint64_t integer_value = 0;
        if (s.contains("seed")) {
            if (!get_nonnegative_integer(s["seed"], UINT32_MAX, &integer_value)) { *error = "invalid seed"; return false; }
            request->sampling.seed = static_cast<uint32_t>(integer_value);
        }
        if (s.contains("top_k")) {
            if (!get_nonnegative_integer(s["top_k"], kMaxTopK, &integer_value)) { *error = "invalid top_k"; return false; }
            request->sampling.top_k = static_cast<int32_t>(integer_value);
        }
        if (s.contains("top_p") && !get_finite_float(s["top_p"], 0.0, 1.0, &request->sampling.top_p)) { *error = "invalid top_p"; return false; }
        if (s.contains("top_p") && request->sampling.top_p <= 0.0F) { *error = "invalid top_p"; return false; }
        if (s.contains("min_p") && !get_finite_float(s["min_p"], 0.0, 1.0, &request->sampling.min_p)) { *error = "invalid min_p"; return false; }
        if (s.contains("temperature") && !get_finite_float(s["temperature"], 0.0, kMaxTemperature, &request->sampling.temperature)) { *error = "invalid temperature"; return false; }
    }
    if (body.contains("images")) {
        if (!body["images"].is_array() || body["images"].size() > 1U) { *error = "images must contain at most one item"; return false; }
        for (const auto & image : body["images"]) {
            if (!image.is_object() || !has_only(image, {"id", "mime", "data_base64"}) || !image.contains("id") || !image.contains("mime") || !image.contains("data_base64") || !image["id"].is_string() || !image["mime"].is_string() || !image["data_base64"].is_string()) { *error = "invalid image object"; return false; }
            ImageInput decoded; decoded.id = image["id"].get<std::string>(); decoded.mime_type = image["mime"].get<std::string>();
            if (!decode_base64_strict(image["data_base64"].get<std::string>(), 10U * 1024U * 1024U, &decoded.encoded_bytes)) { *error = "invalid or oversized image base64"; return false; }
            request->images.push_back(std::move(decoded));
        }
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
    // A single-process memory bound, not a multi-user idempotency cache.
    std::set<std::string> completed_request_ids;
    std::deque<std::string> completed_request_id_order;
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
    s.Get("/metrics", [this](const httplib::Request &, httplib::Response & res) { std::lock_guard<std::mutex> l(impl_->mutex); auto m = json({{"accepted", impl_->accepted.load()}, {"completed", impl_->completed.load()}, {"cancelled", impl_->cancelled.load()}, {"timeout", impl_->timed_out.load()}, {"errors", impl_->errors.load()}, {"active", impl_->active.empty() ? 0 : 1}, {"queue_depth", 0}, {"token_count", impl_->token_count.load()}, {"completed_request_ids", impl_->completed_request_id_order.size()}, {"completed_request_id_capacity", kCompletedRequestIdCapacity}, {"service_ttft_ms", impl_->last_service_ttft_ms}, {"service_tpot_ms", impl_->last_service_tpot_ms}, {"last", metrics_json(impl_->last_metrics)}}); res.set_content(m.dump(), "application/json"); });
    s.Post("/v1/context/reset", [this](const httplib::Request &, httplib::Response & res) {
        std::lock_guard<std::mutex> lock(impl_->mutex);
        if (!impl_->initialized || impl_->stopping) { error_response(res, 503, "unavailable", "service is not ready"); return; }
        if (!impl_->active.empty()) { error_response(res, 409, "busy", "cannot reset an active context"); return; }
        const Status status = impl_->backend->reset_context();
        if (!status.ok()) { error_response(res, http_code(status.code), code_name(status.code), status.message); return; }
        res.set_content(R"({"reset":true})", "application/json");
    });
    s.Post(R"(/v1/cancel/(.*))", [this](const httplib::Request & req, httplib::Response & res) { const std::string id = req.matches.size() > 1 ? req.matches[1].str() : ""; const Status st = impl_->backend->cancel_request(id); if (!st.ok()) { res.status = 404; } else { res.set_content(json({{"request_id", id}, {"cancelled", true}}).dump(), "application/json"); } });
    auto handler = [this](const httplib::Request & req, httplib::Response & res, bool application_diagnosis_route) {
        json body; try { body = json::parse(req.body); } catch (...) { res.status = 400; res.set_content(R"({"error":{"code":"invalid_json","message":"invalid JSON"}})", "application/json"); return; }
        // M8.1 application-facing single-image diagnosis contract. It normalizes
        // into the existing RuntimeService request shape; image decoding remains shared.
        GenerateRequest request; bool stream = false; std::string error;
        try {
            if (application_diagnosis_route) {
                if (!body.is_object() || !has_only(body, {"request_id", "prompt", "images", "stream"}) || !body.contains("prompt") || !body["prompt"].is_string() || !body.contains("images")) {
                    res.status = 400; res.set_content(R"({"error":{"code":"invalid_argument","message":"invalid diagnosis request"}})", "application/json"); return;
                }
                json normalized = {{"request_id", body.value("request_id", "diagnose-image")}, {"messages", {{{"role", "user"}, {"content", body["prompt"]}}}}, {"images", body["images"]}, {"max_new_tokens", static_cast<uint32_t>(128)}, {"stream", body.value("stream", false)}};
                body = std::move(normalized);
            }
            if (!parse_request(body, &request, &stream, impl_->config.model_sha256, &error)) { res.status = 400; res.set_content(json({{"error", {{"code", "invalid_argument"}, {"message", error}}}}).dump(), "application/json"); return; }
        } catch (const json::exception &) {
            error_response(res, 400, "invalid_argument", "invalid request value"); return;
        }
        { std::lock_guard<std::mutex> l(impl_->mutex); if (!impl_->initialized || impl_->stopping) { error_response(res, 503, "unavailable", "service is not ready"); return; } if (impl_->active == request.request_id || impl_->completed_request_ids.count(request.request_id)) { error_response(res, 409, "duplicate_request_id", "request_id is active or recently completed"); return; } if (!impl_->active.empty()) { error_response(res, 429, "busy", "another request is active"); return; } impl_->active = request.request_id; impl_->accepted.fetch_add(1); }
        if (stream) { res.set_chunked_content_provider("text/event-stream", [this, request](size_t, httplib::DataSink & sink) mutable { bool disconnected = false; bool got_token = false; uint64_t first_write = 0; uint64_t last_write = 0; const auto accepted_at = std::chrono::steady_clock::now(); auto emit = [&](const char * event, const json & data) { if (disconnected) return false; const std::string payload = std::string("event: ") + event + "\ndata: " + data.dump() + "\n\n"; if (!sink.write(payload.data(), payload.size())) { disconnected = true; request.cancel_flag->store(true); return false; } return true; }; emit("metadata", json({{"request_id", request.request_id}, {"session_id", request.session_id.empty() ? json(nullptr) : json(request.session_id)}, {"image_tokens", nullptr}, {"image_metrics", {{"image_preprocess_ms", nullptr}, {"vision_encode_ms", nullptr}, {"image_embedding_ms", nullptr}}}, {"measurement_status", "not_measured_before_backend"}})); GenerateResponse out = impl_->backend->generate_text(request, [&](const StreamToken & t) { const bool written = emit("token", json({{"request_id", t.request_id}, {"session_id", request.session_id.empty() ? json(nullptr) : json(request.session_id)}, {"index", t.index}, {"text", t.text}})); if (written) { const uint64_t now = static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - accepted_at).count()); if (!got_token) { first_write = now; got_token = true; } last_write = now; impl_->token_count.fetch_add(1); } return written; }); if (!disconnected) { const char * event = out.finish_reason == "cancelled" ? "cancelled" : out.finish_reason == "timeout" ? "timeout" : out.code == RuntimeErrorCode::kOk ? "done" : "error"; emit(event, response_json(out, impl_->config.model_sha256)); } { std::lock_guard<std::mutex> l(impl_->mutex); impl_->last_service_ttft_ms = got_token ? first_write : 0; impl_->last_service_tpot_ms = got_token && out.generated_tokens > 1 ? (last_write - first_write) / (out.generated_tokens - 1) : 0; } impl_->finish(out); sink.done(); return true; }); res.set_header("Cache-Control", "no-cache"); res.set_header("Connection", "keep-alive"); return; }
        GenerateResponse out = impl_->backend->generate_text(request); impl_->finish(out); res.status = out.code == RuntimeErrorCode::kOk ? 200 : http_code(out.code); res.set_content(response_json(out, impl_->config.model_sha256).dump(), "application/json");
    };
    s.Post("/v1/generate", [handler](const httplib::Request & req, httplib::Response & res) { handler(req, res, false); });
    s.Post("/v1/chat", [handler](const httplib::Request & req, httplib::Response & res) { handler(req, res, false); });
    s.Post("/v1/diagnose/image", [handler](const httplib::Request & req, httplib::Response & res) { handler(req, res, true); });
}

void RuntimeService::Impl::finish(const GenerateResponse & out) {
    std::lock_guard<std::mutex> l(mutex);
    if (active == out.request_id) {
        active.clear();
        completed_request_ids.insert(out.request_id);
        completed_request_id_order.push_back(out.request_id);
        if (completed_request_id_order.size() > kCompletedRequestIdCapacity) {
            completed_request_ids.erase(completed_request_id_order.front());
            completed_request_id_order.pop_front();
        }
    }
    last_metrics = out.metrics; if (out.code == RuntimeErrorCode::kOk) completed.fetch_add(1); else if (out.code == RuntimeErrorCode::kCancelled) cancelled.fetch_add(1); else if (out.code == RuntimeErrorCode::kTimeout) timed_out.fetch_add(1); else errors.fetch_add(1); idle.notify_all();
}

RuntimeService::~RuntimeService() { shutdown(); }
Status RuntimeService::initialize(const ServiceConfig & config) { std::lock_guard<std::mutex> l(impl_->mutex); if (impl_->initialized) return {RuntimeErrorCode::kAlreadyInitialized, "service already initialized"}; if (config.model_sha256.empty() || config.model_sha256 != config.runtime.expected_model_sha256) return {RuntimeErrorCode::kModelHashMismatch, "service model hash must match RuntimeConfig"}; const Status st = impl_->backend->initialize(config.runtime); if (!st.ok()) return st; impl_->config = config; impl_->initialized = true; impl_->stopping = false; return Status::Ok(); }
Status RuntimeService::start(const std::string & host, int port) { std::lock_guard<std::mutex> l(impl_->mutex); if (!impl_->initialized || impl_->running) return {RuntimeErrorCode::kInvalidState, "service is not ready to start"}; if (!impl_->server->bind_to_port(host, port)) return {RuntimeErrorCode::kInternal, "failed to bind HTTP server"}; impl_->running = true; impl_->thread = std::thread([this] { impl_->server->listen_after_bind(); std::lock_guard<std::mutex> l(impl_->mutex); impl_->running = false; }); return Status::Ok(); }
Status RuntimeService::stop() { { std::lock_guard<std::mutex> l(impl_->mutex); if (!impl_->running) return Status::Ok(); impl_->stopping = true; } impl_->server->stop(); if (impl_->thread.joinable()) impl_->thread.join(); return Status::Ok(); }
Status RuntimeService::shutdown() { stop(); std::unique_lock<std::mutex> l(impl_->mutex); impl_->stopping = true; impl_->idle.wait(l, [this] { return impl_->active.empty(); }); if (!impl_->initialized) return Status::Ok(); const Status st = impl_->backend->shutdown(); impl_->initialized = false; return st; }
bool RuntimeService::ready() const { std::lock_guard<std::mutex> l(impl_->mutex); return impl_->initialized && !impl_->stopping; }
bool RuntimeService::running() const { std::lock_guard<std::mutex> l(impl_->mutex); return impl_->running; }
}  // namespace edgeomni
