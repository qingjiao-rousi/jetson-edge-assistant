# Contributing

EdgeOmni accepts narrowly scoped fixes that preserve its offline and evidence boundaries.

## Before opening a pull request

1. Read `docs/architecture.md`, `docs/limitations.md`, and `docs/release-checklist.md`.
2. Do not add model weights, generated SQLite indexes, private manuals, raw device logs, secrets, or machine-specific absolute paths.
3. Do not run, modify, or use the consumed R2.5 holdout for tuning. Candidate retrieval work must use a separate development set and must not change the default pipeline without a new preregistered evaluation.
4. Keep upstream and EdgeOmni attribution explicit. Changes around GGML/CUDA/mtmd must identify whether they are upstream configuration, an adapter, or original code.
5. Run `bash scripts/verify_public_repo.sh` and report any C++/Jetson checks separately.

Pull requests should state the behavior changed, model/hardware requirements, validation commands and outputs, evidence limitations, and whether public claims/docs need updating. A passing model-free CI job does not validate Jetson, CUDA, VLM quality, audio devices, or performance.
