# Public Release Checklist

Use this checklist before a tag, portfolio submission, or public repository snapshot. It records boundaries; it does not authorize deleting local experiments or evidence.

## Source and history

- [ ] `git status --short` is understood. Each source import and its target file are included in the same atomic commit.
- [ ] `app/qa/manual_qa.py` and `app/retrieval/active_pipeline.py` are published together.
- [ ] R2.6 candidate files, development fixtures and evaluation scripts are isolated in a clearly labeled experimental commit/branch. They do not change the default R2.5 path and do not claim a passed gate.
- [ ] Commit messages use descriptive English project history; historical experiments are not rewritten solely for appearance.
- [ ] `third_party/llama.cpp-omni` gitlink equals the delivery-contract commit and the submodule is clean.

## Assets and privacy

- [ ] No GGUF, generated SQLite, upstream build tree, raw benchmark/audio logs, private evidence, `.env`, core dump or host absolute path is tracked.
- [ ] Demo assets are reviewed against `docs/demo.md`; fixtures and knowledge remain labeled synthetic.
- [ ] Model and voice metadata names source, revision, hash and license without implying that weights are distributed.

## Validation

- [ ] `bash scripts/verify_public_repo.sh` passes and its exact test count is recorded.
- [ ] CTest results report pass/fail/**skip** separately. A skipped loopback HTTP test is never reported as passed.
- [ ] Jetson build, CUDA, VLM and performance claims link to a dated, reviewed record; absent values say “待实测”.
- [ ] Q4/Q8 tables follow `docs/benchmark-protocol.md`; exclusions and invalid samples are disclosed.
- [ ] RAG is still labeled PARTIAL in README, architecture, validation, limitations, Demo and release notes unless a new independent evaluation has actually passed.

## Scope and release notes

- [ ] Upstream vs EdgeOmni ownership is unchanged or updated with code references.
- [ ] Single-hot KV, single-image VLM, bounded in-process Agent and no-production-SLA boundaries remain prominent.
- [ ] Docker/systemd/auth/concurrency/soak items are described as roadmap work, not delivered features.
- [ ] `CHANGELOG.md`, Roadmap and third-party notices reflect the tag.

## Current release-hygiene status (2026-08-18)

P0 engineering and deployment validation is closed against clean-clone input commit `de19d15` and pinned upstream commit `19cc26967140407efe34006a355ab445b35b16ac`:

- Approved offline assets passed size/hash, AArch64 ELF and read-only SQLite binding checks in a new local clone.
- Fresh CUDA configure/build completed, and the Jetson host run completed 5/5 CTest with 0 failed and 0 skipped.
- Install produced a relocatable bundle whose 56 canonical ELF files and 14 symlinks passed manifest, strict relative RPATH and `env -u LD_LIBRARY_PATH ldd` checks in the original and a second absolute path.
- `/ready`, one minimal text request, RAG cited-answer/refusal paths and one fixed-fixture single-image request completed without transport or asset errors.
- `bash scripts/verify_public_repo.sh` passed with 118 model-independent Python tests during Phase 2 validation.

The documentation commit that records this result is not itself a rerun of the Jetson build. Screenshot/GIF capture remains optional portfolio polish rather than a P0 engineering gate. RAG R2.5 remains PARTIAL; the single-image request is connectivity evidence, not accuracy evidence. No new performance, power, concurrency, stability or production-readiness claim is created by this closeout.
