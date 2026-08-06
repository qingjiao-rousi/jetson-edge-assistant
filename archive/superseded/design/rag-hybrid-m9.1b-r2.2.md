# M9.1B-R2.2 Concept Fact-Family Evidence

R2.2 leaves R1, R2, and R2.1 committed baselines unchanged. It retains R2 hard device/fault constraints and RRF candidate ordering, but replaces R2.1 term-count evidence with `concept-fact-family-v1`.

The evidence lexicon maps English aliases and Chinese concept phrases to auditable industrial fact families: maintenance interval, pressure, temperature, torque, reset, cavitation, belt tracking, fault meaning, oil specification, bearing, and speed. Evidence checks the candidate heading before content. Device IDs and fault codes are passed only to the existing hard constraint layer and never count as concept evidence. Generic vocabulary including `hydraulic`, `pump`, `maintenance`, and `check` cannot form evidence alone.

Index metadata records the algorithm version, `industrial-concepts-v1` lexicon version, serialized gate parameters, and an R2.2 fingerprint. Admission failures return empty results/citations and stable `missing_fact_family_evidence` reason codes. New calibration/dev fixtures cover English service paraphrase, Chinese maintenance concepts, missing facts on a valid device, generic vocabulary without a relation, and cross-device/cross-code interference.

R2.2 has no holdout authorization or execution path. It may be authorized for a new holdout only after calibration and diagnostic independently satisfy the unchanged complete quality gate.
