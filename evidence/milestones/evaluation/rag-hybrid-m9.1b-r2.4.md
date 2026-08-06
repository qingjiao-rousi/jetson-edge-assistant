# M9.1B-R2.4 Evaluation: DONE (Development Gates)

R2.4 passed the unchanged complete quality gate on both independent calibration and diagnostic/dev sets. Calibration evaluated 135 nonzero candidates and selected vector `0.40`, margin `0.0001`, fact-family coverage `0.25`, and concept-lexical coverage `0.25`. Its metrics were Recall@1 `0.875`, Recall@3 `1.0`, MRR `0.9375`, rejection `1.0`, and zero false positives.

Diagnostic used only the frozen calibration artifact and achieved the same metrics: Recall@1 `0.875`, Recall@3 `1.0`, MRR `0.9375`, rejection `1.0`, and zero false positives. The artifacts include per-question admission evidence and the frozen algorithm fingerprint `31aae901b2b39fb53b2b0cf5cfbbfda2fa95550abda6ebc4f1edc914dbe50c86`.

This `DONE` status covers R2.4 development gates only. No private R2.1 holdout was read, copied, run, or reused; no R2.4 holdout was created or executed, and no M9.2 work was performed.
