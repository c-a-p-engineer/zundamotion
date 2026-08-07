"""Character state and movement calculations for the simple scene fast path.

This module does not execute FFmpeg. It preserves the existing character asset
resolution and overlay-expression semantics used by the fast path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from ....utils.ffmpeg_ops import calculate_overlay_position
from ...video.clip.movement import (
    build_move_expressions,
    build_scale_expression,
)


class SceneFastPathCharacterMixin:
    """Resolve fast-path character state and global movement expressions."""

    @staticmethod
    def _escape_overlay_expr(expr: str) -> str:
        return str(expr).replace(",", "\\,")

    def _resolve_char_base_image(self, name: str, expression: str) -> Optional[Path]:
        base_dir = Path(f"assets/characters/{name}")
        candidates = [
            base_dir / expression / "base.png",
            base_dir / f"{expression}.png",
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

    def _extract_simple_character_state(
        self, line: Dict[str, Any]
    ) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        visible = [ch for ch in (line.get("characters") or []) if ch.get("visible", False)]
        if not visible:
            return None, "no_visible_character"
        if len(visible) != 1:
            return None, "multiple_visible_characters"
        char = dict(visible[0])
        if char.get("color_filter") is not None:
            return None, "color_filter_requires_standard_renderer"
        name = char.get("name")
        if not name:
            return None, "missing_character_name"
        expression = str(char.get("expression", "default"))
        image_path = self._resolve_char_base_image(str(name), expression)
        if image_path is None:
            return None, f"missing_character_asset:{name}/{expression}"
        try:
            from PIL import Image as _PILImage  # type: ignore

            with _PILImage.open(image_path) as image:
                source_width, source_height = image.size
        except Exception:
            return None, f"invalid_character_asset:{name}/{expression}"
        try:
            scale = float(char.get("scale", 1.0))
        except Exception:
            scale = 1.0
        anchor = str(char.get("anchor", "bottom_center"))
        position = char.get("position") or {"x": "0", "y": "0"}
        return (
            {
                "name": str(name),
                "expression": expression,
                "image_path": image_path,
                "source_width": source_width,
                "source_height": source_height,
                "scale": scale,
                "anchor": anchor,
                "position": {
                    "x": str(position.get("x", "0")),
                    "y": str(position.get("y", "0")),
                },
                "enter": char.get("enter"),
                "enter_duration": char.get("enter_duration", 0.3),
                "leave": char.get("leave"),
                "leave_duration": char.get("leave_duration", 0.3),
                "move": char.get("move"),
            },
            None,
        )

    def _character_signature(self, char_state: Dict[str, Any]) -> tuple[Any, ...]:
        return (
            char_state.get("name"),
            char_state.get("expression"),
            Path(str(char_state.get("image_path"))).resolve(),
            float(char_state.get("scale", 1.0)),
            str(char_state.get("anchor", "bottom_center")),
            str((char_state.get("position") or {}).get("x", "0")),
            str((char_state.get("position") or {}).get("y", "0")),
            repr(char_state.get("move")),
        )

    def _compute_global_char_position(
        self,
        char_state: Dict[str, Any],
        *,
        start_time: float,
        end_time: float,
    ) -> Dict[str, Any]:
        x_base, y_base = calculate_overlay_position(
            "W",
            "H",
            "w",
            "h",
            str(char_state.get("anchor", "bottom_center")),
            str((char_state.get("position") or {}).get("x", "0")),
            str((char_state.get("position") or {}).get("y", "0")),
        )

        def _normalize_effect(raw: Any) -> str:
            if not raw:
                return ""
            return str(raw).lower() if not isinstance(raw, bool) else "fade"

        def _to_float(value: Any, fallback: float) -> float:
            try:
                return float(value)
            except Exception:
                return fallback

        enter_effect = _normalize_effect(char_state.get("enter"))
        leave_effect = _normalize_effect(char_state.get("leave"))
        enter_duration = _to_float(char_state.get("enter_duration", 0.3), 0.3)
        leave_duration = _to_float(char_state.get("leave_duration", 0.3), 0.3)
        leave_start = max(start_time, end_time - leave_duration)

        fade_filters: List[str] = []
        if enter_effect == "fade" and enter_duration > 0:
            fade_filters.append(f"fade=t=in:st={start_time:.3f}:d={enter_duration:.3f}:alpha=1")
        if leave_effect == "fade" and leave_duration > 0:
            fade_filters.append(f"fade=t=out:st={leave_start:.3f}:d={leave_duration:.3f}:alpha=1")

        x_expr, y_expr, _move_dynamic = build_move_expressions(
            move_config=char_state.get("move"),
            anchor=str(char_state.get("anchor", "bottom_center")),
            from_position=None,
            to_position=char_state.get("position") or {},
            to_x_expr=x_base,
            to_y_expr=y_base,
            time_base=start_time,
        )
        try:
            final_scale = float(char_state.get("scale", 1.0))
        except Exception:
            final_scale = 1.0
        scale_expr, scale_dynamic = build_scale_expression(
            move_config=char_state.get("move"),
            to_scale=final_scale,
            time_base=start_time,
        )
        if enter_effect == "slide_left" and enter_duration > 0:
            x_expr = (
                f"if(lt(t,{start_time + enter_duration:.3f}), "
                f"-w+({x_base}+w)*(t-{start_time:.3f})/{enter_duration:.3f}, {x_expr})"
            )
        elif enter_effect == "slide_right" and enter_duration > 0:
            x_expr = (
                f"if(lt(t,{start_time + enter_duration:.3f}), "
                f"W+({x_base}-W)*(t-{start_time:.3f})/{enter_duration:.3f}, {x_expr})"
            )
        elif enter_effect == "slide_top" and enter_duration > 0:
            y_expr = (
                f"if(lt(t,{start_time + enter_duration:.3f}), "
                f"-h+({y_base}+h)*(t-{start_time:.3f})/{enter_duration:.3f}, {y_expr})"
            )
        elif enter_effect == "slide_bottom" and enter_duration > 0:
            y_expr = (
                f"if(lt(t,{start_time + enter_duration:.3f}), "
                f"H+({y_base}-H)*(t-{start_time:.3f})/{enter_duration:.3f}, {y_expr})"
            )

        if leave_effect == "slide_left" and leave_duration > 0:
            x_expr = (
                f"if(gt(t,{leave_start:.3f}), "
                f"{x_base} + (-w-{x_base})*(t-{leave_start:.3f})/{leave_duration:.3f}, {x_expr})"
            )
        elif leave_effect == "slide_right" and leave_duration > 0:
            x_expr = (
                f"if(gt(t,{leave_start:.3f}), "
                f"{x_base} + (W-{x_base})*(t-{leave_start:.3f})/{leave_duration:.3f}, {x_expr})"
            )
        elif leave_effect == "slide_top" and leave_duration > 0:
            y_expr = (
                f"if(gt(t,{leave_start:.3f}), "
                f"{y_base} + (-h-{y_base})*(t-{leave_start:.3f})/{leave_duration:.3f}, {y_expr})"
            )
        elif leave_effect == "slide_bottom" and leave_duration > 0:
            y_expr = (
                f"if(gt(t,{leave_start:.3f}), "
                f"{y_base} + (H-{y_base})*(t-{leave_start:.3f})/{leave_duration:.3f}, {y_expr})"
            )

        return {
            "x_expr": self._escape_overlay_expr(x_expr),
            "y_expr": self._escape_overlay_expr(y_expr),
            "enter_effect": enter_effect,
            "leave_effect": leave_effect,
            "enter_duration": enter_duration,
            "fade_filters": fade_filters,
            "scale_expr": scale_expr,
            "scale_dynamic": scale_dynamic,
        }
