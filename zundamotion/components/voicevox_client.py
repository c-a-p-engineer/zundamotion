import json
import time

import requests


def generate_voice(
    text: str,
    speaker: int,
    filepath: str,
    speed: float = 1.0,
    pitch: float = 0.0,
    voicevox_url: str = "http://127.0.0.1:50021",
):
    """
    Generates a voice file using the VOICEVOX API.

    Args:
        text (str): The text to be synthesized.
        speaker (int): The speaker ID.
        filepath (str): The path to save the .wav file.
        speed (float): The speech speed.
        pitch (float): The speech pitch.
        voicevox_url (str): The base URL of the VOICEVOX engine.
    """
    # 1. audio_query
    query_params = {"text": text, "speaker": speaker}
    try:
        res_query = requests.post(f"{voicevox_url}/audio_query", params=query_params)
        res_query.raise_for_status()
        query_data = res_query.json()

        # 2. synthesis
        query_data["speedScale"] = speed
        query_data["pitchScale"] = pitch
        synth_params = {"speaker": speaker}
        res_synth = requests.post(
            f"{voicevox_url}/synthesis",
            params=synth_params,
            data=json.dumps(query_data),
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        res_synth.raise_for_status()

        # 3. save to file
        with open(filepath, "wb") as f:
            f.write(res_synth.content)

    except requests.exceptions.RequestException as e:
        print(f"Failed to connect to VOICEVOX: {e}")
        print("Please ensure the VOICEVOX engine is running.")
        raise
    except Exception as e:
        print(f"An unexpected error occurred during voice generation: {e}")
        raise
