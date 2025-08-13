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
    ) -> Optional[Path]:
        """
        Renders a single video clip with background and multiple characters.

        Args:
            audio_path (Path): Path to the audio file.
            duration (float): Duration of the clip.
            drawtext_filter (Dict[str, Any]): Subtitle filter options.
            background_config (Dict[str, Any]): Configuration for the background.
                Expected keys: 'type' ('image' or 'video'), 'path', 'start_time' (if type is 'video').
            characters_config (List[Dict[str, Any]]): List of character configurations.
                Each dict should contain: 'name', 'expression', 'position' (dict with 'x', 'y'), 'visible'.
            output_filename (str): Base name for the output file.

        Returns:
            Path: Path to the rendered mp4 clip.
        """
        output_path = self.temp_dir / f"{output_filename}.mp4"
        # Delete temporary directory if it exists
        temp_dir_path = Path("/tmp/tmp0uy2ckjk/")
        if temp_dir_path.exists():
            import shutil

            shutil.rmtree(temp_dir_path)
        width = self.video_config.get("width", 1280)
        height = self.video_config.get("height", 720)
        fps = self.video_config.get("fps", 30)

        print(f"[Video] Rendering clip -> {output_path.name}")

        # --- Background Processing ---
        bg_type = background_config.get("type", "image")
        bg_path = background_config.get("path")
        bg_start_time = background_config.get("start_time", 0.0)
        is_bg_video = bg_type == "video"

        if not bg_path:
            raise ValueError("Background path is missing in background_config.")

        # --- Character Image Path Resolution ---
        # This part assumes a structure like assets/characters/{name}/{expression}.png
        # It also needs to handle cases where an expression might not be found and fall back to default.
        resolved_character_images = []
        # Get default character settings from config
        default_char_scale = self.config.get("characters", {}).get("default_scale", 1.0)
        default_char_anchor = self.config.get("characters", {}).get(
            "default_anchor", "bottom_center"
        )

        for char_config in characters_config:
            if char_config.get("visible", False):
                char_name = char_config.get("name")
                char_expression = char_config.get(
                    "expression", "default"
                )  # Default to 'default' if not specified
                char_position = char_config.get(
                    "position", {"x": "0", "y": "0"}
                )  # Default position
                # Get scale and anchor for this specific character, falling back to defaults
                char_scale = char_config.get("scale", default_char_scale)
                char_anchor = char_config.get("anchor", default_char_anchor)

                if not char_name:
                    print(f"[Warning] Skipping character with missing name.")
                    return None

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

                resolved_character_images.append(
                    {
                        "path": str(
                            char_image_path.resolve()
                        ),  # Use absolute path for FFmpeg
                        "position": char_position,
                        "name": char_name,
                        "expression": char_expression,
                        "scale": char_scale,
                        "anchor": char_anchor,
                    }
                )
            else:
                print(f"Skipping invisible character: {char_config.get('name')}")

        # --- FFmpeg Filter Graph Construction ---
        cmd = ["ffmpeg", "-y"]
        if self.num_jobs > 0:
            cmd.extend(["-threads", str(self.num_jobs)])

        input_streams = []
        filter_complex_parts = []
        current_input_index = 0  # Use a single counter for all inputs

        # 1. Background Input
        bg_ffmpeg_input_index = current_input_index
        if is_bg_video:
            cmd.extend(["-ss", str(bg_start_time)])
            cmd.extend(["-stream_loop", "-1", "-i", bg_path])
        else:
            cmd.extend(["-loop", "1", "-i", bg_path])
        input_streams.append(f"[{bg_ffmpeg_input_index}:v]")
        current_input_index += 1

        # 2. Audio Input
        audio_ffmpeg_input_index = current_input_index
        cmd.extend(["-i", str(audio_path)])
        current_input_index += 1

        # 3. Character Inputs
        character_ffmpeg_input_indices = (
            {}
        )  # Map character config index to ffmpeg input index
        for i, char_data in enumerate(resolved_character_images):
            char_ffmpeg_input_index = current_input_index
            cmd.extend(["-loop", "1", "-framerate", str(fps), "-i", char_data["path"]])
            character_ffmpeg_input_indices[i] = char_ffmpeg_input_index
            input_streams.append(f"[{char_ffmpeg_input_index}:v]")
            current_input_index += 1

        # Set duration
        cmd.extend(["-t", str(duration)])

        # Build the filter_complex string
        # Start with background scaling
        # Use bg_ffmpeg_input_index for background video stream
        bg_filter_chain = (
            f"[{bg_ffmpeg_input_index}:v]scale={width}:{height}[bg_scaled]"
        )
        filter_complex_parts.append(bg_filter_chain)
        last_chain_name = "[bg_scaled]"

        # Character Overlays
        for i, char_data in enumerate(resolved_character_images):
            char_ffmpeg_input_index = character_ffmpeg_input_indices[
                i
            ]  # Use the correct ffmpeg input index for character

            scale = char_data["scale"]
            anchor = char_data["anchor"]
            overlay_x = char_data["position"].get("x", "0")
            overlay_y = char_data["position"].get("y", "0")

            # Apply scale filter
            scaled_fg_stream_name = f"scaled_fg{i}"
            filter_complex_parts.append(
                f"[{char_ffmpeg_input_index}:v]scale=iw*{scale}:ih*{scale}[{scaled_fg_stream_name}]"
            )

            # Format the scaled character image to rgba
            formatted_fg_stream_name = f"fg{i}"
            filter_complex_parts.append(
                f"[{scaled_fg_stream_name}]format=rgba[{formatted_fg_stream_name}]"
            )

            # Calculate overlay position using the new helper function
            x_expr, y_expr = calculate_overlay_position(
                bg_width_expr="W",
                bg_height_expr="H",
                fg_width_expr="w",  # 'w' and 'h' in overlay filter refer to the foreground's dimensions
                fg_height_expr="h",
                anchor=anchor,
                offset_x=str(overlay_x),
                offset_y=str(overlay_y),
            )

            # Overlay the formatted character image onto the current video stream
            new_chain_name = f"[char_overlay_{i}]"
            filter_complex_parts.append(
                f"{last_chain_name}[{formatted_fg_stream_name}]overlay=x={x_expr}:y={y_expr}{new_chain_name}"
            )
            last_chain_name = new_chain_name

        final_video_stream_name_before_drawtext = (
            last_chain_name  # Output of the last overlay
        )

        # Add drawtext filter if present (after all overlays)
        default_font_path = self.config.get("subtitle", {}).get("font_path")
        if "fontfile" not in drawtext_filter and default_font_path:
            drawtext_filter["fontfile"] = default_font_path
        drawtext_str = _format_drawtext_filter(drawtext_filter)

        if drawtext_str:
            # Apply drawtext to the final video stream after all character overlays
            final_video_stream_name = "[final_output_with_text]"
            filter_complex_parts.append(
                f"{final_video_stream_name_before_drawtext}drawtext={drawtext_str}{final_video_stream_name}"
            )
        else:
            final_video_stream_name = final_video_stream_name_before_drawtext  # If no drawtext, use the stream name before drawtext

        # Map options
        map_options = []
        map_options.append("-map")
        map_options.append(final_video_stream_name)  # Map the final video stream
        map_options.append("-map")
        map_options.append(f"{audio_ffmpeg_input_index}:a")

        # Add filter_complex to command
        if filter_complex_parts:
            cmd.extend(["-filter_complex", ";".join(filter_complex_parts)])

        # Map options
        cmd.extend(map_options)

        # Add logging options for debugging
        cmd.extend(["-loglevel", "level+info", "-stats"])

        # Output options
        video_codec = "libx264"

        cmd.extend(
            [
                "-c:v",
                video_codec,
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

        result = None
        try:
            print(f"Executing FFmpeg command: {' '.join(cmd)}")  # Debugging
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            print(
                f"Error during ffmpeg processing for {output_filename} with {video_codec}:"
            )
            print(f"STDOUT: {e.stdout}")
            print(f"STDERR: {e.stderr}")

            if self.hw_encoder and video_codec != "libx264":
                print(
                    f"Hardware encoding failed. Falling back to libx264 for {output_filename}."
                )
                # Find and replace the video codec in the command
                try:
                    codec_index = cmd.index("-c:v")
                    cmd[codec_index + 1] = "libx264"
                    result = subprocess.run(
                        cmd,
                        check=True,
                        stdout=subprocess.PIPE,
                        text=True,
                        stderr=subprocess.PIPE,
                    )
                except Exception as fallback_e:
                    print(f"Error during fallback ffmpeg processing: {fallback_e}")
                    raise
            else:
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
            video_codec = "h264_vaapi"
            # TODO: VAAPIの複雑なフィルターグラフ対応を検討
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
                    print(f"STDERR: {fallback_e.stderr}")
                    raise  # フォールバックも失敗した場合はエラーを再スロー
            else:
                raise  # ハードウェアエンコーダーが指定されていないか、libx264で失敗した場合はそのままエラーを再スロー

        return output_path

    def concat_clips(self, clip_paths: List[Path], output_path: str) -> None:
        """
        Concatenates multiple video clips into a single file.

        Args:
            clip_paths (List[Path]): A sorted list of clip paths to concatenate.
            output_path (str): The final output file path.
        """
        if not clip_paths:
            print("[Concat] No clips to concatenate.")
            return

        print(f"[Concat] Concatenating {len(clip_paths)} clips -> {output_path}")

        # Create a file list for ffmpeg concat demuxer
        file_list_path = self.temp_dir / "file_list.txt"
        with open(file_list_path, "w") as f:
            for p in clip_paths:
                f.write(f"file '{p.resolve()}'\n")

        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output files without asking
        ]

        # 並列処理の指定
        if self.num_jobs > 0:
            cmd.extend(["-threads", str(self.num_jobs)])

        cmd.extend(
            [
                "-f",
                "concat",
                "-safe",
                "0",  # Allow unsafe file paths (e.g., absolute paths)
                "-i",
                str(file_list_path),
                "-c",
                "copy",  # Copy streams without re-encoding
                str(output_path),  # output_pathをstrにキャスト
            ]
        )

        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            print(f"Error during ffmpeg concatenation:")
            print(f"STDOUT: {e.stdout}")
            print(f"STDERR: {e.stderr}")
            raise
        finally:
            # Clean up the file list
            if file_list_path.exists():
                file_list_path.unlink()

        print(f"[Success] Final video saved to {output_path}")
