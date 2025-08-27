# -*- coding: utf-8 -*-
import multiprocessing
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..cache import CacheManager
from ..utils.ffmpeg_utils import (
    AudioParams,
    VideoParams,
    calculate_overlay_position,
    concat_videos_copy,
    get_media_info,
    has_audio_stream,
    has_cuda_filters,
    normalize_media,
)


class VideoRenderer:
    def __init__(
        self,
        config: Dict[str, Any],
        temp_dir: Path,
        cache_manager: CacheManager,
        jobs: str = "0",
        hw_kind: Optional[str] = None,
        video_params: Optional[VideoParams] = None,
        audio_params: Optional[AudioParams] = None,
        has_cuda_filters: bool = False,
    ):
        self.config = config
        self.temp_dir = temp_dir
        self.cache_manager = cache_manager
        self.video_config = config.get("video", {})
        self.bgm_config = config.get("bgm", {})
        self.jobs = jobs
        self.ffmpeg_path = "ffmpeg"  # PATH 前提

        self.hw_kind = hw_kind
        self.video_params = video_params or VideoParams()
        self.audio_params = audio_params or AudioParams()
        self.has_cuda_filters = has_cuda_filters

        if self.has_cuda_filters:
            print("[Encoder] CUDA filters (scale_cuda, overlay_cuda) are available.")
        else:
            print("[Encoder] CUDA filters are not available. Using CPU filters.")

    @classmethod
    async def create(
        cls,
        config: Dict[str, Any],
        temp_dir: Path,
        cache_manager: CacheManager,
        jobs: str = "0",
        hw_kind: Optional[str] = None,
        video_params: Optional[VideoParams] = None,
        audio_params: Optional[AudioParams] = None,
    ):
        has_cuda_filters_val = await has_cuda_filters(
            config.get("ffmpeg_path", "ffmpeg")
        )
        return cls(
            config,
            temp_dir,
            cache_manager,
            jobs,
            hw_kind,
            video_params,
            audio_params,
            has_cuda_filters_val,
        )

    # --------------------------
    # 内部ユーティリティ
    # --------------------------
    def _thread_flags(self) -> List[str]:
        """
        ffmpeg7 向けスレッド指定:
        -threads 0（自動）＋ filter_threads / filter_complex_threads = 物理コア数
        """
        nproc = multiprocessing.cpu_count() or 1
        if self.jobs == "auto":
            threads = "0"
            print(f"[Jobs] Auto-detected CPU cores: {nproc} (threads=auto)")
        else:
            try:
                num_jobs = int(self.jobs)
                if num_jobs < 0:
                    raise ValueError
                threads = str(num_jobs)
                print(f"[Jobs] Using {threads} specified threads")
            except ValueError:
                threads = "0"
                print(f"[Jobs] Invalid --jobs '{self.jobs}'. Falling back to auto (0).")
        return [
            "-threads",
            threads,
            "-filter_threads",
            str(nproc),
            "-filter_complex_threads",
            str(nproc),
        ]

    # --------------------------
    # クリップ生成（字幕PNG/立ち絵対応）
    # --------------------------
    async def render_clip(
        self,
        audio_path: Path,
        duration: float,
        background_config: Dict[str, Any],
        characters_config: List[Dict[str, Any]],
        output_filename: str,
        extra_subtitle_inputs: Optional[Dict[str, Any]] = None,
        insert_config: Optional[Dict[str, Any]] = None,
    ) -> Optional[Path]:
        """
        drawtext 全廃版:
        - 字幕は PNG 事前生成入力（-loop 1 -i png）→ overlay のみで合成
        - 位置はデフォルトで下中央（下マージン: subtitle.bottom_margin_px or 100）
        - subtitle_filter_snippet は無視（誤式混入防止）
        """
        output_path = self.temp_dir / f"{output_filename}.mp4"
        width = self.video_params.width
        height = self.video_params.height
        fps = self.video_params.fps

        # 下マージン（px）
        subtitle_cfg = self.config.get("subtitle", {})
        bottom_margin = int(subtitle_cfg.get("bottom_margin_px", 100))

        print(f"[Video] Rendering clip -> {output_path.name}")

        cmd: List[str] = [
            self.ffmpeg_path,
            "-y",
            "-hide_banner",
            "-loglevel",
            "warning",
        ]
        cmd.extend(self._thread_flags())

        # --- Inputs -------------------------------------------------------------
        input_layers: List[Dict[str, Any]] = []

        # 0) Background
        bg_path_str = background_config.get("path")
        if not bg_path_str:
            raise ValueError("Background path is missing.")
        bg_path = Path(bg_path_str)

        if background_config.get("type") == "video":
            try:
                # 正規化（失敗時は as-is）
                _ = get_media_info(str(bg_path))
                bg_path = await normalize_media(
                    input_path=bg_path,
                    video_params=self.video_params,
                    audio_params=self.audio_params,
                    cache_manager=self.cache_manager,
                )
            except Exception as e:
                print(
                    f"[Warning] Could not inspect/normalize BG video {bg_path.name}: {e}. Using as-is."
                )
            cmd.extend(
                [
                    "-ss",
                    str(background_config.get("start_time", 0.0)),
                    "-i",
                    str(bg_path),
                ]
            )
        else:
            cmd.extend(["-loop", "1", "-i", str(bg_path)])
        input_layers.append({"type": "video", "index": len(input_layers)})

        # 1) Speech audio
        cmd.extend(["-i", str(audio_path)])
        speech_audio_index = len(input_layers)
        input_layers.append({"type": "audio", "index": speech_audio_index})

        # 2) Subtitle PNG (optional)
        subtitle_ffmpeg_index = -1
        subtitle_png_used = False
        if isinstance(extra_subtitle_inputs, dict) and extra_subtitle_inputs.get("-i"):
            loop_val = extra_subtitle_inputs.get("-loop", "1")
            png_path = extra_subtitle_inputs["-i"]
            cmd.extend(["-loop", loop_val, "-i", str(Path(png_path).resolve())])
            subtitle_ffmpeg_index = len(input_layers)
            input_layers.append({"type": "video", "index": subtitle_ffmpeg_index})
            subtitle_png_used = True
        elif extra_subtitle_inputs:
            print(
                f"[Warning] extra_subtitle_inputs has unexpected format: {extra_subtitle_inputs}. Subtitle overlay will be skipped."
            )

        # 3) Insert media (optional)
        insert_ffmpeg_index = -1
        insert_audio_index = -1
        insert_is_image = False
        insert_path: Optional[Path] = None
        if insert_config:
            insert_path = Path(insert_config["path"])
            insert_is_image = insert_path.suffix.lower() in [
                ".png",
                ".jpg",
                ".jpeg",
                ".bmp",
                ".webp",
            ]
            if not insert_is_image:
                try:
                    _ = get_media_info(str(insert_path))
                    insert_path = await normalize_media(
                        input_path=insert_path,
                        video_params=self.video_params,
                        audio_params=self.audio_params,
                        cache_manager=self.cache_manager,
                    )
                except Exception as e:
                    print(
                        f"[Warning] Could not inspect/normalize insert video {insert_path.name}: {e}. Using as-is."
                    )
                cmd.extend(["-i", str(insert_path)])
            else:
                cmd.extend(["-loop", "1", "-i", str(insert_path.resolve())])
            insert_ffmpeg_index = len(input_layers)
            input_layers.append({"type": "video", "index": insert_ffmpeg_index})
            if not insert_is_image and has_audio_stream(str(insert_path)):
                insert_audio_index = insert_ffmpeg_index

        # 4) Characters (optional)
        character_indices: Dict[int, int] = {}
        any_character_visible = False
        for i, char_config in enumerate(characters_config):
            if not char_config.get("visible", False):
                continue
            any_character_visible = True
            char_name = char_config.get("name")
            char_expression = char_config.get("expression", "default")
            if not char_name:
                print("[Warning] Skipping character with missing name.")
                continue
            char_image_path = Path(
                f"assets/characters/{char_name}/{char_expression}.png"
            )
            if not char_image_path.exists():
                char_image_path = Path(f"assets/characters/{char_name}/default.png")
                if not char_image_path.exists():
                    print(
                        f"[Warning] Character image not found for {char_name}/{char_expression} (and default). Skipping."
                    )
                    continue
            character_indices[i] = len(input_layers)
            cmd.extend(["-loop", "1", "-i", str(char_image_path.resolve())])
            input_layers.append({"type": "video", "index": len(input_layers)})

        # ---- ここで GPU フィルタ使用可否を判定 --------------------------------
        # RGBAを含むオーバーレイ（字幕PNG/立ち絵/挿入画像）が1つでもあれば CPU 合成へ
        uses_alpha_overlay = (
            subtitle_png_used
            or any_character_visible
            or (insert_config and insert_is_image)
        )
        use_cuda_filters = (
            self.has_cuda_filters and self.hw_kind == "nvenc" and not uses_alpha_overlay
        )
        if use_cuda_filters:
            print(
                "[Filters] Using CUDA filters for scaling/overlay (no RGBA overlays)."
            )
        else:
            if self.hw_kind == "nvenc" and self.has_cuda_filters and uses_alpha_overlay:
                print(
                    "[Filters] Detected RGBA overlays (subtitle/characters/images). "
                    "Falling back to CPU overlays while keeping NVENC encoding."
                )
            else:
                print("[Filters] Using CPU filters.")

        # --- Filter Graph -------------------------------------------------------
        filter_complex_parts: List[str] = []

        # 背景スケール
        if use_cuda_filters:
            # CUDA: 一旦GPUへ上げてスケール＋fps。RGBA→NV12 変換はCUDA側に任せる。
            filter_complex_parts.append("[0:v]format=rgba,hwupload_cuda[hw_bg_in]")
            filter_complex_parts.append(
                f"[hw_bg_in]scale_cuda={width}:{height},fps={fps}[bg]"
            )
        else:
            filter_complex_parts.append(
                f"[0:v]scale={width}:{height}:flags=lanczos,fps={fps}[bg]"
            )

        current_video_stream = "[bg]"
        overlay_streams: List[str] = []
        overlay_filters: List[str] = []

        # 挿入メディア overlay
        if insert_config and insert_ffmpeg_index != -1:
            scale = float(insert_config.get("scale", 1.0))
            anchor = insert_config.get("anchor", "middle_center")
            pos = insert_config.get("position", {"x": "0", "y": "0"})
            x_expr, y_expr = calculate_overlay_position(
                "W",
                "H",
                "w",
                "h",
                anchor,
                str(pos.get("x", "0")),
                str(pos.get("y", "0")),
            )

            if use_cuda_filters:
                # CUDA オンリー（RGBAなし前提）
                if insert_is_image:
                    # ここに来るのは想定外（uses_alpha_overlay=True でCPUに落ちる想定）
                    # ただ、保険として rgba→hwupload_cuda→scale_cuda
                    filter_complex_parts.append(
                        f"[{insert_ffmpeg_index}:v]format=rgba,hwupload_cuda,scale_cuda=iw*{scale}:ih*{scale}[insert_scaled]"
                    )
                else:
                    filter_complex_parts.append(
                        f"[{insert_ffmpeg_index}:v]format=nv12,hwupload_cuda,scale_cuda=iw*{scale}:ih*{scale}[insert_scaled]"
                    )
                overlay_streams.append("[insert_scaled]")
                overlay_filters.append(f"overlay_cuda=x={x_expr}:y={y_expr}")
            else:
                filter_complex_parts.append(
                    f"[{insert_ffmpeg_index}:v]scale=iw*{scale}:ih*{scale}[insert_scaled]"
                )
                overlay_streams.append("[insert_scaled]")
                overlay_filters.append(f"overlay=x={x_expr}:y={y_expr}")

        # 立ち絵 overlay
        for i, char_config in enumerate(characters_config):
            if not char_config.get("visible", False) or i not in character_indices:
                continue
            ffmpeg_index = character_indices[i]
            scale = float(char_config.get("scale", 1.0))
            anchor = char_config.get("anchor", "bottom_center")
            pos = char_config.get("position", {"x": "0", "y": "0"})
            x_expr, y_expr = calculate_overlay_position(
                "W",
                "H",
                "w",
                "h",
                anchor,
                str(pos.get("x", "0")),
                str(pos.get("y", "0")),
            )

            if use_cuda_filters:
                # 想定上ここには来ない（uses_alpha_overlay True → CPU 合成）
                filter_complex_parts.append(
                    f"[{ffmpeg_index}:v]format=rgba,hwupload_cuda,scale_cuda=iw*{scale}:ih*{scale}[char_scaled_{i}]"
                )
                overlay_streams.append(f"[char_scaled_{i}]")
                overlay_filters.append(f"overlay_cuda=x={x_expr}:y={y_expr}")
            else:
                filter_complex_parts.append(
                    f"[{ffmpeg_index}:v]scale=iw*{scale}:ih*{scale}[char_scaled_{i}]"
                )
                overlay_streams.append(f"[char_scaled_{i}]")
                overlay_filters.append(f"overlay=x={x_expr}:y={y_expr}")

        # 字幕PNG overlay（下中央、between(t,0,duration)）
        if subtitle_ffmpeg_index != -1:
            x_expr = "(W-w)/2"
            y_expr = f"H-{bottom_margin}-h"
            if use_cuda_filters:
                # 想定上ここには来ない（uses_alpha_overlay True → CPU 合成）
                filter_complex_parts.append(
                    f"[{subtitle_ffmpeg_index}:v]format=rgba,hwupload_cuda[subtitle_hw]"
                )
                overlay_streams.append("[subtitle_hw]")
                overlay_filters.append(
                    f"overlay_cuda=x='{x_expr}':y='{y_expr}':enable='between(t,0,{duration})'"
                )
            else:
                overlay_streams.append(f"[{subtitle_ffmpeg_index}:v]")
                overlay_filters.append(
                    f"overlay=x='{x_expr}':y='{y_expr}':enable='between(t,0,{duration})'"
                )

        # オーバーレイを連結
        if overlay_streams:
            chain = current_video_stream
            for i, stream in enumerate(overlay_streams):
                chain += f"{stream}{overlay_filters[i]}"
                if i < len(overlay_streams) - 1:
                    chain += f"[tmp_overlay_{i}];[tmp_overlay_{i}]"
                else:
                    chain += "[final_v_overlays]"
            filter_complex_parts.append(chain)
            current_video_stream = "[final_v_overlays]"
        else:
            current_video_stream = "[bg]"

        # 最終フォーマット変換
        if use_cuda_filters:
            filter_complex_parts.append(
                f"{current_video_stream}hwdownload,format=yuv420p[final_v]"
            )
        else:
            filter_complex_parts.append(
                f"{current_video_stream}format=yuv420p[final_v]"
            )

        # --- Audio --------------------------------------------------------------
        has_speech_audio = has_audio_stream(str(audio_path))

        if insert_config and insert_audio_index != -1:
            volume = float(insert_config.get("volume", 1.0))
            filter_complex_parts.append(
                f"[{insert_audio_index}:a]volume={volume}[insert_audio_vol]"
            )
            if has_speech_audio:
                filter_complex_parts.append(
                    f"[{speech_audio_index}:a][insert_audio_vol]amix=inputs=2:duration=longest:dropout_transition=0[final_a]"
                )
                audio_map = "[final_a]"
            else:
                filter_complex_parts.append(f"[insert_audio_vol]anull[final_a]")
                audio_map = "[final_a]"
        else:
            if has_speech_audio:
                filter_complex_parts.append(f"[{speech_audio_index}:a]anull[final_a]")
                audio_map = "[final_a]"
            else:
                # 無音生成
                filter_complex_parts.append(
                    f"anullsrc=channel_layout=stereo:sample_rate={self.audio_params.sample_rate},duration={duration}[final_a]"
                )
                audio_map = "[final_a]"

        # --- Assemble & Run -----------------------------------------------------
        cmd.extend(["-filter_complex", ";".join(filter_complex_parts)])
        cmd.extend(["-map", "[final_v]", "-map", audio_map])
        cmd.extend(["-t", str(duration)])
        cmd.extend(self.video_params.to_ffmpeg_opts(self.hw_kind))
        cmd.extend(self.audio_params.to_ffmpeg_opts())
        cmd.extend(["-movflags", "+faststart"])
        cmd.extend(["-shortest", str(output_path)])

        try:
            print(f"Executing FFmpeg command:\n{' '.join(cmd)}")
            process = subprocess.run(cmd, check=True, capture_output=True, text=True)
            if process.stderr:
                # warning ログも拾っておく
                print(process.stderr.strip())
        except subprocess.CalledProcessError as e:
            print(f"[Error] ffmpeg failed for {output_filename}")
            print("---- FFmpeg STDERR ----")
            print((e.stderr or "").strip())
            print("---- FFmpeg STDOUT ----")
            print((e.stdout or "").strip())
            raise
        except Exception as e:
            print(f"[Error] Unexpected exception during ffmpeg: {e}")
            raise

        return output_path

    # --------------------------
    # 無音待機クリップ
    # --------------------------
    async def render_wait_clip(
        self,
        duration: float,
        background_config: Dict[str, Any],
        output_filename: str,
        line_config: Dict[str, Any],
    ) -> Optional[Path]:
        output_path = self.temp_dir / f"{output_filename}.mp4"
        width = self.video_params.width
        height = self.video_params.height
        fps = self.video_params.fps

        print(f"[Video] Rendering wait clip -> {output_path.name}")

        cmd: List[str] = [
            self.ffmpeg_path,
            "-y",
            "-hide_banner",
            "-loglevel",
            "warning",
        ]
        cmd.extend(self._thread_flags())

        # 1) Background
        bg_path_str = background_config.get("path")
        if not bg_path_str:
            raise ValueError("Background path is missing.")
        bg_path = Path(bg_path_str)

        if background_config.get("type") == "video":
            try:
                # 正規化（失敗時は as-is）
                _ = get_media_info(str(bg_path))
                bg_path = await normalize_media(
                    input_path=bg_path,
                    video_params=self.video_params,
                    audio_params=self.audio_params,
                    cache_manager=self.cache_manager,
                )
            except Exception as e:
                print(
                    f"[Warning] Could not inspect/normalize BG video {bg_path.name}: {e}. Using as-is."
                )
            cmd.extend(
                [
                    "-ss",
                    str(background_config.get("start_time", 0.0)),
                    "-i",
                    str(bg_path),
                ]
            )
        else:
            cmd.extend(["-loop", "1", "-i", str(bg_path)])

        # 2) Silent audio
        cmd.extend(
            [
                "-f",
                "lavfi",
                "-i",
                f"anullsrc=channel_layout=stereo:sample_rate={self.audio_params.sample_rate}",
            ]
        )

        # Filters（CPUで十分）
        filter_complex = f"[0:v]scale={width}:{height},trim=duration={duration},format=yuv420p[final_v]"

        cmd.extend(["-filter_complex", filter_complex])
        cmd.extend(["-map", "[final_v]", "-map", "1:a"])
        cmd.extend(["-t", str(duration)])
        cmd.extend(self.video_params.to_ffmpeg_opts(self.hw_kind))
        cmd.extend(self.audio_params.to_ffmpeg_opts())
        cmd.extend(["-movflags", "+faststart"])
        cmd.extend(["-shortest", str(output_path)])

        try:
            print(f"Executing FFmpeg command:\n{' '.join(cmd)}")
            process = subprocess.run(cmd, check=True, capture_output=True, text=True)
            if process.stderr:
                print(process.stderr.strip())
        except subprocess.CalledProcessError as e:
            print(f"[Error] ffmpeg failed for {output_filename}")
            print("---- FFmpeg STDERR ----")
            print((e.stderr or "").strip())
            print("---- FFmpeg STDOUT ----")
            print((e.stdout or "").strip())
            raise
        except Exception as e:
            print(f"[Error] Unexpected exception during ffmpeg: {e}")
            raise

        return output_path

    # --------------------------
    # BG動画の指定長ループ
    # --------------------------
    async def render_looped_background_video(
        self, bg_video_path_str: str, duration: float, output_filename: str
    ) -> Path:
        """
        指定長でBG動画をループ書き出し。
        """
        output_path = self.temp_dir / f"{output_filename}.mp4"
        width = self.video_params.width
        height = self.video_params.height
        fps = self.video_params.fps

        print(f"[Video] Rendering looped background video -> {output_path.name}")

        cmd: List[str] = [
            self.ffmpeg_path,
            "-y",
            "-hide_banner",
            "-loglevel",
            "warning",
        ]
        cmd.extend(self._thread_flags())

        bg_video_path = Path(bg_video_path_str)
        try:
            # 正規化（失敗時は as-is）
            _ = get_media_info(str(bg_video_path))
            bg_video_path = await normalize_media(
                input_path=bg_video_path,
                video_params=self.video_params,
                audio_params=self.audio_params,
                cache_manager=self.cache_manager,
            )
        except Exception as e:
            print(
                f"[Warning] Could not inspect/normalize looped BG video {bg_video_path.name}: {e}. Using as-is."
            )

        cmd.extend(
            [
                "-stream_loop",
                "-1",
                "-i",
                str(bg_video_path),
                "-t",
                str(duration),
                "-vf",
                f"scale={width}:{height},fps={fps},format=yuv420p",
            ]
        )
        cmd.extend(self.video_params.to_ffmpeg_opts(self.hw_kind))
        cmd.extend(["-an"])  # 音声は不要
        cmd.extend(["-movflags", "+faststart"])
        cmd.extend([str(output_path)])

        try:
            print(f"Executing FFmpeg command:\n{' '.join(cmd)}")
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            print(
                f"[Error] ffmpeg failed for looped background video {output_filename}"
            )
            print("---- FFmpeg STDERR ----")
            print((e.stderr or "").strip())
            print("---- FFmpeg STDOUT ----")
            print((e.stdout or "").strip())
            raise

        return output_path

    # --------------------------
    # -c copy で連結
    # --------------------------
    async def concat_clips(self, clip_paths: List[Path], output_path: str) -> None:
        """
        複数のクリップを -c copy で連結。
        すべての入力に音声/映像が存在し、同一パラメータである前提（本パイプラインの生成物は満たす）。
        """
        if not clip_paths:
            print("[Concat] No clips to concatenate.")
            return

        print(
            f"[Concat] Concatenating {len(clip_paths)} clips -> {output_path} using -c copy."
        )
        try:
            await concat_videos_copy(
                [str(p.resolve()) for p in clip_paths], output_path
            )
        except Exception as e:
            print(f"[Error] -c copy concat failed for {output_path}: {e}")
            raise
