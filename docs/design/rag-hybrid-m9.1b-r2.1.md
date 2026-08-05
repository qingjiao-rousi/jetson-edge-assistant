# M9.1B-R2.1 Fact-Evidence Admission

R2.1 leaves committed R1 and R2 baselines unchanged. R2 continues to rank hard-constrained candidates with RRF. R2.1 separately derives deterministic fact terms from the query after removing parsed device IDs and fault codes; those identifiers cannot increase fact coverage.

The gate checks the selected candidate's original chunk body, not only structured metadata. English informative terms and the existing offline Chinese CJK bigrams are supported. If fact coverage or term count is below the configured threshold, the query returns `answerable=false`, empty `results` and `citations`, and `missing_fact_evidence` in the admission record.

`fact-evidence-v1`, the fact-gate configuration, and an R2.1 index fingerprint are persisted in SQLite metadata. An index without the algorithm version is rejected. Calibration enumerates only nonzero vector, fact-evidence, and margin thresholds and checks the unchanged complete M9.1B quality gate. Diagnostic is development-only; this R2.1 evaluator intentionally exposes no holdout phase.

The R2.1 fixtures expand both calibration and diagnostic negatives for missing device facts, similar operations on another device, unsupported device/fault meanings, missing relations, and Chinese facts. R2.1 remains uncommitted pending review, and it must not run the frozen holdout.
