#pragma once

#include <cstddef>

namespace edgeomni {

// Reuse only complete cold-prefill batches. Re-evaluating the final cold
// batch preserves the batch shape that produced this request's logits.
inline size_t reusable_prefix_tokens(size_t lcp_tokens, size_t prompt_tokens, size_t batch_tokens) {
    if (batch_tokens == 0U || lcp_tokens == 0U) return 0U;
    size_t reusable = lcp_tokens - lcp_tokens % batch_tokens;
    if (reusable == prompt_tokens && reusable >= batch_tokens) reusable -= batch_tokens;
    return reusable;
}

}  // namespace edgeomni
