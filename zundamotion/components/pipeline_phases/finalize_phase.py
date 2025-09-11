# -*- coding: utf-8 -*-
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

    @time_log(logger)
    async def run(  # async を追加
        self,
        scenes: List[Dict[str, Any]],
        timeline: Timeline,
        line_data_map: Dict[str, Dict[str, Any]],
        scene_video_paths: List[Path],
        used_voicevox_info: List[Tuple[int, str]],
    ) -> Path:
        """Phase 4: Finalize the video."""
        logger.info("FinalizePhase: Finalizing video...")

        if not scene_video_paths:
            raise PipelineError("No video clips to finalize.")

        # 1) シーン間トランジションの適用（先行シーンの transition を次シーンとの境界に適用）
        processed_paths: List[Path] = list(scene_video_paths)
        if len(processed_paths) >= 2:
            logger.info("FinalizePhase: Applying scene transitions where defined...")
            merged: List[Path] = []
            current: Path = processed_paths[0]
            for i in range(len(processed_paths) - 1):
                next_path = processed_paths[i + 1]
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
                    try:
                        cur_dur = await get_media_duration(str(current))
                    except Exception:
                        cur_dur = 0.0
                    offset = max(0.0, cur_dur - t_dur)

                    out_path = self.temp_dir / f"transition_{i:03d}_{i+1:03d}.mp4"
                    logger.info(
                        f"FinalizePhase: Applying transition '{t_type}' (d={t_dur}s, offset={offset:.2f}s) between {current.name} -> {Path(next_path).name}"
                    )
                    await apply_transition(
                        str(current),
                        str(next_path),
                        str(out_path),
                        t_type,
                        t_dur,
                        offset,
                        self.video_params,
                        self.audio_params,
                    )
                    current = out_path
                else:
                    # トランジション未指定なら、これまでの current を確定し次へ
                    merged.append(current)
                    current = next_path

            # ループ終了後の最後の current を確定
            merged.append(current)
            processed_paths = merged

        output_video_path = self.temp_dir / "final_output.mp4"
        input_video_str_paths = [str(p.resolve()) for p in processed_paths]

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
                return output_video_path  # 成功時に即座にリターン
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

        final_video_duration = await get_media_duration(str(output_video_path))
        logger.info(
            f"FinalizePhase: Final video '{output_video_path.name}' actual duration: {final_video_duration:.2f}s"
        )

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
