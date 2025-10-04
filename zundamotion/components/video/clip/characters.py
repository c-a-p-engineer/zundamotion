from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...utils.logger import logger
from .effects import resolve_character_effects


@dataclass
class CharacterInputs:
    """Result of preparing character overlays."""

    indices: Dict[int, int]
    effective_scales: Dict[int, float]
    any_visible: bool
    metadata: Dict[int, Dict[str, Any]]


async def collect_character_inputs(
    *,
    renderer: Any,
    characters_config: List[Dict[str, Any]],
    cmd: List[str],
    input_layers: List[Dict[str, Any]],
) -> CharacterInputs:
    """Collect FFmpeg inputs for character overlays and gather placement metadata."""

    character_indices: Dict[int, int] = {}
    char_effective_scale: Dict[int, float] = {}
    any_character_visible = False
    metadata: Dict[int, Dict[str, Any]] = {}

    def _resolve_char_base_image(name: str, expr: str) -> Optional[Path]:
        base_dir = Path(f"assets/characters/{name}")
        candidates = [
            base_dir / expr / "base.png",
            base_dir / f"{expr}.png",
            base_dir / "default" / "base.png",
            base_dir / "default.png",
        ]
        for candidate in candidates:
            try:
                if candidate.exists():
                    return candidate
            except Exception:
                continue
        return None

    for i, char_config in enumerate(characters_config):
        if not char_config.get("visible", False):
            continue

        any_character_visible = True
        char_name = char_config.get("name")
        char_expression = char_config.get("expression", "default")
        if not char_name:
            logger.warning("Skipping character with missing name.")
            continue

        char_image_path = _resolve_char_base_image(str(char_name), str(char_expression))
        if not char_image_path:
            logger.warning(
                "Character image not found for %s/%s (and default). Skipping.",
                char_name,
                char_expression,
            )
            continue

        try:
            scale_cfg = float(char_config.get("scale", 1.0))
        except Exception:
            scale_cfg = 1.0

        use_char_cache = os.environ.get("CHAR_CACHE_DISABLE", "0") != "1"
        if use_char_cache and abs(scale_cfg - 1.0) > 1e-6:
            try:
                thr_env = os.environ.get("CHAR_ALPHA_THRESHOLD")
                thr = int(thr_env) if (thr_env and thr_env.isdigit()) else 128
                scaled_path = await renderer.face_cache.get_scaled_overlay(
                    char_image_path,
                    float(scale_cfg),
                    thr,
                )
                character_indices[i] = len(input_layers)
                cmd.extend(["-loop", "1", "-i", str(scaled_path.resolve())])
                input_layers.append({"type": "video", "index": len(input_layers)})
                effective_scale = 1.0
            except Exception:
                character_indices[i] = len(input_layers)
                cmd.extend(["-loop", "1", "-i", str(char_image_path.resolve())])
                input_layers.append({"type": "video", "index": len(input_layers)})
                effective_scale = scale_cfg
        else:
            character_indices[i] = len(input_layers)
            cmd.extend(["-loop", "1", "-i", str(char_image_path.resolve())])
            input_layers.append({"type": "video", "index": len(input_layers)})
            effective_scale = scale_cfg

        char_effective_scale[i] = float(effective_scale)
        metadata[i] = {
            "name": str(char_name),
            "expression": str(char_expression),
            "image_path": char_image_path,
        }

    return CharacterInputs(
        indices=character_indices,
        effective_scales=char_effective_scale,
        any_visible=any_character_visible,
        metadata=metadata,
    )


