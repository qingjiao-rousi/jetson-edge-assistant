# M9.1B-R2.5 Evaluation

Status: `DONE` for calibration and diagnostic development gates. No holdout was created, read, or run.

The selected calibrated parameters are vector threshold `0.4`, fact-family coverage `0.25`, and nonzero margin `0.0001`. The algorithm fingerprint is recorded in the machine-readable artifacts.

| Dataset | Recall@1 | Recall@3 | MRR | No-answer rejection | False positives | Gate |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Calibration | 0.875 | 0.875 | 0.875 | 1.0 | 0 | PASS |
| Diagnostic | 0.875 | 0.875 | 0.875 | 1.0 | 0 | PASS |

Per-question evidence, candidate-grid results, frozen parameters, dataset hashes, embedding fingerprint, and admission reasons are in `rag-hybrid-m9.1b-r2.5-calibration.json` and `rag-hybrid-m9.1b-r2.5-diagnostic.json`.
