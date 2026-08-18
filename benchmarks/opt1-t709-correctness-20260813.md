# OPT-1 MtmdBackend Prefix Reuse correctness matrix

Status: **REVIEWED JETSON CORRECTNESS RESULT**

This report records a passing correctness matrix for the real Qwen2.5-VL
`MtmdBackend` Prefix Reuse experiment. It is a functional gate, not a latency
benchmark and does not replace the 30-sample exact-prompt measurement in
`opt1-q4-prefix-reuse-20260813.md`.

## Protocol

| Field | Value |
| --- | --- |
| Device | NVIDIA Jetson AGX Orin Developer Kit, aarch64 |
| L4T | R36.4.7 |
| Power mode | MODE_30W |
| Clocks | CPU 1.728 GHz and GPU 612 MHz fixed; EMC override enabled |
| Commit | `5ffcaccde24e0a68f9a23998a3fb8f5ae0cd7aa8` |
| Upstream | `19cc26967140407efe34006a355ab445b35b16ac` |
| Main model | Qwen2.5-VL-3B-Instruct Q4_K_M, 37/37 layers offloaded |
| Model SHA-256 | `d02fe9b69ad8cadbbd228e387667af66612c44bed29ffc8eb1e7caf9ac486c12` |
| MMProj SHA-256 | `980c9b2f78c04e6cff93d277ada09e768394f112d75db3b4e9dea8a69f9fb904` |
| Disabled config SHA-256 | `029148731678d5c3b47bd63750b5dbc572e4b80999411fbfbdd42252ac8a1bfd` |
| Single-hot config SHA-256 | `7d9e215d60a67589fdd409fe94776d76c0640d61900c88fb2a7b901e7203398a` |
| Validator SHA-256 | `d86eb614133a36c138dbef8b26f7ec36593e588419e6a929bb75079f560f0967` |
| Exact prompt | 709 tokens; SHA-256 `1369f0b8fb891c2cd2a20e7d2bced7522761b3ddd955ec83e64e5c8fa22ae79f` |
| Branch prompt | 720 tokens; SHA-256 `89d79b924ab6e5b639f4e46c11b580c89712a613f625b0349ee884af67b0feb1` |

The validator starts isolated disabled and `single_hot_text` Runtime
processes. The final JSON report is local, Git-ignored raw evidence with
SHA-256 `558f210ce4d21893e17e8a429eb299310ec3d8c3dd658a54ef31e8b2856fbe68`.

## Result

All 15 checks passed.

| Gate | Result | Observed evidence |
| --- | --- | --- |
| Warm text request | PASS | Hot Runtime accepted the seed request. |
| Exact-prefix output | PASS | Hot output matched the isolated disabled output. |
| Exact cache accounting | PASS | 512 hit + 197 miss = 709 prompt tokens (72.21% hit ratio). |
| Branch-prefix output | PASS | Hot branch output matched its isolated disabled output. |
| Branch cache accounting | PASS | 512 hit + 208 miss = 720 prompt tokens (71.11% hit ratio). |
| Session switch | PASS | Next request cold; reason `session_id_changed`. |
| Image request and follow-up | PASS | Image succeeded; following text request had zero hit tokens. |
| Timeout and follow-up | PASS | Timeout returned HTTP 408; following text request had zero hit tokens. |
| HTTP cancel and follow-up | PASS | Cancelled request returned HTTP 499; following text request had zero hit tokens. |
| Context reset and follow-up | PASS | Reset returned `{"reset":true}`; following text request had zero hit tokens. |

The exact and branch cases are deterministic for this fixed sampling setup:
the exact cold/hot output had 22 tokens and the branch cold/hot output had 10
tokens, both ending with `finish_reason=stop`.

## Claim boundary

This validates EdgeOmni's Runtime-level token LCP, batch-boundary rollback,
single-hot lifecycle, and the listed invalidation behaviors on one Q4 Jetson
configuration. KV memory storage and low-level APIs remain provided by
`llama.cpp-omni`.

It does not validate a multi-user cache, RAG/Agent session integration, image
KV reuse, Q8 behavior, arbitrary prompt distributions, long-run RAM stability,
concurrency, production failure handling, or a latency SLA. The report also
does not include a persistent Runtime log hash, so the raw JSON/config/script
hashes bind this correctness result but are not a full runtime-log provenance
bundle.
