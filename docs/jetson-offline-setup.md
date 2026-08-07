# Jetson Offline Setup

This guide defines an offline delivery contract for EdgeOmni. It does not download models, build an
index, start a Runtime, or provide Docker, systemd, cloud, or production deployment instructions.

## Recorded Baseline

The recorded environment is a Jetson AGX Orin Developer Kit (aarch64), Ubuntu 22.04.5, L4T
`R36.4.7`, CUDA `12.6.68`, GCC/G++ `11.4.0`, CMake `3.22.1`, and OpenSSL `3.0.2`. The upstream
build uses CUDA architecture `87`, shared libraries, `GGML_CUDA=ON`, and `GGML_CUDA_NCCL=OFF`.
The evidence records L4T, not a standalone JetPack product label. Operators must establish their
own JetPack/L4T compatibility; other releases are not validated by this guide.

The target needs a working Jetson driver stack, `/usr/local/cuda`, CMake 3.20 or newer, a C++17
compiler, GNU Make or an equivalent CMake generator, Threads, and OpenSSL development files. The
recorded toolchain is evidence, not a portability guarantee.

## Offline Inventory

Git provides EdgeOmni source, CMake files, Python code, configs, tests, fixed image fixtures,
`knowledge/`, and tracked evidence. `third_party/llama.cpp-omni` is a submodule pinned to
`19cc26967140407efe34006a355ab445b35b16ac`. An offline repository bundle must include that exact
submodule commit; do not rely on an online submodule update.

The following items are ignored by Git and must be supplied by an approved offline medium:

| Item | Required path | Contract |
| --- | --- | --- |
| Frozen upstream build | `third_party/llama.cpp-omni/build-jetson-release/` | Transfer the complete directory, including symlinks and `bin/libllama.so*`, `libmtmd.so*`, `libggml*.so*`, `llama-embedding`, and `llama-tokenize`. |
| VLM main model | `models/Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf` | 1,929,901,056 bytes; SHA-256 `d02fe9b69ad8cadbbd228e387667af66612c44bed29ffc8eb1e7caf9ac486c12`. |
| VLM MMProj | `models/mmproj-Qwen2.5-VL-3B-Instruct-Q8_0.gguf` | 844,757,728 bytes; SHA-256 `980c9b2f78c04e6cff93d277ada09e768394f112d75db3b4e9dea8a69f9fb904`. |
| Embedding model | `models/embedding/Qwen3-Embedding-0.6B-Q8_0.gguf` | 639,150,592 bytes; SHA-256 `06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439`. |
| RAG database | `generated/rag-m9.1b-r2.2/hybrid.sqlite3` | Prebuilt SQLite; 139,264 bytes and bound to the checked-in R2.2 manifest. Do not rebuild it here. |
| Optional voice assets | Paths in `configs/voice-gateway.json` | ASR/VAD/TTS files are checked only when the voice profile is selected. This does not validate devices or Python audio packages. |

The VLM main model and MMProj are from `ggml-org/Qwen2.5-VL-3B-Instruct-GGUF`, revision
`5037fcf163dd95d1e41d1974465f0898ed108ca2`, Apache-2.0. The embedding model is from
`Qwen/Qwen3-Embedding-0.6B-GGUF`, revision `d20cf9c16f82914a21dbd9c645f56895fb1d7750`,
Apache-2.0. The repository records provenance and hashes, not model bytes or a license grant.

## Read-Only Preflight

Run the verifier before building or starting anything:

```bash
python3 scripts/verify_local_assets.py --root . --config configs/assistant.json --profile contract
python3 scripts/verify_local_assets.py --root . --config configs/assistant.json --profile build-inputs
python3 scripts/verify_local_assets.py --root . --config configs/assistant.json --profile assistant
python3 scripts/verify_local_assets.py --root . --config configs/assistant.json --profile voice
```

`contract` verifies source/config paths and the pinned local submodule commit. `build-inputs` adds
the frozen upstream build and AArch64 ELF checks. `assistant` adds the EdgeOmni Runtime host, VLM,
embedding, RAG SQLite, source hashes, and manifests. `voice` includes `assistant` plus the declared
voice assets. The verifier uses only the standard library, streams SHA-256, opens SQLite using a
read-only URI, and never invokes a model tool or opens a network connection.

Exit codes are `0` for a passing profile, `1` for a missing or mismatched contract item, `2` for
invalid CLI use or an invalid assistant configuration, and `3` when local Git metadata cannot
verify the required submodule commit.
Use `--format json` for a stable JSON object with one result per check.

## Build Boundary

After `build-inputs` passes, the top-level CMake project can build EdgeOmni libraries, tests, and
`edgeomni_vlm_service_host` into a new `build-runtime/` directory. It imports the frozen upstream
libraries directly; it does not build llama.cpp-omni. The upstream build-tree CMake package is not
relocatable and must not be used as an install package.

No independent clean-clone plus offline-asset-bundle rehearsal has yet been recorded. Until that
exercise succeeds, cross-host upstream-build portability, different JetPack compatibility, real
model loading, CUDA behavior/performance, VLM accuracy, RAG quality, and voice-device operation
remain unverified.
