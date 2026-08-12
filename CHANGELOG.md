# Changelog

This project follows a lightweight Keep a Changelog structure. It has not published a stable release yet.

## Unreleased

### Added

- Public contribution/upstream ownership and validation-boundary documentation.
- Explicit edge-AI deployment stack and model-replacement compatibility matrix.
- Model-free repository verification entry point and GitHub Actions workflow.
- Demo evidence, benchmark protocol, empty result schema, roadmap, contribution and release checklists.
- Apache-2.0 project license and third-party/model asset notices.

### Changed

- Public submodule URL uses HTTPS while the gitlink commit remains pinned.
- README separates clean-clone verification from the asset-complete Jetson runtime path.
- Jetson benchmark collection uses the configured persistent VLM Runtime over HTTP rather than the Qwen3-only DirectBackend runner.

### Known limitations

- RAG M9.1B R2.5 remains PARTIAL.
- Reviewed public Q4/Q8 numeric results, long-run stability, power/resource tables and demo captures are pending Jetson execution.
