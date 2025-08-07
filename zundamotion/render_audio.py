# python -m zundamotion.render_audio scripts/sample.yaml
import json
import os
import subprocess

from zundamotion.script_loader import load_script
from zundamotion.tts_client import generate_voice


def render_audio(script_path: str, out_dir: str = "voices") -> None:
    """
    YAMLスクリプトを読み取り、各セリフごとに音声合成と字幕ファイルを出力する。

    - 音声は VOICEVOX で生成し .wav 形式で保存
    - 字幕は .srt（汎用形式）と .drawtext.json（FFmpeg drawtext用）で出力

    Args:
        script_path (str): YAML台本ファイルへのパス
        out_dir (str): 出力ディレクトリ（デフォルトは "voices"）
    """
    script = load_script(script_path)

    # デフォルトの話者・速度・ピッチ
    speaker_default = script.get("defaults", {}).get("voice", {}).get("speaker", 1)
    speed_default = script.get("defaults", {}).get("voice", {}).get("speed", 1.0)
    pitch_default = script.get("defaults", {}).get("voice", {}).get("pitch", 0.0)

    os.makedirs(out_dir, exist_ok=True)

    for scene in script.get("scenes", []):
        scene_id = scene["id"]
        for idx, line in enumerate(scene.get("lines", [])):
            text = line["text"]
            speaker = line.get("speaker", speaker_default)
            speed = line.get("speed", speed_default)
            pitch = line.get("pitch", pitch_default)

            filename_base = f"{scene_id}_{idx+1}"
            wav_path = os.path.join(out_dir, f"{filename_base}.wav")
            srt_path = os.path.join(out_dir, f"{filename_base}.srt")
            json_path = os.path.join(out_dir, f"{filename_base}.drawtext.json")

            print(f"[Audio] {scene_id} #{idx+1}: {text}")
            generate_voice(text, speaker, wav_path, speed, pitch)

            # 再生時間取得（秒）
            duration = get_wav_duration(wav_path)
            start_time = 0.0
            end_time = duration

            # SRT出力
            write_srt_file(srt_path, text, start_time, end_time)

            # drawtext JSON出力
            write_drawtext_json(json_path, text, start_time, end_time)


def get_wav_duration(path: str) -> float:
    """
    ffprobe を使って .wav ファイルの再生時間（秒）を取得する。

    Args:
        path (str): 対象の音声ファイルパス

    Returns:
        float: 音声の再生時間（小数秒）
    """
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    return round(float(result.stdout.strip()), 2)


def format_time(t: float) -> str:
    """
    秒数を SRT形式（HH:MM:SS,mmm）に変換する。

    Args:
        t (float): 秒数

    Returns:
        str: フォーマット済み文字列
    """
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int((t - int(t)) * 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def write_srt_file(path: str, text: str, start: float, end: float) -> None:
    """
    1行のSRT字幕ファイルを書き出す。

    Args:
        path (str): 出力ファイルパス
        text (str): 表示テキスト
        start (float): 表示開始時間（秒）
        end (float): 表示終了時間（秒）
    """
    with open(path, "w", encoding="utf-8") as srt:
        srt.write("1\n")
        srt.write(f"{format_time(start)} --> {format_time(end)}\n")
        srt.write(f"{text}\n")


def write_drawtext_json(path: str, text: str, start: float, end: float) -> None:
    """
    FFmpegの drawtext フィルターで使うための JSON データを出力する。

    Args:
        path (str): 出力ファイルパス
        text (str): 表示テキスト
        start (float): 開始時間（秒）
        end (float): 終了時間（秒）
    """
    drawtext_data = {
        "text": text,
        "start": start,
        "end": end,
        "x": "(w-text_w)/2",
        "y": "h-100",
        "fontcolor": "white",
        "fontsize": 48,
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(drawtext_data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    import sys

    script_path = sys.argv[1] if len(sys.argv) > 1 else "scripts/sample.yaml"
    render_audio(script_path)
