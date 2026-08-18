# Changelog

This project follows a lightweight Keep a Changelog structure. It has not published a stable release yet.

## Unreleased

### Added

- Public contribution/upstream ownership and validation-boundary documentation.
- Explicit edge-AI deployment stack and model-replacement compatibility matrix.
- Model-free repository verification entry point and GitHub Actions workflow.
- Demo evidence, benchmark protocol, empty result schema, roadmap, contribution and release checklists.
- Clean-commit Jetson Q4 text baseline with reviewed aggregate CSV and SHA-256 bindings to local raw evidence.
- Q8 Assistant asset contract with verified model size/hash and Jetson load/ready smoke coverage.
- Clean-commit paired Q4/Q8 text comparison with reviewed performance/resource boundaries.
- Fixed single-image Jetson benchmark mode with image SHA-256 binding and vision-stage summaries.
- Clean-commit paired Q4/Q8 fixed-image end-to-end latency/resource comparison.
- Clean-commit paired Q4/Q8 fixed-image structured stage-timing comparison.
- Apache-2.0 project license and third-party/model asset notices.
- Main-integrated real `MtmdBackend` Prefix Reuse, with `c97a518` Jetson dual-path correctness for exact/branch and session/image/timeout/cancel/reset invalidation. Git-ignored raw results are bound by SHA-256 in the optimization roadmap and benchmarks index.
- Jetson-reviewed OPT-1 calibrated Runtime-length matrix and paired 30-minute serial soak, with raw SHA-256 bindings and explicit batch-boundary/resource-observation limits.
- Runtime HTTP sampling validation for JSON types, integer bounds, finite floating-point values, and structured HTTP 400 errors.
- Runtime API documentation for sampling defaults, validation errors, and EdgeOmni HTTP defensive bounds.
- Opt-in Jetson relocatable bundle build with staged `bin/lib` layout, manifest generation and model-independent verifier tests.
- P0 clean-clone validation for the pinned upstream and approved offline assets, covering fresh CUDA build, 5/5 CTest, two-path relocation audit and minimal Runtime/RAG/single-image smoke.

### Changed

- Public submodule URL uses HTTPS while the gitlink commit remains pinned.
- README separates clean-clone verification from the asset-complete Jetson runtime path.
- Jetson benchmark collection uses the configured persistent VLM Runtime over HTTP rather than the Qwen3-only DirectBackend runner.
- Runtime port preflight checks for a live listener without binding a probe socket, allowing safe back-to-back benchmark runs after normal shutdown.
- Runtime image metrics track measurement availability separately from integer millisecond values and split preprocessing, vision encoding and image-embedding injection around stable upstream mtmd APIs.
- Recorded `de19d15` as the P0 clean-clone validation input while keeping later documentation-only changes distinct from the tested code baseline.
- OPT-1 is `INTEGRATED` in `main` as single-hot, text-only, batch-boundary Prefix Reuse over upstream KV APIs; it is not multi-user caching, RAG/Agent session integration, image KV reuse, a production SLA, or a no-leak claim. The 120-minute soak, fault injection, RAG LCP distribution and Agent/RAG mapping remain future work.
- Sampling validation and its documented bounds are HTTP input guardrails, not a production-service capability claim.

### Known limitations

- RAG M9.1B R2.5 remains PARTIAL.
- VLM quality, long-run stability, wall power and reviewed demo captures remain pending evidence; screenshot/GIF capture is optional portfolio polish rather than a P0 engineering gate.
