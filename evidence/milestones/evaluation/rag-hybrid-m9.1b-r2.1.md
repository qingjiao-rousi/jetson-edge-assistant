# M9.1B-R2.1 Fact-Evidence Gate: PARTIAL

R2.1 adds `fact-evidence-v1` without modifying the committed R1 or R2 baselines. It passed the unchanged full quality gate on the expanded 16-question calibration set and the expanded 16-question diagnostic/dev set. Both reports have Recall@1 `0.875`, Recall@3 `0.875`, MRR `0.875`, no-answer rejection `1.0`, and zero false positives.

The frozen calibration thresholds are nonzero: vector `0.60`, keyword coverage `0.10`, Top1-Top2 RRF margin `0.0005`, and fact evidence coverage `0.25`. Device IDs and fault codes are excluded from fact coverage. Missing evidence returns empty results/citations with `missing_fact_evidence`; the diagnostic report records the terms and matched terms for every decision.

The rebuilt SQLite index passed integrity checks and records `fact-evidence-v1`, the fact-gate configuration, and R2.1 fingerprint `464a66e85a8d40daeb7dc6ff19986ebb26523e5e71b416cbb312bca4024028fc`; see [index manifest](rag-hybrid-m9.1b-r2.1-index-manifest.json). The calibration and diagnostic artifacts are [calibration](rag-hybrid-m9.1b-r2.1-calibration.json) and [diagnostic](rag-hybrid-m9.1b-r2.1-diagnostic.json).

R2.1 is `PARTIAL` at milestone level because no independent holdout has been authorized or run. The evaluator now requires a separate authorization artifact derived from a calibrated artifact and gate-passing diagnostic before it can run a private external holdout once. Authorization records only private-holdout SHA-256, sample count, algorithm/retrieval/gate metadata, and source artifact hashes; it never writes question text. No quality gate was reduced, no answer generation or M9.2 work was added, and these R2.1 changes remain uncommitted pending review.
