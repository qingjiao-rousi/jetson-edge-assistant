# Repository Structure Migration

This record captures the 2026-08-06 structural migration without changing runtime, retrieval, embedding, VLM, KV-cache, or frozen-evaluation behavior.

| Previous location | Current location | Classification |
| --- | --- | --- |
| `scripts/agent_m10_2.py` | `app/agent/service.py` | Mainline Agent service |
| `scripts/audio_gateway_m11.py` | `app/audio/voice_gateway.py` | Mainline audio service |
| `scripts/chat_console_m12.py` | `app/ui/chat_console.py` | Mainline terminal UI |
| `scripts/rag_vlm_m9_2.py` | `app/qa/manual_qa.py` | Mainline QA orchestration |
| Current retrieval implementation | `app/retrieval/` | Mainline retrieval and citations |
| Benchmark runners | `tools/benchmark/` | Tooling |
| Evaluators | `tools/evaluation/` | Tooling |
| Frozen reports, manifests, baselines, weekly reports | `evidence/` | Historical evidence |
| Earlier RAG scripts and retired tests | `archive/experiments/` | Frozen experiments |
| Design and project snapshots | `archive/superseded/` | Superseded history |

`tests/fixtures/rag-m9.1b-r2/holdout-set.json` remains in place and is not moved or executed by this migration.
