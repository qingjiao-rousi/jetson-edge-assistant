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
- Jetson-reviewed real `MtmdBackend` Prefix Reuse correctness matrix for exact/branch and session/image/timeout/cancel/reset invalidation.

### Changed

- Public submodule URL uses HTTPS while the gitlink commit remains pinned.
- README separates clean-clone verification from the asset-complete Jetson runtime path.
- Jetson benchmark collection uses the configured persistent VLM Runtime over HTTP rather than the Qwen3-only DirectBackend runner.
- Runtime port preflight checks for a live listener without binding a probe socket, allowing safe back-to-back benchmark runs after normal shutdown.
- Runtime image metrics track measurement availability separately from integer millisecond values and split preprocessing, vision encoding and image-embedding injection around stable upstream mtmd APIs.
- Documented `d11617e` as the public portfolio baseline and separated existing DirectBackend Prefix Reuse from the planned Qwen2.5-VL MtmdBackend optimization path.

### Known limitations

- RAG M9.1B R2.5 remains PARTIAL.
- VLM quality, long-run stability, wall power and demo captures remain pending evidence.