def build_character_overlays(
    *,
    renderer: Any,
    characters_config: List[Dict[str, Any]],
    duration: float,
    character_indices: Dict[int, int],
    char_effective_scale: Dict[int, float],
    filter_complex_parts: List[str],
    overlay_streams: List[str],
    overlay_filters: List[str],
    use_cuda_filters: bool,
    use_opencl: bool,
    metadata: Dict[int, Dict[str, Any]],
) -> Dict[str, Dict[str, str]]:
    """Build filter graph segments for character overlays."""

    from ...utils.ffmpeg_ops import calculate_overlay_position

    placements: Dict[str, Dict[str, str]] = {}

    for i, char_config in enumerate(characters_config):
        if not char_config.get("visible", False) or i not in character_indices:
            continue

        ffmpeg_index = character_indices[i]
        scale = float(char_effective_scale.get(i, float(char_config.get("scale", 1.0))))
        anchor = char_config.get("anchor", "bottom_center")
        position = char_config.get("position", {"x": "0", "y": "0"}) or {}

        x_base, y_base = calculate_overlay_position(
            "W",
            "H",
            "w",
            "h",
            anchor,
            str(position.get("x", "0")),
            str(position.get("y", "0")),
        )

        def _to_float(value: Any, fallback: float) -> float:
            try:
                return float(value)
            except Exception:
                return fallback

        enter_duration = _to_float(char_config.get("enter_duration", 0.3), 0.3)
        leave_duration = _to_float(char_config.get("leave_duration", 0.3), 0.3)

        def _normalize_effect(raw: Any) -> str:
            if not raw:
                return ""
            return str(raw).lower() if not isinstance(raw, bool) else "fade"

        enter_effect = _normalize_effect(char_config.get("enter"))
        leave_effect = _normalize_effect(char_config.get("leave"))

        fade = ""
        x_expr, y_expr = x_base, y_base
        position_dynamic = False

        if enter_effect == "fade":
            fade += f",fade=t=in:st=0:d={enter_duration}:alpha=1"
        if leave_effect == "fade":
            leave_start = max(0.0, duration - leave_duration)
            fade += f",fade=t=out:st={leave_start}:d={leave_duration}:alpha=1"
        else:
            leave_start = max(0.0, duration - leave_duration)

        if enter_effect == "slide_left":
            x_expr = (
                f"if(lt(t,{enter_duration}), -w+({x_base}+w)*t/{enter_duration}, {x_expr})"
            )
            position_dynamic = True
        elif enter_effect == "slide_right":
            x_expr = (
                f"if(lt(t,{enter_duration}), W+({x_base}-W)*t/{enter_duration}, {x_expr})"
            )
            position_dynamic = True
        elif enter_effect == "slide_top":
            y_expr = (
                f"if(lt(t,{enter_duration}), -h+({y_base}+h)*t/{enter_duration}, {y_expr})"
            )
            position_dynamic = True
        elif enter_effect == "slide_bottom":
            y_expr = (
                f"if(lt(t,{enter_duration}), H+({y_base}-H)*t/{enter_duration}, {y_expr})"
            )
            position_dynamic = True

        if leave_effect == "slide_left":
            x_expr = (
                f"if(gt(t,{leave_start}), {x_base} + (-w-{x_base})*(t-{leave_start})/{leave_duration}, {x_expr})"
            )
            position_dynamic = True
        elif leave_effect == "slide_right":
            x_expr = (
                f"if(gt(t,{leave_start}), {x_base} + (W-{x_base})*(t-{leave_start})/{leave_duration}, {x_expr})"
            )
            position_dynamic = True
        elif leave_effect == "slide_top":
            y_expr = (
                f"if(gt(t,{leave_start}), {y_base} + (-h-{y_base})*(t-{leave_start})/{leave_duration}, {y_expr})"
            )
            position_dynamic = True
        elif leave_effect == "slide_bottom":
            y_expr = (
                f"if(gt(t,{leave_start}), {y_base} + (H-{y_base})*(t-{leave_start})/{leave_duration}, {y_expr})"
            )
            position_dynamic = True

        # Character-specific effects (e.g., dynamic shake)
        effect_snippet = resolve_character_effects(
            effects=char_config.get("effects"),
            base_x_expr=x_expr,
            base_y_expr=y_expr,
            duration=duration,
        )
        if effect_snippet:
            if effect_snippet.filter_chain:
                filter_complex_parts.extend(effect_snippet.filter_chain)
            overlay_kwargs = effect_snippet.overlay_kwargs
            if "x" in overlay_kwargs:
                x_expr = overlay_kwargs["x"]
            if "y" in overlay_kwargs:
                y_expr = overlay_kwargs["y"]
            position_dynamic = position_dynamic or effect_snippet.dynamic

        def _escape_commas(expr: str) -> str:
            return expr.replace(",", "\\,")

        x_expr = _escape_commas(x_expr)
        y_expr = _escape_commas(y_expr)

        overlay_label: Optional[str] = None

        if use_cuda_filters:
            filter_complex_parts.append(
                f"[{ffmpeg_index}:v]format=rgba{fade},hwupload_cuda,{renderer.scale_filter}=iw*{scale}:ih*{scale}[char_scaled_{i}]"
            )
            overlay_label = f"[char_scaled_{i}]"
            overlay_streams.append(overlay_label)
            overlay_filters.append(f"overlay_cuda=x={x_expr}:y={y_expr}")
        elif use_opencl:
            opencl_success = False
            if os.environ.get("CHAR_CACHE_DISABLE", "0") != "1":
                try:
                    filter_complex_parts.append(
                        f"[{ffmpeg_index}:v]format=rgba{fade},hwupload[char_gpu_{i}]"
                    )
                    overlay_label = f"[char_gpu_{i}]"
                    overlay_streams.append(overlay_label)
                    overlay_filters.append(
                        f"overlay_opencl=x={x_expr}:y={y_expr}"
                    )
                    char_effective_scale[i] = 1.0
                    opencl_success = True
                except Exception:
                    overlay_label = None
            if not opencl_success:
                filter_complex_parts.append(
                    f"[{ffmpeg_index}:v]scale=iw*{scale}:ih*{scale},format=rgba{fade},hwupload[char_gpu_{i}]"
                )
                overlay_label = f"[char_gpu_{i}]"
                overlay_streams.append(overlay_label)
                overlay_filters.append(f"overlay_opencl=x={x_expr}:y={y_expr}")
                char_effective_scale[i] = 1.0
        else:
            if os.environ.get("CHAR_CACHE_DISABLE", "0") != "1" and abs(scale - 1.0) < 1e-6:
                filter_complex_parts.append(
                    f"[{ffmpeg_index}:v]format=rgba{fade}[char_scaled_{i}]"
                )
            else:
                filter_complex_parts.append(
                    f"[{ffmpeg_index}:v]scale=iw*{scale}:ih*{scale}:flags={renderer.scale_flags},format=rgba{fade}[char_scaled_{i}]"
                )
            overlay_label = f"[char_scaled_{i}]"
            overlay_streams.append(overlay_label)
            overlay_filters.append(f"overlay=x={x_expr}:y={y_expr}")

        placements.update(
            _build_face_placement(
                renderer=renderer,
                char_config=char_config,
                char_data=metadata.get(i, {}),
                x_expr=x_expr,
                y_expr=y_expr,
                enter_effect=enter_effect,
                leave_effect=leave_effect,
                fade=fade,
                duration=duration,
                scale=scale,
                dynamic_position=position_dynamic,
            )
        )

    return placements


