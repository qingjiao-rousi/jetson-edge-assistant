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
- Retracted OPT-1 short-prompt experiment and correction rationale: `benchmarks/opt1-q4-prefix-reuse-20260813.md`
- Raw local output: `benchmarks/results/` (Git-ignored)

Clean-commit Q4/Q8 locked-clock text, fixed single-image end-to-end and structured vision-stage summaries are checked in with reviewed aggregate numbers and SHA-256 bindings to local Git-ignored evidence. VLM quality and stability results remain pending. Board telemetry rails are not wall power.

The collector consumes a complete Assistant config, starts the matching `MtmdBackend` Runtime once, performs one warm-up plus measured HTTP requests, and stops the Runtime. Text mode uses the configured chat endpoint; `--image` uses the fixed single-image diagnosis endpoint and binds the repository fixture by SHA-256 without writing its base64 payload to raw results. It intentionally does not pass Qwen2.5-VL assets to the Qwen3-only DirectBackend runner.
