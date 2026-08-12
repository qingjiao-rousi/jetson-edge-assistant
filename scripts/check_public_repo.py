#!/usr/bin/env python3
"""Read-only checks for public-repository links and tracked artifact hygiene."""

from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
LINK = re.compile(r"(?<!!)\[[^]]*\]\(([^)]+)\)")
IGNORED_TARGETS = ("http://", "https://", "mailto:", "#")
FORBIDDEN_SUFFIXES = {".gguf", ".sqlite", ".sqlite3", ".db", ".log", ".wav", ".pcm", ".mp3"}
FORBIDDEN_PARTS = {"build-runtime", "models", "generated", "evidence", ".venv", "__pycache__"}
MAX_TRACKED_BYTES = 10 * 1024 * 1024


def repository_files(root: pathlib.Path) -> list[pathlib.Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return [root / item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def check_links(root: pathlib.Path, files: list[pathlib.Path]) -> list[str]:
    errors: list[str] = []
    for path in files:
        if path.suffix.lower() != ".md" or not path.is_file():
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in LINK.finditer(line):
                raw = match.group(1).strip().strip("<>")
                if not raw or raw.startswith(IGNORED_TARGETS):
                    continue
                target = raw.split("#", 1)[0]
                if not target:
                    continue
                resolved = (path.parent / target).resolve()
                if not resolved.is_relative_to(root.resolve()) or not resolved.exists():
                    errors.append(f"{path.relative_to(root)}:{line_number}: missing local link: {raw}")
    return errors


def check_artifacts(root: pathlib.Path, files: list[pathlib.Path]) -> list[str]:
    errors: list[str] = []
    for path in files:
        relative = path.relative_to(root)
        if any(part in FORBIDDEN_PARTS for part in relative.parts):
            errors.append(f"tracked generated/private path: {relative}")
            continue
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            errors.append(f"tracked binary/runtime artifact: {relative}")
            continue
        if path.is_file() and path.stat().st_size > MAX_TRACKED_BYTES:
            errors.append(f"tracked file exceeds 10 MiB: {relative} ({path.stat().st_size} bytes)")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=pathlib.Path, default=ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        files = repository_files(root)
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"public repository check failed: cannot read tracked files: {error}", file=sys.stderr)
        return 2
    errors = check_links(root, files) + check_artifacts(root, files)
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"public repository check: pass ({len(files)} publishable entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