def _build_face_placement(
    *,
    renderer: Any,
    char_config: Dict[str, Any],
    char_data: Dict[str, Any],
    x_expr: str,
    y_expr: str,
    enter_effect: str,
    leave_effect: str,
    fade: str,
    duration: float,
    scale: float,
    dynamic_position: bool,
) -> Dict[str, Dict[str, str]]:
    try:
        name = str(char_config.get("name") or char_data.get("name") or "")
        if not name:
            return {}

        image_path = char_data.get("image_path")
        try:
            from PIL import Image as _PILImage  # type: ignore

            if image_path:
                width, height = _PILImage.open(image_path).size
            else:
                width = height = 0
        except Exception:
            width = height = 0

        try:
            scale_orig = float(char_config.get("scale", 1.0))
        except Exception:
            scale_orig = float(scale)

        pos = char_config.get("position", {"x": "0", "y": "0"}) or {}

        def _to_float(value: Any) -> float:
            try:
                return float(value)
            except Exception:
                return 0.0

        offset_x = _to_float(pos.get("x", "0"))
        offset_y = _to_float(pos.get("y", "0"))

        vw = renderer.video_params.width
        vh = renderer.video_params.height
        cw = width * scale_orig
        ch = height * scale_orig
        anchor = str(char_config.get("anchor", "bottom_center"))

        if anchor == "top_left":
            x_num, y_num = offset_x, offset_y
        elif anchor == "top_center":
            x_num, y_num = (vw - cw) / 2 + offset_x, offset_y
        elif anchor == "top_right":
            x_num, y_num = vw - cw + offset_x, offset_y
        elif anchor == "middle_left":
            x_num, y_num = offset_x, (vh - ch) / 2 + offset_y
        elif anchor == "middle_center":
            x_num, y_num = (
                (vw - cw) / 2 + offset_x,
                (vh - ch) / 2 + offset_y,
            )
        elif anchor == "middle_right":
            x_num, y_num = (
                vw - cw + offset_x,
                (vh - ch) / 2 + offset_y,
            )
        elif anchor == "bottom_left":
            x_num, y_num = offset_x, vh - ch + offset_y
        elif anchor == "bottom_center":
            x_num, y_num = (
                (vw - cw) / 2 + offset_x,
                vh - ch + offset_y,
            )
        elif anchor == "bottom_right":
            x_num, y_num = vw - cw + offset_x, vh - ch + offset_y
        else:
            x_num, y_num = offset_x, offset_y

        try:
            enter_duration = float(char_config.get("enter_duration", 0.0) or 0.0)
        except Exception:
            enter_duration = 0.0

        placement = {
            "x_expr": x_expr,
            "y_expr": y_expr,
            "enter_effect": enter_effect,
            "enter_duration": f"{enter_duration:.3f}",
            "leave_effect": leave_effect,
            "fade": fade,
            "scale_orig": f"{scale_orig}",
            "scale_eff": f"{scale}",
            "x_num": str(int(round(x_num))),
            "y_num": str(int(round(y_num))),
            "expression": str(char_config.get("expression", char_data.get("expression", "default"))),
            "dynamic_position": dynamic_position,
        }

        return {name: placement}
    except Exception:
        return {}
