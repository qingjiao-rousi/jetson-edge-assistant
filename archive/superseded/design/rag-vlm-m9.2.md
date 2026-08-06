# M9.2 Manual Answer Prototype

M9.2 is a deliberately small local demonstration loop: query the existing R2.5 manual index, preserve returned citations, and submit only those passages to the existing local `/v1/chat` service for a non-streaming answer. It does not change R2.5 ranking, admission, calibration, diagnostic, or private-holdout evidence.

`scripts/rag_vlm_m9_2.py` returns JSON. `OK` includes the model answer and citations labelled `S1...`; `NO_EVIDENCE` bypasses model generation; `MODEL_UNAVAILABLE` preserves retrieval citations but does not fabricate an answer. The system prompt requires that model facts use the supplied evidence markers.

This is a prototype integration, not a production safety claim. M9.1B-R2.5 remains `PARTIAL` because its one-time independent holdout did not meet the frozen no-answer gate. The prototype has no streaming orchestration, conversation memory, PDF/log ingestion, auth, operator UI, or real industrial-device integration.

Before a live run, rebuild the ignored derived index when it is absent:

```bash
python3 scripts/build_hybrid_rag_index_m9_1b_r2_2.py \
  --manifest generated/rag-m9.1b-r2.2/index-manifest.json
```

Build and run the local RuntimeService in a separate terminal (the host serves
`/v1/chat` on port `18086`):

```bash
cmake -S . -B build-runtime \
  -DEDGEOMNI_BUILD_TESTS=ON \
  -DEDGEOMNI_BUILD_BENCHMARK_TOOLS=ON \
  -DEDGEOMNI_BUILD_INTEGRATION=OFF
cmake --build build-runtime --target edgeomni_vlm_service_host --parallel 2
./build-runtime/runtime/edgeomni_vlm_service_host 18086
```

Then, in another terminal:

```bash
python3 scripts/rag_vlm_m9_2.py \
  --query "BX-9 的出口压力是多少？" \
  --request-id rag-vlm-demo-001
```
