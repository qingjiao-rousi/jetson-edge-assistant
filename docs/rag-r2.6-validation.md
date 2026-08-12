# R2.6 Candidate Validation Record

Date: 2026-08-07

## Frozen Inputs

- Candidate module SHA-256: `2294c33cca9972208b4dc4a6577b0f8b97c451958ffe99e19a3139a1834f3beb`
- Candidate config SHA-256: `9840155b568eec9090c191be978f8ce2d26ce8640341b3dcd1faab00aadfbff4`
- R2.5 base algorithm fingerprint: `0d84afa229f49d779059ea83d658b768ba91063832377d651702d8d330575df2`
- R2.6 dev dataset SHA-256: `23a4db90cc08646479250453b3d479065451d7cd443662208625f6711d34b696`
- Read-only R2.2 SQLite SHA-256: `1f7e7e17e7854ff5dc27291030da959e9becca1a0857729dfdca0582c68fa18e`

The independent dev set contains 14 manually authored questions based only on
the current AX-17, BX-9, and CT-4 manuals: 7 answerable and 7 no-answer. The
no-answer categories cover missing device attributes, missing numeric alarm
attributes, concept/attribute mismatches, an unlisted maintenance requirement,
a device/fault-code mismatch, and generic terminology without a cited fact.
It does not copy R2.5 fixture questions or consume the R2.5 private holdout.

## Execution Record

The read-only dry run completed and validated the dataset, R2.5/R2.6 frozen
contracts, embedding configuration, and R2.2 SQLite metadata without loading
the embedding model. One real dev comparison was then invoked with:

```bash
python3 tests/evaluation/rag_r2_6_compare.py
```

That execution is `INVALID_EXECUTION`: it ended without producing the
evaluator's required structured JSON, so it is not a valid dev evaluation and
does not consume the allowed recovery dev run. No embedding process remained
and no model, SQLite, or knowledge-base file was modified. The evaluator was
then repaired to emit staged JSON errors and to support an explicit provider
preflight before at most one recovery dev run.

The repaired provider preflight then completed successfully with one local
query embedding (dimension 1024). The one permitted recovery dev run completed
on 2026-08-07 with `EVALUATED_ONCE` and the same frozen input hashes above:

| Metric | Frozen R2.5 baseline | Frozen R2.6 candidate |
| --- | ---: | ---: |
| Recall@1 | 0.7142857142857143 | 0.5714285714285714 |
| Recall@3 | 0.7142857142857143 | 0.5714285714285714 |
| MRR | 0.7142857142857143 | 0.5714285714285714 |
| No-answer correct rejection rate | 0.8571428571428571 | 0.8571428571428571 |
| False positive count | 1 | 1 |
| Device or fault mismatch count | 0 | 0 |

R2.6 satisfies the relative no-answer, false-positive, and mismatch checks,
but fails the pre-registered `Recall@3 >= 0.875` condition. It is therefore
`REJECTED/UNVALIDATED`, is not eligible for a new holdout, and the recovery
dev-run allowance is consumed. This result does not authorize R2.6 tuning,
another dev run, a holdout, or a default-path change.

## Conclusion

R2.6 is `REJECTED/UNVALIDATED` by the frozen dev protocol. No new holdout was
created or executed. R2.5 remains frozen and PARTIAL, and the default
`active_pipeline.py` remains on R2.5. RAG algorithm development is stopped:
the sole recovery dev run has been consumed and may not be followed by R2.6
retuning or another dev run.
