#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from zundamotion.components.video.character_rig_validation import (
    FORMAT_NAME,
    validate,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Zundamotion SVG character rig validator"
    )
    parser.add_argument("svg", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    result = validate(args.svg)
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        state = "OK" if result["valid"] else "NG"
        print(f"[{state}] {args.svg} (rig v{result.get('rig_version', '?')})")
        for message in result["errors"]:
            print(f"ERROR: {message}")
        for message in result["warnings"]:
            print(f"WARN: {message}")
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    sys.exit(main())
