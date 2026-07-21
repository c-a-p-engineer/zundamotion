#!/usr/bin/env python3
"""Export digest-pinned runtime image references from runtime.lock.json."""

from __future__ import annotations

import argparse
import shlex

from runtime_lock import load_lock, runtime_image_ref


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shell", action="store_true", help="emit shell export statements")
    args = parser.parse_args()
    lock = load_lock()
    values = {
        "ZUNDAMOTION_RUNTIME_CPU_IMAGE": runtime_image_ref(lock, "cpu"),
        "ZUNDAMOTION_RUNTIME_GPU_IMAGE": runtime_image_ref(lock, "gpu"),
    }
    for key, value in values.items():
        print(f"export {key}={shlex.quote(value)}" if args.shell else f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
