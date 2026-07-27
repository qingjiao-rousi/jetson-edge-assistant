#pragma once

#include <memory>

#include "edgeomni/runtime.h"

namespace edgeomni {

class DirectBackend final : public RuntimeBackend {
  public:
    DirectBackend();
    ~DirectBackend() override;

    DirectBackend(const DirectBackend &) = delete;
    DirectBackend & operator=(const DirectBackend &) = delete;

    Status initialize(const RuntimeConfig & config) override;
    GenerateResponse generate_text(const GenerateRequest & request, const TokenCallback & on_token = {}) override;
    Status cancel_request(const std::string & request_id) override;
    Status reset_context() override;
    Status shutdown() override;

  private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace edgeomni
