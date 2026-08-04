#pragma once

#include "edgeomni/runtime.h"

namespace edgeomni {

// Project-owned reference counting around llama.cpp's process-global backend.
// Every EdgeOmni backend that calls llama_backend_init() must use this helper.
Status acquire_llama_backend();
void release_llama_backend();

}  // namespace edgeomni
