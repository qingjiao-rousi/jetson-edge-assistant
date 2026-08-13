# OPT-1 Q4 text-only Prefix Reuse result

Status: **REVIEWED EXACT-PROMPT RESULT - CORRECTED BATCH-BOUNDARY POLICY**

This report compares disabled and `single_hot_text` modes for the real
Qwen2.5-VL `MtmdBackend` in clean commit `6f3a2a7`. It validates one 709-token
exact-prompt workload after correcting the rollback policy. OPT-1 remains in
progress until the branch and invalidation matrix also passes.

## Protocol

| Field | Value |
| --- | --- |
| Device | NVIDIA Jetson AGX Orin Developer Kit, aarch64 |
| L4T | R36.4.7 |
| Power mode | MODE_30W |
| Clocks | CPU 1.728 GHz and GPU 612 MHz fixed; EMC override enabled |
| Commit | `6f3a2a797b46a88cd30a7c0b7d3000158e1e0f96` |
| Upstream | `19cc26967140407efe34006a355ab445b35b16ac` |
| Main model | Qwen2.5-VL-3B-Instruct Q4_K_M, 37/37 layers offloaded |
| Model SHA-256 | `d02fe9b69ad8cadbbd228e387667af66612c44bed29ffc8eb1e7caf9ac486c12` |
| MMProj SHA-256 | `980c9b2f78c04e6cff93d277ada09e768394f112d75db3b4e9dea8a69f9fb904` |
| Prompt | 709 tokens; SHA-256 `1369f0b8fb891c2cd2a20e7d2bced7522761b3ddd955ec83e64e5c8fa22ae79f` |
| Output | deterministic; 22 tokens; `finish_reason=stop` |
| Samples | 1 warm-up excluded + 30 measured requests per mode |
| Runtime | context 8192, batch/ubatch 512, GPU layers 99, 8 threads |
| Session | fixed `benchmark-prefix-session` |

Both runs recorded a clean worktree, zero status entries and locked clocks.
All 60 measured requests returned HTTP 200 without a structured error. Each
mode produced one unique output, and the disabled and single-hot output text
was byte-identical.

## Corrected policy

The Runtime computes token LCP but only retains complete cold-prefill batches.
For this 709-token exact prompt it retains 512 KV positions and re-evaluates
the final 197 tokens. Re-evaluating the final cold batch preserves the batch
shape that produced the request logits.

| Cache metric | Disabled | Single-hot |
| --- | ---: | ---: |
| Hit tokens | 0 | 512 |
| Miss / prefill input tokens | 709 | 197 |
| Hit ratio | 0% | 72.21% |

## Results

Nearest-rank percentiles are reported. Percentage is
`(single-hot / disabled - 1) * 100`.

| Metric | Disabled median | Single-hot median | Change |
| --- | ---: | ---: | ---: |
| Prefill | 978 ms | 84 ms | -91.41% |
| TTFT | 1,330 ms | 439 ms | -66.99% |
| Runtime total | 2,793 ms | 1,901 ms | -31.94% |
| Client total | 2,796.160 ms | 1,903.896 ms | -31.91% |
| Decode | 1,811 ms | 1,813 ms | +0.11% |
| Decode throughput | 12.148 token/s | 12.135 token/s | -0.11% |

| Metric | Mode | n | p10 | Median | p90 | Min | Max |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Prefill, ms | disabled | 30 | 973 | 978 | 980 | 973 | 980 |
| Prefill, ms | single-hot | 30 | 78 | 84 | 84 | 78 | 85 |
| TTFT, ms | disabled | 30 | 1,328 | 1,330 | 1,335 | 1,328 | 1,336 |
| TTFT, ms | single-hot | 30 | 429 | 439 | 441 | 429 | 443 |
| Runtime total, ms | disabled | 30 | 2,788 | 2,793 | 2,797 | 2,787 | 2,798 |
| Runtime total, ms | single-hot | 30 | 1,896 | 1,901 | 1,902 | 1,896 | 1,904 |

Decode was effectively unchanged, which is consistent with an optimization
limited to prompt prefill and KV lifecycle. The overall latency reduction is
smaller than the prefill reduction because both modes generated the same 22
tokens.

## Telemetry boundary

Median Jetson unified RAM was 13,428 MB for disabled and 13,581 MB for
single-hot. These sequential short runs are not a controlled memory-overhead
or leak test; unified RAM includes the rest of the system. Board telemetry
rails are not wall power.

## Artifact binding

Raw artifacts remain local and Git-ignored.

| Artifact | Disabled SHA-256 | Single-hot SHA-256 |
| --- | --- | --- |
| JSONL | `eb4144a058771748263b584d76d43daeac20a565a9cc27fed25afb8a3d07ca7b` | `271d853183efdf3f2c278eb4a06d74f1396fcd377cfc6c738d542e6ee780c86a` |
| Environment | `55a081cb5bb08741573221dbce5f2bbb2a6ad44fcca6340c85dfedae4dec384e` | `1a50337e6bd63b2e174df067a0e6ffe2464aa8a634faff8edbbb50435d46c2be` |
| Runtime log | `7441927c409b3953752b29319a9f2b7180723491dac34f9a5fc5e39fc2610f92` | `fd8d5b71c8f476855edf825165b36082a11b9b506bbd14e3010cd7157b828bcc` |
| tegrastats | `ce45ca6bcfc52f3aca1702a8cf1032105096be0edea99f779404b9c494c9b7aa` | `a5b7bcec21dc255d9621a88a8fcfff49c81f3718a9c240d3e21906a2bc8088f9` |

The shared Runtime executable SHA-256 is
`66742733e8c30edc385caacd88d14e3835d83018ad49b56ed2db98b322cc821f`;
the collector source SHA-256 is
`04755e591a14e0f033a0f7692f7982573d55050ddb5fc4aded5a9e9a934ff500`.

## Superseded experiment

The earlier commit `ee0d6ea` re-evaluated only the final token of an exact
prompt. Its 22-token workload appeared correct, but a later 709-token run on
`df9c87c` produced 22 output tokens in disabled mode and 11 in hot mode. That
result was retracted and must not be cited as a gain. The failure established
that HTTP success and within-mode determinism are insufficient; cross-mode
output equivalence is a mandatory gate.

## Claim boundary

This result supports one serial, exact-prompt Q4 workload on one AGX Orin. It
does not yet establish branch-prefix correctness, session/image/cancel/timeout
invalidation on the real backend, RAG-session benefit, Q8 behavior, long-run
memory stability, concurrency, production caching, or a general latency SLA.
