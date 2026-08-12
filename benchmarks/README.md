# Benchmarks

This directory contains the public measurement contract and reviewed summaries. Every summary must state whether it is provisional or final.

- Protocol: `docs/benchmark-protocol.md`
- Persistent Runtime HTTP collector: `scripts/run_jetson_benchmark.py` (shell wrapper: `.sh`)
- Empty reviewed-result schema: `benchmarks/results-template.csv`
- Provisional reviewed Q4 summary: `benchmarks/q4-k-m-locked-20260812.md`
- Raw local output: `benchmarks/results/` (Git-ignored)

A provisional Q4 locked-clock text summary is checked in. It contains reviewed aggregate numbers and SHA-256 bindings to local Git-ignored evidence, but it was built from a dirty worktree and is not a final reproducibility baseline. A clean-commit Q4 repeat, Q8 comparison, VLM latency, and stability results remain pending. Board telemetry rails are not wall power.

The collector consumes a complete Assistant config, starts the matching `MtmdBackend` Runtime once, performs one warm-up plus measured HTTP requests, and stops the Runtime. It intentionally does not pass Qwen2.5-VL assets to the Qwen3-only DirectBackend runner.
