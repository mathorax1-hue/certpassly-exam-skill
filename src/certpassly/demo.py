"""Synthetic-only tasks to test checkpoint/resume without touching live exams."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    src = Path(args.source)
    obj = json.loads(src.read_text(encoding="utf-8"))
    obj["demo_processed"] = True
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
