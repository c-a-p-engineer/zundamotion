"""Deterministic SVG rig materialization into existing PNG face assets."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import importlib
from pathlib import Path
import re
from typing import Any, Mapping
import xml.etree.ElementTree as ET

from ...cache import CacheManager
from ...exceptions import ValidationError
from ..config.validate_character_rig import resolve_character_rig_path
from .character_rig_validation import validate as validate_rig_file
from .character_rig_resources import (
    parse_character_rig_svg,
    resolve_character_rig_resources,
    rewrite_character_rig_resource_hrefs,
)


_MATERIALIZER_VERSION = 1
_STATE_MAPPING_VERSION = 1
_EYE_STATES = {
    "open": "eyes-open",
    "close": "eyes-closed",
}
_MOUTH_STATES = {
    "close": "mouth-closed",
    "half": "mouth-small",
    "open": "mouth-a",
}
_ALL_FACE_STATE_IDS = {
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


@dataclass(frozen=True)
class MaterializedCharacterRig:
    source_path: Path
    raster_width: int
    base: Path
    eyes: dict[str, Path]
    mouth: dict[str, Path]

    def face_paths(self) -> dict[str, dict[str, Path]]:
        return {
            "eyes": dict(self.eyes),
            "mouth": dict(self.mouth),
        }


class CharacterRigMaterializer:
    """Materialize a validated rig to persistent cache entries."""

    def __init__(self, cache_manager: CacheManager) -> None:
        self.cache_manager = cache_manager

    async def materialize(
        self,
        rig_config: Mapping[str, Any],
    ) -> MaterializedCharacterRig:
        path_value = str(rig_config.get("path") or "")
        source_path = resolve_character_rig_path(path_value)
        validation = validate_rig_file(source_path)
        if not validation.get("valid"):
            detail = "; ".join(str(item) for item in validation.get("errors") or [])
            raise ValidationError(
                "Character rig is invalid: " + (detail or "unknown validation error")
            )

        source_text = source_path.read_text(encoding="utf-8")
        root = parse_character_rig_svg(source_text)
        referenced_assets = resolve_character_rig_resources(
            source_path,
            root=root,
        )
        width = _resolve_raster_width(root, rig_config.get("raster_width"))

        source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
        resource_hashes = [
            {
                "path": path.relative_to(Path.cwd().resolve()).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in referenced_assets
        ]
        common_key = {
            "op": "character_rig_materialize",
            "materializer_version": _MATERIALIZER_VERSION,
            "state_mapping_version": _STATE_MAPPING_VERSION,
            "source_sha256": source_hash,
            "resources": resource_hashes,
            "raster_width": width,
            "rig_validation_version": validation.get("version"),
        }

        base = await self._materialize_variant(
            source_path=source_path,
            source_text=source_text,
            raster_width=width,
            key_data={**common_key, "variant": "base"},
            variant="base",
            selected_state=None,
        )

        eyes: dict[str, Path] = {}
        for runtime_state, svg_state in _EYE_STATES.items():
            eyes[runtime_state] = await self._materialize_variant(
                source_path=source_path,
                source_text=source_text,
                raster_width=width,
                key_data={
                    **common_key,
                    "variant": "eyes",
                    "state": runtime_state,
                    "svg_state": svg_state,
                },
                variant="overlay",
                selected_state=svg_state,
            )

        mouth: dict[str, Path] = {}
        for runtime_state, svg_state in _MOUTH_STATES.items():
            mouth[runtime_state] = await self._materialize_variant(
                source_path=source_path,
                source_text=source_text,
                raster_width=width,
                key_data={
                    **common_key,
                    "variant": "mouth",
                    "state": runtime_state,
                    "svg_state": svg_state,
                },
                variant="overlay",
                selected_state=svg_state,
            )

        return MaterializedCharacterRig(
            source_path=source_path,
            raster_width=width,
            base=base,
            eyes=eyes,
            mouth=mouth,
        )

    async def _materialize_variant(
        self,
        *,
        source_path: Path,
        source_text: str,
        raster_width: int,
        key_data: dict[str, Any],
        variant: str,
        selected_state: str | None,
    ) -> Path:
        async def creator(output_path: Path) -> Path:
            await asyncio.to_thread(
                _render_variant,
                source_path,
                source_text,
                output_path,
                raster_width,
                variant,
                selected_state,
            )
            return output_path

        return await self.cache_manager.get_or_create(
            key_data=key_data,
            file_name="character_rig",
            extension="png",
            creator_func=creator,
        )


def rig_runtime_enabled(character: Mapping[str, Any]) -> bool:
    rig = character.get("rig")
    return isinstance(rig, Mapping) and rig.get("enabled", True) is not False


def _resolve_raster_width(root: ET.Element, requested: Any) -> int:
    if requested is not None:
        width = int(requested)
    else:
        width = _numeric_dimension(root.get("width"))
        if width is None:
            raw_viewbox = (root.get("viewBox") or "").replace(",", " ").split()
            if len(raw_viewbox) != 4:
                raise ValidationError(
                    "Character rig requires raster_width when SVG viewBox is invalid."
                )
            try:
                width = int(round(float(raw_viewbox[2])))
            except ValueError as exc:
                raise ValidationError(
                    "Character rig viewBox width must be numeric."
                ) from exc
    if not 1 <= width <= 4096:
        raise ValidationError(
            "Character rig raster width must be between 1 and 4096."
        )
    return width


def _numeric_dimension(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except ValueError:
        return None
    if numeric <= 0:
        return None
    return int(round(numeric))


def _render_variant(
    source_path: Path,
    source_text: str,
    output_path: Path,
    raster_width: int,
    variant: str,
    selected_state: str | None,
) -> None:
    root = parse_character_rig_svg(source_text)
    rewrite_character_rig_resource_hrefs(root, source_path)

    if variant == "base":
        _set_base_face_state(root)
    else:
        if selected_state is None:
            raise ValidationError("Character rig overlay variant requires a state.")
        _isolate_state(root, selected_state)

    try:
        cairosvg = importlib.import_module("cairosvg")
    except ImportError as exc:
        raise ValidationError(
            "Character rig runtime requires CairoSVG. "
            "Install with: pip install 'zundamotion[rig]'"
        ) from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cairosvg.svg2png(
        bytestring=ET.tostring(root, encoding="utf-8"),
        write_to=str(output_path),
        output_width=raster_width,
        unsafe=False,
    )


def _set_base_face_state(root: ET.Element) -> None:
    visible = {"eyes-open", "mouth-closed"}
    for elem in root.iter():
        elem_id = elem.get("id")
        if elem_id in _ALL_FACE_STATE_IDS:
            _set_visible(elem, elem_id in visible)


def _isolate_state(root: ET.Element, selected_state: str) -> None:
    target = _find_by_id(root, selected_state)
    if target is None:
        raise ValidationError(
            f"Character rig is missing required runtime state '{selected_state}'."
        )

    parent_by_elem = {
        child: parent
        for parent in root.iter()
        for child in list(parent)
    }
    keep: set[ET.Element] = {target}
    current = target
    while current in parent_by_elem:
        current = parent_by_elem[current]
        keep.add(current)

    for parent in list(keep):
        for child in list(parent):
            if child not in keep:
                _set_visible(child, False)

    _set_visible(target, True)


def _find_by_id(root: ET.Element, elem_id: str) -> ET.Element | None:
    return next((elem for elem in root.iter() if elem.get("id") == elem_id), None)


def _set_visible(elem: ET.Element, visible: bool) -> None:
    style = elem.get("style") or ""
    style = re.sub(
        r"(?i)(?:^|;)\s*(?:display|opacity)\s*:[^;]*",
        "",
        style,
    ).strip("; ")
    suffix = (
        "display:inline !important;opacity:1 !important"
        if visible
        else "display:none !important;opacity:0 !important"
    )
    elem.set("style", (style + ";" + suffix).strip(";"))
