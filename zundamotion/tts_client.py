import os
import requests
from pathlib import Path

VOICEVOX_API_URL = os.environ.get("VOICEVOX_API_URL", "http://voicevox:50021")


def generate_voice(text: str, speaker: int, out_path: str, speed: float = 1.0, pitch: float = 0.0) -> None:
    """
    VOICEVOXエンジンにテキストを送信して音声ファイルを生成する

    Args:
        text (str): 合成するテキスト
        speaker (int): VOICEVOXの話者ID
        out_path (str): 出力するWAVファイルのパス
        speed (float): 話速（デフォルト=1.0）
        pitch (float): ピッチ（デフォルト=0.0）
    """
    # audio_query取得
    res = requests.post(
        f"{VOICEVOX_API_URL}/audio_query",
        params={"text": text, "speaker": speaker},
    )
    res.raise_for_status()
    query = res.json()

    # パラメータ調整
    query["speedScale"] = speed
    query["pitchScale"] = pitch

    # 音声合成
    synth_res = requests.post(
        f"{VOICEVOX_API_URL}/synthesis",
        params={"speaker": speaker},
        json=query
    )
    synth_res.raise_for_status()

    # 保存
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(synth_res.content)
