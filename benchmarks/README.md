# Benchmarks

This directory contains the public measurement contract and reviewed summaries. Every summary must state whether it is provisional or final.

- Protocol: `docs/benchmark-protocol.md`
- Persistent Runtime HTTP collector: `scripts/run_jetson_benchmark.py` (shell wrapper: `.sh`)
- Empty result schema: `benchmarks/results-template.csv`
- Reviewed aggregate rows: `benchmarks/results-reviewed.csv`
- Final reviewed Q4 text summary: `benchmarks/q4-k-m-locked-20260812.md`
- Final reviewed paired Q4/Q8 text comparison: `benchmarks/q4-q8-paired-20260812.md`
- Final reviewed paired Q4/Q8 single-image end-to-end comparison: `benchmarks/q4-q8-image-paired-20260813.md`
- Final reviewed paired Q4/Q8 single-image stage-timing comparison: `benchmarks/q4-q8-image-stages-paired-20260813.md`
- Reviewed OPT-1 corrected 709-token exact-prompt result and retraction history: `benchmarks/opt1-q4-prefix-reuse-20260813.md`
- Reviewed OPT-1 exact/branch/invalidation correctness matrix: `benchmarks/opt1-t709-correctness-20260813.md`
- Reviewed-draft OPT-1 Q4 Runtime-length matrix: `benchmarks/opt1-q4-length-matrix-20260814.md`
- Reviewed OPT-1 Q4 paired 30-minute stability result: `benchmarks/opt1-q4-soak-20260817.md`
- OPT-1 status: `INTEGRATED` in `main`. Commit `c97a518` passed main Jetson dual-path correctness: `runtime-p264` is `PASS_EXPECTED_NO_REUSE` and `runtime-p1032` is `PASS_REUSE`, with session/image/timeout/cancel/reset invalidation gates passing. Git-ignored raw SHA-256 bindings: `main-opt1-correctness-p264.json` `63cc0fd25af3a36d246c5c8c6a68a1dff2b54a5e2d1828117826d83736c7458e`; `main-opt1-correctness-p1032.json` `5455240f93b3688c80443eecf5d51e527a88e18a464448d0181d26c08b83160b`.
- Raw local output: `benchmarks/results/` (Git-ignored)
- OPT-1 prompt generation/calibration: `scripts/generate_opt1_prompts.py` produces only tokenizer-level `user_prompt_tokens`; `scripts/calibrate_opt1_runtime_tokens.py` measures actual disabled HTTP `runtime_prompt_tokens` including chat template and emits `runtime-p*` labels.
- OPT-1 length matrix: `scripts/run_opt1_length_matrix.py --calibration ...`; audit each pair with `scripts/audit_opt1_matrix.py`. Warm-up is excluded from the required 30 rows.
- OPT-1 soak raw collection/audit: `scripts/run_opt1_soak.py`, `scripts/audit_opt1_soak.py`, and paired formal gate `scripts/audit_opt1_soak_pair.py`. The paired gate requires cross-mode deterministic output hashes as well as each mode's own audit; unified RAM is not proof of a KV leak.

Clean-commit Q4/Q8 locked-clock text, fixed single-image end-to-end, structured vision-stage summaries and the OPT-1 paired 30-minute serial soak are checked in with reviewed aggregate numbers and SHA-256 bindings to local Git-ignored evidence. VLM quality, 120-minute stability and production behavior remain pending. Board telemetry rails are not wall power.

The collector consumes a complete Assistant config, starts the matching `MtmdBackend` Runtime once, performs one warm-up plus measured HTTP requests, and stops the Runtime. Text mode uses the configured chat endpoint; `--image` uses the fixed single-image diagnosis endpoint and binds the repository fixture by SHA-256 without writing its base64 payload to raw results. It intentionally does not pass Qwen2.5-VL assets to the Qwen3-only DirectBackend runner.

For Prefix Reuse correctness rather than latency collection, use `scripts/validate_mtmd_prefix_reuse.py`. It reads the matching Runtime `batch_tokens`, emits exact/branch classifications (`PASS_EXPECTED_NO_REUSE` below the batch boundary or `PASS_REUSE` at/above it), and validates invalidation recovery; it is not a benchmark summary.

The single-hot text policy retains only complete cold-prefill batches. With the current 512-token batch/ubatch, an actual Runtime prompt below 512 has no safe reusable batch: zero hot hits are `PASS_EXPECTED_NO_REUSE` when all cold-path correctness gates pass. Such a row belongs in coverage/correctness reporting but is excluded from Prefix Reuse latency-gain statistics.

Integration remains bounded to one hot text-only session with the upstream `llama.cpp-omni` KV API and batch-boundary rollback. It is not multi-user caching, RAG/Agent session integration, image KV reuse, a production SLA, or evidence that there is no KV leak. A 120-minute soak, fault injection, real RAG LCP distribution and Agent/RAG mapping remain future work.
