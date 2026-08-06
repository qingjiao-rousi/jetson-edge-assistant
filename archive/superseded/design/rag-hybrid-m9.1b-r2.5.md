# M9.1B-R2.5 Core Fact Alignment

R2.5 leaves the R2 index, Qwen3-Embedding-0.6B, RRF ranking, device and fault-code hard constraints, and frozen quality gate unchanged. It replaces R2.4 substring evidence with `core-fact-family-v1` / `industrial-concepts-v3`.

English aliases are tokenized with `[a-z0-9]+`; a phrase must match a contiguous token sequence, so `roller` cannot match `controller`. Longest phrases consume their token span first, so `fluid temperature` is not also counted as the weaker `temperature` term. Chinese aliases are explicit domain phrases because Chinese text does not provide whitespace boundaries.

`fluid` is not a temperature concept. `hydraulic fluid`, `oil`, `lubricant`, `viscosity`, and `grade` belong to the oil family. A candidate must match every requested core family. The specification family prevents a tracking passage from answering a request for a roller specification unless it also supplies a specification fact. Device IDs and fault codes are only hard constraints and never evidence.

Admission retains the existing nonzero vector and margin thresholds, plus fact-family coverage. Rejection clears results and citations and uses `missing_core_fact_family`. R2.5 evaluates only public calibration and diagnostic fixtures; holdout execution is prohibited in this development milestone.
