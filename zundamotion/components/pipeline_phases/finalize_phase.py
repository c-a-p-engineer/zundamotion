# -*- coding: utf-8 -*-
"""Final output orchestration after scene rendering."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from zundamotion.cache import CacheManager
from zundamotion.exceptions import PipelineError
from zundamotion.timeline import Timeline
from zundamotion.utils.ffmpeg_ops import compare_media_params, concat_videos_safe
from zundamotion.utils.ffmpeg_params import AudioParams, VideoParams
from zundamotion.utils.ffmpeg_probe import get_media_duration
from zundamotion.utils.logger import logger, time_log
from .finalize_cache import FinalizeCacheMixin
from .finalize_concat import FinalizeConcatMixin
from .finalize_transitions import FinalizeTransitionMixin


class FinalizePhase(FinalizeTransitionMixin, FinalizeConcatMixin, FinalizeCacheMixin):
    def __init__(
        self,
        config: Dict[str, Any],
        temp_dir: Path,
        cache_manager: CacheManager,
        video_params: VideoParams,
        audio_params: AudioParams,
        hw_encoder: str = "auto",
        quality: str = "balanced",
        final_copy_only: bool = False,
    ):
        self.config = config
        self.temp_dir = temp_dir
        self.cache_manager = cache_manager
        self.video_params = video_params
        self.audio_params = audio_params
        self.hw_encoder = hw_encoder
        self.quality = quality
        self.final_copy_only = final_copy_only
        self.finalize_cache_enabled = bool(
            (config.get("system", {}) or {}).get("finalize_cache", True)
        )
        transitions = config.get("transitions") or {}
        raw_wait = transitions.get("wait_padding_seconds", 2.0)
        try:
            wait_seconds = float(raw_wait)
        except (TypeError, ValueError):
            logger.warning(
                "FinalizePhase: Invalid transitions.wait_padding_seconds=%s. Falling back to 0.0s.",
                raw_wait,
            )
            wait_seconds = 0.0
        self.transition_wait_padding = max(0.0, wait_seconds)

    @time_log(logger)
    async def run(
        self,
        scenes: List[Dict[str, Any]],
        timeline: Timeline,
        line_data_map: Dict[str, Dict[str, Any]],
        scene_video_paths: List[Path],
        used_voicevox_info: List[Tuple[int, str]],
        output_stem: str = "final_output",
    ) -> Path:
        """Apply transitions, concatenate scene outputs, and validate final duration."""
        logger.info("FinalizePhase: Finalizing video...")
        if not scene_video_paths:
            raise PipelineError("No video clips to finalize.")
        processed = list(scene_video_paths)
        durations = await self._probe_scene_durations(processed)
        processed, durations = await self._apply_scene_transitions(
            scenes, timeline, processed, durations
        )
        output = await self._finalize_concat_output(processed, durations, output_stem)
        final_duration = await get_media_duration(
            str(output), caller="finalize_output_duration"
        )
        logger.info(
            "FinalizePhase: Final video '%s' actual duration: %.2fs",
            output.name, final_duration,
        )
        return output
