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

from ..utils.ffmpeg_utils import get_ffmpeg_version, get_hardware_encoder


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
        ffmpeg_version = get_ffmpeg_version(self.ffmpeg_path)
        if ffmpeg_version:
            print(f"[FFmpeg] Detected FFmpeg version: {ffmpeg_version}")
            self.hw_encoder = get_hardware_encoder(self.ffmpeg_path)
            if self.hw_encoder:
                print(f"[FFmpeg] Detected hardware encoder: {self.hw_encoder}")
            else:
                print("[FFmpeg] No hardware encoder detected or supported.")
        else:
            print(
                "[FFmpeg] FFmpeg not found or version could not be determined. Please ensure FFmpeg is installed and in your PATH."
            )
            # Fallback to software encoding if ffmpeg is not found
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
        bg_image_path: str,
        output_filename: str,
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

        # 並列処理の指定
        if self.num_jobs > 0:
            cmd.extend(["-threads", str(self.num_jobs)])

        # 背景動画の開始時間を指定
        if is_bg_video:
            cmd.extend(["-ss", str(start_time)])  # 背景動画の開始位置
            cmd.extend(["-stream_loop", "-1", "-i", bg_image_path])  # 背景動画 (入力0)
        else:
            cmd.extend(["-loop", "1", "-i", bg_image_path])  # 背景画像 (入力0)

        cmd.extend(["-i", str(audio_path)])  # メイン音声 (入力1)

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

        # オーディオフィルター (メイン音声のみをマップ)
        map_options.append("-map")
        map_options.append("1:a")

        # フィルターグラフをコマンドに追加
        if filter_complex:
            cmd.extend(["-filter_complex", ";".join(filter_complex)])

        # マッピングオプションを追加
        cmd.extend(map_options)

        # 出力オプション
        video_codec = "libx264"
        if self.hw_encoder == "nvenc":
            video_codec = "h264_nvenc"
        elif self.hw_encoder == "vaapi":
            video_codec = "h264_vaapi"
            # VAAPIの場合、-vfオプションにhwuploadとformatを追加する必要がある
            # filter_complex.insert(0, f"hwupload,format=nv12") # これはビデオフィルターの前に来るべき
            # TODO: VAAPIの複雑なフィルターグラフ対応を検討
        elif self.hw_encoder == "videotoolbox":
            video_codec = "h264_videotoolbox"

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
                str(fps),  # Set output frame rate
                str(output_path),
            ]
        )

        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            print(
                f"Error during ffmpeg processing for {output_filename} with {video_codec}:"
            )
            print(f"STDOUT: {e.stdout}")
            print(f"STDERR: {e.stderr}")

            # ハードウェアエンコードが失敗した場合、ソフトウェアエンコードにフォールバック
            if self.hw_encoder and video_codec != "libx264":
                print(
                    f"Hardware encoding failed. Falling back to libx264 for {output_filename}."
                )
                cmd[cmd.index("-c:v") + 1] = "libx264"  # -c:v の次の要素をlibx264に変更
                try:
                    subprocess.run(cmd, check=True, capture_output=True, text=True)
                except subprocess.CalledProcessError as fallback_e:
                    print(
                        f"Error during ffmpeg processing with libx264 for {output_filename}:"
                    )
                    print(f"STDOUT: {fallback_e.stdout}")
                    print(f"STDERR: {fallback_e.stderr}")
                    raise  # フォールバックも失敗した場合はエラーを再スロー
            else:
                raise  # ハードウェアエンコーダーが指定されていないか、libx264で失敗した場合はそのままエラーを再スロー

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
