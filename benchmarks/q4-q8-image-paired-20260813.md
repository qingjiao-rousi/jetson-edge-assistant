# Q4_K_M versus Q8_0 paired single-image end-to-end baseline

Status: **FINAL REVIEWED PAIRED SINGLE-IMAGE E2E RESULT - CLEAN COMMIT**

Both runs used clean commit `7415e0e6b7d1447addec2006f4540e0defb08bad`, upstream commit `19cc26967140407efe34006a355ab445b35b16ac`, the same Jetson AGX Orin, MMProj, prompt, image, Runtime executable and locked MODE_30W configuration. The only configured inference variable was the main-model GGUF quantization.

## Fixed protocol

| Field | Value |
| --- | --- |
| Q4 timestamp | 2026-08-13 02:23:03 UTC |
| Q8 timestamp | 2026-08-13 02:27:46 UTC |
| Samples per quantization | 1 warm-up excluded + 15 measured requests |
| Request | `/v1/diagnose/image`, non-streaming, maximum 128 output tokens |
| Image | `synthetic-alarm-panel.png`, PNG, 320x192, 608 bytes, SHA-256 `455963a...483395` |
| Prompt | `Describe the visible panel state and list only directly observable abnormalities.` |
| Runtime | context 8192, batch/ubatch 512, default generation/batch threads 8, Flash Attention, GPU layers 99 |
| Clocks | CPU 1.728 GHz; GPU 612 MHz; EMC override at 3.199 GHz |
| Offload | 37/37 main-model layers for both quantizations |
| Model/MMProj | Q4 `d02fe9b...486c12`; Q8 `fa8aeb3b...72d9fe`; shared MMProj `980c9b2...fb904` |

Both environment records contain `git_worktree_clean=true`, zero status entries and `clocks_locked=true`. Both runs completed 15/15 HTTP requests without structured errors and stopped normally. Every response reported 99 prompt tokens, 77 image tokens, 14 output tokens and the same output text for both quantizations.

## Paired results

Percentage is `(Q8 / Q4 - 1) * 100`. Negative latency favors Q8; positive resource values mean Q8 used more.

| Metric | Q4 median | Q8 median | Q8 versus Q4 |
| --- | ---: | ---: | ---: |
| Model ready, one initialization | 4,834 ms | 6,719 ms | +38.99% |
| TTFT | 598 ms | 537 ms | -10.20% |
| Prefill | 514 ms | 463 ms | -9.92% |
| Decode throughput | 13.820 token/s | 14.042 token/s | +1.61% |
| Runtime total | 1,530 ms | 1,462 ms | -4.44% |
| Client total | 1,532.522 ms | 1,464.419 ms | -4.44% |
| Jetson unified RAM | 12,344.5 MB | 13,800 MB | +1,455.5 MB / +11.79% |
| CUDA main-model buffer | 1,834.83 MiB | 3,127.61 MiB | +1,292.78 MiB / +70.46% |
| GPU temperature | 55.312 C | 56.187 C | +0.875 C |
| VDD_GPU_SOC board rail | 9,177 mW | 9,938 mW | +761 mW / +8.29% |

For this one fixed synthetic image and short deterministic response, Q8 measured 4.44% lower median end-to-end Runtime latency while using about 1.46 GB more unified RAM and taking 38.99% longer to initialize. This small sequential experiment does not establish a general VLM speed or quality advantage. Q4 remains the deployment-first candidate for the current 32 GB target because its resource advantage is much larger than the measured latency difference.

## Telemetry detail

| Metric | Quantization | n | Median | p90 | Min | Max |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Unified RAM, MB | Q4 | 24 | 12,344.5 | 12,430 | 12,335 | 12,431 |
| Unified RAM, MB | Q8 | 23 | 13,800 | 13,881 | 13,718 | 13,886 |
| GPU temperature, C | Q4 | 24 | 55.312 | 55.562 | 54.500 | 55.656 |
| GPU temperature, C | Q8 | 23 | 56.187 | 56.687 | 55.500 | 56.718 |
| VDD_GPU_SOC, mW | Q4 | 24 | 9,177 | 9,556 | 8,412 | 9,560 |
| VDD_GPU_SOC, mW | Q8 | 23 | 9,938 | 10,320 | 9,556 | 10,320 |

Board rails are not summed and are not wall power. Unified RAM is not dedicated GPU memory. The runs were sequential in Q4-then-Q8 order rather than randomized/interleaved, and telemetry has only 23-24 one-second samples per quantization.

## Measurement boundary

The structured response explicitly marked `image_preprocess_ms`, `vision_encode_ms` and `image_embedding_ms` as `not_measured`. Their numeric zero placeholders are therefore excluded from reviewed results. Runtime logs contain upstream diagnostic lines for image encoding/decoding, but those lines are not yet bound to the structured per-request metrics contract and are not published as reviewed stage timings.

The synthetic fixture is an integration/performance input, not a quality dataset. Identical output across these runs proves deterministic behavior under this request only; it does not prove diagnosis correctness or Q4/Q8 quality equivalence.

## Artifact binding

| Artifact | Q4 SHA-256 | Q8 SHA-256 |
| --- | --- | --- |
| Raw JSONL | `249d3db05076040015467b78fa716dfb6d2fcdb1fd59bb1688ba4ad7a6841603` | `cb344c1dd993a985f39990aa2585005de6ee0dabc7ea430eddedfce7863a428b` |
| Environment | `84ed797245bd73fc8a7956d09123f4f20141eeff71f131861b424d23f089806d` | `c3f45b53e657c65520eb05fed4c0e3e0ed2fd7d03bac32f85b2b25feed9b19a1` |
| Runtime log | `0636250a59e8c9c25dbb27956b59dfea7a679b1318f45ad3ddbe82c589c566a9` | `9c7145909c0f8deab872fd124f5b729642ee1c01c5578f9ded1d579673d4fc47` |
| `tegrastats` | `6588b62e5575ff55cb205b2cdc83db6d28fa862206e77786e95dca6aad86801c` | `45b37d104fce01a58fbf3ae6e69baa574941e62ede6b887de14f35785bd85612` |

The shared Runtime executable hash is `19e9e86556fb4af74176e7e1bfd691c4847d3e89667a29fd32b41846038c7863`; the collector source hash is `6c9ecf8b481a98dfd5ab1d5ca524a43730ae1dbac8787652bbe8fcd2a4452f32`.

## Claim boundary

This comparison covers one fixed 320x192 synthetic image, one prompt and a short serial workload. It does not establish visual diagnosis accuracy, general image-resolution scaling, long-context behavior, production tail latency, long-run thermal stability, wall power, concurrency or a production SLA.
