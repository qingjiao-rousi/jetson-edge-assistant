# M9.1B-R2 Retrieval Method Correction

R1 is preserved by commit `ec92a2b` and remains `PARTIAL`. Its former final set (`tests/fixtures/rag-m9.1b/evaluation-set.json`) was inspected during failure analysis, so R2 treats it only as a diagnostic/dev dataset. It is not an independent final set and must not be relabeled or overwritten.

R2 retains the audited `Qwen3-Embedding-0.6B Q8_0` asset. Each indexed embedding has the stable input format `Document`, `Device`, `Section`, and `Content`; `structured-v1` is in index metadata alongside the embedding fingerprint. The FTS body contains those same fields and an explicit offline Unicode CJK bigram expansion (`unicode61-cjk-bigram-v1`). Index construction probes SQLite FTS5 `unicode61` with Chinese text and fails closed if unavailable.

Queries parse known device IDs and fault codes. A stated device limits documents before vector or keyword ranking. A stated fault code further limits chunks to that device's matching code. Thus `CT-4 + E42` returns no candidate when CT-4 has no E42, rather than an E42 result from AX-17 or BX-9.

RRF combines vector and BM25 ranks only for candidate ordering. Admission is independent: the candidate must satisfy its vector, informative-keyword coverage, and Top1-Top2 RRF margin thresholds after hard constraints. Ranking score is never treated as answer confidence.

Calibration enumerates only R2 admission-gate candidates and applies the complete unchanged R1 quality gate to every candidate. If none pass, the artifact status is `CALIBRATION_FAILED`; it has no retrieval parameters and cannot authorize a holdout run. This explicitly prevents the R1 failure mode of selecting a weak objective and continuing to final evaluation.

`tests/fixtures/rag-m9.1b-r2/holdout-set.json` is the new holdout. Its SHA-256 is recorded in `docs/evaluation/rag-hybrid-m9.1b-r2-holdout-manifest.json` before the first run. It must be executed exactly once only after a `CALIBRATED` artifact has frozen an R2 algorithm. This change does not run it.
