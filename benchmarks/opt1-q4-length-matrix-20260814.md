# OPT-1 Q4 Runtime-length matrix — reviewed draft

Status: **REVIEWED DRAFT — PASS_WITH_BATCH_BOUNDARY_LIMITATION**

This draft reviews four locked-clock Jetson Q4 raw pairs collected on clean
commit `eb061513b868362c4352064ae7935ca8a5cb69ed`. It is a Runtime-level
single-hot, text-only result. Low-level KV memory and APIs remain provided by
`llama.cpp-omni`.

## Protocol and audit scope

The source tokenizer lengths were 256/512/1024/2048, but the matrix axis below
uses actual disabled HTTP `runtime_prompt_tokens`, which include the chat
template: 264/520/1032/2056. Every mode had one excluded warm-up followed by
30 measured requests, fixed deterministic sampling and the same prompt SHA-256
within each pair. The environment artifacts recorded a clean worktree and
locked clocks; their paired Runtime logs report `n_batch=512` and `n_ubatch=512`.

The audit checked every measured row for HTTP 200, null error, byte-identical
paired output, equal prompt/output tokens and finish reason, disabled zero hit,
and hot cache accounting. It classified the full matrix as
`PASS_WITH_BATCH_BOUNDARY_LIMITATION`.

## Classification

| Runtime prompt tokens | Batch | Classification | Single-hot hit / miss | Latency-gain statistic? |
| ---: | ---: | --- | --- | --- |
| 264 | 512 | PASS_EXPECTED_NO_REUSE | 0 / 264, 30/30 | No |
| 520 | 512 | PASS_REUSE | 512 / 8, 30/30 | Yes |
| 1032 | 512 | PASS_REUSE | 1024 / 8, 30/30 | Yes |
| 2056 | 512 | PASS_REUSE | 2048 / 8, 30/30 | Yes |

The 264-token row validates the cold path and paired correctness only. It has
no complete 512-token cold-prefill batch to retain, so zero hits are expected
under the batch-aligned rollback policy. It is not a Prefix Reuse speedup and
is excluded from reuse latency statistics. This policy must not be weakened by
reintroducing non-batch-aligned rollback, which previously produced cross-mode
output differences.

## Eligible-length median results

Percentage is `(single-hot / disabled - 1) * 100`; medians use 30 measured
requests per mode.

| Runtime tokens | Prefill disabled → hot | TTFT disabled → hot | Runtime total disabled → hot |
| ---: | --- | --- | --- |
| 520 | 929 → 32 ms (-96.56%) | 1105 → 209 ms (-81.09%) | 2761 → 1867.5 ms (-32.36%) |
| 1032 | 1832 → 32 ms (-98.25%) | 2008 → 210 ms (-89.54%) | 2812 → 1016 ms (-63.87%) |
| 2056 | 3682 → 33 ms (-99.10%) | 3860 → 211 ms (-94.53%) | 4669 → 1022 ms (-78.11%) |

Decode throughput remained a constraint metric rather than a claimed decode
optimization: median disabled/hot token/s was 13.654/13.631, 12.245/12.226,
and 12.183/12.158 for 520/1032/2056 respectively.

## Raw binding

| Runtime tokens | Disabled JSONL SHA-256 | Single-hot JSONL SHA-256 |
| ---: | --- | --- |
| 264 | `8978b1430603fd4cf7df9b14ab785a82e966393f03a9b06ee726edfc0ddaf9bd` | `b1e14a0ac34f16c614e9f5db1e105391090a2312f7512e6d1325627062c2317d` |
| 520 | `9956f22ace1a5e5145acdde4f769a76c75e8f7ad4c8196c82bac0535ea4e6486` | `76e48f9068a35ae0f92613957a9ce598496957869c99a4e7db371b40a2e93670` |
| 1032 | `9849baad9bc2cc599cc762a1e912d494e0ddf40e6765f5fdf068c896c7d3b4b0` | `77599978da3f627298e2c4add359ce6a9aa8964dff07296a4810b2fd97750cb2` |
| 2056 | `48fbf42cc385730fd9822820f9591ed0d5ac13f30d4aca3af2b9a9a0a78cd5f3` | `351155bb5efcef3ab3da07325e612fb5facb02b5d23e083bc6e472eac21b264e` |

## Boundaries

This validates one serial Q4 workload family on one AGX Orin, including the
512-token batch-boundary limitation. It does not validate multi-user caching,
RAG/Agent session integration, image KV reuse, Q8 behavior, concurrency,
general prompt distributions, production caching or an SLA. Long-run RAM and
error-rate soak evidence is still pending; OPT-1 remains **IN_PROGRESS**.
