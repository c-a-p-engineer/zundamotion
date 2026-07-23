"""Validate the feature manifest and its checked-in demo YAML files."""
from __future__ import annotations

import argparse
from pathlib import Path

from site_lib import ROOT, load_manifest

STATUSES = {"implemented", "partial", "unverified", "planned", "rejected"}


def validate(manifest: dict) -> list[str]:
    errors: list[str] = []
    categories = {item["id"] for item in manifest.get("categories", [])}
    ids: set[str] = set()
    outputs: set[str] = set()
    for feature in manifest.get("features", []):
        ident = feature.get("id", "")
        if not ident or ident in ids:
            errors.append(f"duplicate or empty feature id: {ident!r}")
        ids.add(ident)
        if feature.get("category") not in categories:
            errors.append(f"{ident}: unknown category")
        if feature.get("status") not in STATUSES:
            errors.append(f"{ident}: invalid status")
        if not feature.get("source_feature_names"):
            errors.append(f"{ident}: source_feature_names is required")
        if feature.get("status") == "partial" and not feature.get("limitations"):
            errors.append(f"{ident}: partial feature needs limitations")
        demo = feature.get("demo")
        needs_demo = feature.get("kind") == "user-facing" and feature.get("status") in {"implemented", "partial"}
        if needs_demo and not demo:
            errors.append(f"{ident}: implemented user-facing feature needs demo")
        if demo:
            script = demo.get("script", "")
            if ".." in Path(script).parts or not (ROOT / script).is_file():
                errors.append(f"{ident}: missing or unsafe demo script")
            output = demo.get("output", "")
            if not output or output in outputs:
                errors.append(f"{ident}: duplicate or empty output")
            outputs.add(output)
    return errors


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    errors = validate(load_manifest())
    if errors:
        raise SystemExit("\n".join(errors))
    print("site manifest validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
