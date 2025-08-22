# -*- coding: utf-8 -*-
import multiprocessing
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..utils.ffmpeg_utils import (
    calculate_overlay_position,
    get_media_info,
    has_audio_stream,
    normalize_video,
)


# --------------------------
# drawtext ヘルパ
# --------------------------
def _escape_drawtext_value(key: str, value: Any) -> str:
    """
    FFmpeg drawtext 用の値エスケープ。
    - 全キー: バックスラッシュとシングルクォートをエスケープ
    - text/fontfile: ':' と 改行 も FFmpeg 仕様でエスケープ
    """
    s = str(value)
    s = s.replace("\\", "\\\\").replace("'", "\\'")
    if key in ("text", "fontfile"):
        s = s.replace(":", r"\:").replace("\n", r"\n")
    return s


def _format_drawtext_filter(drawtext_params: Dict[str, Any]) -> str:
    """drawtext のパラメータ辞書を 'key='value':key2='value2'' 形式に整形"""
    parts: List[str] = []
    for k, v in drawtext_params.items():
        if isinstance(v, bool):
            v_str = "1" if v else "0"
        elif isinstance(v, (int, float)):
            v_str = str(v)
        else:
            v_str = _escape_drawtext_value(k, v)
        parts.append(f"{k}='{v_str}'")
    return ":".join(parts)


