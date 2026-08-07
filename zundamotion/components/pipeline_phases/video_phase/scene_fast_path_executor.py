"""Execution, fallback, and cache handling for the simple scene fast path."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from ....utils.ffmpeg_runner import run_ffmpeg_async as _run_ffmpeg_async
from ....utils.logger import logger


class SceneFastPathExecutorMixin:
    """Execute a planned fast-scene command while preserving fallback semantics."""

    async def _render_simple_scene_fast(
        self,
        *,
        scene_id: str,
        bg_default: str,
        scene_duration: float,
        start_time_by_idx: Dict[int, float],
        scene_hash_data: Dict[str, Any],
    ) -> Optional[Path]:
        lines = self.scene.get("lines", []) or []
        if not lines:
            return None

        output_path = self.temp_dir / f"scene_output_{scene_id}.mp4"
        plan = self._build_simple_scene_fast_plan(
            scene_id=scene_id,
            bg_default=bg_default,
            scene_duration=scene_duration,
            start_time_by_idx=start_time_by_idx,
        )
        cmd = self._build_simple_scene_fast_command(
            scene_id=scene_id,
            scene_duration=scene_duration,
            output_path=output_path,
            plan=plan,
        )

        try:
            await _run_ffmpeg_async(cmd)
        except subprocess.CalledProcessError as exc:
            logger.warning(
                "Scene fast path failed for '%s': %s",
                scene_id,
                (exc.stderr or exc.stdout or "").strip(),
            )
            return None

        self.cache_manager.cache_file(
            source_path=output_path,
            key_data=scene_hash_data,
            file_name=f"scene_{scene_id}",
            extension="mp4",
        )
        logger.info(
            "Scene %s: rendered via simple fast path -> %s",
            scene_id,
            output_path.name,
        )
        return output_path
