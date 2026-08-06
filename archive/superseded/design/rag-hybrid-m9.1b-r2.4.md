# M9.1B-R2.4 Concept-Aware Lexical Evidence

R2.4 keeps R2 RRF, embedding, hard device/fault constraints, and the frozen quality gate unchanged. It replaces raw keyword coverage as an independent admission veto with `concept-lexical-evidence-v1`. Admission requires nonzero vector and margin thresholds, fact-family evidence, and concept-aware lexical evidence.

The `industrial-concepts-v2` lexicon maps service/servicing/interval/schedule/inspection to the maintenance family. Chinese maintenance, cycle, inspection, tension, alignment, and operating-hours concepts are matched as domain phrases/families rather than raw CJK-bigram counts. Bare `hydraulic`, `pump`, `maintenance`, and `check` do not create a requested family and cannot pass admission. Evidence records heading and content matches plus stable `missing_fact_family_evidence` and `missing_concept_lexical_evidence` reasons.

Calibration enumerates nonzero vector, fact-family, concept-lexical, and margin candidates. Its frozen artifact records all 135 candidate metrics, selected parameters, and algorithm fingerprint. R2.4 does not create or execute a holdout; that requires separate authorization after review.
