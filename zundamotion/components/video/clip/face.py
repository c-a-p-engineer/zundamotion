from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...utils.ffmpeg_ops import calculate_overlay_position
from ...utils.logger import logger


def _enable_expr(
    segments: List[Dict[str, Any]], *, start_offset: float = 0.0
) -> Optional[str]:
    try:
        parts: List[str] = []
        for seg in segments:
            end = float(seg.get("end", 0))
            start = float(seg.get("start", 0))
            if start_offset > 0.0:
                if end <= start_offset:
                    continue
                if start < start_offset:
                    start = start_offset
            if end <= start:
                continue
            parts.append(f"between(t,{start:.3f},{end:.3f})")
        if not parts:
            return None
        return "+".join(parts)
    except Exception:
        return None


async def apply_face_overlays(
    *,
    renderer: Any,
    face_anim: Optional[Dict[str, Any]],
    subtitle_line_config: Optional[Dict[str, Any]],
    char_overlay_placement: Dict[str, Dict[str, str]],
    duration: float,
    cmd: List[str],
    input_layers: List[Dict[str, Any]],
    filter_complex_parts: List[str],
    overlay_streams: List[str],
    overlay_filters: List[str],
) -> None:
    """Apply mouth/eye overlays for face animation."""

    if not face_anim or not isinstance(face_anim, dict):
        return

    target_name = face_anim.get("target_name")
    if not target_name:
        return

    placement = char_overlay_placement.get(str(target_name))
    if not placement and subtitle_line_config:
        try:
            for character in subtitle_line_config.get("characters") or []:
                if character.get("name") != target_name:
                    continue
                scale = float(character.get("scale", 1.0))
                anchor = character.get("anchor", "bottom_center")
                pos = character.get("position", {"x": "0", "y": "0"}) or {}
                x_expr, y_expr = calculate_overlay_position(
                    "W",
                    "H",
                    "w",
                    "h",
                    str(anchor),
                    str(pos.get("x", "0")),
                    str(pos.get("y", "0")),
                )
                enter_val = character.get("enter")
                enter_effect = (
                    str(enter_val).lower()
                    if enter_val and not isinstance(enter_val, bool)
                    else ("fade" if enter_val else "")
                )
                enter_duration = 0.0
                try:
                    enter_duration = float(character.get("enter_duration", 0.0))
                except Exception:
                    enter_duration = 0.0
                placement = {
                    "x_expr": x_expr,
                    "y_expr": y_expr,
                    "scale": str(scale),
                    "enter_effect": enter_effect,
                    "enter_duration": f"{enter_duration:.3f}",
                    "expression": str(character.get("expression", "default")),
                    "dynamic_position": False,
                }
                break
        except Exception:
            placement = None

    if not placement:
        return

    scale_raw = placement.get("scale_orig") or placement.get("scale") or "1.0"
    try:
        scale = float(scale_raw)
    except Exception:
        scale = 1.0

    x_fix = placement.get("x_num") or placement.get("x_expr") or "0"
    y_fix = placement.get("y_num") or placement.get("y_expr") or "0"
    enter_effect = str(placement.get("enter_effect") or "")
    try:
        enter_duration_val = float(placement.get("enter_duration", 0.0) or 0.0)
    except Exception:
        enter_duration_val = 0.0
    fade_str = placement.get("fade", "")
    dynamic_flag = placement.get("dynamic_position")
    if isinstance(dynamic_flag, str):
        dynamic_flag = dynamic_flag.lower() in {"1", "true", "yes", "on"}
    use_dynamic = bool(dynamic_flag) or enter_effect.startswith("slide")
    x_pos = placement.get("x_expr") if use_dynamic else x_fix
    y_pos = placement.get("y_expr") if use_dynamic else y_fix

    base_dir = Path(f"assets/characters/{target_name}")
    expression = str(placement.get("expression") or "default")
    expr_dir = base_dir / expression

    def _first_dir(candidates: List[Path]) -> Path:
        for candidate in candidates:
            try:
                if candidate.exists() and candidate.is_dir():
                    return candidate
            except Exception:
                continue
        return base_dir

    mouth_dir = _first_dir([expr_dir / "mouth", base_dir / "mouth", base_dir / "mouth" / expression])
    eyes_dir = _first_dir([expr_dir / "eyes", base_dir / "eyes", base_dir / "eyes" / expression])

    def _pick_file(expr_path: Path, common_path: Path, name: str) -> Path:
        candidate_expr = expr_path / name
        candidate_common = common_path / name
        return candidate_expr if candidate_expr.exists() else candidate_common

    mouth_close = _pick_file(expr_dir / "mouth", base_dir / "mouth", "close.png")
    mouth_half = _pick_file(expr_dir / "mouth", base_dir / "mouth", "half.png")
    mouth_open = _pick_file(expr_dir / "mouth", base_dir / "mouth", "open.png")
    eyes_open = _pick_file(expr_dir / "eyes", base_dir / "eyes", "open.png")
    eyes_close = _pick_file(expr_dir / "eyes", base_dir / "eyes", "close.png")

    try:
        mouth_segments = face_anim.get("mouth") or []
        eyes_segments = face_anim.get("eyes") or []
        logger.debug(
            "[FaceAnim] target=%s scale=%s mouth(close=%s,half=%s,open=%s) eyes(open=%s,close=%s) segs(m=%d,e=%d)",
            target_name,
            scale,
            mouth_close.exists(),
            mouth_half.exists(),
            mouth_open.exists(),
            eyes_open.exists(),
            eyes_close.exists(),
            len(mouth_segments) if isinstance(mouth_segments, list) else 0,
            len(eyes_segments) if isinstance(eyes_segments, list) else 0,
        )
    except Exception:
        pass

    def _add_image_input(path: Path) -> Optional[int]:
        if path.exists():
            cmd.extend(["-loop", "1", "-i", str(path.resolve())])
            index = len(input_layers)
            input_layers.append({"type": "video", "index": index})
            return index
        return None

    preprocessed_inputs: set[int] = set()

    async def _add_preprocessed_overlay(path: Path, scale_value: float) -> Optional[int]:
        try:
            if os.environ.get("FACE_CACHE_DISABLE", "0") == "1":
                return _add_image_input(path)
            thr_env = os.environ.get("FACE_ALPHA_THRESHOLD")
            thr = int(thr_env) if (thr_env and thr_env.isdigit()) else 128
            cached = await renderer.face_cache.get_scaled_overlay(path, float(scale_value), thr)
            idx = _add_image_input(cached)
            if idx is not None:
                preprocessed_inputs.add(idx)
            return idx
        except Exception:
            return _add_image_input(path)

    def _prep_overlay(
        input_index: int,
        scale_value: float,
        out_label: str,
        fade_add: str = "",
    ) -> None:
        if input_index in preprocessed_inputs:
            filter_complex_parts.append(
                f"[{input_index}:v]format=rgba{fade_add}[{out_label}]"
            )
        else:
            filter_complex_parts.append(
                f"[{input_index}:v]format=rgba{fade_add},scale=iw*{scale_value}:ih*{scale_value}[{out_label}]"
            )

    eyes_segments = face_anim.get("eyes") or []
    eyes_close_expr = _enable_expr(eyes_segments) if eyes_segments else None
    if eyes_close.exists() and eyes_close_expr:
        idx = await _add_preprocessed_overlay(eyes_close, float(scale))
        if idx is not None:
            label = f"eyes_close_scaled_{idx}"
            _prep_overlay(idx, float(scale), label, fade_str)
            overlay_streams.append(f"[{label}]")
            overlay_filters.append(
                f"overlay=x={x_pos}:y={y_pos}:enable='{eyes_close_expr}'"
            )

    mouth_segments = face_anim.get("mouth") or []
    if not isinstance(mouth_segments, list) or not mouth_segments:
        return

    half_segments = [s for s in mouth_segments if s.get("state") == "half"]
    open_segments = [s for s in mouth_segments if s.get("state") == "open"]

    delayed_effects = {"fade", "slide_left", "slide_right", "slide_top", "slide_bottom"}
    requires_delay = enter_effect in delayed_effects and enter_duration_val > 0.0
    start_offset = enter_duration_val if requires_delay else 0.0
    if start_offset > 0.0:
        logger.debug(
            "[FaceAnim] Deferring mouth animation until %.2fs due to enter=%s",
            start_offset,
            enter_effect,
        )

    if half_segments:
        half_expr = _enable_expr(half_segments, start_offset=start_offset)
        if half_expr and mouth_half.exists():
            idx = await _add_preprocessed_overlay(mouth_half, float(scale))
            if idx is not None:
                label = f"mouth_half_scaled_{idx}"
                _prep_overlay(idx, float(scale), label, fade_str)
                overlay_streams.append(f"[{label}]")
                overlay_filters.append(
                    f"overlay=x={x_pos}:y={y_pos}:enable='{half_expr}'"
                )

    if open_segments:
        open_expr = _enable_expr(open_segments, start_offset=start_offset)
        if open_expr and mouth_open.exists():
            idx = await _add_preprocessed_overlay(mouth_open, float(scale))
            if idx is not None:
                label = f"mouth_open_scaled_{idx}"
                _prep_overlay(idx, float(scale), label, fade_str)
                overlay_streams.append(f"[{label}]")
                overlay_filters.append(
                    f"overlay=x={x_pos}:y={y_pos}:enable='{open_expr}'"
                )
