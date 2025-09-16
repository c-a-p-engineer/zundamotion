import asyncio
import json
from typing import Any, Dict, List

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# VOICEVOX APIとの通信エラー時にリトライする例外を指定
RETRY_EXCEPTIONS = (httpx.RequestError, httpx.HTTPStatusError, asyncio.TimeoutError)


@retry(
    stop=stop_after_attempt(5),  # 最大5回リトライ
    wait=wait_exponential(multiplier=1, min=4, max=10),  # 指数バックオフ (4秒から10秒)
    retry=retry_if_exception_type(RETRY_EXCEPTIONS),
    reraise=True,  # リトライ回数を超えたら例外を再発生
)
async def get_speakers_info(
    voicevox_url: str = "http://127.0.0.1:50021",
) -> Dict[int, Dict[str, Any]]:
    """
    Fetches speaker information from the VOICEVOX API asynchronously with retry mechanism.

    Args:
        voicevox_url (str): The base URL of the VOICEVOX engine.

    Returns:
        Dict[int, Dict[str, Any]]: A dictionary mapping speaker ID to speaker information.
    """
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(f"{voicevox_url}/speakers", timeout=10)
            res.raise_for_status()
            speakers_data: List[Dict[str, Any]] = res.json()

            speaker_info = {}
            for speaker_group in speakers_data:
                for speaker in speaker_group.get("styles", []):
                    speaker_info[speaker["id"]] = {
                        "name": speaker["name"],
                        "speaker_name": speaker_group["name"],
                    }
            return speaker_info
    except httpx.RequestError as e:
        print(f"Failed to connect to VOICEVOX to get speaker info: {e}")
        print("Please ensure the VOICEVOX engine is running.")
        raise
    except httpx.HTTPStatusError as e:
        print(f"HTTP error occurred during speaker info retrieval: {e}")
        raise
    except asyncio.TimeoutError as e:
        print(f"Timeout occurred during speaker info retrieval: {e}")
        raise
    except Exception as e:
        print(f"An unexpected error occurred during speaker info retrieval: {e}")
        raise


@retry(
    stop=stop_after_attempt(5),  # 最大5回リトライ
    wait=wait_exponential(multiplier=1, min=4, max=10),  # 指数バックオフ (4秒から10秒)
    retry=retry_if_exception_type(RETRY_EXCEPTIONS),
    reraise=True,  # リトライ回数を超えたら例外を再発生
)
async def generate_voice(
    text: str,
    speaker: int,
    filepath: str,
    speed: float = 1.0,
    pitch: float = 0.0,
    voicevox_url: str = "http://127.0.0.1:50021",
):
    """
    Generates a voice file using the VOICEVOX API asynchronously with retry mechanism.

    Args:
        text (str): The text to be synthesized.
        speaker (int): The speaker ID.
        filepath (str): The path to save the .wav file.
        speed (float): The speech speed.
        pitch (float): The speech pitch.
        voicevox_url (str): The base URL of the VOICEVOX engine.
    """
    async with httpx.AsyncClient() as client:
        # 1. audio_query
        query_params = {"text": text, "speaker": speaker}
        try:
            res_query = await client.post(
                f"{voicevox_url}/audio_query", params=query_params, timeout=10
            )
            res_query.raise_for_status()
            query_data = res_query.json()

            # 2. synthesis
            query_data["speedScale"] = speed
            query_data["pitchScale"] = pitch
            synth_params = {"speaker": speaker}
            res_synth = await client.post(
                f"{voicevox_url}/synthesis",
                params=synth_params,
                content=json.dumps(query_data),
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            res_synth.raise_for_status()

            # 3. save to file
            with open(filepath, "wb") as f:
                f.write(res_synth.content)

        except httpx.RequestError as e:
            print(f"Failed to connect to VOICEVOX: {e}")
            print("Please ensure the VOICEVOX engine is running.")
            raise
        except httpx.HTTPStatusError as e:
            print(f"HTTP error occurred during voice generation: {e}")
            raise
        except asyncio.TimeoutError as e:
            print(f"Timeout occurred during voice generation: {e}")
            raise
        except Exception as e:
            print(f"An unexpected error occurred during voice generation: {e}")
            raise
