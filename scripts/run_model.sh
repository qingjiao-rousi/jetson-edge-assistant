#!/usr/bin/env bash
# Compatibility launcher for the local model tool.
exec "$(dirname "$0")/../tools/maintenance/run_model.sh" "$@"
