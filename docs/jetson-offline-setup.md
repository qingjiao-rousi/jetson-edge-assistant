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

Git provides EdgeOmni source, CMake files, Python code, configs, tracked delivery contracts, tests,
fixed image fixtures, and `knowledge/`. `third_party/llama.cpp-omni` is a submodule pinned to
`19cc26967140407efe34006a355ab445b35b16ac`. An offline repository bundle must include that exact
submodule commit; do not rely on an online submodule update.

The following items are ignored by Git and must be supplied by an approved offline medium:

| Item | Required path | Contract |
| --- | --- | --- |
| Frozen upstream build | `third_party/llama.cpp-omni/build-jetson-release/` | Transfer the complete directory, including symlinks and `bin/libllama.so*`, `libmtmd.so*`, `libggml*.so*`, `llama-embedding`, and `llama-tokenize`. |
| VLM main model | `models/Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf` | 1,929,901,056 bytes; SHA-256 `d02fe9b69ad8cadbbd228e387667af66612c44bed29ffc8eb1e7caf9ac486c12`. |
| Optional Q8 comparison model | `models/Qwen2.5-VL-3B-Instruct-Q8_0.gguf` | 3,285,474,304 bytes; SHA-256 `fa8aeb3b6bf6152774e87d13e09892aa065f4e0c4abe90806cd8ab18ff72d9fe`; contract in `configs/assistant-q8.json`. |
| VLM MMProj | `models/mmproj-Qwen2.5-VL-3B-Instruct-Q8_0.gguf` | 844,757,728 bytes; SHA-256 `980c9b2f78c04e6cff93d277ada09e768394f112d75db3b4e9dea8a69f9fb904`. |
| Embedding model | `models/embedding/Qwen3-Embedding-0.6B-Q8_0.gguf` | 639,150,592 bytes; SHA-256 `06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439`. |
| RAG database | `generated/rag-m9.1b-r2.2/hybrid.sqlite3` | Prebuilt SQLite; its size, metadata, and source binding are in `configs/contracts/rag-r2.2-delivery-contract.json`. Do not rebuild it here. |
| Optional voice assets | Paths in `configs/voice-gateway.json` | ASR/VAD/TTS files are checked only when the voice profile is selected. This does not validate devices or Python audio packages. |

The VLM main model and MMProj are from `ggml-org/Qwen2.5-VL-3B-Instruct-GGUF`, revision
`5037fcf163dd95d1e41d1974465f0898ed108ca2`, Apache-2.0. The embedding model is from
`Qwen/Qwen3-Embedding-0.6B-GGUF`, revision `d20cf9c16f82914a21dbd9c645f56895fb1d7750`,
Apache-2.0. The repository records provenance and hashes, not model bytes or a license grant.

## Read-Only Preflight

Run the verifier before building or starting anything:

```bash
cd /home/nvidia/Desktop/llm/vlmllm-main

python3 scripts/verify_local_assets.py --root . --config configs/assistant.json --profile contract
python3 scripts/verify_local_assets.py --root . --config configs/assistant.json --profile build-inputs
python3 scripts/verify_local_assets.py --root . --config configs/assistant.json --profile assistant
python3 scripts/verify_local_assets.py --root . --config configs/assistant.json --profile voice
```

`contract` verifies source/config paths, both tracked delivery contracts, and the pinned local submodule commit. `build-inputs` adds
the frozen upstream build and AArch64 ELF checks. `assistant` adds the EdgeOmni Runtime host, VLM,
embedding, RAG SQLite, source hashes, and delivery contracts. `voice` includes `assistant` plus the declared
voice assets. The verifier uses only the standard library, streams SHA-256, opens SQLite using a
read-only URI, and never invokes a model tool or opens a network connection.

Exit codes are `0` for a passing profile, `1` for a missing or mismatched contract item, `2` for
invalid CLI use or an invalid assistant configuration, and `3` when local Git metadata cannot
verify the required submodule commit.
Use `--format json` for a stable JSON object with one result per check.

The tracked contracts are `configs/contracts/runtime-contract.json` and
`configs/contracts/rag-r2.2-delivery-contract.json`. `evidence/` is ignored historical material and
is not an input to clean-clone preflight.

## Build Boundary

After `build-inputs` passes, the top-level CMake project can build EdgeOmni libraries, tests, and
`edgeomni_vlm_service_host` into a new `build-runtime/` directory. It imports the frozen upstream
libraries directly; it does not build llama.cpp-omni. The upstream build-tree CMake package is not
relocatable and must not be used as an install package.

No independent clean-clone plus offline-asset-bundle rehearsal has yet been recorded. Until that
exercise succeeds, cross-host upstream-build portability, different JetPack compatibility, real
model loading, CUDA behavior/performance, VLM accuracy, RAG quality, and voice-device operation
remain unverified.

## Build and Failure Triage

After `build-inputs` passes, configure and build without downloading or rebuilding upstream:

```bash
cd /home/nvidia/Desktop/llm/vlmllm-main

cmake -S . -B build-runtime \
  -DEDGEOMNI_BUILD_TESTS=ON \
  -DEDGEOMNI_BUILD_INTEGRATION=OFF \
  -DEDGEOMNI_BUILD_BENCHMARK_TOOLS=ON
cmake --build build-runtime -j"$(nproc)"
ctest --test-dir build-runtime --output-on-failure
```

All paths above are relative to the repository root. If the shell prompt is in `~` (`/home/nvidia`), `scripts/` and `CMakeLists.txt` will not be found. Change directory first or prefix the command with `cd /home/nvidia/Desktop/llm/vlmllm-main &&`.

Interpret common failures conservatively:

| Symptom | Check | Meaning |
| --- | --- | --- |
| `find_library` cannot locate `llama` or `mtmd` | `build-inputs` profile and `third_party/llama.cpp-omni/build-jetson-release/bin/` | Frozen upstream build is missing/incomplete; CMake does not build it for you. |
| ELF architecture check fails | Run the verifier JSON output and `file` on the named library | A non-AArch64 or invalid asset bundle was supplied. |
| Runtime rejects model before ready | Size/SHA-256 and Runtime diagnostic log path printed by launcher | Asset does not match the pinned contract; do not bypass the check. |
| Runtime stays unready | CUDA loader dependencies, RPATH, available memory, and captured Runtime log | This is not evidence of model/CUDA validation; preserve the failure record. |
| CTest service test is skipped with code 77 | Whether the environment permits binding/reaching a temporary `127.0.0.1` port | HTTP assertions did not run. Repeat on a host that permits loopback; do not report the skip as pass. |
| RAG SQLite check fails | Delivery-contract metadata, source hashes, read-only open | Supply the matching generated index; do not rebuild or alter the frozen holdout during deployment. |

For a public reproducibility claim, perform these commands from a fresh clone/path with only the approved offline bundle, then record commit IDs, profile output, build output, CTest pass/skip counts, and exact Jetson environment. That rehearsal is currently pending.
