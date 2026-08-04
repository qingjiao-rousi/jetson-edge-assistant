# M9.1B Evaluation: PARTIAL

The audited `Qwen3-Embedding-0.6B Q8_0` GGUF passed local size, SHA-256, provenance and Provider smoke gates. The real three-document SQLite index and all three retrieval modes were evaluated offline. M9.1B remains `PARTIAL` because the independently frozen final quality gate failed; no threshold or weight was changed after viewing the final set.

## Frozen protocol

The 12-question calibration set and 12-question final set have disjoint IDs and separate SHA-256 values. Calibration selected Keyword `weight=1.0, threshold=0.50`, Vector `weight=1.0, threshold=0.60`, and Hybrid `vector=0.25, keyword=0.75, threshold=0.90`. The pre-evaluation Hybrid gate requires Recall@1 >= 0.75, Recall@3 >= 0.875, MRR >= 0.80, no-answer rejection >= 0.75, and no more than one false positive.

## Final metrics

| Mode | Recall@1 | Recall@3 | MRR | No-answer rejection | False positives | P50 ms | P95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Keyword/FTS5 | 0.625 | 0.750 | 0.6875 | 0.000 | 4 | 4.63 | 6.12 |
| Vector | 0.625 | 0.750 | 0.6875 | 0.250 | 3 | 2809.64 | 2963.20 |
| Hybrid | 0.500 | 0.500 | 0.5000 | 0.250 | 3 | 2837.43 | 2874.24 |

All five Hybrid quality checks failed. The final set contains eight answerable and four no-answer questions; this small synthetic sample validates the project gate only and does not establish general retrieval quality.

## Hybrid per-question result

| ID | Expected | Returned top result | Rank / decision |
| --- | --- | --- | --- |
| eval-ax-torque | AX17 technical specifications | AX17 technical specifications | 1 |
| eval-ax-inspection | AX17 maintenance schedule | none | rejected |
| eval-ax-e42-distractor | AX17 alarm E42 | BX9 alarm E42 | miss |
| eval-bx-pressure | BX9 technical specifications | BX9 technical specifications | 1 |
| eval-bx-temperature | BX9 technical specifications | BX9 technical specifications | 1 |
| eval-bx-bubbles | BX9 cavitation warning | none | rejected |
| eval-ct-t17-en | CT4 belt tracking | CT4 belt tracking | 1 |
| eval-ct-maintenance | CT4 maintenance schedule | CT4 belt tracking | miss |
| eval-no-ax-viscosity | no answer | AX17 technical specifications | false positive |
| eval-no-bx-reset | no answer | CT4 emergency-stop reset | false positive |
| eval-no-ct-e42-zh | no answer | AX17 alarm E42 | false positive |
| eval-no-ct-bearing-zh | no answer | none | correct rejection |

The machine-readable report contains the complete returned chunk lists and scores for Keyword, Vector and Hybrid: [rag-hybrid-m9.1b.json](rag-hybrid-m9.1b.json).

## Resources and limits

The 12-chunk index is 131072 bytes and took 17200.80 ms to build. Build-time embedding child peak RSS was 1973.99 MiB; final evaluation child peak RSS was 1870.75 MiB. Vector/Hybrid latency includes a fresh `llama-embedding` CLI process per uncached query, so it is not a persistent-backend latency claim. The observed failure pattern is insufficient rejection of semantically related but unsupported equipment facts and over-weighted keyword interference between devices.
