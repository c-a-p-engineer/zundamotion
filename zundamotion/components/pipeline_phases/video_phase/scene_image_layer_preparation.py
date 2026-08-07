"""Image-layer state and scene-overlay preparation for SceneRenderer.

Internal mixin. It only resolves timeline state; media rendering remains elsewhere.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ....utils.ffmpeg_ops import calculate_overlay_position
from .scene_background_preparation import _to_offset_expr


class SceneImageLayerPreparationMixin:
    """Resolve persistent image-layer actions into line and scene overlay plans."""

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
            line_entries: Dict[str, Dict[str, Any]] = {
                layer_id: dict(state) for layer_id, state in active.items()
            }

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
            last_entries = {
                entry.get("id"): entry
                for entry in per_line.get(last_line_idx, [])
            }
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

        def _extract_transition(
            transition: Optional[Dict[str, Any]], key: str
        ) -> Optional[Dict[str, Any]]:
            if not isinstance(transition, dict):
                return None
            block = transition.get(key)
            if not isinstance(block, dict) or block.get("type") != "fade":
                return None
            try:
                duration = float(block.get("duration", 0.0))
            except Exception:
                duration = 0.0
            if duration <= 0:
                return None
            return {"type": "fade", "duration": duration}

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
            at_time = float(start_time_by_idx.get(idx, 0.0))
            for action in actions:
                if not isinstance(action, dict):
                    continue
                if "show" in action:
                    show = action.get("show") or {}
                    layer_id = show.get("id")
                    if not layer_id:
                        continue
                    if layer_id in active:
                        finalized = _finalize_layer(active[layer_id], at_time)
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
                        "start_time": at_time,
                    }
                elif "hide" in action:
                    hide = action.get("hide") or {}
                    layer_id = hide.get("id")
                    if not layer_id or layer_id not in active:
                        continue
                    hide_transition = _extract_transition(hide.get("transition"), "out")
                    finalized = _finalize_layer(
                        active[layer_id], at_time, hide_transition
                    )
                    if finalized:
                        overlays.append(finalized)
                    active.pop(layer_id, None)

        for state in active.values():
            finalized = _finalize_layer(state, scene_duration)
            if finalized:
                overlays.append(finalized)

        overlays.sort(key=lambda item: float(item.get("timing", {}).get("start", 0.0)))
        return overlays
