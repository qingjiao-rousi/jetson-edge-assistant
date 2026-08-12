# Roadmap

Roadmap items are planned work, not implemented capability or delivery commitments.

## P0: public portfolio baseline

- [x] Contribution/upstream ownership matrix and explicit limitations
- [x] Model-free public validation entry point and CI contract
- [x] Demo evidence specification and benchmark result template
- [x] License, third-party notice, issue and release hygiene
- [ ] Publish reviewed, redacted Jetson screenshots and Q4/Q8 result table (**Jetson required**)
- [ ] Rehearse clean clone plus offline asset bundle in a new directory/device (**Jetson and assets required**)

## P1: deployment evidence

- [ ] Run Runtime HTTP contract test where loopback binding is allowed and require no skip
- [ ] Add a minimal systemd unit and shutdown/log rotation runbook (**Jetson required**)
- [ ] Run 30-60 minute serial soak with RSS/GPU memory, temperature and error accounting (**Jetson required**)
- [ ] Publish fixed single-image latency/resource measurements without claiming accuracy (**Jetson required**)
- [ ] Define a new RAG evaluation before changing the frozen default; R2.5 remains PARTIAL
- [ ] Make Runtime backend/model profiles data-driven and publish validated Q4/Q8 example contracts (**Jetson and assets required**)

Docker is optional P1/P2 rather than a portfolio P0: offline Jetson deployment already depends on a host driver/CUDA stack and frozen native upstream build, so a container adds value only after its runtime/driver compatibility is demonstrated.

## P2: productization research

- [ ] Authentication, authorization, audit policy and threat model
- [ ] Multi-session scheduling/cache design with explicit concurrency and memory targets
- [ ] Persistent session/idempotency semantics and restart recovery
- [ ] Longer soak, fault injection and production observability
- [ ] Multi-image/video only after a new API, memory budget and validation plan
- [ ] AEC, interruption and full-duplex audio only after real microphone/device testing
