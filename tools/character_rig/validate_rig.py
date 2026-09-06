#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

REQUIRED_IDS = {
    "character",
    "body",
    "head",
    "face",
    "eyes",
    "eyes-open",
    "eyes-closed",
    "mouth",
    "mouth-closed",
}
RECOMMENDED_IDS = {
    "eyes-half",
    "mouth-small",
    "mouth-a",
    "mouth-i",
    "mouth-u",
    "mouth-e",
    "mouth-o",
    "hair-back",
    "hair-front",
    "hair-left",
    "hair-right",
    "ahoge",
    "arm-left",
    "arm-right",
}
ANIMATABLE_IDS = {
    "head",
    "hair-back",
    "hair-front",
    "hair-left",
    "hair-right",
    "ahoge",
    "arm-left",
    "arm-right",
}


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def collect_ids(root: ET.Element) -> tuple[set[str], list[str]]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for elem in root.iter():
        elem_id = elem.get("id")
        if not elem_id:
            continue
        if elem_id in seen:
            duplicates.append(elem_id)
        seen.add(elem_id)
    return seen, sorted(set(duplicates))


def validate(path: Path) -> dict[str, object]:
    result: dict[str, object] = {
        "format": "zundamotion.svg-character-rig-validation",
        "version": 1,
        "path": str(path),
        "valid": False,
        "errors": [],
        "warnings": [],
    }
    errors = result["errors"]
    warnings = result["warnings"]
    assert isinstance(errors, list)
    assert isinstance(warnings, list)

    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        errors.append(f"SVGを解析できません: {exc}")
        return result

    if local_name(root.tag) != "svg":
        errors.append("ルート要素が <svg> ではありません。")
        return result

    if not root.get("viewBox"):
        errors.append("viewBox がありません。座標系を固定してください。")

    ids, duplicates = collect_ids(root)
    missing = sorted(REQUIRED_IDS - ids)
    if missing:
        errors.append("必須IDが不足しています: " + ", ".join(missing))
    if duplicates:
        errors.append("IDが重複しています: " + ", ".join(duplicates))

    recommended_missing = sorted(RECOMMENDED_IDS - ids)
    if recommended_missing:
        warnings.append("推奨IDがありません: " + ", ".join(recommended_missing))

    image_elements = [elem for elem in root.iter() if local_name(elem.tag) == "image"]
    if image_elements:
        warnings.append(
            "<image> を含むハイブリッドSVGです。見た目維持用途では許容しますが、純ベクターではありません。"
        )

    missing_pivots: list[str] = []
    for elem in root.iter():
        elem_id = elem.get("id")
        if elem_id in ANIMATABLE_IDS:
            has_pivot = (
                elem.get("data-pivot-x") is not None
                and elem.get("data-pivot-y") is not None
            )
            if not has_pivot:
                missing_pivots.append(elem_id)
    if missing_pivots:
        warnings.append(
            "可動推奨パーツに pivot metadata がありません: "
            + ", ".join(sorted(missing_pivots))
        )

    result["ids"] = sorted(ids)
    result["missing_required_ids"] = missing
    result["missing_recommended_ids"] = recommended_missing
    result["hybrid_raster"] = bool(image_elements)
    result["valid"] = not errors
    return result


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
        print(f"[{state}] {args.svg}")
        for message in result["errors"]:
            print(f"ERROR: {message}")
        for message in result["warnings"]:
            print(f"WARN: {message}")
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    sys.exit(main())
