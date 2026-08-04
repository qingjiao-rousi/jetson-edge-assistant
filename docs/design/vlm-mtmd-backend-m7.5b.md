# M7.5B MtmdBackend

M7.5B connects the M7.5A VLM contract to the frozen `libmtmd` build at Runtime commit `19cc26967140407efe34006a355ab445b35b16ac`. It has no HTTP image interface and accepts only in-memory `ImageInput.encoded_bytes`; no image path is exposed above the Adapter.

Initialization verifies the fixed main-model/mmproj pair using the M7.5A streaming verifier, acquires EdgeOmni's reference-counted process-global llama backend, loads the text model and context, and creates one persistent mtmd vision context. The project-local lifecycle helper is shared with DirectBackend, so coexistence does not double-free `llama_backend`.

For a request, public `mtmd_helper_bitmap_init_from_buf` decodes the byte buffer. Authoritative decoded dimensions are sent through M7.5A validation. The Adapter formats messages using `llama_model_chat_template` and `llama_chat_apply_template`, inserts the public mtmd media marker, tokenizes to chunks, reads image tokens directly from image chunks, and evaluates chunks through `mtmd_helper_eval_chunks`. It admits only one active request; a concurrent request returns `RESOURCE_EXHAUSTED`. Every terminal path clears the LLM KV memory before the next request.

Metrics record direct Adapter timings. `image_preprocess_ms`, `prefill_ms`, first-token/TTFT, decode and total are directly timed. Current frozen mtmd helper does not separately expose vision encode versus embedding injection timing, so those two fields remain zero rather than being inferred from CLI timings. M7.5B's planned one-shot uses 8192 only; 16384 remains experimental with one recovery fact and 32768 is disabled. A successful single run is not a stability, average-performance, or deployment conclusion.
