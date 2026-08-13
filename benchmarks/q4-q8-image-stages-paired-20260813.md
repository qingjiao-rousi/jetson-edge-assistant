# Q4_K_M versus Q8_0 paired single-image stage-timing baseline

Status: **FINAL REVIEWED PAIRED SINGLE-IMAGE STAGE RESULT - CLEAN COMMIT**

Both runs used clean commit `f806e59e01b5275ed8a06e18b0e4ce53f7563425`, upstream commit `19cc26967140407efe34006a355ab445b35b16ac`, the same Jetson AGX Orin, MMProj, prompt, image, Runtime executable and locked MODE_30W configuration. The only configured inference variable was the main-model GGUF quantization.

## Fixed protocol

| Field | Value |
| --- | --- |
| Q4 timestamp | 2026-08-13 03:16:34 UTC |
| Q8 timestamp | 2026-08-13 03:19:43 UTC |
| Samples per quantization | 1 warm-up excluded + 15 measured requests |
| Request | `/v1/diagnose/image`, non-streaming, maximum 128 output tokens |
| Image | `synthetic-alarm-panel.png`, PNG, 320x192, 608 bytes, SHA-256 `455963a...483395` |
| Prompt | `Describe the visible panel state and list only directly observable abnormalities.` |
| Runtime | context 8192, batch/ubatch 512, default generation/batch threads 8, Flash Attention, GPU layers 99 |
| Clocks | CPU 1.728 GHz; GPU 612 MHz; EMC override at 3.199 GHz |
| Offload | 37/37 main-model layers for both quantizations |
| Model/MMProj | Q4 `d02fe9b...486c12`; Q8 `fa8aeb3b...72d9fe`; shared MMProj `980c9b2...fb904` |

Both environment records contain `git_worktree_clean=true`, zero status entries and `clocks_locked=true`. Both runs completed 15/15 HTTP requests without structured errors and stopped normally. Every response reported all three image-stage fields as `measured`, 99 prompt tokens, 77 image tokens, 14 output tokens and the same output text for both quantizations.

## Paired results

Percentage is `(Q8 / Q4 - 1) * 100`. Negative latency favors Q8; positive resource values mean Q8 used more.

| Metric | Q4 median | Q8 median | Q8 versus Q4 |
| --- | ---: | ---: | ---: |
| Model ready, one initialization | 4,769 ms | 6,673 ms | +39.92% |
| Image preprocessing | 0 ms measured | 0 ms measured | below 1 ms resolution |
| Vision encode | 305 ms | 277 ms | -9.18% |
| Image embedding injection | 31 ms | 28 ms | -9.68% |
| TTFT | 598 ms | 537 ms | -10.20% |
| Prefill, aggregate | 514 ms | 463 ms | -9.92% |
| Decode throughput | 13.820 token/s | 14.042 token/s | +1.61% |
| Runtime total | 1,531 ms | 1,463 ms | -4.44% |
| Client total | 1,533.431 ms | 1,466.137 ms | -4.39% |
| Jetson unified RAM | 12,779 MB | 14,182 MB | +1,403 MB / +10.98% |
| CUDA main-model buffer | 1,834.83 MiB | 3,127.61 MiB | +1,292.78 MiB / +70.46% |
| GPU temperature | 58.078 C | 58.156 C | +0.078 C |
| VDD_GPU_SOC board rail | 9,177 mW | 9,938 mW | +761 mW / +8.29% |

For this one fixed synthetic image and short deterministic response, Q8 measured lower median vision encode, embedding injection and end-to-end latency while using about 1.40 GB more unified RAM and taking 39.92% longer to initialize. This small sequential experiment does not establish a general VLM speed or quality advantage. Q4 remains the deployment-first candidate for the current 32 GB target because its resource advantage is substantially larger than the observed latency difference.

## Stage detail

