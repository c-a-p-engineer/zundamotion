"""Scene background layout, badge markers, and visual overlay preparation.

Internal SceneRenderer mixin. FFmpeg execution is intentionally out of scope.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ....utils.ffmpeg_ops import (
    BACKGROUND_FIT_STRETCH,
    DEFAULT_BACKGROUND_ANCHOR,
    DEFAULT_BACKGROUND_FILL_COLOR,
)


def _to_offset_expr(value: Any) -> str:
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return "0"
    return str(value)


class SceneBackgroundPreparationMixin:
    """Resolve scene background layout and badge/foreground overlay inputs."""

    def _resolve_background_layout(self, line_config: Dict[str, Any]) -> Dict[str, Any]:
        video_defaults = self.config.get("video", {}) or {}
        background_defaults = self.config.get("background", {}) or {}
        scene_bg_cfg = self.scene.get("background")
        if not isinstance(scene_bg_cfg, dict):
            scene_bg_cfg = {}
        line_bg_cfg = line_config.get("background") if isinstance(line_config, dict) else None
        if not isinstance(line_bg_cfg, dict):
            line_bg_cfg = {}

        fit = str(
            line_bg_cfg.get(
                "fit",
                scene_bg_cfg.get(
                    "fit",
                    video_defaults.get("background_fit", BACKGROUND_FIT_STRETCH),
                ),
            )
        ).lower()
        fill = str(
            line_bg_cfg.get(
                "fill_color",
                scene_bg_cfg.get(
                    "fill_color",
                    background_defaults.get(
                        "fill_color", DEFAULT_BACKGROUND_FILL_COLOR
                    ),
                ),
            )
            or DEFAULT_BACKGROUND_FILL_COLOR
        )
        anchor = (
            line_bg_cfg.get(
                "anchor",
                scene_bg_cfg.get(
                    "anchor",
                    background_defaults.get("anchor", DEFAULT_BACKGROUND_ANCHOR),
                ),
            )
            or DEFAULT_BACKGROUND_ANCHOR
        )
        raw_position = line_bg_cfg.get("position")
        if not isinstance(raw_position, dict):
            raw_position = scene_bg_cfg.get("position")
            if not isinstance(raw_position, dict):
                raw_position = background_defaults.get("position")
                if not isinstance(raw_position, dict):
                    raw_position = {}
        offset_x = _to_offset_expr(raw_position.get("x"))
        offset_y = _to_offset_expr(raw_position.get("y"))
        return {
            "fit": fit,
            "fill_color": fill,
            "anchor": str(anchor),
            "position": {"x": offset_x, "y": offset_y},
        }

    def _resolve_background_source(
        self,
        line_config: Dict[str, Any],
        scene_bg_default: Optional[str],
    ) -> Optional[str]:
        line_bg_cfg = line_config.get("background") if isinstance(line_config, dict) else None
        if isinstance(line_bg_cfg, dict):
            line_bg_path = line_bg_cfg.get("path")
            if line_bg_path:
                return str(line_bg_path)
        return scene_bg_default

    async def _resolve_visual_overlays(
        self,
        container: Dict[str, Any],
        *,
        scope_id: str,
        line_markers: Optional[Dict[str, float]] = None,
    ) -> List[Dict[str, Any]]:
        overlays = list(container.get("fg_overlays") or [])
        badge_cache = getattr(self.video_renderer, "badge_cache", None)
        direct_badges = container.get("badges") or []
        if badge_cache is not None and isinstance(direct_badges, list):
            for idx, badge_cfg in enumerate(direct_badges, start=1):
                if (
                    isinstance(badge_cfg, dict)
                    and badge_cfg.get("text")
                    and badge_cfg.get("position")
                    and badge_cfg.get("visible", True) is not False
                ):
                    font_path = str(
                        (self.config.get("subtitle", {}) or {}).get("font_path") or ""
                    )
                    badge_overlay = await badge_cache.get_badge_overlay(
                        badge_cfg,
                        video_width=int(self.video_params.width),
                        video_height=int(self.video_params.height),
                        font_path=font_path,
                        line_markers=line_markers,
                    )
                    badge_overlay["id"] = f"{scope_id}_badges_{idx}"
                    overlays.append(badge_overlay)
        for idx, badge_state in enumerate(container.get("_resolved_badges") or [], start=1):
            if not isinstance(badge_state, dict) or badge_cache is None:
                continue
            font_path = str(
                (self.config.get("subtitle", {}) or {}).get("font_path") or ""
            )
            badge_overlay = await badge_cache.get_badge_overlay(
                badge_state,
                video_width=int(self.video_params.width),
                video_height=int(self.video_params.height),
                font_path=font_path,
            )
            badge_overlay["id"] = f"{scope_id}_badge_{idx}"
            overlays.append(badge_overlay)
        badge_cfg = container.get("badge")
        if isinstance(badge_cfg, dict) and badge_cache is not None:
            font_path = str(
                (self.config.get("subtitle", {}) or {}).get("font_path") or ""
            )
            badge_overlay = await badge_cache.get_badge_overlay(
                badge_cfg,
                video_width=int(self.video_params.width),
                video_height=int(self.video_params.height),
                font_path=font_path,
                line_markers=line_markers,
            )
            badge_overlay["id"] = f"{scope_id}_badge"
            overlays.append(badge_overlay)
        return overlays

    def _build_badge_line_markers(
        self,
        *,
        start_time_by_idx: Dict[int, float],
    ) -> Dict[str, float]:
        markers: Dict[str, float] = {}
        for idx, line in enumerate(self.scene.get("lines", []) or [], start=1):
            start = float(start_time_by_idx.get(idx, 0.0))
            markers[str(idx)] = start
            line_id = line.get("id")
            if isinstance(line_id, str) and line_id.strip():
                markers[line_id.strip()] = start
        return markers
