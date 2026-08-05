# M9.1B-R2.5 One-Time Holdout Runner

The R2.5 runner is for a new private holdout only. It validates the frozen milestone, algorithm fingerprint `0d84afa229f49d779059ea83d658b768ba91063832377d651702d8d330575df2`, embedding fingerprint, retrieval settings, frozen quality gate, and public R2.2 SQLite metadata contract. Authorization checks calibrated calibration and DONE diagnostic artifacts, holdout-ID disjointness, holdout SHA-256, and writes no question text into the authorization file.

Both authorization and result paths are create-only. Execution rehashes the private holdout, verifies the SQLite metadata, atomically consumes authorization before retrieval, and does not retry or alter parameters. Do not use it with any previously consumed holdout.

Private holdout JSON format:

```json
{"questions":[{"id":"unique-blind-id","query":"private question","expected_chunk_id":"DOCUMENT-ID#section-or-null"}]}
```

After the project owner creates a new private file outside this repository:

```bash
python3 scripts/evaluate_rag_hybrid_m9_1b_r2_5_holdout.py --phase authorize-holdout \
  --calibration docs/evaluation/rag-hybrid-m9.1b-r2.5-calibration.json \
  --diagnostic docs/evaluation/rag-hybrid-m9.1b-r2.5-diagnostic.json \
  --holdout /absolute/private/new-r2.5-holdout.json \
  --output /absolute/private/new-r2.5-holdout.authorization.json

python3 scripts/evaluate_rag_hybrid_m9_1b_r2_5_holdout.py --phase holdout \
  --database generated/rag-m9.1b-r2.2/hybrid.sqlite3 \
  --holdout /absolute/private/new-r2.5-holdout.json \
  --authorization /absolute/private/new-r2.5-holdout.authorization.json \
  --output /absolute/private/new-r2.5-holdout.result.json
```
