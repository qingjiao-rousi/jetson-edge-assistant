#!/usr/bin/env python3
"""Start the unified local Assistant application."""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from app.assistant.application import AssistantConfigError, AssistantPreflightError, run_console


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/assistant.json")
    parser.add_argument("--session-id")
    parser.add_argument("--speak", action="store_true", help="enable optional sentence TTS when first needed")
    args = parser.parse_args()
    try:
        run_console(args.config, args.session_id, args.speak)
        return 0
    except (AssistantConfigError, AssistantPreflightError, OSError, ValueError) as error:
        print(f"助手：启动预检失败：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
