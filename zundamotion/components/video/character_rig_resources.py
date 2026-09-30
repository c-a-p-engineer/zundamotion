"""Safe local resource resolution for SVG character rigs."""

from __future__ import annotations

from pathlib import Path
import re
import xml.etree.ElementTree as ET

from ...exceptions import ValidationError
from .character_rig_validation import local_name


_XLINK_HREF = "{http://www.w3.org/1999/xlink}href"


def parse_character_rig_svg(source_text: str) -> ET.Element:
    upper = source_text.upper()
    if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
        raise ValidationError("Character rig SVG must not contain DOCTYPE or ENTITY.")
    try:
        root = ET.fromstring(source_text)
    except ET.ParseError as exc:
        raise ValidationError(f"Character rig SVG cannot be parsed: {exc}") from exc
    if local_name(root.tag) != "svg":
        raise ValidationError("Character rig root element must be <svg>.")
    if any(local_name(elem.tag).lower() == "script" for elem in root.iter()):
        raise ValidationError("Character rig SVG must not contain <script>.")
    return root


def resolve_character_rig_resources(
    source_path: Path,
    *,
    project_root: Path | None = None,
    root: ET.Element | None = None,
) -> list[Path]:
    project = (project_root or Path.cwd()).resolve()
    source = source_path.resolve()
    source_dir = source.parent
    if root is None:
        root = parse_character_rig_svg(source.read_text(encoding="utf-8"))

    resolved: list[Path] = []
    for elem in root.iter():
        if local_name(elem.tag) != "image":
            continue
        href = elem.get("href") or elem.get(_XLINK_HREF)
        if not href or href.startswith("data:"):
            continue
        lowered = href.strip().lower()
        if re.match(r"^[a-z][a-z0-9+.-]*:", lowered):
            raise ValidationError(
                f"Character rig image resource '{href}' must be local or embedded."
            )

        resource = (source_dir / href).resolve()
        try:
            resource.relative_to(project)
        except ValueError as exc:
            raise ValidationError(
                f"Character rig image resource '{href}' escapes the project directory."
            ) from exc
        if not resource.exists() or not resource.is_file():
            raise ValidationError(
                f"Character rig image resource '{href}' does not exist."
            )
        resolved.append(resource)

    return sorted(set(resolved), key=lambda item: item.as_posix())


def rewrite_character_rig_resource_hrefs(
    root: ET.Element,
    source_path: Path,
) -> None:
    source_dir = source_path.parent.resolve()
    for elem in root.iter():
        if local_name(elem.tag) != "image":
            continue
        key = "href" if elem.get("href") is not None else _XLINK_HREF
        href = elem.get(key)
        if not href or href.startswith("data:"):
            continue
        elem.set(key, (source_dir / href).resolve().as_uri())
