import json
import subprocess


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
        probe_data = json.loads(result.stdout)
        duration = float(probe_data["format"]["duration"])
        return round(duration, 2)
    except subprocess.CalledProcessError as e:
        print(f"Error running ffprobe for {file_path}: {e}")
        print(e.stderr)
        raise
    except (json.JSONDecodeError, KeyError) as e:
        print(f"Error parsing ffprobe output for {file_path}: {e}")
        raise
