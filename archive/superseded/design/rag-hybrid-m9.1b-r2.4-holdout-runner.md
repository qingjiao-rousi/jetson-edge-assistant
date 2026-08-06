# M9.1B-R2.4 One-Time Holdout Runner

R2.4 holdout must be external to this repository and must be new, private, and never previously executed. The runner validates the frozen milestone, algorithm fingerprint `31aae901b2b39fb53b2b0cf5cfbbfda2fa95550abda6ebc4f1edc914dbe50c86`, embedding fingerprint, retrieval parameters, quality gate, calibration/diagnostic success, IDs, and SHA-256. Authorization and result files are exclusive; authorization is consumed before execution.

After the project owner has placed a new private holdout outside the repository, authorize it once:

```bash
python3 scripts/evaluate_rag_hybrid_m9_1b_r2_4_holdout.py \
  --phase authorize-holdout \
  --calibration docs/evaluation/rag-hybrid-m9.1b-r2.4-calibration.json \
  --diagnostic docs/evaluation/rag-hybrid-m9.1b-r2.4-diagnostic.json \
  --holdout /absolute/private/new-r2.4-holdout.json \
  --output /absolute/private/new-r2.4-holdout.authorization.json
```

Then execute exactly once:

```bash
python3 scripts/evaluate_rag_hybrid_m9_1b_r2_4_holdout.py \
  --phase holdout \
  --database generated/rag-m9.1b-r2.2/hybrid.sqlite3 \
  --holdout /absolute/private/new-r2.4-holdout.json \
  --authorization /absolute/private/new-r2.4-holdout.authorization.json \
  --output /absolute/private/new-r2.4-holdout.result.json
```

Do not run either command against an old R2.1 holdout or an existing authorization/result file.
