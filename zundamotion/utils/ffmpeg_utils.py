import json
import re
import subprocess
from typing import Optional


def get_ffmpeg_version(ffmpeg_path: str = "ffmpeg") -> Optional[str]:
    """
    Gets the FFmpeg version string.
    """
    try:
        cmd = [ffmpeg_path, "-version"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        match = re.search(r"ffmpeg version (\S+)", result.stdout)
        if match:
            return match.group(1)
        return None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def get_hardware_encoder(ffmpeg_path: str = "ffmpeg") -> Optional[str]:
    """
    Detects available hardware encoders (NVENC, VAAPI, VideoToolbox).
    Returns the name of the first detected encoder or None.
    """
    try:
        cmd = [ffmpeg_path, "-encoders"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        output = result.stdout

        if "h264_nvenc" in output or "hevc_nvenc" in output:
            return "nvenc"
        if "h264_vaapi" in output or "hevc_vaapi" in output:
            return "vaapi"
        if "h264_videotoolbox" in output or "hevc_videotoolbox" in output:
            return "videotoolbox"
        # Add more encoders as needed

        return None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def get_audio_duration(file_path: str) -> float:
    """
    Get the duration of an audio file using ffprobe.

    Args:
        file_path (str): Path to the audio file.

    Returns:
        float: Duration in seconds.
    """
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            file_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)

        # デバッグログの追加
        print(f"  [DEBUG] ffprobe stdout for {file_path}: {result.stdout}")

        probe_data = json.loads(result.stdout)

        # デバッグログの追加
        print(f"  [DEBUG] Type of probe_data: {type(probe_data)}, Value: {probe_data}")

        duration = float(probe_data["format"]["duration"])
        return round(duration, 2)
    except subprocess.CalledProcessError as e:
        print(f"Error running ffprobe for {file_path}: {e}")
        print(e.stderr)
        raise
    except (json.JSONDecodeError, KeyError) as e:
        print(f"Error parsing ffprobe output for {file_path}: {e}")
        raise


def add_bgm_to_video(
    video_path: str,
    bgm_path: str,
    output_path: str,
    bgm_volume: float = 0.5,
    bgm_start_time: float = 0.0,
    fade_in_duration: float = 0.0,
    fade_out_duration: float = 0.0,
    video_duration: Optional[float] = None,
):
    """
    Adds background music to a video file with fade-in/out and volume control.

    Args:
        video_path (str): Path to the input video file.
        bgm_path (str): Path to the background music file.
        output_path (str): Path for the output video file with BGM.
        bgm_volume (float): Volume of the BGM (0.0 to 1.0).
        bgm_start_time (float): Start time of the BGM in the video (seconds).
        fade_in_duration (float): Duration of BGM fade-in (seconds).
        fade_out_duration (float): Duration of BGM fade-out (seconds).
        video_duration (Optional[float]): Duration of the video in seconds.
                                          If None, it will be detected automatically.
    """
    if video_duration is None:
        video_duration = get_audio_duration(
            video_path
        )  # Assuming video duration can be obtained like audio

    bgm_duration = get_audio_duration(bgm_path)

    # Calculate effective BGM end time
    effective_bgm_end_time = min(video_duration, bgm_start_time + bgm_duration)

    # FFmpeg command construction
    cmd = [
        "ffmpeg",
        "-i",
        video_path,
        "-i",
        bgm_path,
        "-filter_complex",
    ]

    # Audio filter for BGM
    audio_filters = []
    audio_filters.append(f"volume={bgm_volume}")

    if fade_in_duration > 0:
        audio_filters.append(f"afade=t=in:st=0:d={fade_in_duration}")

    if fade_out_duration > 0:
        # フェードアウトはBGMファイルの終了位置から逆算
        fade_out_start_relative_to_bgm = bgm_duration - fade_out_duration
        if fade_out_start_relative_to_bgm < 0:
            fade_out_start_relative_to_bgm = 0  # BGMの長さよりフェードアウトが長い場合
        audio_filters.append(
            f"afade=t=out:st={fade_out_start_relative_to_bgm}:d={fade_out_duration}"
        )

    # Apply audio filters to BGM stream
    bgm_filter_str = f"[1:a]{','.join(audio_filters)}[bgm_filtered]"

    # Mix original video audio and BGM
    # Ensure BGM starts at bgm_start_time and ends at effective_bgm_end_time
    # Use aevalsrc to create a silent audio stream for the video's duration
    # Then overlay the BGM onto this silent stream at the specified start time
    # Finally, mix this combined audio with the original video's audio

    # Create a silent audio stream for the duration of the video
    # This ensures the output audio stream matches the video duration
    silent_audio_cmd = (
        f"anullsrc=r=44100:cl=stereo,atrim=duration={video_duration}[silent]"
    )

    # Overlay BGM onto the silent stream
    # The 'shortest=1' option ensures the output duration is limited by the shortest input stream,
    # which in this case is the video duration.
    # The 'amix=inputs=2:duration=shortest' ensures the mixed audio matches the video length.
    # The 'apad' filter is used to pad the BGM if it's shorter than the video segment it's supposed to cover.
    # The 'atrim' and 'setpts' are used to ensure the BGM is correctly placed and trimmed.

    # First, prepare the BGM stream to be overlaid
    # We need to ensure the BGM stream is correctly positioned and potentially trimmed/padded
    # [1:a] is the BGM input
    # [0:a] is the original video audio input

    # If there's original audio, mix it. Otherwise, just use the BGM.
    # We need to handle cases where there might be no original audio in the video.
    # For simplicity, let's assume we always want to mix, and if video has no audio, it's silent.

    # The main audio mixing logic:
    # 1. Apply filters to BGM: [1:a] -> [bgm_filtered]
    # 2. Overlay BGM onto a silent stream of video duration, starting at bgm_start_time
    #    This creates the BGM track aligned with the video timeline.
    # 3. Mix this BGM track with the original video audio [0:a]

    # Complex filter graph for audio
    # [0:a] is the original audio from the video
    # [1:a] is the BGM audio

    # We need to ensure the BGM is correctly placed and mixed.
    # The 'adelay' filter can be used to delay the BGM.
    # The 'amix' filter combines the audio streams.

    # Let's refine the filter_complex string.
    # We need to ensure the BGM is mixed with the video's audio,
    # starting at `bgm_start_time` and ending at `effective_bgm_end_time`.
    # If the video has no audio, it should still work.

    # Option 1: Use `amerge` and `adelay` for mixing
    # This approach is more robust for handling different start times and durations.
    # [0:a] is the video's original audio.
    # [1:a] is the BGM.

    # We need to ensure the BGM is delayed and then mixed.
    # If the video has no audio, we can create a silent stream for it.

    # Let's simplify the filter_complex for now and assume video has audio.
    # If video has no audio, ffmpeg will handle it by treating it as silent.

    # The `amix` filter is suitable for combining two audio streams.
    # We need to ensure the BGM is correctly positioned.

    # The `atrim` and `setpts` filters are crucial for precise timing.
    # [1:a] is the BGM stream.
    # [0:a] is the video's original audio stream.

    # Let's try a more direct approach with `amix` and `adelay` for the BGM.
    # The BGM needs to be delayed by `bgm_start_time`.
    # The output audio stream should match the video duration.

    # Filter for BGM: apply volume and fades, then delay
    bgm_processed_stream = f"[1:a]{','.join(audio_filters)}[bgm_processed]"

    # Mix original audio and processed BGM
    # Use `amix` to combine, `duration=shortest` to match video length
    # `inputs=2` for video audio and BGM
    # `[0:a]` is the video's audio stream
    # `[bgm_processed]` is the BGM stream after volume/fade filters

    # We need to ensure the BGM starts at the correct time.
    # The `adelay` filter can be used on the BGM stream.
    # `adelay=delays={int(bgm_start_time * 1000)}:all=1`

    # Let's construct the filter_complex string carefully.
    # [0:a] is the video's audio.
    # [1:a] is the BGM.

    # Apply volume and fade filters to BGM.
    # Then, delay the BGM.
    # Then, mix with the video's audio.

    # Filter for BGM: apply volume and fades
    bgm_filter_str = f"[1:a]{','.join(audio_filters)}[bgm_filtered]"

    # Delay the filtered BGM
    delayed_bgm_str = (
        f"[bgm_filtered]adelay={int(bgm_start_time * 1000)}:all=1[delayed_bgm]"
    )

    # Mix original video audio with delayed BGM
    # Use `amix` to combine, `duration=shortest` to match video length
    # `inputs=2` for video audio and BGM
    # `[0:a]` is the video's audio stream
    # `[delayed_bgm]` is the delayed BGM stream

    # The `amix` filter will combine the two audio streams.
    # `duration=shortest` ensures the output audio stream is no longer than the video.

    # Final filter_complex string
    filter_complex_str = f"{bgm_filter_str};{delayed_bgm_str};[0:a][delayed_bgm]amix=inputs=2:duration=shortest[aout]"

    cmd.append(filter_complex_str)

    cmd.extend(
        [
            "-map",
            "0:v",  # Map video stream from input 0 (original video)
            "-map",
            "[aout]",  # Map the mixed audio stream
            "-c:v",
            "copy",  # Copy video codec
            "-c:a",
            "aac",  # Encode audio to AAC
            "-b:a",
            "192k",  # Audio bitrate
            "-shortest",  # Finish encoding when the shortest input stream ends (video)
            output_path,
        ]
    )

    try:
        subprocess.run(cmd, check=True)
        print(f"Successfully added BGM to {video_path} and saved to {output_path}")
    except subprocess.CalledProcessError as e:
        print(f"Error adding BGM to video: {e}")
        print(e.stderr)
        raise
