# Third-Party and Asset Notices

The root `LICENSE` applies to original EdgeOmni source and documentation in this repository. It does not replace the terms of third-party source, model weights, datasets, or local assets.

## llama.cpp-omni

- Location: `third_party/llama.cpp-omni` Git submodule
- Pinned commit: `19cc26967140407efe34006a355ab445b35b16ac`
- Upstream repository: `https://github.com/qingjiao-rousi/llama.cpp-omni`
- License at the pinned revision: MIT; see `third_party/llama.cpp-omni/LICENSE`

EdgeOmni links against a separately prepared upstream AArch64/CUDA build. GGML/GGUF, CUDA kernels, model loading, tokenizer/sampler, and `mtmd` capabilities are upstream capabilities, not original EdgeOmni implementations. The submodule may contain additional vendored components with their own notices; downstream distributors must review the pinned upstream tree.

## Model assets

Model binaries are not tracked or distributed by this repository. Configuration files record provenance for offline operators:

| Asset | Recorded source/revision | Recorded license | Distribution |
| --- | --- | --- | --- |
| Qwen2.5-VL-3B-Instruct GGUF and MMProj | `ggml-org/Qwen2.5-VL-3B-Instruct-GGUF` at `5037fcf163dd95d1e41d1974465f0898ed108ca2` | Apache-2.0 | Not included |
| Qwen3-Embedding-0.6B GGUF | `Qwen/Qwen3-Embedding-0.6B-GGUF` at `d20cf9c16f82914a21dbd9c645f56895fb1d7750` | Apache-2.0 | Not included |
| Voice assets | Repositories/revisions in `configs/voice-gateway.json` | Per recorded upstream fields | Not included |

Recorded metadata is an integrity and provenance contract, not a grant of model rights. Operators must verify the applicable model license and usage policy for their distribution and jurisdiction.

## Knowledge and fixtures

The manuals under `knowledge/` are marked `synthetic-test-data`; image fixtures under `tests/fixtures/` are test assets. They are not real maintenance instructions and must not be used to operate industrial equipment.
