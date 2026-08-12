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

## Current working-tree audit (2026-08-12)

At review time, the worktree contained modified Runtime/Agent/request-id changes plus untracked active-pipeline and R2.6 candidate/evaluation files. These changes may be valid, but they are not a clean public release boundary. Preserve them, test them as one workspace, then separate mainline correctness changes from R2.6 experiments before tagging. In particular, never commit `app/qa/manual_qa.py` without its imported `app/retrieval/active_pipeline.py`.
