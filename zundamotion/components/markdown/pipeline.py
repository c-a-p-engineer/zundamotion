from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Tuple

from PIL import Image, ImageDraw
import yaml

from ...exceptions import ValidationError
from ..subtitles.png import _build_background_layer, _load_font_with_fallback
from .render_config import (
    resolve_markdown_background,
    resolve_markdown_characters,
    resolve_markdown_render_config,
)
from .text_layout import (
    fit_markdown_text as _fit_markdown_text,
    tokenize_markdown_lines as _tokenize_markdown_lines,
)


FRONTMATTER_BOUNDARY = re.compile(r"^---\s*$", re.MULTILINE)
SPEAKER_LINE_RE = re.compile(r"^\s*([^:：]+?)\s*[:：]\s*(.+)\s*$")
MARKDOWN_LAYER_ID = "markdown_panel"

# Historical private imports remain available from this module.
_resolve_bg = resolve_markdown_background
_character_defaults = resolve_markdown_characters
_markdown_render_config = resolve_markdown_render_config


@dataclass
class Dialogue:
    speaker: str
    text: str


def load_markdown_script(path: Path) -> Dict[str, Any]:
    frontmatter, body = _split_frontmatter(path)
    frontmatter_data = _load_frontmatter(frontmatter, path)
    if "scenes" in frontmatter_data:
        raise ValidationError(
            "Markdown frontmatter does not support 'scenes'. Define script in markdown body only."
        )

    bg_path = resolve_markdown_background(frontmatter_data)
    characters = resolve_markdown_characters(frontmatter_data)
    markdown_config = resolve_markdown_render_config(frontmatter_data)
    image_dir = Path("output") / "intermediate" / path.stem / "images"
    image_dir.mkdir(parents=True, exist_ok=True)

    lines = _build_lines_from_body(
        body,
        image_dir=image_dir,
        characters=characters,
        markdown_config=markdown_config,
    )
    merged: Dict[str, Any] = dict(frontmatter_data)
    merged["scenes"] = [{"id": "markdown-main", "bg": bg_path, "lines": lines}]
    return merged


