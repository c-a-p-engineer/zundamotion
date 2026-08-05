"""Build ordered AudioPhase entries without owning phase execution."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Tuple

from zundamotion.timeline import Timeline
from zundamotion.utils.subtitle_text import (
    is_effective_subtitle_text,
    normalize_subtitle_text,
)
from zundamotion.utils.text_processing import parse_reading_markup

AudioTaskResult = Tuple[Path, List[Tuple[int, str]], List[Dict[str, Any]]]
AudioFactory = Callable[[str, Dict[str, Any], str], Awaitable[AudioTaskResult]]


def _scene_items(scene: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return the explicit item stream or derive it from legacy ``lines``."""
    items = scene.get("items")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    lines = scene.get("lines")
    if not isinstance(lines, list):
        return []

    derived_items: List[Dict[str, Any]] = []
    for line in lines:
        if not isinstance(line, dict):
            continue
        if "wait" in line:
            derived_items.append({"wait": line})
        elif "text" in line or line.get("image_layers") is None:
            derived_items.append({"say": line})
        else:
            derived_items.append({"image_layers": line})
    return derived_items


def _line_from_item(item: Dict[str, Any]) -> tuple[str, Dict[str, Any]] | None:
    """Normalize one timeline item into its entry type and line mapping."""
    if "say" in item:
        value = item.get("say")
        return "say", value if isinstance(value, dict) else {"text": str(value or "")}
    if "wait" in item:
        value = item.get("wait")
        return (
            "wait",
            value if isinstance(value, dict) and "wait" in value else {"wait": value},
        )
    if "image_layers" in item:
        value = item.get("image_layers")
        return (
            "image_layer",
            value if isinstance(value, dict) else {"image_layers": value},
        )
    return None


def _resolve_speech_text(
    config: Dict[str, Any], line: Dict[str, Any]
) -> tuple[str, str, str]:
    """Resolve TTS text, display text, and effective subtitle text."""
    original_text = str(line.get("text", ""))
    subtitle_config = config.get("subtitle", {}) or {}
    reading_display = str(subtitle_config.get("reading_display", "none")).lower()
    if line.get("reading") or line.get("read"):
        read_text = str(line.get("reading") or line.get("read") or original_text)
        display_from_markup, _ = parse_reading_markup(original_text, reading_display)
    else:
        display_from_markup, read_text = parse_reading_markup(
            original_text, reading_display
        )
    display_text = normalize_subtitle_text(
        line.get("subtitle_text") or display_from_markup
    )
    effective_text = display_text if is_effective_subtitle_text(display_text) else ""
    return read_text, display_text, effective_text


def _prepare_scene_entries(
    *,
    scene: Dict[str, Any],
    config: Dict[str, Any],
    generate_line_audio: AudioFactory,
) -> List[Dict[str, Any]]:
    scene_id = scene["id"]
    entries: List[Dict[str, Any]] = []
    line_idx = 0
    for item in _scene_items(scene):
        if "bgm" in item:
            entries.append(
                {
                    "entry_type": "bgm",
                    "scene_id": scene_id,
                    "bgm_cfg": item.get("bgm") or {},
                }
            )
            continue
        if "topic" in item:
            entries.append(
                {
                    "entry_type": "topic",
                    "scene_id": scene_id,
                    "topic": str(item.get("topic")),
                }
            )
            continue

        normalized = _line_from_item(item)
        if normalized is None:
            continue
        entry_type, line = normalized
        line_idx += 1
        line_id = f"{scene_id}_{line_idx}"
        base_entry = {
            "entry_type": entry_type,
            "scene_id": scene_id,
            "line_idx": line_idx,
            "line_id": line_id,
            "line": line,
        }
        if entry_type == "wait":
            entries.append(base_entry)
            continue
        if entry_type == "image_layer" and line.get("image_layers") is not None:
            entries.append(base_entry)
            continue

        read_text, display_text, effective_text = _resolve_speech_text(config, line)
        entries.append(
            {
                **base_entry,
                "entry_type": "say",
                "read_text": read_text,
                "display_text": display_text,
                "effective_subtitle_text": effective_text,
                "audio_task": asyncio.create_task(
                    generate_line_audio(read_text, line, line_id)
                ),
            }
        )
    return entries


def prepare_audio_entries(
    *,
    scenes: List[Dict[str, Any]],
    config: Dict[str, Any],
    timeline: Timeline,
    generate_line_audio: AudioFactory,
) -> List[Dict[str, Any]]:
    """Build the ordered work list while preserving eager audio task creation."""
    ordered_entries: List[Dict[str, Any]] = []
    default_background = config.get("background", {}).get("default")
    for scene in scenes:
        timeline.add_scene_change(
            scene["id"], scene.get("bg", default_background)
        )
        ordered_entries.extend(
            _prepare_scene_entries(
                scene=scene,
                config=config,
                generate_line_audio=generate_line_audio,
            )
        )
    return ordered_entries
