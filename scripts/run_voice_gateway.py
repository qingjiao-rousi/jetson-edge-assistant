#!/usr/bin/env python3
"""Start the local voice gateway."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from app.audio.voice_gateway import main


if __name__ == "__main__":
    raise SystemExit(main())