| Metric | Quantization | n | Median | p90 | Min | Max |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Image preprocessing, ms | Q4 | 15 | 0 | 0 | 0 | 0 |
| Image preprocessing, ms | Q8 | 15 | 0 | 0 | 0 | 0 |
| Vision encode, ms | Q4 | 15 | 305 | 309 | 302 | 309 |
| Vision encode, ms | Q8 | 15 | 277 | 282 | 275 | 282 |
| Image embedding injection, ms | Q4 | 15 | 31 | 31 | 31 | 36 |
| Image embedding injection, ms | Q8 | 15 | 28 | 28 | 28 | 32 |
| Aggregate prefill, ms | Q4 | 15 | 514 | 517 | 504 | 518 |
| Aggregate prefill, ms | Q8 | 15 | 463 | 464 | 458 | 465 |

`0 ms measured` means the preprocessing duration was below the Runtime's integer-millisecond resolution; it is not an unavailable placeholder. Vision encode is measured around `mtmd_encode_chunk()`. Image embedding injection is measured around `mtmd_helper_decode_image_chunk()`, which includes upstream batching, M-RoPE position handling, causal-attention handling and `llama_decode()` of the encoded image embeddings. EdgeOmni did not reimplement those upstream mechanisms.

`prefill_ms` spans evaluation of all image and text chunks. The vision and embedding values are child observations inside that interval, so they must not be added to prefill or total latency.

## Telemetry detail

| Metric | Quantization | n | Median | p90 | Min | Max |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Unified RAM, MB | Q4 | 24 | 12,779 | 12,874 | 12,760 | 12,878 |
| Unified RAM, MB | Q8 | 23 | 14,182 | 14,260 | 14,117 | 14,262 |
| GPU temperature, C | Q4 | 24 | 58.078 | 58.281 | 57.000 | 58.375 |
| GPU temperature, C | Q8 | 23 | 58.156 | 58.562 | 57.406 | 58.750 |
| VDD_GPU_SOC, mW | Q4 | 24 | 9,177 | 9,560 | 7,265 | 9,560 |
| VDD_GPU_SOC, mW | Q8 | 23 | 9,938 | 10,320 | 9,556 | 10,320 |

Board rails are not summed and are not wall power. Unified RAM is not dedicated GPU memory. The runs were sequential in Q4-then-Q8 order rather than randomized/interleaved, and telemetry has only 23-24 one-second samples per quantization.

## Artifact binding

| Artifact | Q4 SHA-256 | Q8 SHA-256 |
| --- | --- | --- |
| Raw JSONL | `aeb4c0fe52427054e34c85d812091f817d38b1b291f6c4ce7a0628606b4a5cec` | `b3ae113b64a279f43e02e1b5e5c0c6b565e430c9dca8aa01f26d7feb4797e20d` |
| Environment | `fdd901b5e099af76e7299703d269521e346ccdde7cef66e5d5b8173252647d03` | `bd221d9c7d042abd3e95fb72d5ec2d778a7beadc1335525146850b1deadccd16` |
| Runtime log | `670e4c9bdf263c42b495e8def2c17efa0f2268b42f106fe155cbf30f8f7e2d1c` | `12c6e8e985ec5d77bbe36c660c0b9dce81e6ba23d5a08752241cb26a9218ada6` |
| `tegrastats` | `d567f10b0d4de903696fce029aad38dd8278698d590436518a938d361d1926a5` | `5038d40ba7fb7770150efe233c1d44d36e715822a083506485e6c4955c9fea0e` |

The shared Runtime executable hash is `136225857955190cf75349018f13d9a10803a777aa166c4037672fd424985095`; the collector source hash is `6c9ecf8b481a98dfd5ab1d5ca524a43730ae1dbac8787652bbe8fcd2a4452f32`.

## Claim boundary

This comparison covers one fixed 320x192 synthetic image, one prompt and a short serial workload. The fixture is an integration and performance input, not a quality dataset. Identical output proves deterministic behavior under this request only; it does not prove diagnosis correctness or Q4/Q8 quality equivalence. These results do not establish general image-resolution scaling, long-context behavior, production tail latency, long-run thermal stability, wall power, concurrency or a production SLA.
