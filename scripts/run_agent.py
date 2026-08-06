#!/usr/bin/env python3
"""Start the Agent application service."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from app.agent.service import main


if __name__ == "__main__":
    raise SystemExit(main())
