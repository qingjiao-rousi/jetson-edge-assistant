# M8.2-D Application API Failure Audit

Date: 2026-08-04. This audit did not load GGUF/mmproj, initialize MtmdBackend, or run inference. The frozen failure directory `benchmark-results/vlm-application-api-smoke/20260730-m8.2-001` was not modified.

## Root cause

The failure is reproducibly classified as `request_rejected`. The M8.1 route normalized application input into the shared RuntimeService shape using the signed JSON literal `128` for `max_new_tokens`. The shared parser intentionally accepts only an unsigned JSON number. A real loopback test with FakeBackend reproduced HTTP 400 and body `{"error":{"code":"invalid_argument","message":"invalid max_new_tokens"}}`; FakeBackend generate call count remained zero. The host binary contained the route, so this was not an old-binary or route-not-found failure.

The normalization now stores `static_cast<uint32_t>(128)`. The same real loopback test then returned HTTP 200, invoked FakeBackend exactly once, preserved request ID/prompt/one ImageInput, and produced one `metadata`, ordered token events, and exactly one `done` terminal.

## Evidence semantics and runner repair

The historical M8.2 result remains unchanged, but its `inference_run_count=1` was derived from service readiness and is not valid inference evidence. Corrected audit ledger: `service_process_start_count=1`, `application_request_attempt_count=1`, `backend_generate_invoked=false`, `inference_run_count=0`, `retry_count=0`.

The runner now writes `http-response.json` for success and failures, capturing HTTP status/reason/headers, redacted response body, response byte count, exception type/message, request stage, and elapsed time. HTTPError, URLError, timeout, RemoteDisconnected, and SSE parse failures are distinguished. Base64 values are redacted, and inference count is set only when token or terminal events directly show backend execution.

Loopback inability now exits nonzero (`77`) with `BLOCKED_LOOPBACK`; it can no longer appear as a passing HTTP contract test. M8.2-R may be proposed because the exact failure is reproduced and the corrected FakeBackend route test genuinely passes. This audit itself performed no retry or model execution.
