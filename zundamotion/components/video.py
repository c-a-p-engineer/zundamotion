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


class VideoRenderer:
    def __init__(self, config: Dict[str, Any], temp_dir: Path):
        self.config = config
        self.temp_dir = temp_dir
        self.video_config = config.get("video", {})
        self.bgm_config = config.get("bgm", {})

    def render_clip(
        self,
        audio_path: Path,
        duration: float,
        drawtext_filter: Dict[str, Any],
        bg_image_path: str,
        output_filename: str,
        bgm_path: Optional[str] = None,
        bgm_volume: Optional[float] = None,
        is_bg_video: bool = False,
        start_time: float = 0.0,  # 新しいパラメータ: 背景動画の開始時間
    ) -> Path:
        """
        Renders a single video clip.

        Args:
            audio_path (Path): Path to the audio file.
            duration (float): Duration of the clip.
            drawtext_filter (Dict[str, Any]): Subtitle filter options.
            bg_image_path (str): Path to the background image.
            output_filename (str): Base name for the output file.
            bgm_path (Optional[str]): Path to the background music file.
            bgm_volume (Optional[float]): Volume for the background music (0.0-1.0).
            is_bg_video (bool): True if the background is a video file, False if an image.
            start_time (float): Start time for the background video (in seconds).

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

        # FFmpegコマンドの構築
        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output files without asking
        ]

        # 背景動画の開始時間を指定
        if is_bg_video:
            cmd.extend(["-ss", str(start_time)])  # 背景動画の開始位置
            cmd.extend(["-stream_loop", "-1", "-i", bg_image_path])  # 背景動画 (入力0)
        else:
            cmd.extend(["-loop", "1", "-i", bg_image_path])  # 背景画像 (入力0)

        cmd.extend(["-i", str(audio_path)])  # メイン音声 (入力1)

        bgm_input_index = -1
        if bgm_path:
            cmd.extend(["-i", bgm_path])  # BGM (入力2)
            bgm_input_index = 2  # BGMの入力インデックス

        cmd.extend(["-t", str(duration)])  # 出力時間

        # 複雑なフィルターグラフの構築
        filter_complex = []
        map_options = []

        # ビデオフィルター (スケールとdrawtext)
        video_filter_str = f"scale={width}:{height},drawtext={drawtext_str}"

        # 背景が動画でも画像でも、入力0のビデオストリームに直接フィルターを適用
        filter_complex.append(f"[0:v]{video_filter_str}[v]")

        map_options.append("-map")
        map_options.append("[v]")

        # オーディオフィルター (メイン音声とBGMのミキシング)
        if bgm_path:
            # BGMの音量調整
            final_bgm_volume = (
                bgm_volume
                if bgm_volume is not None
                else self.bgm_config.get("volume", 0.5)
            )
            filter_complex.append(
                f"[{bgm_input_index}:a]volume={final_bgm_volume}[bgm_vol]"
            )
            # メイン音声とBGMをミックス
            filter_complex.append(
                f"[1:a][bgm_vol]amix=inputs=2:duration=first:dropout_transition=0[aout]"
            )
            map_options.append("-map")
            map_options.append("[aout]")
        else:
            # BGMがない場合、メイン音声のみをマップ
            map_options.append("-map")
            map_options.append("1:a")

        # フィルターグラフをコマンドに追加
        if filter_complex:
            cmd.extend(["-filter_complex", ";".join(filter_complex)])

        # マッピングオプションを追加
        cmd.extend(map_options)

        # 出力オプション
        cmd.extend(
            [
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
        )

        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            print(f"Error during ffmpeg processing for {output_filename}:")
            print(f"STDOUT: {e.stdout}")
            print(f"STDERR: {e.stderr}")
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
            "-stream_loop",
            "-1",  # Loop indefinitely
            "-i",
            bg_video_path,
            "-t",
            str(duration),  # Trim to desired duration
            "-vf",
            f"scale={width}:{height}",  # Scale to target resolution
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(fps),
            "-an",  # No audio
            str(output_path),
        ]

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
