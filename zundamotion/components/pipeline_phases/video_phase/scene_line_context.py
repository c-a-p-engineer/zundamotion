"""Resolve immutable per-line inputs for standard scene rendering."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from ....exceptions import PipelineError
from .scene_run_base_renderer import RenderedRunBase


@dataclass(frozen=True)
class SceneLineContext:
    """All non-rendering inputs needed to process one original scene line."""

    line_index: int
    line_id: str
    visual_container: Dict[str, Any]
    line_data: Dict[str, Any]
    line_type: str
    duration: float
    pre_duration: float
    post_duration: float
    line_config: Dict[str, Any]
    text: str
    audio_path: Any
    extra_audio_overlays: tuple[Dict[str, Any], ...]
    image_layer_overlays: tuple[Dict[str, Any], ...]
    background_layout: Dict[str, Any]
    background_source: str
    background_is_video: bool
    uses_scene_background: bool
    run_base: Optional[RenderedRunBase]
    background_config: Dict[str, Any]


class SceneLineContextMixin:
    """Resolve line identity, media sources, and background selection."""

    def _build_scene_line_context(
        self,
        *,
        scene_id: str,
        line_index: int,
        line: Dict[str, Any],
        scene_background: str,
        scene_base_path: Optional[Path],
        normalized_background_path: Optional[Path],
        start_time_by_index: Mapping[int, float],
        run_bases: list[RenderedRunBase],
        image_layers_by_line: Mapping[int, list[Dict[str, Any]]],
    ) -> SceneLineContext:
        line_id = f"{scene_id}_{line_index}"
        line_data = self.line_data_map[line_id]
        duration = line_data["duration"]
        pre_duration = float(line_data.get("pre_duration", 0.0))
        post_duration = float(line_data.get("post_duration", 0.0))
        line_config = line_data["line_config"]
        background_layout = self._resolve_background_layout(line_config)
        background_source = self._resolve_background_source(
            line_config,
            scene_background,
        )
        if not background_source:
            raise PipelineError(
                f"Background is not defined for scene '{scene_id}', line {line_index}."
            )

        background_is_video = (
            Path(background_source).suffix.lower() in self.video_extensions
        )
        uses_scene_background = background_source == scene_background
        run_base = self._find_run_base(run_bases, line_index)
        background_config = self._resolve_line_background_config(
            line_index=line_index,
            background_source=background_source,
            background_is_video=background_is_video,
            uses_scene_background=uses_scene_background,
            background_layout=background_layout,
            scene_base_path=scene_base_path,
            normalized_background_path=normalized_background_path,
            run_base=run_base,
            start_time_by_index=start_time_by_index,
        )

        video_filter = line_config.get("video_filter") or self.scene.get(
            "video_filter"
        )
        if video_filter:
            background_config["video_filter"] = video_filter

        extra_audio_overlays = tuple(
            item
            for item in (line_data.get("extra_audio_overlays") or [])
            if isinstance(item, dict)
        )
        image_layer_overlays = tuple(image_layers_by_line.get(line_index, []))
        return SceneLineContext(
            line_index=line_index,
            line_id=line_id,
            visual_container=line,
            line_data=line_data,
            line_type=str(line_data["type"]),
            duration=duration,
            pre_duration=pre_duration,
            post_duration=post_duration,
            line_config=line_config,
            text=str(line_data.get("text") or ""),
            audio_path=line_data.get("audio_path"),
            extra_audio_overlays=extra_audio_overlays,
            image_layer_overlays=image_layer_overlays,
            background_layout=background_layout,
            background_source=str(background_source),
            background_is_video=background_is_video,
            uses_scene_background=uses_scene_background,
            run_base=run_base,
            background_config=background_config,
        )

    def _resolve_line_background_config(
        self,
        *,
        line_index: int,
        background_source: str,
        background_is_video: bool,
        uses_scene_background: bool,
        background_layout: Dict[str, Any],
        scene_base_path: Optional[Path],
        normalized_background_path: Optional[Path],
        run_base: Optional[RenderedRunBase],
        start_time_by_index: Mapping[int, float],
    ) -> Dict[str, Any]:
        common = {
            "fit": background_layout["fit"],
            "fill_color": background_layout["fill_color"],
            "anchor": background_layout["anchor"],
            "position": dict(background_layout["position"]),
        }
        if (
            uses_scene_background
            and scene_base_path is not None
            and scene_base_path.exists()
        ):
            return {
                "type": "video",
                "path": str(scene_base_path),
                "start_time": start_time_by_index[line_index],
                "normalized": True,
                "pre_scaled": True,
                **common,
            }
        if uses_scene_background and run_base is not None and run_base.path.exists():
            return {
                "type": "video",
                "path": str(run_base.path),
                "start_time": float(run_base.offsets[line_index]),
                "normalized": True,
                "pre_scaled": True,
                **common,
            }
        if background_is_video:
            if (
                uses_scene_background
                and normalized_background_path is not None
                and Path(normalized_background_path).exists()
            ):
                return {
                    "type": "video",
                    "path": str(normalized_background_path),
                    "start_time": start_time_by_index[line_index],
                    "normalized": True,
                    "pre_scaled": True,
                    **common,
                }
            return {
                "type": "video",
                "path": str(background_source),
                "start_time": start_time_by_index[line_index],
                **common,
            }
        return {
            "type": "image",
            "path": str(background_source),
            "start_time": start_time_by_index[line_index],
            **common,
        }
