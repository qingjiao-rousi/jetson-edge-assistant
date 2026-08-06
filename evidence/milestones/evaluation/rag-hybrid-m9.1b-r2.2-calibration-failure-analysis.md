# M9.1B-R2.2 Calibration Failure Analysis

All 18 candidates fail the frozen quality gate. The closest group is vector `0.60`, fact coverage `0.25/0.50/1.00`, margin `0.0005`: Recall@1/3 and MRR are each `0.75`, while rejection is `1.0` and false positives are `0`. The machine-readable matrix and per-question evidence are in [the JSON analysis](rag-hybrid-m9.1b-r2.2-calibration-failure-analysis.json).

The fact-family threshold is not the discriminator: positive candidates all have coverage `1.0`, and all three fact thresholds produce identical metrics. The English maintenance case succeeds. The Chinese maintenance case has family evidence but the expected section is only raw rank 2, which is an RRF ranking/Chinese concept routing issue. Pressure and cavitation have valid fact evidence but are rejected by margin; cavitation also has zero keyword coverage. Generic hydraulic/pump negatives correctly reject through `missing_fact_family_evidence`; ordinary-word false admission is not present in this calibration run.

Classification: the margin failures expose a calibration-grid defect because the smallest tested margin (`0.0005`) exceeds observed valid margins (`0.00025602` and `0.00026441`). Chinese maintenance is primarily RRF ranking plus Chinese concept routing, not fact-family absence. Cavitation is a combined alias/keyword-coverage issue. The current result provides no evidence of a quality-set annotation defect.

R2.3 hypotheses, not implemented:

1. Expand the calibration grid below `0.0005`, independently testing margin `0` and values around the observed valid margins while retaining the full gate.
2. Add concept-level retrieval features for Chinese maintenance terms so the maintenance section receives a rank signal beyond the Chinese operator note; test this against independent cross-section examples.
3. Make concept-family evidence feed a separately normalized candidate feature, then test whether cavitation aliases can improve keyword coverage without admitting generic hydraulic/pump questions.

Conclusion: expand the calibration grid first. The available evidence does not justify replacing the fact-evidence algorithm before testing the omitted margin range; R2.3 should still investigate Chinese routing and cavitation aliases if the expanded grid cannot satisfy Recall@3 and MRR.
