# OPT-1 Q4 text-only Prefix Reuse preliminary result

Status: **REVIEWED PRELIMINARY RESULT - SHORT PROMPT ONLY**

This report compares the disabled and `single_hot_text` Runtime modes for the
experimental `MtmdBackend` Prefix Reuse implementation in commit `ee0d6ea`.
It is evidence for the Runtime mechanism, not a production SLA or a complete
OPT-1 validation.

## Protocol

| Field | Value |
| --- | --- |
| Device | NVIDIA Jetson AGX Orin Developer Kit, aarch64 |
| JetPack/L4T | R36.4.7 |
| Power mode | MODE_30W |
| Clocks | CPU/GPU fixed; EMC override enabled |
| Main model | Qwen2.5-VL-3B-Instruct Q4_K_M |
| Model SHA-256 | `d02fe9b69ad8cadbbd228e387667af66612c44bed29ffc8eb1e7caf9ac486c12` |
| MMProj SHA-256 | `980c9b2f78c04e6cff93d277ada09e768394f112d75db3b4e9dea8a69f9fb904` |
| Prompt | 22 tokens, SHA-256 `97b1201f13a6845c295938d6461b3d44041455da4e613d13e10b4633eaa8f16d` |
| Output | 128 tokens, deterministic seed 424242 |
| Samples | 1 warm-up excluded + 30 measured requests per mode |
| Runtime | context 8192, batch/ubatch 512, GPU layers 99, 8 threads |
| Session | fixed `benchmark-prefix-session` for text requests |

Both environment records report a clean worktree, zero status entries,
`clocks_locked=true`, HTTP 200 for all 30 measured requests, no structured
errors, `finish_reason=length`, and one unique output text per mode. The two
modes produced identical output text for this workload.

## Results

| Metric | Disabled median | Single-hot median | Observation |
| --- | ---: | ---: | --- |
| Cache hit tokens | 0 | 21 / 22 | Single-hot reused 95.45% of the prompt token prefix |
| Cache miss / prefill input tokens | 22 | 1 | Exact prompt re-evaluates the final token for logits |
| Prefill | 17 ms | 0 ms | Integer millisecond timer; hot value is below 1 ms or rounded to zero |
| TTFT | 112 ms | 78 ms | 34 ms lower in this short workload |
| Runtime total | 8,492 ms | 8,452 ms | Decode dominates the 128-token request |
| Decode throughput | 15.110 token/s | 15.146 token/s | Small difference; not the optimization target here |

The raw runs are:

- Disabled: `benchmarks/results/20260813T061133Z-opt1-q4-disabled-v2.jsonl`
- Single-hot: `benchmarks/results/20260813T061647Z-opt1-q4-single-hot-v2.jsonl`

Raw JSONL and telemetry remain local and Git-ignored. Their SHA-256 bindings
are recorded here for review:

| Artifact | SHA-256 |
| --- | --- |
| Disabled JSONL | `725b88f11796796a03d6c63e4be12eef95d1851237dc9596b40f621f3bb997c9` |
| Disabled tegrastats | `f5184c80b48c8c2a6f04f0b7c20b7169e2ca6e272c1515b3fa2634a2138639d7` |
| Single-hot JSONL | `aaa0d92f3dfaa1c38495cc9d52e9a374d9669a0c3b5ffacb0032d49a12800022` |
| Single-hot tegrastats | `ffbbe342a8af3169fddfdc41ab623338922ad76fb8931985c68c013e55f807f2` |

## Claim boundary

This result supports that the experimental Runtime path can reuse a single
text prompt prefix in a real Qwen2.5-VL `MtmdBackend` process under this exact
short-prompt workload. It does not yet prove long-context scaling, RAG-session
benefit, image safety invalidation, cancellation recovery, memory stability,
Q8 behavior, or production multi-user caching. Longer prompts (256/512/1024/
2048 tokens) and the full correctness matrix remain **待实测**.
