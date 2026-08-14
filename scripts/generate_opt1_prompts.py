#!/usr/bin/env python3
"""Generate synthetic prompts exact only in tokenizer (user-prompt) tokens.

Use calibrate_opt1_runtime_tokens.py before labeling any workload by Runtime
prompt_tokens: chat-template tokens make these values different.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_TOKENIZER = ROOT / "third_party/llama.cpp-omni/build-jetson-release/bin/llama-tokenize"
DEFAULT_MODEL = ROOT / "models/Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf"


def token_count(tokenizer: pathlib.Path, model: pathlib.Path, prompt: pathlib.Path) -> int:
    result = subprocess.run([str(tokenizer), "--model", str(model), "--file", str(prompt), "--ids", "--show-count", "--log-disable"],
                            cwd=ROOT, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"tokenizer failed ({result.returncode}): {result.stderr[-500:]}")
    matches = re.findall(r"Total number of tokens:\s*(\d+)", result.stdout)
    if len(matches) != 1:
        raise RuntimeError("tokenizer did not emit exactly one token count")
    return int(matches[0])


def generate(target: int, tokenizer: pathlib.Path, model: pathlib.Path, output: pathlib.Path) -> dict:
    if not tokenizer.is_file() or not model.is_file():
        raise FileNotFoundError("a local Q4 model and executable llama-tokenize are required")
    base = ("SYNTHETIC OPT-1 PREFIX REUSE PROMPT. This text contains no private or model-derived "
            "information. Repeat the deterministic filler below and treat it as plain user context.\n")
    probe = output.with_suffix(output.suffix + ".probe")
    def find_exact(unit: str) -> int | None:
        low, high = 0, max(64, target * 3)
        def write(n: int) -> int:
            probe.write_text(base + unit * n, encoding="utf-8")
            return token_count(tokenizer, model, probe)
        while write(high) < target:
            high *= 2
        while low < high:
            mid = (low + high) // 2
            if write(mid) < target:
                low = mid + 1
            else:
                high = mid
        for n in range(max(0, low - 8), low + 9):
            if write(n) == target:
                return n
        return None
    # Probe tokenization rather than assuming a word occupies one token.  The
    # short ASCII candidates make exact low targets reachable on this model.
    unit, found = next(((candidate, count) for candidate in ("a ", "b ", "x ", "0 ")
                        if (count := find_exact(candidate)) is not None), (None, None))
    probe.unlink(missing_ok=True)
    if found is None:
        raise RuntimeError(f"could not construct exact {target}-token prompt with tokenizer")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(base + unit * found, encoding="utf-8")
    return {"user_prompt_target_tokens": target, "user_prompt_tokens": token_count(tokenizer, model, output),
            "runtime_prompt_tokens": None, "label": f"user-p{target}", "path": str(output),
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "synthetic_only": True}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=pathlib.Path, required=True)
    parser.add_argument("--tokenizer", type=pathlib.Path, default=DEFAULT_TOKENIZER)
    parser.add_argument("--model", type=pathlib.Path, default=DEFAULT_MODEL)
    parser.add_argument("--targets", type=int, nargs="*", default=[256, 512, 1024, 2048])
    parser.add_argument("--manifest", type=pathlib.Path, help="optional local JSON manifest of user-prompt token counts")
    args = parser.parse_args()
    try:
        results = [generate(target, args.tokenizer.resolve(), args.model.resolve(), args.output_dir / f"p{target}.txt") for target in args.targets]
    except (OSError, RuntimeError, ValueError) as error:
        print(f"prompt generation failed: {error}", file=sys.stderr)
        return 1
    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