# --------------------------
# 本体
# --------------------------
class VideoRenderer:
    def __init__(self, config: Dict[str, Any], temp_dir: Path, jobs: str = "0"):
        self.config = config
        self.temp_dir = temp_dir
        self.video_config = config.get("video", {})
        self.bgm_config = config.get("bgm", {})
        self.jobs = jobs
        self.ffmpeg_path = "ffmpeg"  # PATH 前提

        # エンコード関連（初期化時に決定）
        self.using_qsv: bool = False
        self.h264_encoder_options: List[str] = []
        self.hevc_encoder_options: List[str] = []
        self._pix_fmt: str = "yuv420p"  # QSV 使用時は nv12 に切替

        self._initialize_ffmpeg_settings()

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

    def _qsv_device_available(self) -> bool:
        # 典型的なレンダーデバイス（Docker なら /dev/dri をマウントしている必要あり）
        return os.path.exists("/dev/dri/renderD128") or os.path.exists("/dev/dri/card0")

    def _probe_qsv_encode(self) -> bool:
        """
        QSV エンコードが実際に初期化できるかを極小ジョブで検証。
        失敗する場合は MFX session エラー（-9 など）になる。
        """
        cmd = [
            self.ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=size=64x64:rate=30:duration=0.1:color=black",
            "-frames:v",
            "1",
            "-c:v",
            "h264_qsv",
            "-f",
            "null",
            "-",
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            return True
        except subprocess.CalledProcessError as e:
            # デバッグ用に一行だけ残す
            msg = (
                (e.stderr or "").strip().splitlines()[-1]
                if (e.stderr or "")
                else "qsv open failed"
            )
            print(f"[Encoder] QSV probe failed: {msg}")
            return False

    def _initialize_ffmpeg_settings(self):
        # 環境変数で強制指定
        force_cpu = os.environ.get("ZUNDAMOTION_FORCE_CPU") == "1"
        force_qsv = os.environ.get("ZUNDAMOTION_FORCE_QSV") == "1"

        qsv_ok = False
        if not force_cpu:
            # デバイスがあり、かつ実試行が成功したら QSV を採用
            if self._qsv_device_available() or force_qsv:
                qsv_ok = self._probe_qsv_encode()

        if qsv_ok:
            self.using_qsv = True
            self.h264_encoder_options = [
                "-c:v",
                "h264_qsv",
                "-preset",
                "veryfast",
                "-global_quality",
                "23",
            ]
            self.hevc_encoder_options = [
                "-c:v",
                "hevc_qsv",
                "-preset",
                "veryfast",
                "-global_quality",
                "28",
            ]
            self._pix_fmt = "nv12"  # QSV は nv12 が安定
            print("[Encoder] Using QSV (Intel Quick Sync) for video encoding.")
        else:
            self.using_qsv = False
            self.h264_encoder_options = [
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "23",
            ]
            self.hevc_encoder_options = [
                "-c:v",
                "libx265",
                "-preset",
                "fast",
                "-crf",
                "28",
            ]
            self._pix_fmt = "yuv420p"
            print("[Encoder] Using CPU (libx264/libx265) for video encoding.")

    # --------------------------
    # クリップ生成
    # --------------------------
    def render_clip(
        self,
        audio_path: Path,
        duration: float,
        drawtext_filter: Dict[str, Any],
        background_config: Dict[str, Any],
        characters_config: List[Dict[str, Any]],
        output_filename: str,
        insert_config: Optional[Dict[str, Any]] = None,
    ) -> Optional[Path]:
        output_path = self.temp_dir / f"{output_filename}.mp4"
        width = self.video_config.get("width", 1280)
        height = self.video_config.get("height", 720)
        fps = self.video_config.get("fps", 30)

        print(f"[Video] Rendering clip -> {output_path.name}")

        cmd: List[str] = [self.ffmpeg_path, "-y"]
        cmd.extend(self._thread_flags())

        # --- Inputs ---
        input_layers: List[Dict[str, Any]] = []

        # 1) Background
        bg_path_str = background_config.get("path")
        if not bg_path_str:
            raise ValueError("Background path is missing.")
        bg_path = Path(bg_path_str)

        if background_config.get("type") == "video":
            try:
                media_info = get_media_info(str(bg_path))
                video_info = media_info.get("video", {})
                audio_info = media_info.get("audio", {})

                is_standard = (
                    int(round(video_info.get("fps", 0))) == 30
                    and audio_info.get("sample_rate") == 48000
                )
                if not is_standard:
                    print(f"[Video] Normalizing background video: {bg_path.name}")
                    normalized_bg_path = self.temp_dir / f"normalized_{bg_path.name}"
                    normalize_video(str(bg_path), str(normalized_bg_path))
                    bg_path = normalized_bg_path
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

        # 2) Speech audio
        cmd.extend(["-i", str(audio_path)])
        speech_audio_index = len(input_layers)
        input_layers.append({"type": "audio", "index": speech_audio_index})

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
                    media_info = get_media_info(str(insert_path))
                    video_info = media_info.get("video", {})
                    audio_info = media_info.get("audio", {})
                    is_standard = (
                        int(round(video_info.get("fps", 0))) == 30
                        and audio_info.get("sample_rate") == 48000
                    )
                    if not is_standard:
                        print(f"[Video] Normalizing insert video: {insert_path.name}")
                        normalized_insert_path = (
                            self.temp_dir / f"normalized_{insert_path.name}"
                        )
                        normalize_video(str(insert_path), str(normalized_insert_path))
                        insert_path = normalized_insert_path
                except Exception as e:
                    print(
                        f"[Warning] Could not inspect/normalize insert video {insert_path.name}: {e}. Using as-is."
                    )
                cmd.extend(["-i", str(insert_path)])
            else:
                cmd.extend(["-loop", "1", "-i", str(insert_path)])

            insert_ffmpeg_index = len(input_layers)
            input_layers.append({"type": "video", "index": insert_ffmpeg_index})
            if is_video and has_audio_stream(str(insert_path)):
                insert_audio_index = insert_ffmpeg_index  # 同じ入力に音声も載る

        # 4) Character images
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

        # --- Filter Graph ---
        filter_complex_parts: List[str] = []

        # 背景スケール（CPUフィルタ）
        filter_complex_parts.append(f"[0:v]scale={width}:{height}[bg_scaled]")
        last_video_stream = "[bg_scaled]"

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
            filter_complex_parts.append(f"[insert_scaled]format=rgba[insert_rgba]")
            filter_complex_parts.append(
                f"{last_video_stream}[insert_rgba]overlay=x={x_expr}:y={y_expr}[with_insert]"
            )
            last_video_stream = "[with_insert]"

        # Character overlays
        for i, char_config in enumerate(characters_config):
            if not char_config.get("visible", False) or i not in character_indices:
                continue
            ffmpeg_index = character_indices[i]
            scale = float(
                char_config.get(
                    "scale", self.config.get("characters", {}).get("default_scale", 1.0)
                )
            )
            anchor = char_config.get(
                "anchor",
                self.config.get("characters", {}).get(
                    "default_anchor", "bottom_center"
                ),
            )
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
            filter_complex_parts.append(f"[char_scaled_{i}]format=rgba[char_rgba_{i}]")
            filter_complex_parts.append(
                f"{last_video_stream}[char_rgba_{i}]overlay=x={x_expr}:y={y_expr}[with_char_{i}]"
            )
            last_video_stream = f"[with_char_{i}]"

        # Subtitles (drawtext)
        drawtext_str = _format_drawtext_filter(drawtext_filter)
        if drawtext_str:
            filter_complex_parts.append(
                f"{last_video_stream}drawtext={drawtext_str}[final_v]"
            )
            last_video_stream = "[final_v]"

        # --- Audio ---
        if insert_config and insert_audio_index != -1:
            volume = float(insert_config.get("volume", 1.0))
            filter_complex_parts.append(
                f"[{insert_audio_index}:a]volume={volume}[insert_audio_vol]"
            )
            filter_complex_parts.append(
                f"[1:a][insert_audio_vol]amix=inputs=2:duration=longest:dropout_transition=0[final_a]"
            )
            audio_map = "[final_a]"
        else:
            filter_complex_parts.append("[1:a]anull[final_a]")
            audio_map = "[final_a]"

        # --- Assemble & Run ---
        cmd.extend(["-filter_complex", ";".join(filter_complex_parts)])
        cmd.extend(["-map", last_video_stream, "-map", audio_map])
        cmd.extend(["-t", str(duration)])
        cmd.extend(self.h264_encoder_options)  # QSV/CPU を自動選択済み
        cmd.extend(
            [
                "-pix_fmt",
                self._pix_fmt,
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-r",
                str(fps),
                "-shortest",
                str(output_path),
            ]
        )

        try:
            print(f"Executing FFmpeg command: {' '.join(cmd)}")
            process = subprocess.run(cmd, check=True, capture_output=True, text=True)
            # ffmpeg の詳細は stderr に出ることが多い
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

    def render_wait_clip(
        self,
        duration: float,
        background_config: Dict[str, Any],
        output_filename: str,
        line_config: Dict[str, Any],
    ) -> Optional[Path]:
        output_path = self.temp_dir / f"{output_filename}.mp4"
        width = self.video_config.get("width", 1280)
        height = self.video_config.get("height", 720)
        fps = self.video_config.get("fps", 30)

        print(f"[Video] Rendering wait clip -> {output_path.name}")

        cmd: List[str] = [self.ffmpeg_path, "-y"]
        cmd.extend(self._thread_flags())

        # 1) Background
        bg_path = background_config.get("path")
        if not bg_path:
            raise ValueError("Background path is missing.")
        if background_config.get("type") == "video":
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
            ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
        )

        # Filters
        filter_complex = (
            f"[0:v]scale={width}:{height},trim=duration={duration}[final_v]"
        )

        cmd.extend(["-filter_complex", filter_complex])
        cmd.extend(["-map", "[final_v]", "-map", "1:a"])
        cmd.extend(["-t", str(duration)])
        cmd.extend(self.h264_encoder_options)
        cmd.extend(
            [
                "-pix_fmt",
                self._pix_fmt,
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-r",
                str(fps),
                str(output_path),
            ]
        )

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

    def render_looped_background_video(
        self, bg_video_path: str, duration: float, output_filename: str
    ) -> Path:
        """
        指定長でBG動画をループ書き出し。
        """
        output_path = self.temp_dir / f"{output_filename}.mp4"
        width = self.video_config.get("width", 1280)
        height = self.video_config.get("height", 720)
        fps = self.video_config.get("fps", 30)

        print(f"[Video] Rendering looped background video -> {output_path.name}")

        cmd: List[str] = [self.ffmpeg_path, "-y"]
        cmd.extend(self._thread_flags())
        cmd.extend(
            [
                "-stream_loop",
                "-1",
                "-i",
                bg_video_path,
                "-t",
                str(duration),
                "-vf",
                f"scale={width}:{height}",
            ]
        )
        cmd.extend(self.h264_encoder_options)
        cmd.extend(
            [
                "-pix_fmt",
                self._pix_fmt,
                "-r",
                str(fps),
                "-an",
                str(output_path),
            ]
        )

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

    def concat_clips(self, clip_paths: List[Path], output_path: str) -> None:
        """
        複数のクリップを concat フィルタで連結。
        すべての入力に音声/映像が存在し、同一パラメータである前提（本パイプラインの生成物は満たす）。
        """
        if not clip_paths:
            print("[Concat] No clips to concatenate.")
            return

        print(
            f"[Concat] Concatenating {len(clip_paths)} clips -> {output_path} using concat filter."
        )

        cmd: List[str] = [self.ffmpeg_path, "-y"]
        cmd.extend(self._thread_flags())

        for p in clip_paths:
            cmd.extend(["-i", str(p.resolve())])

        # 映像/音声ともに0番ストリームを連結
        filter_inputs = "".join([f"[{i}:v:0][{i}:a:0]" for i in range(len(clip_paths))])
        filter_complex = (
            f"{filter_inputs}concat=n={len(clip_paths)}:v=1:a=1[outv][outa]"
        )

        cmd.extend(
            ["-filter_complex", filter_complex, "-map", "[outv]", "-map", "[outa]"]
        )
        cmd.extend(self.h264_encoder_options)
        cmd.extend(
            [
                "-pix_fmt",
                self._pix_fmt,
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                str(output_path),
            ]
        )

        try:
            print(f"Executing FFmpeg command: {' '.join(cmd)}")
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            print(f"Error during ffmpeg processing for {output_path}:")
            print(f"STDOUT: {e.stdout}")
            print(f"STDERR: {e.stderr}")
            raise
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            raise
