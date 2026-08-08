"""Execute subtitle overlay FFmpeg jobs with diagnostics."""

from __future__ import annotations

import time
from importlib import import_module
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...utils.logger import logger


async def run_subtitle_ffmpeg(
    cmd: List[str], context: Optional[Dict[str, Any]] = None
) -> None:
    video_module = import_module("zundamotion.components.video")
    await video_module._run_ffmpeg_async(cmd, context=context)


async def execute_subtitle_burn(
    *,
    cmd: List[str],
    base_video: Path,
    output_path: Path,
    scene_id: Optional[str],
    chunk_index: Optional[int],
) -> Path:
    started = time.perf_counter()
    await run_subtitle_ffmpeg(
        cmd,
        context={
            "phase": "VideoPhase",
            "operation": "subtitle_burn",
            "scene_id": scene_id,
            "chunk_index": chunk_index,
            "input_paths": [str(base_video)],
            "output_path": str(output_path),
        },
    )
    logger.info(
        "[FilterGraph] target=%s ffmpeg_ms=%.1f",
        output_path.stem,
        (time.perf_counter() - started) * 1000.0,
    )
    return output_path


async def execute_simple_subtitle_job(cmd: List[str], output_path: Path) -> Path:
    await run_subtitle_ffmpeg(cmd)
    return output_path
