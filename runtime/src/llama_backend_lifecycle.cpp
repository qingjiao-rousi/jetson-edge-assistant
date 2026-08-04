#include "llama_backend_lifecycle.h"

#include <mutex>

#include "llama.h"

namespace edgeomni {
namespace {
std::mutex g_mutex;
bool g_initialized = false;
size_t g_users = 0;
}  // namespace

Status acquire_llama_backend() {
    std::lock_guard<std::mutex> lock(g_mutex);
    if (!g_initialized) {
        llama_backend_init();
        g_initialized = true;
    }
    ++g_users;
    return Status::Ok();
}

void release_llama_backend() {
    std::lock_guard<std::mutex> lock(g_mutex);
    if (g_users == 0U) return;
    --g_users;
    if (g_users == 0U && g_initialized) {
        llama_backend_free();
        g_initialized = false;
    }
}
}  // namespace edgeomni
