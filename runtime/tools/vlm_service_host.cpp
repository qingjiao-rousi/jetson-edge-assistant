#include <atomic>
#include <chrono>
#include <csignal>
#include <iostream>
#include <memory>
#include <thread>

#include "edgeomni/mtmd_backend.h"
#include "edgeomni/service.h"

namespace { std::atomic_bool stop{false}; void on_signal(int) { stop.store(true); } }
int main(int argc, char ** argv) {
    if (argc != 2) { std::cerr << "usage: " << argv[0] << " PORT\n"; return 2; }
    edgeomni::RuntimeConfig runtime;
    runtime.model_path = "models/Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf"; runtime.expected_model_size_bytes = 1929901056ULL;
    runtime.expected_model_sha256 = "d02fe9b69ad8cadbbd228e387667af66612c44bed29ffc8eb1e7caf9ac486c12";
    runtime.mmproj_path = "models/mmproj-Qwen2.5-VL-3B-Instruct-Q8_0.gguf"; runtime.expected_mmproj_size_bytes = 844757728ULL;
    runtime.expected_mmproj_sha256 = "980c9b2f78c04e6cff93d277ada09e768394f112d75db3b4e9dea8a69f9fb904";
    runtime.context_tokens = 8192; runtime.batch_tokens = 512; runtime.ubatch_tokens = 512; runtime.gpu_layers = 99; runtime.flash_attention = true;
    edgeomni::ServiceConfig config; config.runtime = runtime; config.model_name = "Qwen2.5-VL-3B-Instruct-Q4_K_M"; config.model_sha256 = runtime.expected_model_sha256; config.context_capacity = 8192;
    auto backend = std::make_shared<edgeomni::MtmdBackend>(); edgeomni::RuntimeService service(backend);
    const auto initialized = service.initialize(config); if (!initialized.ok()) { std::cerr << "SERVICE_INIT_FAILED " << static_cast<int>(initialized.code) << " " << initialized.message << '\n'; return 1; }
    const auto started = service.start("127.0.0.1", std::atoi(argv[1])); if (!started.ok()) { std::cerr << "SERVICE_START_FAILED " << started.message << '\n'; service.shutdown(); return 1; }
    std::cout << "SERVICE_READY\n" << std::flush; std::signal(SIGTERM, on_signal); std::signal(SIGINT, on_signal);
    while (!stop.load()) std::this_thread::sleep_for(std::chrono::milliseconds(20));
    service.shutdown(); std::cout << "SERVICE_STOPPED\n" << std::flush; return 0;
}
