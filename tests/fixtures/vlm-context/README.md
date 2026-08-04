# VLM Long-Context Fixture

M7.4B does not store a large static prompt in the source tree. `scripts/generate_vlm_long_context_fixture.py` deterministically generates an entirely synthetic equipment manual from a `filler_blocks` integer. It contains no real customer, operator, site, or device information.

The generator places one authoritative fact near each retrieval boundary:

- start: `start_code = A17`
- middle: `middle_torque_nm = 42`
- end: `reset_seconds = 7`

The generated prompt does not disclose the newspaper publisher. That answer must come from `third_party/llama.cpp-omni/tools/mtmd/test-1.jpeg`.

`scripts/run_vlm_long_context.py` searches the configured filler-block range with `llama-tokenize`; it saves the selected `fixture.txt`, its SHA-256, the tokenizer command and raw token output inside a new timestamped benchmark directory. Tokenizer calls are calibration only and are not inference attempts.
