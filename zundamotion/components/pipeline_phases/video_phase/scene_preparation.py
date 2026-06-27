"""Background, overlay, badge, face, image-layer, and character preparation.

This module is an internal SceneRenderer mixin; use scene_renderer.SceneRenderer.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from ....utils.ffmpeg_ops import (
    BACKGROUND_FIT_STRETCH,
    DEFAULT_BACKGROUND_ANCHOR,
    DEFAULT_BACKGROUND_FILL_COLOR,
    calculate_overlay_position,
)
from ....utils.logger import logger
from ...video.clip.face import _resolve_face_asset
from ...video.clip.characters import is_horizontal_flip_enabled, is_vertical_flip_enabled


def _to_offset_expr(value: Any) -> str:
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return "0"
    return str(value)


class ScenePreparationMixin:
    """Resolve scene assets and precompute line-level visual state."""

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
            if not isinstance(badge_state, dict):
                continue
            if badge_cache is None:
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
        badge_cache = getattr(self.video_renderer, "badge_cache", None)
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

    async def _precache_face_overlays(
        self,
        *,
        scene_id: str,
        scene: Dict[str, Any],
        line_data_map: Dict[str, Dict[str, Any]],
    ) -> None:
        """Warm scaled mouth/eye overlay PNGs before clip rendering."""

        if os.environ.get("FACE_CACHE_DISABLE", "0") == "1":
            return

        vcfg = self.config.get("video", {}) or {}
        if vcfg.get("precache_face_overlays", True) is False:
            return

        try:
            thr_env = os.environ.get("FACE_ALPHA_THRESHOLD")
            alpha_threshold = int(thr_env) if (thr_env and thr_env.isdigit()) else 128
        except Exception:
            alpha_threshold = 128

        specs: Dict[str, Dict[str, Any]] = {}
        for idx, _line in enumerate(scene.get("lines", []) or [], start=1):
            data = line_data_map.get(f"{scene_id}_{idx}") or {}
            line_config = data.get("line_config") or {}
            face_anim_raw = data.get("face_anim")
            if isinstance(face_anim_raw, list):
                face_anims = [item for item in face_anim_raw if isinstance(item, dict)]
            elif isinstance(face_anim_raw, dict):
                face_anims = [face_anim_raw]
            else:
                face_anims = []
            if not face_anims:
                continue

            characters = line_config.get("characters") or []
            char_by_name = {
                str(ch.get("name")): ch
                for ch in characters
                if isinstance(ch, dict) and ch.get("name")
            }

            for face_anim in face_anims:
                target_name = str(face_anim.get("target_name") or "")
                if not target_name:
                    continue
                char_cfg = char_by_name.get(target_name, {})
                try:
                    scale = float(char_cfg.get("scale", 1.0))
                except Exception:
                    scale = 1.0
                expression = str(char_cfg.get("expression", "default"))
                asset_name = str(char_cfg.get("asset_name") or target_name)
                flip_x = is_horizontal_flip_enabled(char_cfg)
                flip_y = is_vertical_flip_enabled(char_cfg)
                base_dir = Path(f"assets/characters/{asset_name}")

                candidates: List[Path] = []
                eyes_segments = face_anim.get("eyes") or []
                if isinstance(eyes_segments, list) and eyes_segments:
                    candidates.append(
                        _resolve_face_asset(base_dir, expression, "eyes", "close.png")
                    )

                mouth_segments = face_anim.get("mouth") or []
                if isinstance(mouth_segments, list) and mouth_segments:
                    states = {str(seg.get("state") or "") for seg in mouth_segments}
                    if "half" in states:
                        candidates.append(
                            _resolve_face_asset(base_dir, expression, "mouth", "half.png")
                        )
                    if "open" in states:
                        candidates.append(
                            _resolve_face_asset(base_dir, expression, "mouth", "open.png")
                        )

                for path in candidates:
                    if not path.exists():
                        continue
                    try:
                        stat = path.stat()
                    except Exception:
                        continue
                    key = json.dumps(
                        {
                            "path": str(path.resolve()),
                            "mtime": int(stat.st_mtime),
                            "size": stat.st_size,
                            "scale": scale,
                            "alpha_threshold": alpha_threshold,
                            "flip_x": flip_x,
                            "flip_y": flip_y,
                        },
                        sort_keys=True,
                        default=str,
                    )
                    specs.setdefault(
                        key,
                        {
                            "path": path,
                            "scale": scale,
                            "alpha_threshold": alpha_threshold,
                            "flip_x": flip_x,
                            "flip_y": flip_y,
                        },
                    )

        if not specs:
            return

        tasks = [
            self.video_renderer.face_cache.get_scaled_overlay(
                spec["path"],
                spec["scale"],
                spec["alpha_threshold"],
                horizontal_flip=spec["flip_x"],
                vertical_flip=spec["flip_y"],
            )
            for spec in specs.values()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        failures = sum(1 for result in results if isinstance(result, Exception))
        if failures:
            logger.warning(
                "Precached %d/%d face overlay PNG(s) for scene '%s' (%d failed)",
                len(specs) - failures,
                len(specs),
                scene_id,
                failures,
            )
        else:
            logger.info(
                "Precached %d face overlay PNG(s) for scene '%s'",
                len(specs),
                scene_id,
            )

    def _collect_image_layers_by_line(
        self, lines: List[Dict[str, Any]]
    ) -> Dict[int, List[Dict[str, Any]]]:
        per_line: Dict[int, List[Dict[str, Any]]] = {}
        active: Dict[str, Dict[str, Any]] = {}
        last_line_idx = len(lines)

        def _normalize_state(show: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "id": show.get("id"),
                "path": show.get("path"),
                "anchor": show.get("anchor", "middle_center"),
                "position": show.get("position") or {"x": "0", "y": "0"},
                "scale": show.get("scale", 1.0),
                "opacity": show.get("opacity"),
                "opaque": bool(show.get("opaque", True)),
                "transition_out": (show.get("transition") or {}).get("out"),
            }

        for idx, line in enumerate(lines, start=1):
            actions = line.get("image_layers") or []
            line_entries: Dict[str, Dict[str, Any]] = {}

            for layer_id, state in active.items():
                line_entries[layer_id] = dict(state)

            for action in actions:
                if not isinstance(action, dict):
                    continue
                if "show" in action:
                    show = action.get("show") or {}
                    layer_id = show.get("id")
                    if not layer_id:
                        continue
                    state = _normalize_state(show)
                    active[layer_id] = state
                    entry = dict(state)
                    trans = show.get("transition") or {}
                    if isinstance(trans, dict) and trans.get("in"):
                        entry["fade_in"] = {
                            "type": trans["in"].get("type"),
                            "duration": trans["in"].get("duration"),
                            "align": "start",
                        }
                    line_entries[layer_id] = entry
                elif "hide" in action:
                    hide = action.get("hide") or {}
                    layer_id = hide.get("id")
                    if not layer_id or layer_id not in active:
                        continue
                    entry = line_entries.get(layer_id, dict(active[layer_id]))
                    trans = hide.get("transition") or {}
                    if isinstance(trans, dict) and trans.get("out"):
                        entry["fade_out"] = {
                            "type": trans["out"].get("type"),
                            "duration": trans["out"].get("duration"),
                            "align": "start",
                        }
                    elif active[layer_id].get("transition_out"):
                        out_t = active[layer_id]["transition_out"]
                        if isinstance(out_t, dict):
                            entry["fade_out"] = {
                                "type": out_t.get("type"),
                                "duration": out_t.get("duration"),
                                "align": "start",
                            }
                    line_entries[layer_id] = entry
                    active.pop(layer_id, None)

            per_line[idx] = list(line_entries.values())

        if last_line_idx > 0 and active:
            last_entries = {e.get("id"): e for e in per_line.get(last_line_idx, [])}
            for layer_id, state in active.items():
                out_t = state.get("transition_out")
                if not isinstance(out_t, dict):
                    continue
                entry = last_entries.get(layer_id, dict(state))
                entry["fade_out"] = {
                    "type": out_t.get("type"),
                    "duration": out_t.get("duration"),
                    "align": "end",
                }
                last_entries[layer_id] = entry
            per_line[last_line_idx] = list(last_entries.values())

        return per_line

    def _build_image_layer_overlays(
        self,
        *,
        lines: List[Dict[str, Any]],
        start_time_by_idx: Dict[int, float],
        scene_duration: float,
    ) -> List[Dict[str, Any]]:
        overlays: List[Dict[str, Any]] = []
        active: Dict[str, Dict[str, Any]] = {}

        def _extract_transition(transition: Optional[Dict[str, Any]], key: str) -> Optional[Dict[str, Any]]:
            if not isinstance(transition, dict):
                return None
            block = transition.get(key)
            if not isinstance(block, dict):
                return None
            if block.get("type") == "fade":
                try:
                    duration = float(block.get("duration", 0.0))
                except Exception:
                    duration = 0.0
                if duration > 0:
                    return {"type": "fade", "duration": duration}
            return None

        def _finalize_layer(
            state: Dict[str, Any],
            end_time: float,
            hide_transition: Optional[Dict[str, Any]] = None,
        ) -> Optional[Dict[str, Any]]:
            start_time = float(state.get("start_time", 0.0))
            if end_time <= start_time:
                return None
            duration = end_time - start_time
            anchor = state.get("anchor", "middle_center")
            pos = state.get("position") or {}
            offset_x = _to_offset_expr(pos.get("x"))
            offset_y = _to_offset_expr(pos.get("y"))
            x_expr, y_expr = calculate_overlay_position(
                "W",
                "H",
                "w",
                "h",
                str(anchor),
                offset_x,
                offset_y,
            )
            overlay: Dict[str, Any] = {
                "id": state.get("id"),
                "src": state.get("path"),
                "mode": state.get("mode", "overlay"),
                "position": {"x": x_expr, "y": y_expr},
                "timing": {"start": start_time, "duration": duration},
                "opaque": True,
            }
            if state.get("scale") is not None:
                overlay["scale"] = state.get("scale")
            if state.get("opacity") is not None:
                overlay["opacity"] = state.get("opacity")
            if state.get("effects"):
                overlay["effects"] = list(state.get("effects") or [])
            if state.get("fps") is not None:
                overlay["fps"] = state.get("fps")

            fade_in = state.get("transition_in")
            if isinstance(fade_in, dict) and fade_in.get("type") == "fade":
                overlay["fade_in"] = {
                    "start": start_time,
                    "duration": fade_in.get("duration", 0.0),
                }
            fade_out = hide_transition or state.get("transition_out")
            if isinstance(fade_out, dict) and fade_out.get("type") == "fade":
                out_dur = float(fade_out.get("duration", 0.0))
                out_start = max(start_time, end_time - out_dur)
                if out_dur > 0 and out_start < end_time:
                    overlay["fade_out"] = {
                        "start": out_start,
                        "duration": out_dur,
                    }
            return overlay

        for idx, line in enumerate(lines, start=1):
            actions = line.get("image_layers")
            if not actions:
                continue
            t = float(start_time_by_idx.get(idx, 0.0))
            for action in actions:
                if not isinstance(action, dict):
                    continue
                if "show" in action:
                    show = action.get("show") or {}
                    layer_id = show.get("id")
                    if not layer_id:
                        continue
                    if layer_id in active:
                        finalized = _finalize_layer(active[layer_id], t)
                        if finalized:
                            overlays.append(finalized)
                    active[layer_id] = {
                        "id": layer_id,
                        "path": show.get("path"),
                        "anchor": show.get("anchor", "middle_center"),
                        "position": show.get("position") or {"x": "0", "y": "0"},
                        "scale": show.get("scale", 1.0),
                        "opacity": show.get("opacity"),
                        "effects": show.get("effects"),
                        "fps": show.get("fps"),
                        "mode": show.get("mode", "overlay"),
                        "transition_in": _extract_transition(show.get("transition"), "in"),
                        "transition_out": _extract_transition(show.get("transition"), "out"),
                        "start_time": t,
                    }
                elif "hide" in action:
                    hide = action.get("hide") or {}
                    layer_id = hide.get("id")
                    if not layer_id or layer_id not in active:
                        continue
                    hide_transition = _extract_transition(hide.get("transition"), "out")
                    finalized = _finalize_layer(active[layer_id], t, hide_transition)
                    if finalized:
                        overlays.append(finalized)
                    active.pop(layer_id, None)

        for state in active.values():
            finalized = _finalize_layer(state, scene_duration)
            if finalized:
                overlays.append(finalized)

        overlays.sort(key=lambda o: float(o.get("timing", {}).get("start", 0.0)))
        return overlays
