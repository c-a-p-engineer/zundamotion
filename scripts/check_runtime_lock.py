#!/usr/bin/env python3
"""Validate the authoritative BtbN runtime lock file."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from runtime_lock import LOCK_PATH, load_lock, validate_lock


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=LOCK_PATH)
    args = parser.parse_args()
    errors = validate_lock(load_lock(args.lock))
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
