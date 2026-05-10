# -*- coding: utf-8 -*-
import asyncio
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from zundamotion.cache import CacheManager
from zundamotion.exceptions import PipelineError
from zundamotion.timeline import Timeline
from zundamotion.utils.ffmpeg_probe import get_media_info, get_audio_duration, get_media_duration
from zundamotion.utils.ffmpeg_params import AudioParams, VideoParams
from zundamotion.utils.ffmpeg_capabilities import (
    _threading_flags,
    get_encoder_options,
    get_nproc_value,
)
from zundamotion.utils.ffmpeg_ops import (
    apply_transition_local,
    apply_transition,
    compare_media_params,
    concat_videos_copy,
)
from zundamotion.utils.logger import logger, time_log


class FinalizePhase:
    def __init__(
        self,
        config: Dict[str, Any],
        temp_dir: Path,
        cache_manager: CacheManager,
        video_params: VideoParams,
        audio_params: AudioParams,
        hw_encoder: str = "auto",
        quality: str = "balanced",
        final_copy_only: bool = False,  # 追加
    ):
        self.config = config
        self.temp_dir = temp_dir
        self.cache_manager = cache_manager
        self.video_params = video_params
        self.audio_params = audio_params
        self.hw_encoder = hw_encoder
        self.quality = quality
        self.final_copy_only = final_copy_only  # 追加
        self.finalize_cache_enabled = bool(
            (config.get("system", {}) or {}).get("finalize_cache", True)
        )
        transitions_cfg = (config.get("transitions") or {})
        wait_value = transitions_cfg.get("wait_padding_seconds", 2.0)
        try:
            wait_seconds = float(wait_value)
        except (TypeError, ValueError):
            logger.warning(
                "FinalizePhase: Invalid transitions.wait_padding_seconds=%s. Falling back to 0.0s.",
                wait_value,
            )
            wait_seconds = 0.0
        self.transition_wait_padding = max(0.0, wait_seconds)

    @staticmethod
    def _file_signature(path: Path) -> Dict[str, Any]:
        resolved = Path(path).resolve()
        try:
            stat = resolved.stat()
            digest = hashlib.sha256()
            with resolved.open("rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    digest.update(chunk)
            return {
                "size": stat.st_size,
                "sha256": digest.hexdigest(),
            }
        except Exception:
            return {"path": str(resolved), "missing": True}

    @time_log(logger)
    async def run(  # async を追加
        self,
        scenes: List[Dict[str, Any]],
        timeline: Timeline,
        line_data_map: Dict[str, Dict[str, Any]],
        scene_video_paths: List[Path],
        used_voicevox_info: List[Tuple[int, str]],
        output_stem: str = "final_output",
    ) -> Path:
        """Phase 4: Finalize the video."""
        logger.info("FinalizePhase: Finalizing video...")

        if not scene_video_paths:
            raise PipelineError("No video clips to finalize.")

        # 1) シーン間トランジションの適用（先行シーンの transition を次シーンとの境界に適用）
        processed_paths: List[Path] = list(scene_video_paths)

        duration_tasks = [get_media_duration(str(p)) for p in processed_paths]
        scene_durations: List[float] = []
        if duration_tasks:
            duration_results = await asyncio.gather(*duration_tasks, return_exceptions=True)
            for path, result in zip(processed_paths, duration_results):
                if isinstance(result, Exception):
                    logger.warning(
                        "FinalizePhase: Failed to probe duration for %s (%s). Falling back to 0.0s.",
                        path.name,
                        result,
                    )
                    scene_durations.append(0.0)
                else:
                    try:
                        scene_durations.append(float(result))
                    except Exception:
                        scene_durations.append(0.0)

        if len(processed_paths) >= 2:
            logger.info("FinalizePhase: Applying scene transitions where defined...")
            merged: List[Path] = []
            current: Path = processed_paths[0]
            current_duration = scene_durations[0] if scene_durations else 0.0
            for i in range(len(processed_paths) - 1):
                next_path = processed_paths[i + 1]
                next_duration = scene_durations[i + 1] if i + 1 < len(scene_durations) else 0.0
                scene = scenes[i] if i < len(scenes) else {}
                transition_cfg = scene.get("transition") if isinstance(scene, dict) else None

                if transition_cfg:
                    try:
                        t_type = str(transition_cfg.get("type", "fade"))
                        t_dur = float(transition_cfg.get("duration", 1.0))
                    except Exception:
                        t_type = "fade"
                        t_dur = 1.0

                    # offset = 現在クリップの末尾から duration 秒前
                    offset = max(0.0, current_duration - t_dur)
                    consume_next_head = self.transition_wait_padding > 0

                    out_path = self.temp_dir / f"transition_{i:03d}_{i+1:03d}.mp4"
                    timeline_shift = self.transition_wait_padding
                    logger.info(
                        "FinalizePhase: Applying transition '%s' (d=%.2fs, offset=%.2fs, wait=%.2fs, timeline_shift=%.2fs) between %s -> %s",
                        t_type,
                        t_dur,
                        offset,
                        self.transition_wait_padding,
                        timeline_shift,
                        current.name,
                        Path(next_path).name,
                    )
                    transition_key_data = {
                        "type": "finalize_transition_boundary",
                        "version": "20260510_v1",
                        "current": self._file_signature(current),
                        "next": self._file_signature(next_path),
                        "transition": {
                            "type": t_type,
                            "duration": t_dur,
                            "offset": offset,
                            "wait_padding": self.transition_wait_padding,
                            "consume_next_head": consume_next_head,
                        },
                        "video_params": self.video_params.__dict__,
                        "audio_params": self.audio_params.__dict__,
                        "hw_encoder": self.hw_encoder,
                    }

                    async def transition_creator(cache_output_path: Path) -> Path:
                        await apply_transition_local(
                            str(current),
                            str(next_path),
                            str(cache_output_path),
                            t_type,
                            t_dur,
                            offset,
                            self.video_params,
                            self.audio_params,
                            wait_padding=self.transition_wait_padding,
                            hw_encoder=self.hw_encoder,
                            consume_next_head=consume_next_head,
                        )
                        return cache_output_path

                    if self.finalize_cache_enabled:
                        out_path = await self.cache_manager.get_or_create(
                            key_data=transition_key_data,
                            file_name=f"finalize_transition_{i:03d}_{i+1:03d}",
                            extension="mp4",
                            creator_func=transition_creator,
                        )
                    else:
                        await transition_creator(out_path)
                    if timeline_shift > 0 and timeline is not None and i + 1 < len(scenes):
                        next_scene = scenes[i + 1]
                        next_scene_id = str(next_scene.get("id", f"scene_{i+1}"))
                        gap_start = timeline.get_scene_start_time(next_scene_id)
                        if gap_start is not None:
                            timeline.shift_from(
                                gap_start,
                                timeline_shift,
                            )
                        else:
                            logger.debug(
                                "FinalizePhase: Could not locate start time for scene '%s' when shifting transition wait.",
                                next_scene_id,
                            )
                    current = out_path
                    if self.transition_wait_padding > 0:
                        merged_duration = (
                            current_duration
                            + next_duration
                            + self.transition_wait_padding
                        )
                    else:
                        merged_duration = current_duration + next_duration - t_dur
                    current_duration = max(0.0, merged_duration)
                else:
                    # トランジション未指定なら、これまでの current を確定し次へ
                    merged.append(current)
                    current = next_path
                    current_duration = next_duration

            # ループ終了後の最後の current を確定
            merged.append(current)
            processed_paths = merged

        safe_output_stem = output_stem or "final_output"
        output_video_path = self.temp_dir / f"{safe_output_stem}.mp4"
        input_video_str_paths = [str(p.resolve()) for p in processed_paths]

        final_concat_key_data = {
            "type": "finalize_concat_intermediate",
            "version": "20260510_v1",
            "inputs": [self._file_signature(path) for path in processed_paths],
            "video_params": self.video_params.__dict__,
            "audio_params": self.audio_params.__dict__,
            "hw_encoder": self.hw_encoder,
            "quality": self.quality,
            "movflags_faststart": True,
        }

        async def final_concat_creator(cache_output_path: Path) -> Path:
            await self._concat_processed_paths(
                processed_paths,
                cache_output_path,
                input_video_str_paths,
            )
            return cache_output_path

        if self.finalize_cache_enabled:
            output_video_path = await self.cache_manager.get_or_create(
                key_data=final_concat_key_data,
                file_name="finalize_concat",
                extension="mp4",
                creator_func=final_concat_creator,
            )
        else:
            await final_concat_creator(output_video_path)

        final_video_duration = await get_media_duration(str(output_video_path))
        logger.info(
            f"FinalizePhase: Final video '{output_video_path.name}' actual duration: {final_video_duration:.2f}s"
        )

        return output_video_path

    async def _concat_processed_paths(
        self,
        processed_paths: List[Path],
        output_video_path: Path,
        input_video_str_paths: List[str],
    ) -> Path:
        """Concat transition-processed scene videos, copying when possible."""

        if await compare_media_params(input_video_str_paths):
            logger.info(
                "FinalizePhase: All video clips have identical parameters. Attempting -c copy concat."
            )
            try:
                # Final output should be faststart-enabled for better streaming
                await concat_videos_copy(
                    input_video_str_paths, str(output_video_path), movflags_faststart=True
                )
                logger.info(
                    f"FinalizePhase: Successfully concatenated videos using -c copy to {output_video_path}"
                )
                return output_video_path
            except Exception as e:
                logger.warning(
                    f"FinalizePhase: Failed to concat with -c copy: {e}. Falling back to re-encode concat."
                )
                if self.final_copy_only:
                    raise PipelineError(
                        "FinalizePhase: --final-copy-only is enabled, but -c copy concat failed."
                    )
                await self._reencode_concat(processed_paths, output_video_path)
        else:
            # パラメータ不一致時の詳細ログ
            logger.warning("FinalizePhase: Video parameters mismatch.")
            base_info = None
            if input_video_str_paths:
                base_info = await get_media_info(input_video_str_paths[0])
                logger.warning(
                    f"  Base video parameters ({input_video_str_paths[0]}): {json.dumps(base_info, indent=2)}"
                )

            for i, path in enumerate(input_video_str_paths[1:], start=1):
                current_info = await get_media_info(path)
                logger.warning(
                    f"  Mismatch detected with {path}: {json.dumps(current_info, indent=2)}"
                )
                # ここで詳細な差分を比較してログに出力することも可能だが、まずは全体をログに出す

            if self.final_copy_only:
                raise PipelineError(
                    "FinalizePhase: --final-copy-only is enabled, but video parameters mismatch."
                )
            logger.warning("FinalizePhase: Falling back to re-encode concat.")
            await self._reencode_concat(processed_paths, output_video_path)

        return output_video_path

    async def _reencode_concat(
        self, scene_video_paths: List[Path], output_video_path: Path
    ):  # async を追加
        """
        従来の再エンコード方式で動画を結合する。
        """
        logger.info(
            "FinalizePhase: Performing re-encode concat using -filter_complex concat."
        )

        encoder, video_opts = await get_encoder_options(self.hw_encoder, self.quality)
        audio_opts = self.audio_params.to_ffmpeg_opts()
        threading_flags = _threading_flags()

        cmd = [
            "ffmpeg",
            "-y",
        ]
        cmd.extend(threading_flags)

        for p in scene_video_paths:
            cmd.extend(["-i", str(p.resolve())])

        num_clips = len(scene_video_paths)
        video_inputs = "".join([f"[{i}:v]" for i in range(num_clips)])
        audio_inputs = "".join([f"[{i}:a]" for i in range(num_clips)])

        filter_complex = (
            f"{video_inputs}concat=n={num_clips}:v=1:a=0[v_out];"
            f"{audio_inputs}concat=n={num_clips}:v=0:a=1[a_out]"
        )

        cmd.extend(["-filter_complex", filter_complex])
        cmd.extend(["-map", "[v_out]", "-map", "[a_out]"])

        cmd.extend(["-c:v", encoder])
        cmd.extend(video_opts)
        cmd.extend(audio_opts)
        cmd.extend(["-movflags", "+faststart"])  # final output only
        cmd.extend(["-shortest", str(output_video_path)])

        logger.info(f"FinalizePhase: FFmpeg re-encode concat command: {' '.join(cmd)}")

        try:
            proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
            logger.debug(f"FFmpeg stdout:\n{proc.stdout}")
            logger.debug(f"FFmpeg stderr:\n{proc.stderr}")
            logger.info(
                f"Successfully concatenated all scene videos with re-encoding to {output_video_path}"
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"Error concatenating final video with re-encoding: {e}")
            logger.error(f"FFmpeg stdout:\n{e.stdout}")
            logger.error(f"FFmpeg stderr:\n{e.stderr}")
            raise PipelineError(f"Failed to finalize video with re-encoding: {e}")
        return output_video_path
