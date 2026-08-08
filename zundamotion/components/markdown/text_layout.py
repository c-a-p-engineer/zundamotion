"""Markdown tokenization, wrapping, and text layout helpers."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Dict, List, Tuple

from PIL import ImageFont

from ..subtitles.png import _load_font_with_fallback


@dataclass(frozen=True)
class MarkdownLine:
    text: str
    kind: str
    level: int = 0


def fit_markdown_text(
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
    source_lines = tokenize_markdown_lines(markdown_text)
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
        chosen_lines, chosen_metrics = lines, metrics
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
            spacing = max(6, _resolve_line_spacing(spacing_override, base_font_size) // 2)
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
        available_width = max_width - (int(text_cfg.get("list_indent", 28)) if prefix else 0)
        for index, wrapped in enumerate(
            _wrap_text_to_width(source.text, font, max(80, available_width))
        ):
            display_text = f"{prefix}{wrapped}" if index == 0 and prefix else wrapped
            line_obj = MarkdownLine(display_text, source.kind, source.level)
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


def tokenize_markdown_lines(markdown_text: str) -> List[MarkdownLine]:
    normalized = markdown_text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ")
    lines: List[MarkdownLine] = []
    for raw in normalized.split("\n"):
        stripped = raw.strip()
        if not stripped:
            lines.append(MarkdownLine("", "blank"))
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading:
            lines.append(MarkdownLine(heading.group(2).strip(), "heading", len(heading.group(1))))
            continue
        bullet = re.match(r"^([-*+])\s+(.+)$", stripped)
        if bullet:
            lines.append(MarkdownLine(bullet.group(2).strip(), "bullet"))
            continue
        numbered = re.match(r"^(\d+)\.\s+(.+)$", stripped)
        if numbered:
            lines.append(MarkdownLine(f"{numbered.group(1)}. {numbered.group(2).strip()}", "numbered"))
            continue
        quote = re.match(r"^>\s+(.+)$", stripped)
        if quote:
            lines.append(MarkdownLine(quote.group(1).strip(), "quote"))
            continue
        lines.append(MarkdownLine(stripped, "paragraph"))
    return lines


def _markdown_font_size(line: MarkdownLine, base_font_size: int, text_cfg: Dict[str, Any]) -> int:
    if line.kind != "heading":
        return base_font_size
    scale = text_cfg["heading_scale"] if line.level <= 1 else text_cfg["subheading_scale"]
    if line.level > 3:
        return base_font_size
    return max(base_font_size, int(round(base_font_size * float(scale))))


def _line_prefix(line: MarkdownLine) -> str:
    if line.kind == "bullet":
        return "• "
    if line.kind == "quote":
        return "│ "
    return ""


def _wrap_text_to_width(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
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


def _text_metric(font: ImageFont.FreeTypeFont, text: str) -> Tuple[int, int, int, int]:
    probe = text or "Ag"
    if hasattr(font, "getbbox"):
        bbox = font.getbbox(probe)
    else:  # pragma: no cover - Pillow fallback
        width, height = font.getsize(probe)
        bbox = (0, 0, width, height)
    x0, y0, x1, y1 = bbox
    return int(x0), int(y0), int(x1), int(y1 - y0)


def _metrics_total_height(metrics: List[Dict[str, Any]]) -> int:
    return sum(int(metric["bbox"][3]) + int(metric["spacing_after"]) for metric in metrics)


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
