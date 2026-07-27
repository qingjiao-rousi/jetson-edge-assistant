#pragma once

#include <cstdint>
#include <memory>
#include <string>

#include "edgeomni/runtime.h"

namespace edgeomni {

struct ServiceConfig {
    RuntimeConfig runtime;
    std::string model_name;
    std::string model_sha256;
    std::string template_fingerprint;
    uint32_t context_capacity = 4096;
};

class RuntimeService final {
  public:
    explicit RuntimeService(std::shared_ptr<RuntimeBackend> backend);
    ~RuntimeService();

    RuntimeService(const RuntimeService &) = delete;
    RuntimeService & operator=(const RuntimeService &) = delete;

    Status initialize(const ServiceConfig & config);
    Status start(const std::string & host = "127.0.0.1", int port = 8080);
    Status stop();
    Status shutdown();
    bool ready() const;
    bool running() const;

  private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace edgeomni
