"""Final concat cache planning and FFmpeg execution for FinalizePhase."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from zundamotion.exceptions import PipelineError
from zundamotion.utils.ffmpeg_capabilities import _threading_flags, get_encoder_options
from zundamotion.utils.ffmpeg_ops import compare_media_params, concat_videos_safe
from zundamotion.utils.ffmpeg_probe import get_media_info
from zundamotion.utils.ffmpeg_runner import run_ffmpeg_async as _run_ffmpeg_async
from zundamotion.utils.logger import logger


class FinalizeConcatMixin:
    def _final_concat_key(self, processed_paths: List[Path]) -> Dict[str, Any]:
        return {
            "type": "finalize_concat_intermediate",
            "version": "20260510_v1",
            "inputs": [self._file_signature(path) for path in processed_paths],
            "video_params": self.video_params.__dict__,
            "audio_params": self.audio_params.__dict__,
            "hw_encoder": self.hw_encoder,
            "quality": self.quality,
            "movflags_faststart": True,
        }

    async def _finalize_concat_output(
        self, processed_paths: List[Path], processed_durations: List[float],
        output_stem: str,
    ) -> Path:
        output = self.temp_dir / f"{output_stem or 'final_output'}.mp4"
        input_paths = [str(path.resolve()) for path in processed_paths]

        async def creator(cache_output: Path) -> Path:
            await self._concat_processed_paths(processed_paths, cache_output, input_paths)
            return cache_output

        if not self.finalize_cache_enabled:
            return await creator(output)
        return await self._get_or_create_finalize_cache(
            key_data=self._final_concat_key(processed_paths),
            file_name="finalize_concat", extension="mp4", creator_func=creator,
            expected_duration=sum(processed_durations), cache_label="final concat",
        )

    async def _concat_processed_paths(
        self, processed_paths: List[Path], output_video_path: Path,
        input_video_str_paths: List[str],
    ) -> Path:
        if await compare_media_params(input_video_str_paths):
            logger.info("FinalizePhase: All video clips have identical parameters. Attempting -c copy concat.")
            try:
                mode = await concat_videos_safe(
                    input_video_str_paths, str(output_video_path), self.audio_params,
                    movflags_faststart=True,
                    context={
                        "phase": "FinalizePhase", "operation": "final_concat",
                        "output_path": str(output_video_path),
                    },
                )
                logger.info(
                    "FinalizePhase: Successfully concatenated videos using %s to %s",
                    mode, output_video_path,
                )
                return output_video_path
            except Exception as exc:
                logger.warning(
                    "FinalizePhase: Failed to concat with -c copy: %s. Falling back to re-encode concat.",
                    exc,
                )
                if self.final_copy_only:
                    raise PipelineError(
                        "FinalizePhase: --final-copy-only is enabled, but -c copy concat failed."
                    )
                return await self._reencode_concat(processed_paths, output_video_path)
        await self._log_media_mismatch(input_video_str_paths)
        if self.final_copy_only:
            raise PipelineError(
                "FinalizePhase: --final-copy-only is enabled, but video parameters mismatch."
            )
        logger.warning("FinalizePhase: Falling back to re-encode concat.")
        return await self._reencode_concat(processed_paths, output_video_path)

    async def _log_media_mismatch(self, paths: List[str]) -> None:
        logger.warning("FinalizePhase: Video parameters mismatch.")
        if not paths:
            return
        base = await get_media_info(paths[0], caller="finalize_compare_media_params")
        logger.warning("  Base video parameters (%s): %s", paths[0], json.dumps(base, indent=2))
        for path in paths[1:]:
            current = await get_media_info(path, caller="finalize_compare_media_params")
            logger.warning("  Mismatch detected with %s: %s", path, json.dumps(current, indent=2))

    async def _reencode_concat(
        self, scene_video_paths: List[Path], output_video_path: Path,
    ) -> Path:
        logger.info("FinalizePhase: Performing re-encode concat using -filter_complex concat.")
        encoder, video_opts = await get_encoder_options(self.hw_encoder, self.quality)
        cmd = ["ffmpeg", "-y", *_threading_flags()]
        for path in scene_video_paths:
            cmd.extend(["-i", str(path.resolve())])
        count = len(scene_video_paths)
        video_inputs = "".join(f"[{index}:v]" for index in range(count))
        audio_inputs = "".join(f"[{index}:a]" for index in range(count))
        cmd.extend([
            "-filter_complex",
            f"{video_inputs}concat=n={count}:v=1:a=0[v_out];"
            f"{audio_inputs}concat=n={count}:v=0:a=1[a_out]",
            "-map", "[v_out]", "-map", "[a_out]", "-c:v", encoder,
            *video_opts, *self.audio_params.to_ffmpeg_opts(),
            "-movflags", "+faststart", "-shortest", str(output_video_path),
        ])
        logger.info("FinalizePhase: FFmpeg re-encode concat command: %s", " ".join(cmd))
        try:
            proc = await _run_ffmpeg_async(
                cmd,
                context={
                    "phase": "FinalizePhase", "operation": "final_concat_reencode",
                    "output_path": str(output_video_path),
                },
            )
            logger.debug("FFmpeg stdout:\n%s", proc.stdout)
            logger.debug("FFmpeg stderr:\n%s", proc.stderr)
            logger.info("Successfully concatenated all scene videos with re-encoding to %s", output_video_path)
            return output_video_path
        except subprocess.CalledProcessError as exc:
            logger.error("Error concatenating final video with re-encoding: %s", exc)
            logger.error("FFmpeg stdout:\n%s", exc.stdout)
            logger.error("FFmpeg stderr:\n%s", exc.stderr)
            raise PipelineError(f"Failed to finalize video with re-encoding: {exc}")
