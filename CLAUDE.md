# EdgeOmni repository guidance

This file provides repository context for coding assistants. Public capability claims must follow `README.md`, `docs/architecture.md`, `docs/jetson-validation.md`, and `docs/limitations.md`.

## Project identity

- Project: EdgeOmni, a Jetson AGX Orin offline industrial knowledge-assistant prototype.
- Runtime: C++ adaptation built on a pinned `llama.cpp-omni` submodule.
- Application: local SQLite/FTS5 hybrid RAG, citation/refusal gates, bounded read-only Agent, terminal/JSONL and experimental half-duplex audio adapters.
- VLM scope: one image per request; no video, multi-image batching, or visual-quality claim.
- KV scope: one hot text session using Token LCP Prefix reuse; no production multi-user cache.
- RAG status: M9.1B R2.5 is PARTIAL. Its consumed holdout must not be rerun, modified, or used for tuning.
- Production scope: Docker/systemd, authentication, high concurrency, long soak, AEC/interruption and full duplex are not completed.

## Ownership boundary

EdgeOmni owns the code in `runtime/`, `app/`, its configs, launchers, validation contracts and tests. The pinned upstream provides GGUF/GGML, CUDA kernels/backend, model loading, tokenizer/sampler and `mtmd`. Do not describe upstream capabilities as original EdgeOmni work, and do not modify `third_party/llama.cpp-omni` from this repository.

Read [architecture](docs/architecture.md) before changing boundaries, [offline setup](docs/jetson-offline-setup.md) before changing build/assets, and [release checklist](docs/release-checklist.md) before public claims.

## Repository layout

```text
runtime/       C++ backend adapters, service, contracts and tests
app/           retrieval, QA, Agent, Assistant, UI and audio adapters
configs/       top-level and module contracts with relative asset paths
knowledge/     synthetic test manuals, not real operating instructions
tests/         model-free unit/integration tests and fixed fixtures
scripts/       thin launchers and read-only verification/benchmark entry points
benchmarks/    protocol and empty reviewed-result schema
docs/          current public architecture, validation and limitations
third_party/   pinned upstream git submodule
```

`archive/`, `evidence/`, generated indexes, build trees and models are local/ignored material and must not be required by clean-clone checks or linked as public evidence.

## Engineering rules

1. Inspect upstream headers/source before using an API; do not guess signatures.
2. Keep the upstream adapter boundary explicit and cite upstream file/commit when attribution matters.
3. Use repository-relative config paths. Reject absolute paths and traversal rather than normalizing them silently.
4. Do not download models, rebuild indexes, consume frozen holdouts, or access audio hardware in routine tests.
5. Any performance, memory, power, CUDA, VLM-quality or stability claim needs an actual Jetson record. Otherwise write “待实测” or “不足以证明”.
6. Do not add GGUF, generated SQLite, raw benchmark/audio logs, private manuals/evidence, secrets or machine-specific paths.
7. The default retrieval entry point is `app/retrieval/active_pipeline.py`. Candidate retrieval work must remain separate and must not imply a passed gate.
8. Preserve existing user changes. In particular, publish an importer and a newly added imported module in the same atomic change.
9. Before completing a model-free change, run `bash scripts/verify_public_repo.sh`. Report CTest pass/skip separately when C++ build assets are available.

## Public claim hierarchy

If documents conflict, use this order: current source/tests and Git state, then `README.md`, `docs/architecture.md`, `docs/jetson-validation.md`, `docs/limitations.md`, and finally archived/ignored records. Never upgrade a frozen summary into numeric or production claims without publishable evidence.
