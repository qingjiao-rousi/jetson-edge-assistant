# Changelog

This project follows a lightweight Keep a Changelog structure. It has not published a stable release yet.

## Unreleased

### Added

- Public contribution/upstream ownership and validation-boundary documentation.
- Explicit edge-AI deployment stack and model-replacement compatibility matrix.
- Model-free repository verification entry point and GitHub Actions workflow.
- Demo evidence, benchmark protocol, empty result schema, roadmap, contribution and release checklists.
- Clean-commit Jetson Q4 text baseline with reviewed aggregate CSV and SHA-256 bindings to local raw evidence.
- Apache-2.0 project license and third-party/model asset notices.

### Changed

- Public submodule URL uses HTTPS while the gitlink commit remains pinned.
- README separates clean-clone verification from the asset-complete Jetson runtime path.
- Jetson benchmark collection uses the configured persistent VLM Runtime over HTTP rather than the Qwen3-only DirectBackend runner.

### Known limitations

- RAG M9.1B R2.5 remains PARTIAL.
- Q8 comparison, VLM latency/quality, long-run stability, wall power and demo captures remain pending evidence.
