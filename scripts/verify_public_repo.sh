#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

echo "[1/4] Python unit and integration tests (no model or device required)"
python3 -m unittest discover -s tests -p 'test_*.py' -v

echo "[2/4] Offline source/config contract"
python3 scripts/verify_local_assets.py \
  --root . --config configs/assistant.json --profile contract

echo "[3/4] Markdown links and tracked artifact hygiene"
python3 scripts/check_public_repo.py --root .

echo "[4/4] Patch whitespace"
git diff --check

echo "Public repository verification passed."
echo "Scope: source/config/Python contracts only; Jetson, CUDA, models, audio, and performance were not tested."
