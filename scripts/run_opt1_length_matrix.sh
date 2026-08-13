#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
out=${1:-benchmarks/results/opt1-length}
for n in 256 512 1024 2048; do
  python3 "$root/scripts/run_jetson_benchmark.py" --config "$root/configs/assistant.json" --label "opt1-p${n}-disabled" --output "$out" --repeats 30 --max-new-tokens 128 --prompt-file "/tmp/edgeomni-opt1/prompts/p${n}.txt" --tegrastats /usr/bin/tegrastats
  python3 "$root/scripts/run_jetson_benchmark.py" --config "$root/configs/assistant-prefix-single-hot.json" --label "opt1-p${n}-single-hot" --output "$out" --repeats 30 --max-new-tokens 128 --prompt-file "/tmp/edgeomni-opt1/prompts/p${n}.txt" --tegrastats /usr/bin/tegrastats
done
