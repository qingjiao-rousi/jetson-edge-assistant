# R2.6 Candidate: Keyword Coverage Final Gate

R2.5 remains frozen and PARTIAL. Its public holdout summary reports that
no-answer correct rejection did not meet the target; this is not a recall
failure. The private holdout questions and raw outputs are unavailable here,
so the specific failures cannot be identified or inferred.

R2.6 is an unvalidated, isolated candidate. Its only algorithm difference is
to restore the existing `minimum_keyword_coverage` admission comparison after
the frozen R2.5 query-time gate passes. It preserves the R2.2 SQLite index
contract, R2 base ranking, R2.5 thresholds, fact-family gate, and response
shape. `fact_evidence.minimum_terms` remains retained configuration metadata;
R2.6 does not claim to consume it.

This candidate must not replace R2.5, enter `active_pipeline.py`, or run on
the consumed R2.5 holdout. It is not production-ready and has not passed any
new quality gate.

## Frozen Validation Protocol

R2.6 code, thresholds, embedding contract, index contract, and candidate
configuration are frozen before `rag-m9.1b-r2.6-dev-v1` is evaluated. The dev
set compares frozen R2.5 and frozen R2.6 only; its result cannot authorize any
R2.6 retuning. R2.6 may enter a new independent holdout only when all of these
pre-registered conditions hold on that dev set:

- no-answer correct rejection rate is not lower than the R2.5 dev baseline;
- false positive count is not higher than the R2.5 dev baseline;
- Recall@3 is at least 0.875;
- the per-question report has no unexplained device or fault-code mismatch.

If any condition fails, R2.6 is `REJECTED/UNVALIDATED`, R2.5 remains PARTIAL,
and RAG algorithm development stops. If all conditions hold, a new 8-12
question independent mini holdout may be created only after this freeze. At
least half of that holdout must be no-answer; it must remain in an ignored
private evidence path, record its SHA-256, creation time, authorization, and
algorithm/config fingerprints before one execution, and be marked consumed
afterward. Public material may report only its hash, execution time, summary
metrics, and conclusion. No R2.6 change is allowed after either dev or the new
holdout, regardless of outcome; only a passing new holdout could support a
future proposal to replace the default path.
