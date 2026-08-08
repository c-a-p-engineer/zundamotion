"""Scene-transition planning and execution for FinalizePhase."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Tuple

from zundamotion.timeline import Timeline
from zundamotion.utils.ffmpeg_ops import apply_transition_local
from zundamotion.utils.logger import logger


class FinalizeTransitionMixin:
    async def _probe_scene_durations(self, paths: List[Path]) -> List[float]:
        from . import finalize_phase as compat

        tasks = [
            compat.get_media_duration(str(path), caller="finalize_scene_duration")
            for path in paths
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True) if tasks else []
        durations: List[float] = []
        for path, result in zip(paths, results):
            if isinstance(result, Exception):
                logger.warning(
                    "FinalizePhase: Failed to probe duration for %s (%s). Falling back to 0.0s.",
                    path.name, result,
                )
                durations.append(0.0)
            else:
                try:
                    durations.append(float(result))
                except Exception:
                    durations.append(0.0)
        return durations

    @staticmethod
    def _transition_values(config: Dict[str, Any]) -> tuple[str, float]:
        try:
            return str(config.get("type", "fade")), float(config.get("duration", 1.0))
        except Exception:
            return "fade", 1.0

    def _transition_cache_key(
        self, *, current: Path, next_path: Path, from_scene: str, to_scene: str,
        transition_type: str, duration: float, offset: float, consume_next_head: bool,
    ) -> Dict[str, Any]:
        return {
            "type": "finalize_transition_boundary",
            "version": "20260805_wait_padding_v2",
            "from_scene": from_scene,
            "to_scene": to_scene,
            "current": self._file_signature(current),
            "next": self._file_signature(next_path),
            "transition": {
                "type": transition_type, "duration": duration, "offset": offset,
                "wait_padding": self.transition_wait_padding,
                "consume_next_head": consume_next_head,
            },
            "video_params": self.video_params.__dict__,
            "audio_params": self.audio_params.__dict__,
            "hw_encoder": self.hw_encoder,
        }

    async def _render_transition_boundary(
        self, *, current: Path, next_path: Path, index: int,
        from_scene: str, to_scene: str, transition_type: str,
        duration: float, offset: float, consume_next_head: bool,
        current_duration: float, next_duration: float,
    ) -> Path:
        output = self.temp_dir / f"transition_{index:03d}_{index + 1:03d}.mp4"
        key_data = self._transition_cache_key(
            current=current, next_path=next_path, from_scene=from_scene,
            to_scene=to_scene, transition_type=transition_type, duration=duration,
            offset=offset, consume_next_head=consume_next_head,
        )

        async def creator(cache_output: Path) -> Path:
            await apply_transition_local(
                str(current), str(next_path), str(cache_output), transition_type,
                duration, offset, self.video_params, self.audio_params,
                wait_padding=self.transition_wait_padding, hw_encoder=self.hw_encoder,
                consume_next_head=consume_next_head,
                context={
                    "phase": "FinalizePhase", "operation": "transition_boundary",
                    "scene_id": from_scene, "from_scene": from_scene,
                    "to_scene": to_scene, "transition_index": index,
                },
            )
            return cache_output

        if not self.finalize_cache_enabled:
            return await creator(output)
        expected = (
            current_duration + next_duration + self.transition_wait_padding
            if self.transition_wait_padding > 0
            else current_duration + next_duration - duration
        )
        return await self._get_or_create_finalize_cache(
            key_data=key_data,
            file_name=f"finalize_transition_{index:03d}_{index + 1:03d}",
            extension="mp4", creator_func=creator,
            expected_duration=max(0.0, expected), cache_label="transition",
        )

    def _shift_transition_timeline(
        self, timeline: Timeline, scenes: List[Dict[str, Any]], index: int
    ) -> None:
        shift = self.transition_wait_padding
        if shift <= 0 or timeline is None or index + 1 >= len(scenes):
            return
        next_scene = scenes[index + 1]
        next_scene_id = str(next_scene.get("id", f"scene_{index + 1}"))
        start = timeline.get_scene_start_time(next_scene_id)
        if start is not None:
            timeline.shift_from(start, shift)
        else:
            logger.debug(
                "FinalizePhase: Could not locate start time for scene '%s' when shifting transition wait.",
                next_scene_id,
            )

    async def _apply_one_transition(
        self, *, scenes: List[Dict[str, Any]], timeline: Timeline, index: int,
        current: Path, next_path: Path, current_duration: float, next_duration: float,
    ) -> tuple[Path, float]:
        scene = scenes[index] if index < len(scenes) else {}
        next_scene = scenes[index + 1] if index + 1 < len(scenes) else {}
        from_scene = str(scene.get("id", f"scene_{index}"))
        to_scene = str(next_scene.get("id", f"scene_{index + 1}"))
        config = scene.get("transition") if isinstance(scene, dict) else None
        if not config:
            return next_path, next_duration
        transition_type, duration = self._transition_values(config)
        offset = max(0.0, current_duration - duration)
        consume_next_head = self.transition_wait_padding > 0
        logger.info(
            "FinalizePhase: Applying transition '%s' (d=%.2fs, offset=%.2fs, wait=%.2fs, timeline_shift=%.2fs) between %s -> %s",
            transition_type, duration, offset, self.transition_wait_padding,
            self.transition_wait_padding, current.name, next_path.name,
        )
        output = await self._render_transition_boundary(
            current=current, next_path=next_path, index=index,
            from_scene=from_scene, to_scene=to_scene, transition_type=transition_type,
            duration=duration, offset=offset, consume_next_head=consume_next_head,
            current_duration=current_duration, next_duration=next_duration,
        )
        self._shift_transition_timeline(timeline, scenes, index)
        merged = (
            current_duration + next_duration + self.transition_wait_padding
            if self.transition_wait_padding > 0
            else current_duration + next_duration - duration
        )
        return output, max(0.0, merged)

    async def _apply_scene_transitions(
        self, scenes: List[Dict[str, Any]], timeline: Timeline,
        paths: List[Path], durations: List[float],
    ) -> Tuple[List[Path], List[float]]:
        if len(paths) < 2:
            return paths, durations
        logger.info("FinalizePhase: Applying scene transitions where defined...")
        merged_paths: List[Path] = []
        merged_durations: List[float] = []
        current, current_duration = paths[0], durations[0] if durations else 0.0
        for index in range(len(paths) - 1):
            next_path = paths[index + 1]
            next_duration = durations[index + 1] if index + 1 < len(durations) else 0.0
            scene = scenes[index] if index < len(scenes) else {}
            if not (scene.get("transition") if isinstance(scene, dict) else None):
                merged_paths.append(current)
                merged_durations.append(current_duration)
                current, current_duration = next_path, next_duration
                continue
            current, current_duration = await self._apply_one_transition(
                scenes=scenes, timeline=timeline, index=index, current=current,
                next_path=next_path, current_duration=current_duration,
                next_duration=next_duration,
            )
        merged_paths.append(current)
        merged_durations.append(current_duration)
        return merged_paths, merged_durations
