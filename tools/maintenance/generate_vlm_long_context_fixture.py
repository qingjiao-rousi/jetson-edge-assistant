#!/usr/bin/env python3
"""Generate the deterministic synthetic manual used by M7.4B."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


FACTS = {
    "start_code": "A17",
    "middle_torque_nm": 42,
    "reset_seconds": 7,
}


def alphabetic_label(index: int) -> str:
    """Return a deterministic letters-only label using one-based spreadsheet notation."""
    if index < 0:
        raise ValueError("index must be non-negative")
    value = index + 1
    output = ""
    while value:
        value, remainder = divmod(value - 1, 26)
        output = chr(ord("A") + remainder) + output
    return output


def filler_block(index: int) -> str:
    labels = ("amber", "cobalt", "ivory", "silver", "violet")
    modules = ("relay", "conduit", "sensor", "latch", "manifold")
    actions = ("inspect", "observe", "verify", "review", "document")
    label = alphabetic_label(index)
    color = labels[index % len(labels)]
    module = modules[(index * 3) % len(modules)]
    action = actions[(index * 2) % len(actions)]
    return (
        f"Procedure block {label}. This fictional training unit uses a sealed {module} and a {color} "
        f"status indicator. Technicians {action} the indicator, confirm that the braided service conduit "
        "is seated, and record the neutral operating state in the synthetic worksheet. This routine "
        "paragraph carries no control value, customer detail, site identity, or answer to the retrieval task."
    )


def generate_fixture(filler_blocks: int) -> str:
    if filler_blocks < 2:
        raise ValueError("filler_blocks must be at least 2")

    first_half = filler_blocks // 2
    second_half = filler_blocks - first_half
    lines = [
        "SYNTHETIC DEVICE SERVICE MANUAL - DETERMINISTIC CONTEXT FIXTURE",
        "",
        "This document is entirely synthetic and contains no real customer, operator, site, or device data.",
        "Use the attached image only to identify the newspaper publisher. Retrieve the three explicit control facts from the start, middle, and end records of this manual.",
        "",
        "START CONTROL RECORD",
        "For this synthetic device, start_code = A17.",
        "Do not derive the start code from any routine procedure block.",
        "",
    ]

    lines.extend(filler_block(index) for index in range(first_half))
    lines.extend([
        "",
        "MIDDLE CALIBRATION RECORD",
        "For the synthetic center coupling, middle_torque_nm = 42.",
        "This is the only authoritative torque value in the manual.",
        "",
    ])
    lines.extend(filler_block(first_half + index) for index in range(second_half))
    lines.extend([
        "",
        "END RECOVERY RECORD",
        "For the synthetic recovery control, reset_seconds = 7.",
        "This is the only authoritative reset duration in the manual.",
        "",
        "FINAL RESPONSE CONTRACT",
        "Identify publisher from the attached newspaper image, not from the manual text. Retrieve each control value from its explicit record above.",
        "Output only one valid JSON object with exactly these four keys. Do not add Markdown, commentary, or code fences:",
        "{",
        '  "publisher": "...",',
        '  "start_code": "...",',
        '  "middle_torque_nm": 0,',
        '  "reset_seconds": 0',
        "}",
    ])
    fixture = "\n".join(lines)
    validate_fixture(fixture)
    return fixture


def validate_fixture(fixture: str) -> dict[str, object]:
    fact_markers = {
        "start_code": "start_code = A17",
        "middle_torque_nm": "middle_torque_nm = 42",
        "reset_seconds": "reset_seconds = 7",
    }
    for name, marker in fact_markers.items():
        count = fixture.count(marker)
        if count != 1:
            raise ValueError(f"{name} fact marker count must be 1, got {count}")

    if "The New York Times" in fixture:
        raise ValueError("fixture must not disclose the image-derived publisher")
    if not fixture.startswith("SYNTHETIC DEVICE SERVICE MANUAL"):
        raise ValueError("fixture header missing")
    if not fixture.endswith("}"):
        raise ValueError("fixture must end with the JSON response contract")

    length = len(fixture)
    positions = {name: fixture.index(marker) for name, marker in fact_markers.items()}
    ratios = {name: position / length for name, position in positions.items()}
    if ratios["start_code"] >= 0.10:
        raise ValueError("start fact is not near the beginning")
    if not 0.40 <= ratios["middle_torque_nm"] <= 0.60:
        raise ValueError("middle fact is not near the middle")
    if ratios["reset_seconds"] <= 0.90:
        raise ValueError("reset fact is not near the end")

    return {
        "synthetic_only": True,
        "contains_real_customer_information": False,
        "fact_marker_counts": {name: fixture.count(marker) for name, marker in fact_markers.items()},
        "fact_position_ratios": ratios,
        "publisher_disclosed_in_text": False,
    }


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