def _split_frontmatter(path: Path) -> Tuple[str, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        raise ValidationError(
            f"Markdown script must start with YAML frontmatter ('---'): {path}"
        )
    matches = list(FRONTMATTER_BOUNDARY.finditer(text))
    if len(matches) < 2:
        raise ValidationError(
            f"Markdown frontmatter closing boundary ('---') is missing: {path}"
        )
    return (
        text[matches[0].end() : matches[1].start()].strip(),
        text[matches[1].end() :].strip(),
    )


def _load_frontmatter(frontmatter: str, path: Path) -> Dict[str, Any]:
    try:
        data = yaml.safe_load(frontmatter) or {}
    except yaml.YAMLError as exc:
        mark = getattr(exc, "mark", None)
        raise ValidationError(
            f"Invalid Markdown frontmatter YAML in {path}: {exc}",
            line_number=mark.line + 1 if mark else None,
            column_number=mark.column + 1 if mark else None,
        )
    if not isinstance(data, dict):
        raise ValidationError("Markdown frontmatter must be a mapping.")
    return data


def _build_lines_from_body(
    body: str,
    *,
    image_dir: Path,
    characters: Dict[str, Dict[str, Any]],
    markdown_config: Dict[str, Any],
) -> List[Dict[str, Any]]:
    if not body.strip():
        raise ValidationError("Markdown body must contain markdown text or dialogue lines.")

    lines: List[Dict[str, Any]] = []
    markdown_buffer: List[str] = []
    last_markdown_key: str | None = None
    for raw_line in body.splitlines():
        line = raw_line.rstrip()
        dialogue = _parse_dialogue(line)
        if dialogue is None:
            markdown_buffer.append(line)
            continue

        if _has_non_empty(markdown_buffer):
            markdown_text = "\n".join(markdown_buffer).strip()
            markdown_key = _markdown_panel_cache_key(markdown_text, markdown_config)
            if markdown_key != last_markdown_key:
                image_path = _render_markdown_panel(
                    markdown_text,
                    image_dir=image_dir,
                    image_id=markdown_key,
                    markdown_config=markdown_config,
                )
                layer = markdown_config["layer"]
                lines.append(
                    {
                        "image_layers": [
                            {
                                "show": {
                                    "id": MARKDOWN_LAYER_ID,
                                    "path": str(image_path.resolve()),
                                    "scale": layer["scale"],
                                    "anchor": layer["anchor"],
                                    "position": dict(layer["position"]),
                                }
                            }
                        ]
                    }
                )
                last_markdown_key = markdown_key
            markdown_buffer = []

        line_obj: Dict[str, Any] = {
            "speaker_name": dialogue.speaker,
            "text": dialogue.text,
        }
        visible_chars = _visible_characters(characters)
        if visible_chars:
            line_obj["characters"] = visible_chars
        lines.append(line_obj)

    if not any("text" in line for line in lines):
        raise ValidationError(
            "Markdown body must contain at least one dialogue line in '話者:セリフ' format."
        )
    return lines


def _parse_dialogue(line: str) -> Dialogue | None:
    match = SPEAKER_LINE_RE.match(line)
    if not match:
        return None
    speaker, text = match.group(1).strip(), match.group(2).strip()
    if not speaker or not text:
        return None
    return Dialogue(speaker=speaker, text=text)


def _has_non_empty(lines: List[str]) -> bool:
    return any(line.strip() for line in lines)


def _visible_characters(
    characters: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for name, cfg in characters.items():
        merged = dict(cfg)
        if "position" not in merged and ("x" in merged or "y" in merged):
            merged["position"] = {
                "x": merged.get("x", 0),
                "y": merged.get("y", 0),
            }
        merged["name"] = name
        result.append(merged)
    return result


def _render_markdown_panel(
    markdown_text: str,
    *,
    image_dir: Path,
    image_id: str,
    markdown_config: Dict[str, Any],
) -> Path:
    output_path = image_dir / f"panel-{image_id}.png"
    if output_path.exists():
        return output_path

    width = int(markdown_config["canvas"]["width"])
    height = int(markdown_config["canvas"]["height"])
    image = Image.new("RGBA", (width, height), color=(0, 0, 0, 0))
    panel_left, panel_top, panel_right, panel_bottom = _panel_bounds(
        width, height, markdown_config["panel"]["margin"]
    )
    panel_width = panel_right - panel_left
    panel_height = panel_bottom - panel_top
    background_layer = _build_background_layer(
        (panel_width, panel_height),
        dict(markdown_config["panel"]["background"]),
    )
    if background_layer is not None:
        image.paste(background_layer, (panel_left, panel_top), background_layer)

    inner_left, inner_top, inner_width, inner_height = _inner_bounds(
        panel_left,
        panel_top,
        panel_width,
        panel_height,
        markdown_config["panel"]["padding"],
    )
    text_cfg = markdown_config["text"]
    wrapped_lines, line_metrics = _fit_markdown_text(
        markdown_text,
        font_path=str(text_cfg["font_path"]),
        preferred_font_size=int(text_cfg["font_size"]),
        min_font_size=int(text_cfg["min_font_size"]),
        max_width=inner_width,
        max_height=inner_height,
        spacing_override=text_cfg.get("line_spacing"),
        markdown_config=markdown_config,
    )

    draw = ImageDraw.Draw(image)
    current_y = float(inner_top)
    for line, metric in zip(wrapped_lines, line_metrics):
        x0, y0, _, line_height = metric["bbox"]
        font = _load_font_with_fallback(
            str(text_cfg["font_path"]), int(metric["font_size"])
        )
        if line.text:
            draw.text(
                (inner_left - x0, current_y - y0),
                line.text,
                fill=text_cfg["color"],
                font=font,
            )
        current_y += line_height + int(metric["spacing_after"])
    image.save(output_path)
    return output_path


def _panel_bounds(
    width: int, height: int, margin: Dict[str, Any]
) -> tuple[int, int, int, int]:
    left = int(margin["left"])
    top = int(margin["top"])
    right = width - int(margin["right"])
    bottom = height - int(margin["bottom"])
    if right <= left or bottom <= top:
        raise ValidationError(
            "Markdown panel margin is too large for the configured video size."
        )
    return left, top, right, bottom


def _inner_bounds(
    panel_left: int,
    panel_top: int,
    panel_width: int,
    panel_height: int,
    padding: Dict[str, Any],
) -> tuple[int, int, int, int]:
    left = panel_left + int(padding["left"])
    top = panel_top + int(padding["top"])
    width = panel_width - int(padding["left"]) - int(padding["right"])
    height = panel_height - int(padding["top"]) - int(padding["bottom"])
    if width <= 0 or height <= 0:
        raise ValidationError(
            "Markdown panel padding is too large for the configured panel area."
        )
    return left, top, width, height


def _markdown_panel_cache_key(
    markdown_text: str, markdown_config: Dict[str, Any]
) -> str:
    raw = json.dumps(
        {"text": markdown_text, "config": markdown_config},
        ensure_ascii=False,
        sort_keys=True,
    )
    return sha1(raw.encode("utf-8")).hexdigest()[:12]
