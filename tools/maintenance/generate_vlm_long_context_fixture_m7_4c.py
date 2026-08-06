#!/usr/bin/env python3
"""Generate the deterministic, versioned M7.4C 16384-context fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import generate_vlm_long_context_fixture as m7_4b


FACTS = m7_4b.FACTS


def generate_fixture(filler_blocks: int) -> str:
    """Create an M7.4C fixture without changing the M7.4B generator."""
    fixture = m7_4b.generate_fixture(filler_blocks)
    fixture = fixture.replace(
        "SYNTHETIC DEVICE SERVICE MANUAL - DETERMINISTIC CONTEXT FIXTURE",
        "SYNTHETIC DEVICE SERVICE MANUAL - DETERMINISTIC M7.4C CONTEXT FIXTURE",
        1,
    )
    validate_fixture(fixture)
    return fixture


def validate_fixture(fixture: str) -> dict[str, object]:
    validation = m7_4b.validate_fixture(fixture)
    if not fixture.startswith("SYNTHETIC DEVICE SERVICE MANUAL - DETERMINISTIC M7.4C"):
        raise ValueError("M7.4C fixture header missing")
    return validation


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--filler-blocks", type=int, required=True)
    parser.add_argument("--metadata-output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    fixture = generate_fixture(args.filler_blocks)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(fixture, encoding="utf-8")
    metadata = {
        "schema_version": 1,
        "milestone": "M7.4C",
        "synthetic_only": True,
        "contains_real_customer_information": False,
        "filler_blocks": args.filler_blocks,
        "size_bytes": len(fixture.encode("utf-8")),
        "sha256": sha256_text(fixture),
        "facts": FACTS,
        "validation": validate_fixture(fixture),
    }
    if args.metadata_output:
        args.metadata_output.parent.mkdir(parents=True, exist_ok=True)
        args.metadata_output.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadata))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
