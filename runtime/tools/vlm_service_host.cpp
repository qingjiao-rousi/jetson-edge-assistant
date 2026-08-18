#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdlib>
#include <iostream>
#include <memory>
#include <string>
#include <thread>

#include "edgeomni/mtmd_backend.h"
#include "edgeomni/service.h"

namespace {
std::atomic_bool stop{false};
void on_signal(int) { stop.store(true); }

bool take(int & index, int argc, char ** argv, const char * name, std::string * value) {
    if (std::string(argv[index]) != name || index + 1 >= argc) return false;
    *value = argv[++index];
    return true;
}

void usage(const char * program) {
    std::cerr << "usage: " << program << " --port PORT --model PATH --model-size BYTES --model-sha256 HASH "
              << "--mmproj PATH --mmproj-size BYTES --mmproj-sha256 HASH --context TOKENS "
              << "--batch TOKENS --ubatch TOKENS --gpu-layers N --prefix-reuse disabled|single_hot_text\n";
}
}
int main(int argc, char ** argv) {
    std::string port, model, model_size, model_sha256, mmproj, mmproj_size, mmproj_sha256, context, batch, ubatch, gpu_layers, prefix_reuse;
    for (int index = 1; index < argc; ++index) {
        if (take(index, argc, argv, "--port", &port) || take(index, argc, argv, "--model", &model) ||
            take(index, argc, argv, "--model-size", &model_size) || take(index, argc, argv, "--model-sha256", &model_sha256) ||
            take(index, argc, argv, "--mmproj", &mmproj) || take(index, argc, argv, "--mmproj-size", &mmproj_size) ||
            take(index, argc, argv, "--mmproj-sha256", &mmproj_sha256) || take(index, argc, argv, "--context", &context) ||
            take(index, argc, argv, "--batch", &batch) || take(index, argc, argv, "--ubatch", &ubatch) ||
            take(index, argc, argv, "--gpu-layers", &gpu_layers) || take(index, argc, argv, "--prefix-reuse", &prefix_reuse)) continue;
        usage(argv[0]); return 2;
    }
    if (port.empty() || model.empty() || model_size.empty() || model_sha256.empty() || mmproj.empty() || mmproj_size.empty() ||
        mmproj_sha256.empty() || context.empty() || batch.empty() || ubatch.empty() || gpu_layers.empty() || prefix_reuse.empty()) { usage(argv[0]); return 2; }
    edgeomni::RuntimeConfig runtime;
    try {
        runtime.model_path = model; runtime.expected_model_size_bytes = std::stoull(model_size); runtime.expected_model_sha256 = model_sha256;
        runtime.mmproj_path = mmproj; runtime.expected_mmproj_size_bytes = std::stoull(mmproj_size); runtime.expected_mmproj_sha256 = mmproj_sha256;
        runtime.context_tokens = static_cast<uint32_t>(std::stoul(context)); runtime.batch_tokens = static_cast<uint32_t>(std::stoul(batch));
        runtime.ubatch_tokens = static_cast<uint32_t>(std::stoul(ubatch)); runtime.gpu_layers = std::stoi(gpu_layers); runtime.flash_attention = true;
        if (prefix_reuse == "disabled") runtime.prefix_reuse_mode = edgeomni::PrefixReuseMode::kDisabled;
        else if (prefix_reuse == "single_hot_text") runtime.prefix_reuse_mode = edgeomni::PrefixReuseMode::kSingleHotText;
        else throw std::invalid_argument("invalid prefix reuse mode");
    } catch (const std::exception &) { usage(argv[0]); return 2; }
    std::cerr << "edgeomni-runtime: initializing model=" << runtime.model_path << " context=" << runtime.context_tokens
              << " port=" << port << '\n';
    edgeomni::ServiceConfig config; config.runtime = runtime; config.model_name = "configured-vlm"; config.model_sha256 = runtime.expected_model_sha256; config.context_capacity = runtime.context_tokens;
    auto backend = std::make_shared<edgeomni::MtmdBackend>(); edgeomni::RuntimeService service(backend);
    const auto initialized = service.initialize(config); if (!initialized.ok()) { std::cerr << "edgeomni-runtime: initialization failed code=" << static_cast<int>(initialized.code) << " detail=" << initialized.message << '\n'; return 1; }
    const auto started = service.start("127.0.0.1", std::atoi(port.c_str())); if (!started.ok()) { std::cerr << "edgeomni-runtime: bind failed port=" << port << " detail=" << started.message << '\n'; service.shutdown(); return 1; }
    std::cerr << "edgeomni-runtime: ready url=http://127.0.0.1:" << port << " context=" << runtime.context_tokens << '\n' << std::flush;
    std::signal(SIGTERM, on_signal); std::signal(SIGINT, on_signal);
    while (!stop.load()) std::this_thread::sleep_for(std::chrono::milliseconds(20));
    std::cerr << "edgeomni-runtime: stopping\n" << std::flush;
    service.shutdown(); std::cerr << "edgeomni-runtime: stopped\n" << std::flush; return 0;
}
