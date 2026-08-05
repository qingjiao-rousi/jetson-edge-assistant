# M9.1B-R2.3 Evaluation: PARTIAL

R2.3 changes only the calibration margin grid to `0.0001, 0.0002, 0.00025, 0.0003, 0.0005, 0.001, 0.005`; it does not change R2.2 indexing, RRF, concept/fact-family evidence, embedding, lexicon, fixtures, or quality gate.

Calibration evaluated all 63 vector/fact/margin candidates and passed the complete frozen gate. It selected vector `0.40`, keyword coverage `0.10`, fact-family coverage `0.25`, and margin `0.0001`: Recall@1 `0.75`, Recall@3 `0.875`, MRR `0.8125`, rejection `1.0`, false positives `0`. The calibration artifact records every candidate and the selected algorithm fingerprint.

Diagnostic failed the unchanged gate: Recall@1 `0.5`, Recall@3 `0.5`, MRR `0.5`, rejection `1.0`, false positives `0`. The English service paraphrase had no recognized fact family and zero keyword coverage; the Chinese maintenance case had a recognized family but insufficient keyword coverage. R2.3 remains `PARTIAL`; it does not freeze a deployable algorithm or authorize a new holdout.

No R2.1 private holdout artifact was read, copied, run, or reused. No new holdout was created and no M9.2 work was performed.
