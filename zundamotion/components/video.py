# -*- coding: utf-8 -*-
import multiprocessing
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..cache import CacheManager
from ..utils.ffmpeg_utils import concat_videos_copy  # 追加
from ..utils.ffmpeg_utils import (
    AudioParams,
    VideoParams,
    calculate_overlay_position,
    get_media_info,
    has_audio_stream,
    is_nvenc_available,
    normalize_media,
)


class VideoRenderer:
    def __init__(
        self,
        config: Dict[str, Any],
        temp_dir: Path,
        cache_manager: CacheManager,
        jobs: str = "0",
        hw_kind: Optional[str] = None,  # 新しい引数
        video_params: Optional[VideoParams] = None,  # 新しい引数
        audio_params: Optional[AudioParams] = None,  # 新しい引数
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

        # _initialize_ffmpeg_settings は削除されるため、関連する属性も削除
        # self.using_qsv: bool = False
        # self.h264_encoder_options: List[str] = []
        # self.hevc_encoder_options: List[str] = []
        # self._pix_fmt: str = "yuv420p"

        # self._initialize_ffmpeg_settings() # 削除

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

    # _qsv_device_available と _probe_qsv_encode は _initialize_ffmpeg_settings でのみ使用されていたため削除
    # def _qsv_device_available(self) -> bool:
    #     # 典型的なレンダーデバイス（Docker なら /dev/dri をマウントしている必要あり）
    #     return os.path.exists("/dev/dri/renderD128") or os.path.exists("/dev/dri/card0")

    # def _probe_qsv_encode(self) -> bool:
    #     """
    #     QSV エンコードが実際に初期化できるかを極小ジョブで検証。
    #     失敗する場合は MFX session エラー（-9 など）になる。
    #     """
    #     cmd = [
    #         self.ffmpeg_path,
    #         "-hide_banner",
    #         "-loglevel",
    #         "error",
    #         "-f",
    #         "lavfi",
    #         "-i",
    #         "color=size=64x64:rate=30:duration=0.1:color=black",
    #         "-frames:v",
    #         "1",
    #         "-c:v",
    #         "h264_qsv",
    #         "-f",
    #         "null",
    #         "-",
    #     ]
    #     try:
    #         subprocess.run(cmd, check=True, capture_output=True, text=True)
    #         return True
    #     except subprocess.CalledProcessError as e:
    #         # デバッグ用に一行だけ残す
    #         msg = (
    #             (e.stderr or "").strip().splitlines()[-1]
    #             if (e.stderr or "")
    #             else "qsv open failed"
    #         )
    #         print(f"[Encoder] QSV probe failed: {msg}")
    #         return False

    # _initialize_ffmpeg_settings メソッドは削除
    # def _initialize_ffmpeg_settings(self):
    #     """
    #     シンプル版: ハードウェア自動選択のみ
    #     優先度: NVENC > QSV > CPU
    #     品質指定: config["encoder"]["quality"] or config["video"]["quality"] or "balanced"
    #         - "speed"    -> NVENC: preset p7, cq=30/31
    #         - "balanced" -> NVENC: preset p5, cq=23/24
    #         - "quality"  -> NVENC: preset p4, cq=20/21
    #     QSV/CPU は固定設定（必要なら後で拡張）
    #     """
    #     # 既定リセット
    #     self.using_nvenc = False
    #     self.using_qsv = False
    #     self._pix_fmt = "yuv420p"

    #     # ---- 1) NVENC 可否 ----
    #     nvenc_ok = False
    #     try:
    #         nvenc_ok = is_nvenc_available(self.ffmpeg_path)
    #     except Exception as e:
    #         print(f"[Encoder] NVENC check error: {e}")

    #     # ---- 2) QSV 可否（NVENC不可のときだけ試す）----
    #     qsv_ok = False
    #     if not nvenc_ok and self._qsv_device_available():
    #         qsv_ok = self._probe_qsv_encode()

    #     # ---- 3) 採用とオプション設定 ----
    #     if nvenc_ok:
    #         # 品質プロファイル（configのみ）
    #         quality = (
    #             self.config.get("encoder", {}).get("quality")
    #             or self.config.get("video", {}).get("quality")
    #             or "balanced"
    #         ).lower()

    #         if quality == "speed":
    #             preset, cq_h264, cq_hevc = "p7", "30", "31"
    #         elif quality == "quality":
    #             preset, cq_h264, cq_hevc = "p4", "20", "21"
    #         else:  # balanced
    #             preset, cq_h264, cq_hevc = "p5", "23", "24"

    #         self.using_nvenc = True
    #         self.h264_encoder_options = [
    #             "-c:v",
    #             "h264_nvenc",
    #             "-preset",
    #             preset,
    #             "-cq",
    #             cq_h264,
    #         ]
    #         self.hevc_encoder_options = [
    #             "-c:v",
    #             "hevc_nvenc",
    #             "-preset",
    #             preset,
    #             "-cq",
    #             cq_hevc,
    #         ]
    #         # NVENC は yuv420p でOK（10bit/HDRは別途）
    #         self._pix_fmt = "yuv420p"
    #         print(f"[Encoder] Using NVENC (h264_nvenc), preset={preset}, cq={cq_h264}")

    #     elif qsv_ok:
    #         self.using_qsv = True
    #         self.h264_encoder_options = [
    #             "-c:v",
    #             "h264_qsv",
    #             "-preset",
    #             "veryfast",
    #             "-global_quality",
    #             "23",
    #         ]
    #         self.hevc_encoder_options = [
    #             "-c:v",
    #             "hevc_qsv",
    #             "-preset",
    #             "veryfast",
    #             "-global_quality",
    #             "28",
    #         ]
    #         # QSV は nv12 が安定
    #         self._pix_fmt = "nv12"
    #         print("[Encoder] Using QSV (Intel Quick Sync) for video encoding.")

    #     else:
    #         # CPU フォールバック
    #         self.h264_encoder_options = [
    #             "-c:v",
    #             "libx264",
    #             "-preset",
    #             "fast",
    #             "-crf",
    #             "23",
    #         ]
    #         self.hevc_encoder_options = [
    #             "-c:v",
    #             "libx265",
    #             "-preset",
    #             "fast",
    #             "-crf",
    #             "28",
    #         ]
    #         self._pix_fmt = "yuv420p"
    #         print("[Encoder] Using CPU (libx264/libx265) for video encoding.")

    async def render_clip(  # async を追加
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

        cmd: List[str] = [self.ffmpeg_path, "-y"]
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
                bg_path = await normalize_media(  # await を追加
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
        if isinstance(extra_subtitle_inputs, dict) and extra_subtitle_inputs.get("-i"):
            # 期待形式: {"-loop": "1", "-i": "/abs/path/subs.png"}
            loop_val = extra_subtitle_inputs.get("-loop", "1")
            png_path = extra_subtitle_inputs["-i"]
            cmd.extend(["-loop", loop_val, "-i", str(Path(png_path).resolve())])
            subtitle_ffmpeg_index = len(input_layers)
            input_layers.append({"type": "video", "index": subtitle_ffmpeg_index})
        elif extra_subtitle_inputs:
            print(
                f"[Warning] extra_subtitle_inputs has unexpected format: {extra_subtitle_inputs}. Subtitle overlay will be skipped."
            )

        # 3) Insert media (optional)
        insert_ffmpeg_index = -1
        insert_audio_index = -1
        if insert_config:
            insert_path = Path(insert_config["path"])
            is_video = insert_path.suffix.lower() not in [
                ".png",
                ".jpg",
                ".jpeg",
                ".bmp",
                ".webp",
            ]
            if is_video:
                try:
                    _ = get_media_info(str(insert_path))
                    insert_path = await normalize_media(  # await を追加
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
            if is_video and has_audio_stream(str(insert_path)):
                insert_audio_index = insert_ffmpeg_index

        # 4) Characters (optional)
        character_indices: Dict[int, int] = {}
        for i, char_config in enumerate(characters_config):
            if not char_config.get("visible", False):
                continue
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

        # --- Filter Graph -------------------------------------------------------
        filter_complex_parts: List[str] = []

        # BG scale
        filter_complex_parts.append(
            f"[0:v]scale={width}:{height}:flags=lanczos,fps={fps}[bg]"
        )
        current_video_stream = "[bg]"

        # Overlay elements
        overlay_streams: List[str] = []
        overlay_filters: List[str] = []

        # Insert overlay
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
            filter_complex_parts.append(
                f"[{insert_ffmpeg_index}:v]scale=iw*{scale}:ih*{scale}[insert_scaled]"
            )
            overlay_streams.append("[insert_scaled]")
            overlay_filters.append(f"overlay=x={x_expr}:y={y_expr}")

        # Characters overlay
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
            filter_complex_parts.append(
                f"[{ffmpeg_index}:v]scale=iw*{scale}:ih*{scale}[char_scaled_{i}]"
            )
            overlay_streams.append(f"[char_scaled_{i}]")
            overlay_filters.append(f"overlay=x={x_expr}:y={y_expr}")

        # Subtitles overlay（PNG）— 下中央寄せ、表示は between(t,0,duration)
        if subtitle_ffmpeg_index != -1:
            x_expr = "(W-w)/2"
            y_expr = f"H-{bottom_margin}-h"
            overlay_streams.append(f"[{subtitle_ffmpeg_index}:v]")
            overlay_filters.append(
                f"overlay=x='{x_expr}':y='{y_expr}':enable='between(t,0,{duration})'"
            )

        # Combine all overlays into a single chain
        if overlay_streams:
            # Start with the background stream
            overlay_chain = current_video_stream
            for i, stream in enumerate(overlay_streams):
                overlay_chain += f"{stream}{overlay_filters[i]}"
                if i < len(overlay_streams) - 1:
                    overlay_chain += f"[tmp_overlay_{i}];[tmp_overlay_{i}]"
                else:
                    overlay_chain += "[final_v_overlays]"
            filter_complex_parts.append(overlay_chain)
            current_video_stream = "[final_v_overlays]"
        else:
            current_video_stream = "[bg]"  # No overlays, just use the background

        # Final format conversion
        filter_complex_parts.append(f"{current_video_stream}format=yuv420p[final_v]")

        # --- Audio --------------------------------------------------------------
        if insert_config and insert_audio_index != -1:
            volume = float(insert_config.get("volume", 1.0))
            filter_complex_parts += [
                f"[{insert_audio_index}:a]volume={volume}[insert_audio_vol]",
                f"[1:a][insert_audio_vol]amix=inputs=2:duration=longest:dropout_transition=0[final_a]",
            ]
            audio_map = "[final_a]"
        else:
            filter_complex_parts.append("[1:a]anull[final_a]")
            audio_map = "[final_a]"

        # --- Assemble & Run -----------------------------------------------------
        cmd.extend(["-filter_complex", ";".join(filter_complex_parts)])
        cmd.extend(["-map", "[final_v]", "-map", audio_map])
        cmd.extend(["-t", str(duration)])
        cmd.extend(self.video_params.to_ffmpeg_opts(self.hw_kind))  # 変更
        cmd.extend(self.audio_params.to_ffmpeg_opts())  # 変更
        cmd.extend(["-movflags", "+faststart"])  # 追加
        cmd.extend(["-shortest", str(output_path)])

        try:
            print(f"Executing FFmpeg command: {' '.join(cmd)}")
            process = subprocess.run(cmd, check=True, capture_output=True, text=True)
            if process.stderr:
                print(process.stderr)
        except subprocess.CalledProcessError as e:
            print(f"Error during ffmpeg processing for {output_filename}:")
            print(f"STDOUT: {e.stdout}")
            print(f"STDERR: {e.stderr}")
            raise
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            raise

        return output_path

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

        cmd: List[str] = [self.ffmpeg_path, "-y"]
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
                bg_path = await normalize_media(  # await を追加
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

        # Filters
        filter_complex = f"[0:v]scale={width}:{height},trim=duration={duration},format=yuv420p[final_v]"

        cmd.extend(["-filter_complex", filter_complex])
        cmd.extend(["-map", "[final_v]", "-map", "1:a"])
        cmd.extend(["-t", str(duration)])
        cmd.extend(self.video_params.to_ffmpeg_opts(self.hw_kind))
        cmd.extend(self.audio_params.to_ffmpeg_opts())
        cmd.extend(["-movflags", "+faststart"])
        cmd.extend(["-shortest", str(output_path)])

        try:
            print(f"Executing FFmpeg command: {' '.join(cmd)}")
            process = subprocess.run(cmd, check=True, capture_output=True, text=True)
            if process.stderr:
                print(process.stderr)
        except subprocess.CalledProcessError as e:
            print(f"Error during ffmpeg processing for {output_filename}:")
            print(f"STDOUT: {e.stdout}")
            print(f"STDERR: {e.stderr}")
            raise
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            raise

        return output_path

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

        cmd: List[str] = [self.ffmpeg_path, "-y"]
        cmd.extend(self._thread_flags())

        bg_video_path = Path(bg_video_path_str)
        try:
            # 正規化（失敗時は as-is）
            _ = get_media_info(str(bg_video_path))
            bg_video_path = await normalize_media(  # await を追加
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
                f"scale={width}:{height},format=yuv420p",
            ]
        )
        cmd.extend(self.video_params.to_ffmpeg_opts(self.hw_kind))
        cmd.extend(["-an"])  # 音声は不要
        cmd.extend(["-movflags", "+faststart"])
        cmd.extend([str(output_path)])

        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            print(
                f"Error during ffmpeg processing for looped background video {output_filename}:"
            )
            print(f"STDOUT: {e.stdout}")
            print(f"STDERR: {e.stderr}")
            raise

        return output_path

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
            concat_videos_copy([str(p.resolve()) for p in clip_paths], output_path)
        except Exception as e:
            print(f"Error during -c copy concat for {output_path}: {e}")
            raise
