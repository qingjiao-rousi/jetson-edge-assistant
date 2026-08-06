#!/usr/bin/env python3
"""Start the terminal chat console."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from app.ui.chat_console import main


if __name__ == "__main__":
    raise SystemExit(main())
