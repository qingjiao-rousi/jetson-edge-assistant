# M9.1B Qwen3 Embedding Asset Record

The offline asset gate is satisfied by `Qwen/Qwen3-Embedding-0.6B-GGUF` at immutable revision `d20cf9c16f82914a21dbd9c645f56895fb1d7750`. The installed file is `models/embedding/Qwen3-Embedding-0.6B-Q8_0.gguf`, size `639150592` bytes, SHA-256 `06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439`, Xet hash `c07418bff31dfab7ab0754eaa7a376c0cbb0cba7dada80fe4c5adb4d24d44291`, and license `apache-2.0`.

The independent asset manifest is [qwen3-embedding-m9.1b.json](../../manifests/qwen3-embedding-m9.1b.json). Runtime admission verifies the repository identity fields, exact byte size and local SHA-256 before starting `llama-embedding`. The GGUF metadata reports version 3, `qwen3`, 1024 embedding dimensions, context 32768, Q8_0 and last-token pooling. A real provider smoke returned exactly 1024 finite values with L2 norm `0.9999999999999991`.

The GGUF bytes are not distributed by Git. `*.gguf` remains ignored, and `git check-ignore -v models/embedding/Qwen3-Embedding-0.6B-Q8_0.gguf` resolves to `.gitignore:4`. Existing Qwen3 Instruct and VLM files are not accepted as retrieval embedding assets. No network access is required for indexing or querying.

Asset admission alone does not make M9.1B `DONE`. The independent final quality gate remains authoritative; the 2026-08-04 evaluation missed it and therefore retains `PARTIAL`.
