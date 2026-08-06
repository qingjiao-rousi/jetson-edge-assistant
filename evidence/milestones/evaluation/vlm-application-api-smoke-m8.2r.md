# M8.2-R Application API Recovery Smoke

Date: 2026-08-04. The repaired `POST /v1/diagnose/image` route completed one real 8192-context single-image HTTP/SSE request through RuntimeService and MtmdBackend. One service process was started, one application request was sent, one backend inference ran, and no retry occurred. The historical M8.2 failure and M8.2-D audit evidence were not modified.

The response was HTTP 200. SSE order was one `metadata` event, 67 ordered `token` events, and one `done` terminal. The backend directly reported 391 image tokens, 415 prompt tokens, and 67 output tokens. Output was non-empty and identified the publisher as The New York Times.

The frozen Runtime commit was `19cc26967140407efe34006a355ab445b35b16ac`. Logs show 37/37 model layers offloaded to CUDA0, Flash Attention enabled, an 8192-cell 288 MiB KV cache, successful image encode (`2947 ms`) and embedding decode (`54 ms`), and no OOM, CUDA error, context overflow, or crash.

Adapter response metrics were: model ready 6220 ms, image preprocess 11 ms, prefill 4709 ms, TTFT 4899 ms, decode 9205 ms, and total 13940 ms. The independent mtmd encode/decode lines above are kept separate from Adapter metrics. Telemetry had 80 samples; peaks were UMA 9483/30697 MiB, GR3D 99%, temperature 57.281 C, VDD_GPU_SOC 6886 mW, VDD_CPU_CV 1915 mW, and VIN_SYS_5V0 6461 mW.

Ledger: service process starts 1, current application attempts 1, cumulative application attempts 2, backend generate invoked true, current inference runs 1, cumulative inference runs 1, retries 0, child exit code 0. Service and tegrastats both stopped normally.

This is one repaired application-route smoke fact, not an average-performance, stability, concurrency, or deployment conclusion. Development context remains 8192; the model metadata value 128000 is not a Jetson deployment-length conclusion. No 16384 or 32768 execution occurred.
