# M9.1B-R2.5 Holdout Result: PARTIAL

R2.5 froze `core-fact-family-v1` at algorithm fingerprint
`0d84afa229f49d779059ea83d658b768ba91063832377d651702d8d330575df2`.
The private holdout was authorized and executed once. Its questions and raw
artifact remain outside the repository.

| Metric | Result | Frozen gate | Result |
| --- | ---: | ---: | --- |
| Recall@1 | 0.875 | >= 0.75 | pass |
| Recall@3 | 0.875 | >= 0.875 | pass |
| MRR | 0.875 | >= 0.80 | pass |
| No-answer correct rejection | 0.50 | >= 0.75 | fail |
| False positives | 1 | <= 1 | pass |

Audit identifiers:

- holdout SHA-256: `d65e310f500c93c2f193be81d423b5fcdd8d57f24e55062267bff3fd4c16cfde`
- authorization SHA-256: `cdb5d0d84255e7c6f062944782e5d509dc2ccb1a2070d4e36b01bcf82110d868`
- calibration SHA-256: `cc8bc6f46a61d7d79211b5de12259a396da2f7b8fa564dd465cb5a8a9d24dbac`
- diagnostic SHA-256: `0522b0ac53da3d7a067b1b9ffb9d1a31faf2649d9b220d08d7b0375f8c195072`

The holdout is consumed. It must not be rerun, changed, or used to tune R2.6.
M9.1B remains `PARTIAL`; M9.2 is not authorized by this result.
