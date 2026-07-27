#pragma once

#include <string>
#include <vector>

#include "edgeomni/runtime.h"

namespace edgeomni {

class ChatTemplateRenderer {
  public:
    static constexpr const char * kQwen3TemplateSha256 =
        "57f1fd00f0013a2be96aa79b857391f27e23df5b5f847072b524c897e24d0361";

    Status validate_template(const std::string & template_source) const;
    Status render(const std::vector<ChatMessage> & messages, bool add_generation_prompt,
                  std::string * prompt) const;

    static std::string sha256_hex(const std::string & input);
};

}  // namespace edgeomni
