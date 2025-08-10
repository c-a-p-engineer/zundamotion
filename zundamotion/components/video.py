import subprocess
from pathlib import Path
from typing import Any, Dict, List


def _format_drawtext_filter(drawtext_params: Dict[str, Any]) -> str:
    """Formats drawtext parameters into an FFmpeg drawtext filter string."""
    parts = []
    for key, value in drawtext_params.items():
        if isinstance(value, str) and "'" in value:
            # Escape single quotes within the string
            value = value.replace("'", "\\'")
        parts.append(f"{key}='{value}'")
    return ":".join(parts)


class VideoRenderer:
    def __init__(self, config: Dict[str, Any], temp_dir: Path):
        self.config = config
        self.temp_dir = temp_dir
        self.video_config = config.get("video", {})

    def render_clip(
        self,
        audio_path: Path,
        duration: float,
        drawtext_filter: Dict[str, Any],
        bg_image_path: str,
        output_filename: str,
    ) -> Path:
        """
        Renders a single video clip.

        Args:
            audio_path (Path): Path to the audio file.
            duration (float): Duration of the clip.
            drawtext_filter (Dict[str, Any]): Subtitle filter options.
            bg_image_path (str): Path to the background image.
            output_filename (str): Base name for the output file.

        Returns:
            Path: Path to the rendered mp4 clip.
        """
        output_path = self.temp_dir / f"{output_filename}.mp4"
        width = self.video_config.get("width", 1280)  # Default width
        height = self.video_config.get("height", 720)  # Default height
        fps = self.video_config.get("fps", 30)  # Default fps

        print(f"[Video] Rendering clip -> {output_path.name}")

        # configからデフォルトのフォントパスを取得
        default_font_path = self.config.get("subtitle", {}).get("font_path")
        # drawtext_filterにfontfileがなければ追加
        if "fontfile" not in drawtext_filter and default_font_path:
            drawtext_filter["fontfile"] = default_font_path

        drawtext_str = _format_drawtext_filter(drawtext_filter)

        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output files without asking
            "-loop",
            "1",
            "-i",
            bg_image_path,
            "-i",
            str(audio_path),
            "-t",
            str(duration),
            "-vf",
            f"scale={width}:{height},drawtext={drawtext_str}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-r",
            str(fps),  # Set output frame rate
            str(output_path),
        ]

        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            print(f"Error during ffmpeg processing for {output_filename}:")
            print(f"STDOUT: {e.stdout}")
            print(f"STDERR: {e.stderr}")
            raise

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
                f.write(f"file '{p}'\n")

        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output files without asking
            "-f",
            "concat",
            "-safe",
            "0",  # Allow unsafe file paths (e.g., absolute paths)
            "-i",
            str(file_list_path),
            "-c",
            "copy",  # Copy streams without re-encoding
            output_path,
        ]

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
