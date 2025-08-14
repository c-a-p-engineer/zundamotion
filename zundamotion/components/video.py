import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional


def _format_drawtext_filter(drawtext_params: Dict[str, Any]) -> str:
    """Formats drawtext parameters into an FFmpeg drawtext filter string."""
    parts = []
    for key, value in drawtext_params.items():
        if isinstance(value, str) and "'" in value:
            # Escape single quotes within the string
            value = value.replace("'", "\\'")
        parts.append(f"{key}='{value}'")
    return ":".join(parts)


import multiprocessing
import os

from ..utils.ffmpeg_utils import (
    calculate_overlay_position,
    get_ffmpeg_version,
    get_hardware_encoder,
    has_audio_stream,
)


class VideoRenderer:
    def __init__(self, config: Dict[str, Any], temp_dir: Path, jobs: str = "1"):
        self.config = config
        self.temp_dir = temp_dir
        self.video_config = config.get("video", {})
        self.bgm_config = config.get("bgm", {})
        self.jobs = jobs
        self.hw_encoder = None
        self.ffmpeg_path = "ffmpeg"  # Assume ffmpeg is in PATH

        self._initialize_ffmpeg_settings()

    def _initialize_ffmpeg_settings(self):
        """Detects FFmpeg version and available hardware encoders."""
        self.hw_encoder = None

        if self.jobs == "auto":
            self.num_jobs = multiprocessing.cpu_count()
            print(f"[Jobs] Auto-detected CPU cores: {self.num_jobs} jobs")
        else:
            try:
                self.num_jobs = int(self.jobs)
                if self.num_jobs <= 0:
                    raise ValueError
                print(f"[Jobs] Using {self.num_jobs} specified jobs")
            except ValueError:
                print(
                    f"[Jobs] Invalid --jobs value '{self.jobs}'. Falling back to 1 job."
                )
                self.num_jobs = 1

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

        cmd = ["ffmpeg", "-y"]
        if self.num_jobs > 0:
            cmd.extend(["-threads", str(self.num_jobs)])

        # --- Input Configuration ---
        input_layers = []
        # 1. Background
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
        input_layers.append({"type": "video", "index": len(input_layers)})

        # 2. Main Audio (from speech)
        cmd.extend(["-i", str(audio_path)])
        speech_audio_index = len(input_layers)
        input_layers.append({"type": "audio", "index": speech_audio_index})

        # 3. Insert Media (if any)
        insert_ffmpeg_index = -1
        insert_audio_index = -1
        if insert_config:
            insert_path = Path(insert_config["path"])
            is_video = insert_path.suffix.lower() not in [
                ".png",
                ".jpg",
                ".jpeg",
                ".bmp",
            ]
            if is_video:
                cmd.extend(["-i", str(insert_path)])
            else:
                cmd.extend(["-loop", "1", "-i", str(insert_path)])
            insert_ffmpeg_index = len(input_layers)
            input_layers.append({"type": "video", "index": insert_ffmpeg_index})
            if is_video and has_audio_stream(str(insert_path)):
                insert_audio_index = (
                    insert_ffmpeg_index  # Video and audio are in the same input
                )

        # 4. Character Images
        character_indices = {}
        for i, char_config in enumerate(characters_config):
            if char_config.get("visible", False):
                char_name = char_config.get("name")
                char_expression = char_config.get(
                    "expression", "default"
                )  # Default to 'default' if not specified
                char_position = char_config.get(
                    "position", {"x": "0", "y": "0"}
                )  # Default position
                # Get scale and anchor for this specific character, falling back to defaults
                char_scale = char_config.get(
                    "scale", self.config.get("characters", {}).get("default_scale", 1.0)
                )
                char_anchor = char_config.get(
                    "anchor",
                    self.config.get("characters", {}).get(
                        "default_anchor", "bottom_center"
                    ),
                )

                if not char_name:
                    print(f"[Warning] Skipping character with missing name.")
                    continue

                # Construct the expected image path
                # This logic might need to be more robust, e.g., checking for existence and falling back
                char_image_path = Path(
                    f"assets/characters/{char_name}/{char_expression}.png"
                )
                if not char_image_path.exists():
                    # Fallback to default if expression image not found
                    char_image_path = Path(f"assets/characters/{char_name}/default.png")
                    if not char_image_path.exists():
                        print(
                            f"[Warning] Character image not found for {char_name}/{char_expression} or default. Skipping."
                        )
                        continue

                character_indices[i] = len(input_layers)
                cmd.extend(["-loop", "1", "-i", str(char_image_path.resolve())])
                input_layers.append({"type": "video", "index": len(input_layers)})

        # --- Filter Graph Construction ---
        filter_complex_parts = []
        last_video_stream = f"[0:v]scale={width}:{height}[bg_scaled]"
        filter_complex_parts.append(last_video_stream)
        last_video_stream = "[bg_scaled]"

        # Overlay Insert Media
        if insert_config and insert_ffmpeg_index != -1:
            scale = insert_config.get("scale", 1.0)
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

        # Overlay Characters
        for i, char_config in enumerate(characters_config):
            if char_config.get("visible", False) and i in character_indices:
                ffmpeg_index = character_indices[i]
                scale = char_config.get("scale", 1.0)
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
                filter_complex_parts.append(
                    f"[char_scaled_{i}]format=rgba[char_rgba_{i}]"
                )
                filter_complex_parts.append(
                    f"{last_video_stream}[char_rgba_{i}]overlay=x={x_expr}:y={y_expr}[with_char_{i}]"
                )
                last_video_stream = f"[with_char_{i}]"

        # Subtitles
        drawtext_str = _format_drawtext_filter(drawtext_filter)
        if drawtext_str:
            filter_complex_parts.append(
                f"{last_video_stream}drawtext={drawtext_str}[final_v]"
            )
            last_video_stream = "[final_v]"

        # --- Audio Mixing ---
        # まずはセリフの音声を準備
        if insert_config and insert_audio_index != -1:
            volume = insert_config.get("volume", 1.0)
            # 挿入動画の音量調整
            filter_complex_parts.append(
                f"[{insert_audio_index}:a]volume={volume}[insert_audio_vol]"
            )
            # 長い方を優先してミックス。終端のクリック回避に dropout_transition を指定
            filter_complex_parts.append(
                f"[1:a][insert_audio_vol]amix=inputs=2:duration=longest:dropout_transition=0[final_a]"
            )
            audio_map = "[final_a]"
        else:
            filter_complex_parts.append(f"[1:a]anull[final_a]")
            audio_map = "[final_a]"

        # --- Final Command Assembly ---
        cmd.extend(["-filter_complex", ";".join(filter_complex_parts)])
        cmd.extend(["-map", last_video_stream, "-map", audio_map])
        cmd.extend(
            [
                "-t",
                str(duration),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
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

        cmd = ["ffmpeg", "-y"]
        if self.num_jobs > 0:
            cmd.extend(["-threads", str(self.num_jobs)])

        # --- Input Configuration ---
        # 1. Background
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

        # 2. Silent Audio
        cmd.extend(
            ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
        )

        # --- Filter Graph Construction ---
        # P0: Just use the background as is.
        # For P1 'freeze_video=false', this is the correct behavior.
        # For P0 'freeze_video=true' (default), we should ideally hold the last frame.
        # This is complex in the current pipeline. A simpler approach for now is to just show the static/looping background.
        # A true freeze would require `tpad=stop_mode=clone:stop_duration={duration}` but needs a single frame input.
        filter_complex = (
            f"[0:v]scale={width}:{height},trim=duration={duration}[final_v]"
        )

        # --- Final Command Assembly ---
        cmd.extend(["-filter_complex", filter_complex])
        cmd.extend(["-map", "[final_v]", "-map", "1:a"])
        cmd.extend(
            [
                "-t",
                str(duration),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
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
        Renders a looped background video of a specified duration.

        Args:
            bg_video_path (str): Path to the background video file.
            duration (float): Desired duration of the output video.
            output_filename (str): Base name for the output file.

        Returns:
            Path: Path to the rendered mp4 video.
        """
        output_path = self.temp_dir / f"{output_filename}.mp4"
        width = self.video_config.get("width", 1280)
        height = self.video_config.get("height", 720)
        fps = self.video_config.get("fps", 30)

        print(f"[Video] Rendering looped background video -> {output_path.name}")

        cmd = [
            "ffmpeg",
            "-y",
        ]

        # 並列処理の指定
        if self.num_jobs > 0:
            cmd.extend(["-threads", str(self.num_jobs)])

        cmd.extend(
            [
                "-stream_loop",
                "-1",  # Loop indefinitely
                "-i",
                bg_video_path,
                "-t",
                str(duration),  # Trim to desired duration
                "-vf",
                f"scale={width}:{height}",  # Scale to target resolution
            ]
        )

        video_codec = "libx264"
        if self.hw_encoder == "nvenc":
            video_codec = "h264_nvenc"
        elif self.hw_encoder == "vaapi":
            video_codec = "h264_videotoolbox"
        elif self.hw_encoder == "videotoolbox":
            video_codec = "h264_videotoolbox"

        cmd.extend(
            [
                "-c:v",
                video_codec,
                "-pix_fmt",
                "yuv420p",
                "-r",
                str(fps),
                "-an",  # No audio
                str(output_path),
            ]
        )

        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            print(
                f"Error during ffmpeg processing for looped background video {output_filename} with {video_codec}:"
            )
            print(f"STDOUT: {e.stdout}")
            print(f"STDERR: {e.stderr}")

            # ハードウェアエンコードが失敗した場合、ソフトウェアエンコードにフォールバック
            if self.hw_encoder and video_codec != "libx264":
                print(
                    f"Hardware encoding failed. Falling back to libx264 for looped background video {output_filename}."
                )
                cmd[cmd.index("-c:v") + 1] = "libx264"  # -c:v の次の要素をlibx264に変更
                try:
                    subprocess.run(cmd, check=True, capture_output=True, text=True)
                except subprocess.CalledProcessError as fallback_e:
                    print(
                        f"Error during ffmpeg processing with libx264 for looped background video {output_filename}:"
                    )
                    print(f"STDOUT: {fallback_e.stdout}")
                    print(f"STDERR: {e.stderr}")
                    raise  # ハードウェアエンコーダーが指定されていないか、libx264で失敗した場合はそのままエラーを再スロー
            else:
                raise  # ハードウェアエンコーダーが指定されていないか、libx264で失敗した場合はそのままエラーを再スロー

        return output_path

    def concat_clips(self, clip_paths: List[Path], output_path: str) -> None:
        """
        Concatenates multiple video clips into a single file using the concat filter for robustness.

        Args:
            clip_paths (List[Path]): A sorted list of clip paths to concatenate.
            output_path (str): The final output file path.
        """
        if not clip_paths:
            print("[Concat] No clips to concatenate.")
            return

        print(
            f"[Concat] Concatenating {len(clip_paths)} clips -> {output_path} using concat filter."
        )

        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output files without asking
        ]

        # Add all clips as inputs
        for p in clip_paths:
            cmd.extend(["-i", str(p.resolve())])

        # Build the filter_complex string for the concat filter
        filter_inputs = "".join([f"[{i}:v:0][{i}:a:0]" for i in range(len(clip_paths))])
        filter_complex = (
            f"{filter_inputs}concat=n={len(clip_paths)}:v=1:a=1[outv][outa]"
        )

        cmd.extend(
            [
                "-filter_complex",
                filter_complex,
                "-map",
                "[outv]",
                "-map",
                "[outa]",
                "-c:v",
                "libx264",  # Re-encoding is necessary with concat filter
                "-pix_fmt",
                "yuv420p",
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
