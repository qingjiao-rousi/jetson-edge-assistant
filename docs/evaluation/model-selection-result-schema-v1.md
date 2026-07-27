# 第一轮模型比较结果 Schema（v1）

本 schema 适用于 `scripts/benchmark_model_selection.py` 生成的第一轮 CLI 比较。目录在 Git 忽略的 `benchmark-results/model-selection/<run_id>/`；不得将原始回答、模型文件或 telemetry 提交到 Git。

```text
<run_id>/
  config.json                 # 固定输入、hash、执行参数与 provenance
  validation.json             # 启动门禁结果
  runs.jsonl                  # 每次 preconditioning / measured 尝试一条记录
  blind-review.jsonl          # 不含 candidate/model 名的人工评分输入
  blind-review-map.json       # response_id 到内部执行记录的映射，单独保管
  candidates/<candidate_id>/
    preconditioning/attempt-01/{command.json,stdout.log,stderr.log,tegrastats.log}
    <prompt_id>/attempt-01/{command.json,stdout.log,stderr.log,tegrastats.log}
```

## `runs.jsonl`

每行是一次独立 `llama-cli` 进程，至少包含 `run_id`、`candidate_id`、`prompt_id`、`phase`、`attempt`、`valid`、`exit_code`、项目/Runtime/CLI/模型/脚本/配置 hash、实际 `offload_matches` 与 `offload_all_layers`、`response_text`、`response_sha256`、`output_complete`、Qwen3 thinking 字段、自动检查结果、llama.cpp timing、`wall_time_ms` 和 telemetry 峰值。

`wall_time_ms` 是进程从启动到退出的墙钟时间，不是 TTFT 或 TPOT。第一轮不写入真实 TTFT、TPOT、服务端 Prefill 或服务端 Decode 指标；`runtime_prompt_*` 与 `runtime_decode_*` 仅来自 llama.cpp 自报 timing。

`valid` 只表示 Runtime 工程门禁成功：退出码 0、完整非空回答、无 CUDA/OOM/GGUF/tokenizer/template 错误且 `X/Y` 全层 offload。JSON、exact-READY、四步格式和疑似截断是质量自动检查，不改变该工程有效性。

## `blind-review.jsonl`

此文件不含 `candidate_id`、模型路径或模型名。每行仅含 `response_id`、`prompt_id`、回答、回答 SHA-256，以及 `scorer_a`、`scorer_b`、`disagreement`、`final_score`、`notes` 的空评分字段。评分者先独立填写，之后才允许用单独保管的 `blind-review-map.json` 关联模型。
