# M9.1B-R2.1 Fact-Evidence Admission

R2.1 leaves committed R1 and R2 baselines unchanged. R2 continues to rank hard-constrained candidates with RRF. R2.1 separately derives deterministic fact terms from the query after removing parsed device IDs and fault codes; those identifiers cannot increase fact coverage.

The gate checks the selected candidate's original chunk body, not only structured metadata. English informative terms and the existing offline Chinese CJK bigrams are supported. If fact coverage or term count is below the configured threshold, the query returns `answerable=false`, empty `results` and `citations`, and `missing_fact_evidence` in the admission record.

`fact-evidence-v1`, the fact-gate configuration, and an R2.1 index fingerprint are persisted in SQLite metadata. An index without the algorithm version is rejected. Calibration enumerates only nonzero vector, fact-evidence, and margin thresholds and checks the unchanged complete M9.1B quality gate.

Holdout is a two-phase, explicitly authorized protocol. `authorize-holdout` accepts a calibrated artifact, a gate-passing diagnostic artifact, and a private holdout at any filesystem path. It rejects changed milestone, algorithm, embedding fingerprint, retrieval parameters, quality gate, overlapping IDs, and an existing authorization output. The authorization records only SHA-256, question count, algorithm/retrieval/gate metadata, and source-artifact hashes; it never records private question text.

`holdout` requires that authorization, recalculates the private holdout SHA-256 and question count, then consumes the authorization before evaluation. It rejects a consumed authorization and any existing result output, so neither the same authorization nor the same output can be retried or overwritten. Holdout has no calibration loop, retry path, or parameter mutation.

The R2.1 fixtures expand both calibration and diagnostic negatives for missing device facts, similar operations on another device, unsupported device/fault meanings, missing relations, and Chinese facts. Authorization tests use only temporary private data, never a repository holdout. R2.1 remains uncommitted pending review.
