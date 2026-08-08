from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Tuple

from PIL import Image, ImageDraw, ImageFont
import yaml

from ...exceptions import ValidationError
from ..subtitles.png import _build_background_layer, _load_font_with_fallback
from .render_config import (
    resolve_markdown_background,
    resolve_markdown_characters,
    resolve_markdown_render_config,
)


FRONTMATTER_BOUNDARY = re.compile(r"^---\s*$", re.MULTILINE)
SPEAKER_LINE_RE = re.compile(r"^\s*([^:：]+?)\s*[:：]\s*(.+)\s*$")
MARKDOWN_LAYER_ID = "markdown_panel"

# Preserve historical private imports while keeping resolution in one module.
_resolve_bg = resolve_markdown_background
_character_defaults = resolve_markdown_characters
_markdown_render_config = resolve_markdown_render_config


@dataclass
class Dialogue:
    speaker: str
    text: str


@dataclass(frozen=True)
class MarkdownLine:
    text: str
    kind: str
    level: int = 0


def load_markdown_script(path: Path) -> Dict[str, Any]:
    frontmatter, body = _split_frontmatter(path)
    frontmatter_data = _load_frontmatter(frontmatter, path)
    if "scenes" in frontmatter_data:
        raise ValidationError(
            "Markdown frontmatter does not support 'scenes'. Define script in markdown body only."
        )

    bg_path = resolve_markdown_background(frontmatter_data)
    character_defaults = resolve_markdown_characters(frontmatter_data)
    markdown_config = resolve_markdown_render_config(frontmatter_data)

    intermediate_root = Path("output") / "intermediate" / path.stem
    image_dir = intermediate_root / "images"
    image_dir.mkdir(parents=True, exist_ok=True)

    lines = _build_lines_from_body(
        body,
        image_dir=image_dir,
        characters=character_defaults,
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
    frontmatter = text[matches[0].end() : matches[1].start()].strip()
    body = text[matches[1].end() :].strip()
    return frontmatter, body


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
            markdown_text = _normalize_markdown_block(markdown_buffer)
            markdown_key = _markdown_panel_cache_key(markdown_text, markdown_config)
            if markdown_key != last_markdown_key:
                image_path = _render_markdown_panel(
                    markdown_text,
                    image_dir=image_dir,
                    image_id=markdown_key,
                    markdown_config=markdown_config,
                )
                lines.append(
                    {
                        "image_layers": [
                            {
                                "show": {
                                    "id": MARKDOWN_LAYER_ID,
                                    "path": str(image_path.resolve()),
                                    "scale": markdown_config["layer"]["scale"],
                                    "anchor": markdown_config["layer"]["anchor"],
                                    "position": dict(
                                        markdown_config["layer"]["position"]
                                    ),
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
    speaker = match.group(1).strip()
    text = match.group(2).strip()
    if not speaker or not text:
        return None
    return Dialogue(speaker=speaker, text=text)


def _has_non_empty(lines: List[str]) -> bool:
    return any(line.strip() for line in lines)


def _normalize_markdown_block(lines: List[str]) -> str:
    return "\n".join(lines).strip()


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

    margin = markdown_config["panel"]["margin"]
    panel_left = int(margin["left"])
    panel_top = int(margin["top"])
    panel_right = width - int(margin["right"])
    panel_bottom = height - int(margin["bottom"])
    if panel_right <= panel_left or panel_bottom <= panel_top:
        raise ValidationError(
            "Markdown panel margin is too large for the configured video size."
        )

    panel_width = panel_right - panel_left
    panel_height = panel_bottom - panel_top
    background_layer = _build_background_layer(
        (panel_width, panel_height),
        dict(markdown_config["panel"]["background"]),
    )
    if background_layer is not None:
        image.paste(background_layer, (panel_left, panel_top), background_layer)

    padding = markdown_config["panel"]["padding"]
    inner_left = panel_left + int(padding["left"])
    inner_top = panel_top + int(padding["top"])
    inner_width = panel_width - int(padding["left"]) - int(padding["right"])
    inner_height = panel_height - int(padding["top"]) - int(padding["bottom"])
    if inner_width <= 0 or inner_height <= 0:
        raise ValidationError(
            "Markdown panel padding is too large for the configured panel area."
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


def _markdown_panel_cache_key(
    markdown_text: str, markdown_config: Dict[str, Any]
) -> str:
    raw = json.dumps(
        {"text": markdown_text, "config": markdown_config},
        ensure_ascii=False,
        sort_keys=True,
    )
    return sha1(raw.encode("utf-8")).hexdigest()[:12]


def _fit_markdown_text(
    markdown_text: str,
    *,
    font_path: str,
    preferred_font_size: int,
    min_font_size: int,
    max_width: int,
    max_height: int,
    spacing_override: Any,
    markdown_config: Dict[str, Any],
) -> Tuple[List[MarkdownLine], List[Dict[str, Any]]]:
    chosen_lines: List[MarkdownLine] = []
    chosen_metrics: List[Dict[str, Any]] = []
    source_lines = _tokenize_markdown_lines(markdown_text)

    for font_size in range(preferred_font_size, min_font_size - 1, -2):
        lines, metrics = _wrap_markdown_lines(
            source_lines,
            font_path=font_path,
            base_font_size=font_size,
            max_width=max_width,
            spacing_override=spacing_override,
            markdown_config=markdown_config,
        )
        block_height = _metrics_total_height(metrics)
        block_width = max((metric["width"] for metric in metrics), default=0)
        if block_width <= max_width and block_height <= max_height:
            return lines, metrics
        chosen_lines = lines
        chosen_metrics = metrics
    return chosen_lines, chosen_metrics


def _wrap_markdown_lines(
    source_lines: List[MarkdownLine],
    *,
    font_path: str,
    base_font_size: int,
    max_width: int,
    spacing_override: Any,
    markdown_config: Dict[str, Any],
) -> Tuple[List[MarkdownLine], List[Dict[str, Any]]]:
    text_cfg = markdown_config["text"]
    wrapped_lines: List[MarkdownLine] = []
    metrics: List[Dict[str, Any]] = []

    for source in source_lines:
        if source.kind == "blank":
            spacing = max(
                6, _resolve_line_spacing(spacing_override, base_font_size) // 2
            )
            wrapped_lines.append(source)
            metrics.append(
                {
                    "bbox": (0, 0, 0, spacing),
                    "width": 0,
                    "font_size": base_font_size,
                    "spacing_after": 0,
                }
            )
            continue

        font_size = _markdown_font_size(source, base_font_size, text_cfg)
        font = _load_font_with_fallback(font_path, font_size)
        spacing = _resolve_line_spacing(spacing_override, font_size)
        prefix = _line_prefix(source)
        list_indent = int(text_cfg.get("list_indent", 28)) if prefix else 0
        available_width = max_width - list_indent
        for index, wrapped in enumerate(
            _wrap_text_to_width(source.text, font, max(80, available_width))
        ):
            display_text = f"{prefix}{wrapped}" if index == 0 and prefix else wrapped
            line_obj = MarkdownLine(
                text=display_text, kind=source.kind, level=source.level
            )
            bbox = _text_metric(font, display_text)
            wrapped_lines.append(line_obj)
            metrics.append(
                {
                    "bbox": bbox,
                    "width": bbox[2] - bbox[0],
                    "font_size": font_size,
                    "spacing_after": spacing,
                }
            )
        if metrics:
            metrics[-1]["spacing_after"] = _spacing_after_line(source, spacing)
    return wrapped_lines, metrics


def _tokenize_markdown_lines(markdown_text: str) -> List[MarkdownLine]:
    normalized = (
        markdown_text.replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\t", "    ")
    )
    lines: List[MarkdownLine] = []
    for raw in normalized.split("\n"):
        stripped = raw.strip()
        if not stripped:
            lines.append(MarkdownLine(text="", kind="blank"))
            continue

        heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading:
            lines.append(
                MarkdownLine(
                    text=heading.group(2).strip(),
                    kind="heading",
                    level=len(heading.group(1)),
                )
            )
            continue

        bullet = re.match(r"^([-*+])\s+(.+)$", stripped)
        if bullet:
            lines.append(MarkdownLine(text=bullet.group(2).strip(), kind="bullet"))
            continue

        numbered = re.match(r"^(\d+)\.\s+(.+)$", stripped)
        if numbered:
            lines.append(
                MarkdownLine(
                    text=f"{numbered.group(1)}. {numbered.group(2).strip()}",
                    kind="numbered",
                )
            )
            continue

        quote = re.match(r"^>\s+(.+)$", stripped)
        if quote:
            lines.append(MarkdownLine(text=quote.group(1).strip(), kind="quote"))
            continue

        lines.append(MarkdownLine(text=stripped, kind="paragraph"))
    return lines


def _markdown_font_size(
    line: MarkdownLine, base_font_size: int, text_cfg: Dict[str, Any]
) -> int:
    if line.kind != "heading":
        return base_font_size
    if line.level <= 1:
        return max(
            base_font_size,
            int(round(base_font_size * float(text_cfg["heading_scale"]))),
        )
    if line.level <= 3:
        return max(
            base_font_size,
            int(round(base_font_size * float(text_cfg["subheading_scale"]))),
        )
    return base_font_size


def _line_prefix(line: MarkdownLine) -> str:
    if line.kind == "bullet":
        return "• "
    if line.kind == "quote":
        return "│ "
    return ""


def _wrap_text_to_width(
    text: str, font: ImageFont.FreeTypeFont, max_width: int
) -> List[str]:
    if not text:
        return [""]
    lines: List[str] = []
    current = ""
    for char in text:
        candidate = f"{current}{char}"
        if current and _text_width(font, candidate) > max_width:
            lines.append(current)
            current = char
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [text]


def _text_width(font: ImageFont.FreeTypeFont, text: str) -> int:
    x0, _, x1, _ = _text_metric(font, text)
    return x1 - x0


def _text_metric(
    font: ImageFont.FreeTypeFont, text: str
) -> Tuple[int, int, int, int]:
    probe = text or "Ag"
    if hasattr(font, "getbbox"):
        bbox = font.getbbox(probe)
    else:  # pragma: no cover - Pillow fallback
        width, height = font.getsize(probe)
        bbox = (0, 0, width, height)
    x0, y0, x1, y1 = bbox
    return int(x0), int(y0), int(x1), int(y1 - y0)


def _metrics_total_height(metrics: List[Dict[str, Any]]) -> int:
    return sum(
        int(metric["bbox"][3]) + int(metric["spacing_after"])
        for metric in metrics
    )


def _resolve_line_spacing(value: Any, font_size: int) -> int:
    if value is not None:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            pass
    return max(8, int(round(font_size * 0.24)))


def _spacing_after_line(line: MarkdownLine, base_spacing: int) -> int:
    if line.kind == "heading":
        return int(round(base_spacing * (1.2 if line.level <= 2 else 1.0)))
    if line.kind in {"bullet", "numbered", "quote"}:
        return max(6, int(round(base_spacing * 0.7)))
    return base_spacing
