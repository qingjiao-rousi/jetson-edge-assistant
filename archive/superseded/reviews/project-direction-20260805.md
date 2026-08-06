# Project Direction Review: 2026-08-05

## Decision

The repository remains aligned with its assigned part of the project: Jetson
offline LLM/VLM Runtime and an evidence-grounded industrial fault-assistance
backend. Local document retrieval, device/fault constraints, citations, and
refusal behavior are all directly relevant to that outcome. The repository is
not the owner of real-time audio/video capture, VAD/AEC, ASR, TTS, playback, or
full-duplex stream control; those remain integration dependencies rather than
completed repository capabilities.

## Current Boundary

M8 provides a bounded single-image VLM application API. M9.1B provides an
offline retrieval prototype over three synthetic Markdown manuals. R2.5 passed
development calibration and diagnostic gates but failed its one-time holdout on
no-answer rejection (`0.50` versus `0.75`). Therefore the repository has not
yet demonstrated a dependable knowledge-retrieval component for fault
assistance, and it must not claim a complete multimodal industrial assistant.

## Direction Risk

The R2 sequence has improved retrieval safety, but repeated micro-iterations
over three synthetic manuals are now a scope-concentration risk. More threshold
or vocabulary tuning alone would move the work away from the application goal.
The next change must be time-boxed and must address the observed semantic gap:
the retriever must distinguish a mentioned object from the requested attribute
or relation. After that, evidence needs to broaden to representative manuals,
logs/PDF inputs, and a citation-grounded application response.

## Next Gate

1. Archive R2.5 `PARTIAL` evidence and preserve all consumed private artifacts.
2. Implement one bounded R2.6 relation/facet admission correction using only
   new calibration and diagnostic data; do not access prior private holdouts.
3. If R2.6 development gates pass, run one new holdout. If it fails, stop
   synthetic-gate iteration and conduct a RAG quality-set and real-document
   design review before more code changes.
4. Only a passing holdout authorizes M9.2: pass retrieved snippets and stable
   citations into the existing VLM application API, enforce source-grounded
   Markdown/JSON answers, and test unsupported questions.

M10.1 KV prefix reuse, Agent/tooling, deployment, and long-stability work stay
out of scope until the RAG application boundary is accepted.
