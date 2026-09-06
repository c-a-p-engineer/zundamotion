#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

FORMAT_NAME = "zundamotion.svg-character-rig-validation"
REQUIRED_V1_IDS = {
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
RECOMMENDED_FACE_IDS = {
    "face-base",
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
}
V2_REQUIRED_IDS = {
    "torso",
    "arm-left",
    "upper-arm-left",
    "forearm-left",
    "hand-left",
    "arm-right",
    "upper-arm-right",
    "forearm-right",
    "hand-right",
    "leg-left",
    "thigh-left",
    "calf-left",
    "foot-left",
    "leg-right",
    "thigh-right",
    "calf-right",
    "foot-right",
}
V2_MARKER_IDS = V2_REQUIRED_IDS - {"arm-left", "arm-right"}
V2_WAIST_IDS = {"waist", "skirt-waist"}
V1_PIVOT_IDS = {
    "head",
    "hair-back",
    "hair-front",
    "hair-left",
    "hair-right",
    "ahoge",
    "arm-left",
    "arm-right",
}
V2_PIVOT_IDS = {
    "head",
    "hair-back",
    "hair-front",
    "hair-left",
    "hair-right",
    "ahoge",
    "upper-arm-left",
    "forearm-left",
    "hand-left",
    "upper-arm-right",
    "forearm-right",
    "hand-right",
    "thigh-left",
    "calf-left",
    "foot-left",
    "thigh-right",
    "calf-right",
    "foot-right",
}
STATE_IDS = {
    "eyes-open",
    "eyes-half",
    "eyes-closed",
    "mouth-closed",
    "mouth-small",
    "mouth-a",
    "mouth-i",
    "mouth-u",
    "mouth-e",
    "mouth-o",
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


def find_by_id(root: ET.Element, elem_id: str) -> ET.Element | None:
    return next((elem for elem in root.iter() if elem.get("id") == elem_id), None)


def collect_descendants(elem: ET.Element) -> list[ET.Element]:
    return list(elem.iter())[1:]


def detect_rig_version(root: ET.Element, ids: set[str]) -> int:
    declared = root.get("data-rig-version")
    if declared == "2":
        return 2
    if declared == "1":
        return 1
    return 2 if ids & V2_MARKER_IDS else 1


def has_pivot(elem: ET.Element | None) -> bool:
    if elem is None:
        return False
    return elem.get("data-pivot-x") is not None and elem.get("data-pivot-y") is not None


def validate_required_ids(
    ids: set[str], rig_version: int, errors: list[str], warnings: list[str]
) -> tuple[list[str], list[str]]:
    missing_required = sorted(REQUIRED_V1_IDS - ids)
    if missing_required:
        errors.append("必須IDが不足しています: " + ", ".join(missing_required))

    missing_v2: list[str] = []
    if rig_version == 2:
        missing_v2 = sorted(V2_REQUIRED_IDS - ids)
        if missing_v2:
            errors.append("v2関節IDが不足しています: " + ", ".join(missing_v2))
        if not ids & V2_WAIST_IDS:
            errors.append("v2では waist または skirt-waist が必要です。")
    else:
        warnings.append(
            "legacy v1リグとして検証しました。手足のjoint-level QAにはv2リグを推奨します。"
        )
    return missing_required, missing_v2


def validate_pivots(
    root: ET.Element, ids: set[str], rig_version: int, errors: list[str], warnings: list[str]
) -> list[str]:
    expected = V2_PIVOT_IDS if rig_version == 2 else V1_PIVOT_IDS
    missing = sorted(
        elem_id
        for elem_id in expected & ids
        if not has_pivot(find_by_id(root, elem_id))
    )
    if not missing:
        return []
    message = "可動パーツにpivot metadataがありません: " + ", ".join(missing)
    if rig_version == 2:
        errors.append(message)
    else:
        warnings.append(message)
    return missing


def validate_source_parts(
    root: ET.Element, rig_version: int, errors: list[str], warnings: list[str]
) -> tuple[bool, list[str]]:
    image_elements = [elem for elem in root.iter() if local_name(elem.tag) == "image"]
    if image_elements:
        warnings.append(
            "<image> を含むハイブリッドSVGです。見た目維持用途では許容しますが、純ベクターではありません。"
        )
    if rig_version != 2:
        return bool(image_elements), []

    character = find_by_id(root, "character")
    if character is None:
        return bool(image_elements), []
    character_images = [
        elem for elem in collect_descendants(character) if local_name(elem.tag) == "image"
    ]
    untraceable = sorted(
        elem.get("id", "<unnamed>")
        for elem in character_images
        if not elem.get("data-source-part")
    )
    if untraceable:
        warnings.append(
            "v2のraster assetにdata-source-partがありません: " + ", ".join(untraceable)
        )

    fullbody_assets = [
        elem.get("id", "<unnamed>")
        for elem in character_images
        if elem.get("data-source-part") == "fullbody_ref"
    ]
    if fullbody_assets:
        errors.append(
            "fullbody_refをcharacter可動階層へ入れないでください: "
            + ", ".join(sorted(fullbody_assets))
        )
    return bool(image_elements), untraceable


def validate_state_groups(root: ET.Element, ids: set[str], warnings: list[str]) -> list[str]:
    empty_states: list[str] = []
    for state_id in sorted(STATE_IDS & ids):
        elem = find_by_id(root, state_id)
        if elem is not None and not list(elem):
            empty_states.append(state_id)
    if empty_states:
        warnings.append("状態groupが空です: " + ", ".join(empty_states))
    return empty_states


def validate(path: Path) -> dict[str, object]:
    result: dict[str, object] = {
        "format": FORMAT_NAME,
        "version": 2,
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
    if duplicates:
        errors.append("IDが重複しています: " + ", ".join(duplicates))

    rig_version = detect_rig_version(root, ids)
    missing_required, missing_v2 = validate_required_ids(
        ids, rig_version, errors, warnings
    )
    recommended_missing = sorted(RECOMMENDED_FACE_IDS - ids)
    if recommended_missing:
        warnings.append("推奨IDがありません: " + ", ".join(recommended_missing))

    missing_pivots = validate_pivots(root, ids, rig_version, errors, warnings)
    hybrid_raster, untraceable_assets = validate_source_parts(
        root, rig_version, errors, warnings
    )
    empty_states = validate_state_groups(root, ids, warnings)

    result.update(
        {
            "rig_version": rig_version,
            "ids": sorted(ids),
            "missing_required_ids": missing_required,
            "missing_v2_joint_ids": missing_v2,
            "missing_recommended_ids": recommended_missing,
            "missing_pivots": missing_pivots,
            "hybrid_raster": hybrid_raster,
            "untraceable_raster_assets": untraceable_assets,
            "empty_state_groups": empty_states,
            "valid": not errors,
        }
    )
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
        print(f"[{state}] {args.svg} (rig v{result.get('rig_version', '?')})")
        for message in result["errors"]:
            print(f"ERROR: {message}")
        for message in result["warnings"]:
            print(f"WARN: {message}")
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    sys.exit(main())
