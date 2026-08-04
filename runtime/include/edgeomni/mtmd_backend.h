#pragma once

#include <memory>

#include "edgeomni/runtime.h"

namespace edgeomni {

// Single-context, single-image VLM backend backed by frozen libmtmd.
class MtmdBackend final : public RuntimeBackend {
  public:
    MtmdBackend();
    ~MtmdBackend() override;
    MtmdBackend(const MtmdBackend &) = delete;
    MtmdBackend & operator=(const MtmdBackend &) = delete;

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
