#pragma once

#include <mutex>
#include <vector>

#include "edgeomni/runtime.h"

namespace edgeomni {

class FakeBackend final : public RuntimeBackend {
  public:
    Status initialize(const RuntimeConfig & config) override;
    GenerateResponse generate_text(const GenerateRequest & request, const TokenCallback & on_token = {}) override;
    Status cancel_request(const std::string & request_id) override;
    Status reset_context() override;
    Status shutdown() override;

    // Test-only deterministic pacing; production DirectBackend has no such hook.
    void set_test_delay_ms(uint32_t delay_ms);
    unsigned int generate_call_count() const;
    GenerateRequest last_request() const;

  private:
    mutable std::mutex mutex_;
    bool initialized_ = false;
    unsigned int request_count_ = 0;
    std::string active_request_id_;
    std::shared_ptr<std::atomic_bool> active_cancel_flag_;
    uint32_t test_delay_ms_ = 0;
    unsigned int generate_call_count_ = 0;
    GenerateRequest last_request_;
    std::string hot_session_id_;
    std::vector<uint8_t> hot_prompt_tokens_;
};

}  // namespace edgeomni
